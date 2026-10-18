"""Distillation with evolving contexts (Section 3.3).

An annotated trajectory is replayed forward through Eq. 1: the outputs are
the recorded actions with the teacher's rationale and edits at decision
points, and the observations are the recorded ones. Every turn whose edits
execute closes a segment, and the next segment opens with the rendering of
the state those edits produce. Each segment is an ordinary causal sequence:
its prefix reflects every earlier edit.

A segment is a list of pieces ``(text, loss)``. Model outputs (actions,
rationales and edits alike) and the closing assistant tag carry
``loss = 1``; the rendered prefix, observations and reminders carry
``loss = 0``. Within a segment the concatenated pieces always equal the
rendering of the current state, which :func:`distill` asserts at every turn.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Tuple

from .render import DEFAULT_FORMAT, ChatFormat, render_text
from .runtime import REMINDER_TEXT, Runtime
from .state import State


@dataclass
class Segment:
    trajectory_id: str
    index: int
    first_turn: int
    last_turn: int = 0
    pieces: List[Tuple[str, int]] = field(default_factory=list)
    edits: int = 0                  # executed edits in the closing turn

    @property
    def text(self) -> str:
        return "".join(t for t, _ in self.pieces)

    def supervised(self) -> str:
        return "".join(t for t, m in self.pieces if m)

    def char_mask(self) -> List[int]:
        """One loss flag per character of :attr:`text`."""
        return [m for t, m in self.pieces for _ in t]

    def to_json(self) -> dict:
        return {"id": f"{self.trajectory_id}#{self.index}", "turns": [self.first_turn, self.last_turn],
                "edits": self.edits,
                "pieces": [{"text": t, "loss": m} for t, m in self.pieces]}


def _add(seg: Segment, text: str, loss: int) -> None:
    if not text:
        return
    if seg.pieces and seg.pieces[-1][1] == loss:
        seg.pieces[-1] = (seg.pieces[-1][0] + text, loss)
    else:
        seg.pieces.append((text, loss))


def distill(traj, fmt: ChatFormat = DEFAULT_FORMAT) -> List[Segment]:
    """Cut an annotated :class:`~nce.annotate.trajectory.Trajectory` into segments."""
    rt = Runtime(fmt)
    rt.add_block("system", traj.system, locked=True)
    rt.add_block("user", traj.task)
    segments: List[Segment] = []
    seg = None
    for t, turn in enumerate(traj.turns, start=1):
        if turn.reminder:
            rt.state.add_reminder(turn.reminder, REMINDER_TEXT[turn.reminder])
        prompt = render_text(rt.state, fmt, add_generation_prompt=True)
        if seg is None:
            seg = Segment(traj.id, len(segments), t)
            _add(seg, prompt, 0)
        else:
            assert prompt.startswith(seg.text), "a segment must extend its own prefix"
            _add(seg, prompt[len(seg.text):], 0)
        step = rt.step(turn.output)
        if step.executed:
            _add(seg, turn.output, 1)
        else:
            _add(seg, step.action_text, 1)
        _add(seg, fmt.assistant_close, 1)
        seg.last_turn = t
        for obs in turn.observations:
            role = "tool" if obs.role == "tool" else "user"
            rt.add_block(role, obs.text, tool_name=obs.tool if role == "tool" else None)
        if step.executed:
            seg.edits = sum(r.executed for r in step.results)
            segments.append(seg)
            seg = None
        else:
            # Without an executed edit the rendering only grows.
            assert render_text(rt.state, fmt).startswith(seg.text)
    if seg is not None:
        segments.append(seg)
    return segments


def write_jsonl(segments: Iterable[Segment], path: str) -> int:
    import json
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for s in segments:
            f.write(json.dumps(s.to_json(), ensure_ascii=False) + "\n")
            n += 1
    return n
