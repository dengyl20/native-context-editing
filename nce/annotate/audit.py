"""Final audit (Appendix B).

The audit replays the trajectory with the teacher's edits and rejects an
edit when

  (i)   a number, path, identifier, or quoted string in a summary or note
        does not occur in its source block, or in the trajectory for a note;
  (ii)  a literal the edit removes reappears in a later action without
        having appeared in a summary or in visible output first; or
  (iii) the editing turn frees less than 3% of the context (all edits of
        the turn are rejected).

It discards the trajectory when a hard reminder ends without an edit, or
when more than six turns, and more than 15% of all turns, carry edits.

The source of a rewrite is the block's text at the time of the edit
together with the tool call that produced it, since a summary names the
file it was read from. The surviving edits are compiled into the grammar on
the replayed state; the result is the annotated trajectory.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..render import DEFAULT_FORMAT, ChatFormat, Counter, approx_tokens
from .literals import PATH_RE, extract_literals
from .online import DecisionPoint
from .release import Context
from .replay import Op, Replayer, compose_output
from .trajectory import Observation, Trajectory, Turn

MIN_TURN_FREED = 0.03
MAX_EDIT_TURNS = 6
MAX_EDIT_TURN_SHARE = 0.15

_NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])")
_QUOTED_RE = re.compile(r"\"([^\"\n]{1,200})\"|'([^'\n]{1,200})'|`([^`\n]{1,200})`")
_CODE_IDENT_RE = re.compile(r"\b(?:[A-Za-z]\w*_\w*|_\w+|[a-z]+[A-Z]\w*)\b")


def checked_items(text: str) -> List[str]:
    """Numbers, paths, identifiers and quoted strings that a summary asserts."""
    items: Dict[str, None] = {}
    for m in PATH_RE.finditer(text):
        items[m.group().rstrip(".")] = None
    for m in _CODE_IDENT_RE.finditer(text):
        items[m.group()] = None
    for m in _QUOTED_RE.finditer(text):
        items[next(g for g in m.groups() if g is not None)] = None
    for m in _NUMBER_RE.finditer(text):
        items[m.group()] = None
    return list(items)


@dataclass
class AuditEntry:
    turn: int
    op: Op
    verdict: str                    # kept | rejected
    reason: str = ""

    def to_json(self) -> dict:
        return {"turn": self.turn, "op": self.op.to_json(), "verdict": self.verdict,
                "reason": self.reason}


@dataclass
class AuditResult:
    outputs: List[str]
    reminders: Dict[int, str]
    entries: List[AuditEntry] = field(default_factory=list)
    edit_turns: List[int] = field(default_factory=list)
    discarded: bool = False
    discard_reason: str = ""

    def annotated(self, traj: Trajectory, budget: Optional[int]) -> Trajectory:
        turns = [Turn(out, [Observation(o.tool, o.text, o.role) for o in tr.observations],
                      self.reminders.get(t))
                 for t, (out, tr) in enumerate(zip(self.outputs, traj.turns), start=1)]
        meta = dict(traj.meta)
        meta["budget"] = budget
        return Trajectory(traj.id, traj.system, traj.task, turns, meta)


def final_audit(ctx: Context, points: List[DecisionPoint], fmt: ChatFormat = DEFAULT_FORMAT,
                counter: Counter = approx_tokens) -> AuditResult:
    by_turn = {dp.turn: dp for dp in points}
    reminders = {dp.turn: dp.trigger for dp in points if dp.trigger in ("soft", "hard")}
    all_text = "\n".join([b.text for b in ctx.blocks] + ctx.actions)
    written = _written_texts(points)
    rp = Replayer(ctx, fmt, counter)
    res = AuditResult([], reminders)
    for t in range(1, ctx.T + 1):
        dp = by_turn.get(t)
        if t in reminders:
            rp.add_reminder(reminders[t])
        ops: List[Op] = []
        note = ""
        if dp is not None:
            note = dp.note if dp.outcome in ("edited", "declined") else ""
            for op in dp.ops:
                reason = _check_op(ctx, rp, op, t, dp.note, all_text, written)
                res.entries.append(AuditEntry(t, op, "rejected" if reason else "kept", reason))
                if not reason:
                    ops.append(op)
            envelopes, ops = rp.compile(ops)
            if ops:
                before, after = rp.measure(envelopes)
                if before and (before - after) / before < MIN_TURN_FREED:
                    for e in res.entries:
                        if e.turn == t and e.verdict == "kept":
                            e.verdict, e.reason = "rejected", "turn frees less than 3%"
                    ops = []
            if not ops and dp.outcome == "edited":
                note = ""  # no edit survived: the turn trains as a plain turn
            if dp.trigger == "hard" and not ops:
                res.discarded = True
                res.discard_reason = f"hard reminder at turn {t} ended without an edit"
        envelopes, ops = rp.compile(ops)
        output = compose_output(note, envelopes, ctx.actions[t - 1])
        rp.finish_turn(t, output, ops)
        res.outputs.append(output)
        if ops:
            res.edit_turns.append(t)
    n = len(res.edit_turns)
    if not res.discarded and n > MAX_EDIT_TURNS and n > MAX_EDIT_TURN_SHARE * ctx.T:
        res.discarded = True
        res.discard_reason = f"{n} of {ctx.T} turns carry edits"
    return res


def _written_texts(points: List[DecisionPoint]) -> Dict[int, List[str]]:
    """Summary and note texts written at each turn, and the visible rationale."""
    out: Dict[int, List[str]] = {}
    for dp in points:
        out.setdefault(dp.turn, []).append(dp.note)
        out[dp.turn].extend(op.text for op in dp.ops if op.text)
    return out


def _source_text(ctx: Context, rp: Replayer, ref: str) -> str:
    blk = rp.state.blocks.get(rp.addr_of.get(ref, -1))
    text = blk.text if blk is not None else ""
    if ref.startswith("b"):
        rec = ctx.blocks[int(ref[1:])]
        if rec.call is not None:
            text = f"{rec.call.name} {rec.call.arguments}\n{text}"
    return text


def _check_op(ctx: Context, rp: Replayer, op: Op, t: int, note: str, all_text: str,
              written: Dict[int, List[str]]) -> str:
    source = all_text if op.op == "append" else _source_text(ctx, rp, op.ref)
    if op.text is not None:
        for item in checked_items(op.text):
            if item not in source:
                return f"unsupported: {item!r} is not in the source"
    if op.op == "append":
        return ""
    current = rp.state.blocks.get(rp.addr_of.get(op.ref, -1))
    if current is None:
        return ""
    kept_text = op.text or ""
    removed = [lit.text for lit in ctx.index.rare(current.text) if lit.text not in kept_text]
    for lit in removed:
        u = next((u for u in range(t + 1, ctx.T + 1) if lit in ctx.actions[u - 1]), None)
        if u is None:
            continue
        visible = [ctx.actions[v - 1] for v in range(t, u)]
        visible += [b.text for b in ctx.blocks if t + 1 <= b.entry_turn <= u]
        for v in range(1, u + 1):
            visible += written.get(v, [])
        if not any(lit in s for s in visible):
            return f"removed literal {lit!r} reappears at turn {u}"
    return ""
