"""Offline teacher: release analysis (Section 3.2, Appendix B).

The offline teacher reads the whole trajectory and assigns each block a
release point ``r_hat``, the turn after which the block may be edited. It
keeps every block by default and releases one only by citing the event that
ended its use, at turn ``k_b``. A mechanical literal check then traces the
rare literals of the block through later actions; ``lambda_b`` is the last
turn at which one reappears, and

    r_hat = max(k_b, lambda_b).

The check can only postpone a release. A drop whose literal reappears
becomes a summary. Two clamps postpone further: a block read from a file is
not released before the last turn that edits that file, and a block the
teacher marks as the blueprint of the final solution is held until the turn
that writes the solution out.

A second pass revisits the kept blocks. Candidates come from the teacher's
nominations, from a mechanical rule (tool results whose rare literals stop
reappearing at least three turns before the end), and from injected
reminders and bare continuation messages. A review must cite the event that
ended the use of each candidate. A claim that a later block supersedes the
candidate is verified mechanically: every distinctive line of the candidate
must appear in that block. Approved releases pass the same literal check.

The teacher is an interface (:class:`OfflineTeacher`); any implementation,
an LLM or a set of rules, plugs in. :mod:`nce.annotate.rules` ships a
deterministic one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .literals import Literal, LiteralIndex, last_reappearance
from .trajectory import (BlockRecord, ToolCall, ToolCallParser, Trajectory, blockize,
                         parse_tool_calls)

TO_SUMMARY = "to_summary"
TO_DROP = "to_drop"

# Tool names that read a file, and tool names that change one. Override per harness.
READ_TOOLS = ("read", "Read", "view", "cat")
EDIT_TOOLS = ("edit", "Edit", "write", "Write", "MultiEdit", "apply_patch", "str_replace")
PATH_KEYS = ("path", "file_path", "filename")

SECOND_PASS_TAIL = 3  # literals must stop reappearing this many turns before the end

_CONTINUATION_RE = re.compile(r"^\s*(continue|go on|please continue|keep going)\W*\s*$", re.I)
_REMINDER_PREFIX = "[context-monitor]"


@dataclass
class Release:
    """A release proposed by the teacher."""
    block: int
    after_turn: int                 # k_b: the turn of the cited event
    kind: str                       # to_summary | to_drop
    trigger: str                    # one sentence naming the turn and the action
    superseded_by: Optional[int] = None  # set when the cause is a superseding block


@dataclass
class Milestone:
    after_turn: int
    description: str


@dataclass
class ForwardResult:
    releases: List[Release] = field(default_factory=list)
    milestones: List[Milestone] = field(default_factory=list)  # at most two are used
    hold: Dict[int, int] = field(default_factory=dict)  # blueprint block -> turn writing the solution


@dataclass
class ReleasePoint:
    block: int
    k: int                          # k_b
    lam: Optional[int]              # lambda_b, None if no literal reappears
    r_hat: int
    kind: str
    trigger: str
    stage: str                      # forward | second_pass
    postponed_by: List[str] = field(default_factory=list)  # literal | file_edit | blueprint
    reappeared: List[str] = field(default_factory=list)    # literals that moved the release

    def to_json(self) -> dict:
        return {"block": self.block, "k": self.k, "lambda": self.lam, "r_hat": self.r_hat,
                "kind": self.kind, "trigger": self.trigger, "stage": self.stage,
                "postponed_by": self.postponed_by, "reappeared": self.reappeared}


class Context:
    """Everything the teachers and checks read about one trajectory."""

    def __init__(self, traj: Trajectory, tool_calls: ToolCallParser = parse_tool_calls,
                 read_tools: Sequence[str] = READ_TOOLS, edit_tools: Sequence[str] = EDIT_TOOLS):
        self.traj = traj
        self.T = traj.T
        self.blocks: List[BlockRecord] = blockize(traj, tool_calls)
        self.actions: List[str] = [tr.output for tr in traj.turns]
        self.calls: List[List[ToolCall]] = [tool_calls(a) for a in self.actions]
        self.index = LiteralIndex([b.text for b in self.blocks] + self.actions)
        self.read_tools, self.edit_tools = tuple(read_tools), tuple(edit_tools)

    def rare(self, i: int) -> List[Literal]:
        return self.index.rare(self.blocks[i].text)

    def read_path(self, i: int) -> Optional[str]:
        call = self.blocks[i].call
        if call is not None and call.name in self.read_tools:
            return call_path(call)
        return None

    def last_edit_of(self, path: str) -> Optional[int]:
        last = None
        for u, calls in enumerate(self.calls, start=1):
            if any(c.name in self.edit_tools and call_path(c) == path for c in calls):
                last = u
        return last

    def is_continuation(self, i: int) -> bool:
        b = self.blocks[i]
        return b.role == "user" and i > 1 and (
            bool(_CONTINUATION_RE.match(b.text)) or b.text.startswith(_REMINDER_PREFIX))


def call_path(call: ToolCall) -> Optional[str]:
    for k in PATH_KEYS:
        if isinstance(call.arguments.get(k), str):
            return call.arguments[k]
    return None


class OfflineTeacher:
    """Interface of the offline teacher. All three methods see the whole trajectory."""

    def forward(self, ctx: Context) -> ForwardResult:
        """Forward pass: releases with cited events, and up to two milestones."""
        raise NotImplementedError

    def nominate(self, ctx: Context, kept: List[int]) -> List[int]:
        """Second pass, recall-oriented: kept blocks on abandoned or superseded branches."""
        return []

    def review(self, ctx: Context, block: int) -> Optional[Release]:
        """Second pass, strict: a release with a cited event, or None to keep the block."""
        return None


# ------------------------------------------------------------------ checks


def literal_check(ctx: Context, rel: Release, stage: str,
                  hold: Optional[Dict[int, int]] = None) -> ReleasePoint:
    """Turn a proposed release into a release point. Only postpones."""
    b = ctx.blocks[rel.block]
    k = max(rel.after_turn, b.entry_turn)
    rare = ctx.rare(rel.block)
    # Identifiers are traced only for drops, since a summary keeps them.
    kinds = None if rel.kind == TO_DROP else {"path", "integer", "hex", "decimal", "line_number"}
    lam = last_reappearance(rare, ctx.actions, after=k, kinds=kinds)
    kind, postponed, reappeared = rel.kind, [], []
    r_hat = k
    if lam is not None:
        r_hat = max(k, lam)
        postponed.append("literal")
        reappeared = sorted({lit.text for lit in rare
                             if (kinds is None or lit.kind in kinds)
                             and any(lit.text in ctx.actions[u - 1] for u in range(k + 1, lam + 1))})
        if kind == TO_DROP:
            kind = TO_SUMMARY
    path = ctx.read_path(rel.block)
    if path is not None:
        last_edit = ctx.last_edit_of(path)
        if last_edit is not None and last_edit > r_hat:
            r_hat = last_edit
            postponed.append("file_edit")
    if hold and rel.block in hold and hold[rel.block] > r_hat:
        r_hat = hold[rel.block]
        postponed.append("blueprint")
    return ReleasePoint(rel.block, k, lam, r_hat, kind, rel.trigger, stage, postponed, reappeared)


def distinctive_lines(text: str) -> List[str]:
    """The lines a superseding block must reproduce. This implementation
    treats every non-blank line as distinctive."""
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def verify_supersession(ctx: Context, block: int, by: int) -> Optional[str]:
    """None if block ``by`` contains every distinctive line of ``block``,
    otherwise the first missing line."""
    if not (0 <= by < len(ctx.blocks)) or ctx.blocks[by].entry_turn <= ctx.blocks[block].entry_turn:
        return "<superseding block is not later>"
    target = ctx.blocks[by].text
    for ln in distinctive_lines(ctx.blocks[block].text):
        if ln not in target:
            return ln
    return None


# ---------------------------------------------------------------- analysis


@dataclass
class ReleaseAnalysis:
    points: Dict[int, ReleasePoint]
    milestones: List[Milestone]
    second_pass_log: List[dict]

    def r_hat(self, block: int, T: int) -> int:
        """Release point of ``block``; ``T`` (never editable) if it is kept."""
        p = self.points.get(block)
        return p.r_hat if p is not None else T

    def to_json(self) -> dict:
        return {"releases": [self.points[i].to_json() for i in sorted(self.points)],
                "milestones": [{"after_turn": m.after_turn, "description": m.description}
                               for m in self.milestones],
                "second_pass": self.second_pass_log}


def release_analysis(ctx: Context, teacher: OfflineTeacher) -> ReleaseAnalysis:
    fwd = teacher.forward(ctx)
    points: Dict[int, ReleasePoint] = {}
    for rel in fwd.releases:
        if _releasable(ctx, rel.block) and rel.block not in points:
            points[rel.block] = literal_check(ctx, rel, "forward", fwd.hold)

    kept = [i for i in range(len(ctx.blocks)) if _releasable(ctx, i) and i not in points]
    candidates: Dict[int, str] = {}
    for i in teacher.nominate(ctx, kept):
        if i in kept:
            candidates.setdefault(i, "nominated")
    for i in kept:
        b = ctx.blocks[i]
        if b.role == "tool":
            last = last_reappearance(ctx.rare(i), ctx.actions, after=b.entry_turn - 1)
            if last is None or last <= ctx.T - SECOND_PASS_TAIL:
                candidates.setdefault(i, "literals_stopped")
        if ctx.is_continuation(i):
            candidates.setdefault(i, "continuation")

    log = []
    for i in sorted(candidates):
        entry = {"block": i, "source": candidates[i]}
        rel = teacher.review(ctx, i)
        if rel is None:
            entry["verdict"] = "kept"
        elif rel.superseded_by is not None and verify_supersession(ctx, i, rel.superseded_by):
            entry["verdict"] = "rejected"
            entry["reason"] = (f"block {rel.superseded_by} lacks the line "
                               f"{verify_supersession(ctx, i, rel.superseded_by)!r}")
        else:
            points[i] = literal_check(ctx, rel, "second_pass", fwd.hold)
            entry["verdict"] = "released"
        log.append(entry)
    return ReleaseAnalysis(points, fwd.milestones[:2], log)


def _releasable(ctx: Context, i: int) -> bool:
    # The locked system prompt is never released.
    return 0 <= i < len(ctx.blocks) and not ctx.blocks[i].locked
