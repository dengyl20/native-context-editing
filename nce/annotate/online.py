"""Online teacher: edit generation at decision points (Section 3.2, Appendix B).

Each trajectory is assigned a context budget ``W`` from 32K, 48K, 64K and
128K: the largest tier under which its peak context crosses the soft line
while its incompressible floor still fits. Replaying the trajectory turn by
turn, a decision point arises when

  (i)   the context first reaches 0.70 W  (soft reminder, declinable),
  (ii)  it reaches 0.95 W                 (hard reminder, declinable only
                                           when nothing is editable), or
  (iii) a milestone of the forward pass is reached.

Each trigger has a cool-down of two turns, and a milestone fires only if the
last edit lies at least two turns back. At soft and milestone points the
teacher is not called if the editable blocks hold less than 8% of the
context, and its edits are discarded if they free less than 8%.

At a decision point the teacher plays the agent at turn ``t``. It sees the
trigger and every block still in context, each marked editable if
``t > r_hat`` and off-limits otherwise. It does not see release points,
release reasons, token counts, or anything after turn ``t``. The edits
execute immediately, so the next decision point sees the rewritten blocks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from ..render import DEFAULT_FORMAT, ChatFormat, Counter, approx_tokens, render_text
from ..runtime import REMINDER_TEXT
from .release import Context, ReleaseAnalysis
from .replay import Op, Replayer, compose_output

BUDGET_TIERS = (32_000, 48_000, 64_000, 128_000)
SOFT_LINE = 0.70
HARD_LINE = 0.95
TRIGGER_COOLDOWN = 2
MILESTONE_GAP = 2
MIN_EDITABLE_SHARE = 0.08
MIN_FREED_SHARE = 0.08


# ------------------------------------------------------------- interface


@dataclass
class ViewBlock:
    address: int
    source: str          # system | task | user | note | the tool call that produced it
    editable: bool
    text: str
    rewritten: bool = False  # the text is an earlier summary


@dataclass
class DecisionView:
    turn: int
    trigger: str                    # soft | hard | milestone
    reminder: Optional[str]         # the reminder text at soft and hard points
    milestone: Optional[str]        # the milestone description at milestone points
    blocks: List[ViewBlock]


@dataclass
class TeacherEdit:
    """The teacher's output format: ``{"op": "rewrite", "block": <id>, "text": "..."}``."""
    op: str
    block: Optional[int] = None     # the address shown in the view
    text: Optional[str] = None


@dataclass
class Decision:
    no_op: bool
    note: str = ""                  # the visible one-sentence rationale
    edits: List[TeacherEdit] = field(default_factory=list)
    reason: str = ""                # internal, for reviewers


class OnlineTeacher:
    def decide(self, view: DecisionView) -> Decision:
        raise NotImplementedError


# ------------------------------------------------------------------ budget


def unedited_prompt_tokens(ctx: Context, fmt: ChatFormat = DEFAULT_FORMAT,
                           counter: Counter = approx_tokens) -> List[int]:
    """Context size at the start of every turn of the unedited replay."""
    rp = Replayer(ctx, fmt, counter)
    sizes = []
    for t in range(1, ctx.T + 1):
        sizes.append(rp.tokens())
        rp.finish_turn(t, ctx.actions[t - 1], [])
    return sizes


def select_budget(ctx: Context, ra: ReleaseAnalysis, tiers: Sequence[int] = BUDGET_TIERS,
                  fmt: ChatFormat = DEFAULT_FORMAT,
                  counter: Counter = approx_tokens) -> Optional[int]:
    """The largest tier whose soft line the peak crosses while the floor fits.

    The floor is the final unedited context without every block that is
    ever released. Returns None if no tier qualifies.
    """
    peak = max(unedited_prompt_tokens(ctx, fmt, counter), default=0)
    rp = Replayer(ctx, fmt, counter)
    for t in range(1, ctx.T + 1):
        rp.finish_turn(t, ctx.actions[t - 1], [])
    floor_state = rp.state.copy()
    for ref, address in rp.live_refs():
        if ref.startswith("b") and ra.r_hat(int(ref[1:]), ctx.T) < ctx.T:
            floor_state.drop(address)
    floor = counter(render_text(floor_state, fmt))
    ok = [w for w in tiers if peak >= SOFT_LINE * w and floor <= w]
    return max(ok) if ok else None


# ----------------------------------------------------------------- triggers


class Triggers:
    def __init__(self, budget: Optional[int], milestones: Sequence[int]):
        self.budget = budget
        self.milestones = set(milestones)   # turns after which a milestone is reached
        self.last: Dict[str, int] = {}
        self.prev_tokens: Optional[int] = None

    def _cool(self, kind: str, t: int) -> bool:
        return kind not in self.last or t - self.last[kind] >= TRIGGER_COOLDOWN

    def check(self, t: int, tokens: int, last_edit: Optional[int]) -> Optional[str]:
        fired = None
        W = self.budget
        if W:
            soft_crossed = tokens >= SOFT_LINE * W and (
                self.prev_tokens is None or self.prev_tokens < SOFT_LINE * W)
            if tokens >= HARD_LINE * W and self._cool("hard", t):
                fired = "hard"
            elif soft_crossed and self._cool("soft", t):
                fired = "soft"
        if fired is None and (t - 1) in self.milestones and self._cool("milestone", t) and (
                last_edit is None or t - last_edit >= MILESTONE_GAP):
            fired = "milestone"
        self.prev_tokens = tokens
        if fired:
            self.last[fired] = t
        return fired


# ----------------------------------------------------------------- driver


@dataclass
class DecisionPoint:
    turn: int
    trigger: str
    tokens: int
    outcome: str        # edited | declined | not_called | discarded
    note: str = ""
    ops: List[Op] = field(default_factory=list)
    freed: float = 0.0
    reason: str = ""

    def to_json(self) -> dict:
        return {"turn": self.turn, "trigger": self.trigger, "tokens": self.tokens,
                "outcome": self.outcome, "note": self.note,
                "ops": [op.to_json() for op in self.ops], "freed": round(self.freed, 4),
                "reason": self.reason}


def build_view(rp: Replayer, ra: ReleaseAnalysis, t: int, trigger: str,
               milestone: Optional[str]) -> DecisionView:
    ctx = rp.ctx
    blocks = []
    for ref, address in rp.live_refs():
        blk = rp.state.blocks[address]
        if ref.startswith("b"):
            rec = ctx.blocks[int(ref[1:])]
            source = rec.source
            editable = not blk.locked and t > ra.r_hat(rec.index, ctx.T)
        else:
            source, editable = "note", True
        blocks.append(ViewBlock(address, source, editable, blk.text, ref in rp.rewritten))
    reminder = REMINDER_TEXT.get(trigger)
    return DecisionView(t, trigger, reminder, milestone, blocks)


def to_ops(rp: Replayer, decision: Decision) -> List[Op]:
    ops = []
    for e in decision.edits:
        if e.op == "append":
            ops.append(Op("append", None, e.text))
        elif e.block in rp.ref_of:
            ops.append(Op(e.op, rp.ref_of[e.block], e.text if e.op == "rewrite" else None))
    return ops


def generate_edits(ctx: Context, ra: ReleaseAnalysis, teacher: OnlineTeacher,
                   budget: Optional[int], fmt: ChatFormat = DEFAULT_FORMAT,
                   counter: Counter = approx_tokens) -> List[DecisionPoint]:
    rp = Replayer(ctx, fmt, counter)
    milestones = {m.after_turn: m.description for m in ra.milestones}
    triggers = Triggers(budget, milestones)
    points: List[DecisionPoint] = []
    last_edit: Optional[int] = None
    for t in range(1, ctx.T + 1):
        tokens = rp.tokens()
        trigger = triggers.check(t, tokens, last_edit)
        ops: List[Op] = []
        note = ""
        if trigger:
            if trigger in ("soft", "hard"):
                rp.add_reminder(trigger)
            view = build_view(rp, ra, t, trigger, milestones.get(t - 1))
            editable = sum(rp.block_tokens(b.address) for b in view.blocks if b.editable)
            dp = DecisionPoint(t, trigger, tokens, "declined")
            if trigger != "hard" and editable < MIN_EDITABLE_SHARE * tokens:
                dp.outcome, dp.reason = "not_called", "editable blocks below 8% of the context"
            elif trigger == "hard" and editable == 0:
                dp.outcome, dp.reason = "not_called", "nothing is editable"
            else:
                decision = teacher.decide(view)
                dp.note, dp.reason = decision.note, decision.reason
                if not decision.no_op:
                    cand = to_ops(rp, decision)
                    envelopes, cand = rp.compile(cand)
                    before, after = rp.measure(envelopes)
                    dp.freed = (before - after) / before if before else 0.0
                    if trigger != "hard" and dp.freed < MIN_FREED_SHARE:
                        dp.outcome = "discarded"
                        dp.reason = "edits free less than 8% of the context"
                    elif cand:
                        dp.outcome, ops, note = "edited", cand, decision.note
            if dp.outcome == "declined" and trigger in ("soft", "hard"):
                note = dp.note  # a declined reminder is answered in the rationale
            points.append(dp)
        envelopes, ops = rp.compile(ops)
        output = compose_output(note, envelopes, ctx.actions[t - 1])
        rp.finish_turn(t, output, ops)
        if ops:
            last_edit = t
            points[-1].ops = ops
    return points
