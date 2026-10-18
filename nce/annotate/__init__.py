"""Building editing supervision from recorded trajectories (Section 3.2).

Recorded trajectories contain no edits. The offline teacher assigns every
block a release point from hindsight (:mod:`.release`), the online teacher
writes edits at decision points while seeing only the present
(:mod:`.online`), and a final audit removes edits that fail a mechanical
check (:mod:`.audit`). Both teachers are interfaces; :mod:`.rules` provides
deterministic implementations that run without any model.
"""
from .audit import AuditResult, final_audit
from .literals import Literal, LiteralIndex, extract_literals
from .online import (BUDGET_TIERS, Decision, DecisionPoint, DecisionView, OnlineTeacher,
                     TeacherEdit, ViewBlock, generate_edits, select_budget)
from .pipeline import Annotation, annotate
from .release import (Context, ForwardResult, Milestone, OfflineTeacher, Release, ReleaseAnalysis,
                      ReleasePoint, release_analysis)
from .rules import RuleBasedOfflineTeacher, RuleBasedOnlineTeacher
from .trajectory import (BlockRecord, Observation, ToolCall, Trajectory, Turn, blockize,
                         load_trajectory, parse_tool_calls)
