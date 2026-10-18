"""The annotation pipeline: recorded trajectory -> annotated trajectory.

    blocks -> offline teacher (release analysis) -> online teacher (edits at
    decision points) -> final audit -> annotated trajectory

Only the online teacher writes edits; the offline teacher decides which
blocks it may touch, and the audit removes edits that fail a mechanical
check. :func:`nce.distill.distill` then cuts the annotated trajectory into
training segments.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence

from ..render import DEFAULT_FORMAT, ChatFormat, Counter, approx_tokens
from .audit import AuditResult, final_audit
from .online import BUDGET_TIERS, DecisionPoint, OnlineTeacher, generate_edits, select_budget
from .release import Context, OfflineTeacher, ReleaseAnalysis, release_analysis
from .trajectory import ToolCallParser, Trajectory, parse_tool_calls


@dataclass
class Annotation:
    trajectory: Trajectory          # the recorded trajectory
    context: Context
    releases: ReleaseAnalysis
    budget: Optional[int]
    decisions: List[DecisionPoint]
    audit: AuditResult

    @property
    def discarded(self) -> bool:
        return self.audit.discarded

    def annotated(self) -> Trajectory:
        """The trajectory with every turn's rationale and edits in its output."""
        return self.audit.annotated(self.trajectory, self.budget)

    def report(self) -> dict:
        return {
            "id": self.trajectory.id,
            "turns": self.trajectory.T,
            "blocks": [{"block": b.index, "entry_turn": b.entry_turn, "source": b.source,
                        **({"locked": True} if b.locked else {})}
                       for b in self.context.blocks],
            "budget": self.budget,
            **self.releases.to_json(),
            "decision_points": [dp.to_json() for dp in self.decisions],
            "audit": [e.to_json() for e in self.audit.entries],
            "edit_turns": self.audit.edit_turns,
            "discarded": self.audit.discarded,
            "discard_reason": self.audit.discard_reason,
        }


def annotate(traj: Trajectory, offline: OfflineTeacher, online: OnlineTeacher, *,
             tiers: Sequence[int] = BUDGET_TIERS, fmt: ChatFormat = DEFAULT_FORMAT,
             counter: Counter = approx_tokens,
             tool_calls: ToolCallParser = parse_tool_calls) -> Annotation:
    ctx = Context(traj, tool_calls)
    ra = release_analysis(ctx, offline)
    budget = select_budget(ctx, ra, tiers, fmt, counter)
    decisions = generate_edits(ctx, ra, online, budget, fmt, counter)
    audit = final_audit(ctx, decisions, fmt, counter)
    return Annotation(traj, ctx, ra, budget, decisions, audit)
