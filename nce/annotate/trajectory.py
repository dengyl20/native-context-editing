"""Recorded trajectories and their blocks.

A trajectory runs for ``T`` turns from a task. At turn ``t`` (counted from
one) the agent writes output ``a_t`` and receives the observations of that
turn. Replaying it with every edit empty splits it into blocks: the system
prompt (locked), the task, and every tool result each form one block. The
block that enters before turn ``t`` has entry turn ``t``, so the system
prompt and the task enter at turn 1 and the results of turn ``t`` at
``t + 1``. Block ``i`` is the ``i``-th block created, which is also its
address in the unedited replay.

The JSON layout read by :func:`load_trajectory`::

    {"id": "...", "system": "...", "task": "...",
     "turns": [{"output": "...", "observations": [{"tool": "read", "text": "..."}]}]}

An annotated trajectory has the same layout: each output carries the
rationale and edits of its turn, and a turn may name the ``reminder``
(``soft`` or ``hard``) that precedes it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass
class ToolCall:
    name: str
    arguments: Dict


@dataclass
class Observation:
    tool: Optional[str]
    text: str
    role: str = "tool"  # tool | user


@dataclass
class Turn:
    output: str
    observations: List[Observation] = field(default_factory=list)
    reminder: Optional[str] = None  # soft | hard: a reminder precedes this turn's output


@dataclass
class Trajectory:
    id: str
    system: str
    task: str
    turns: List[Turn]
    meta: Dict = field(default_factory=dict)

    @property
    def T(self) -> int:
        return len(self.turns)

    def action(self, t: int) -> str:
        """The recorded output ``a_t`` (``t`` from one)."""
        return self.turns[t - 1].output

    def to_json(self) -> dict:
        return {
            "id": self.id, "system": self.system, "task": self.task,
            "turns": [_turn_json(tr) for tr in self.turns],
            **({"meta": self.meta} if self.meta else {}),
        }

    @classmethod
    def from_json(cls, d: dict) -> "Trajectory":
        turns = [Turn(tr["output"], [Observation(o.get("tool"), o["text"], o.get("role", "tool"))
                                     for o in tr.get("observations", [])], tr.get("reminder"))
                 for tr in d["turns"]]
        # :meth:`to_json` writes the extra keys flat, so that a trajectory file
        # stays the plain layout documented above. A file that has already been
        # through one round trip may instead carry them nested under "meta";
        # both are read the same way and neither nests again.
        meta = {k: v for k, v in d.items() if k not in ("id", "system", "task", "turns", "meta")}
        if isinstance(d.get("meta"), dict):
            meta = {**meta, **d["meta"]}
        return cls(d["id"], d["system"], d["task"], turns, meta)


def _turn_json(tr: Turn) -> dict:
    d = {"output": tr.output, "observations": [_obs_json(o) for o in tr.observations]}
    if tr.reminder is not None:
        d["reminder"] = tr.reminder
    return d


def _obs_json(o: Observation) -> dict:
    d = {"tool": o.tool, "text": o.text}
    if o.role != "tool":
        d["role"] = o.role
    return d


def load_trajectory(path: str) -> Trajectory:
    with open(path, encoding="utf-8") as f:
        return Trajectory.from_json(json.load(f))


# ------------------------------------------------------------- tool calls

_TOOL_CALL_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.S)


def parse_tool_calls(output: str) -> List[ToolCall]:
    """Tool calls written as ``<tool_call>{"name": ..., "arguments": {...}}</tool_call>``.

    This is the convention of the bundled examples. Pass a different parser
    to :func:`blockize` and the annotation pipeline for other formats.
    """
    calls = []
    for m in _TOOL_CALL_RE.finditer(output):
        try:
            d = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        calls.append(ToolCall(d.get("name", ""), d.get("arguments") or {}))
    return calls


ToolCallParser = Callable[[str], List[ToolCall]]


# ----------------------------------------------------------------- blocks


@dataclass
class BlockRecord:
    index: int
    role: str                      # system | user | tool
    text: str
    entry_turn: int
    tool: Optional[str] = None
    call: Optional[ToolCall] = None  # the call that produced a tool result
    locked: bool = False

    @property
    def source(self) -> str:
        """A short label: ``system``, ``task``, ``user`` or ``tool:<call>``."""
        if self.role == "tool":
            if self.call is not None:
                args = ", ".join(f"{k}={v}" for k, v in self.call.arguments.items())
                return f"{self.call.name}({args})"
            return self.tool or "tool"
        if self.index == 1:
            return "task"
        return self.role


def blockize(traj: Trajectory, tool_calls: ToolCallParser = parse_tool_calls) -> List[BlockRecord]:
    blocks = [BlockRecord(0, "system", traj.system, 1, locked=True),
              BlockRecord(1, "user", traj.task, 1)]
    for t, turn in enumerate(traj.turns, start=1):
        calls = tool_calls(turn.output)
        tool_obs = 0
        for obs in turn.observations:
            call = None
            if obs.role == "tool":
                call = calls[tool_obs] if tool_obs < len(calls) else None
                tool_obs += 1
            blocks.append(BlockRecord(len(blocks), obs.role, obs.text, t + 1,
                                      tool=obs.tool, call=call))
    return blocks
