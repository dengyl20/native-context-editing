"""Forward replay of a trajectory through Eq. 1 with stable block references.

Edits produced during annotation refer to blocks by a stable reference:
``b<i>`` for block ``i`` of the unedited replay, ``n<k>`` for the ``k``-th
note appended by an edit, and ``r<address>`` for the note that a rewrite of
a dropped block leaves behind. Addresses depend on which notes were appended
before, so they are resolved only when an edit is compiled into the grammar
on the state at hand. This lets the audit remove an edit and replay the rest
without renumbering anything by hand.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..grammar import Append, Drop, Rewrite, parse_output, serialize
from ..render import DEFAULT_FORMAT, ChatFormat, Counter, approx_tokens, render_item, render_text
from ..runtime import REMINDER_TEXT, StepResult, apply_output, execute
from ..state import State
from .release import Context


@dataclass
class Op:
    """One edit in the teacher's form, targeting a stable reference."""
    op: str                         # drop | rewrite | append
    ref: Optional[str] = None       # target of drop / rewrite; the new note of an append
    text: Optional[str] = None

    def to_json(self) -> dict:
        d = {"op": self.op}
        if self.ref is not None:
            d["ref"] = self.ref
        if self.text is not None:
            d["text"] = self.text
        return d

    @classmethod
    def from_json(cls, d: dict) -> "Op":
        return cls(d["op"], d.get("ref"), d.get("text"))


def compose_output(note: str, envelopes: List[str], recorded: str) -> str:
    """An editing turn: the rationale, the edits, then the recorded output."""
    parts = [p for p in (note.strip(), "\n".join(envelopes), recorded) if p]
    return "\n".join(parts)


class Replayer:
    def __init__(self, ctx: Context, fmt: ChatFormat = DEFAULT_FORMAT,
                 counter: Counter = approx_tokens):
        self.ctx, self.fmt, self.counter = ctx, fmt, counter
        self.state = State()
        self.addr_of: Dict[str, int] = {}
        self.ref_of: Dict[int, str] = {}
        self.rewritten: set = set()
        self.notes = 0
        self._next_block = 0
        self._add_blocks_entering(1)

    # -- growth ------------------------------------------------------------

    def _bind(self, ref: str, address: int) -> None:
        self.addr_of[ref] = address
        self.ref_of[address] = ref

    def _add_blocks_entering(self, turn: int) -> None:
        blocks = self.ctx.blocks
        while self._next_block < len(blocks) and blocks[self._next_block].entry_turn == turn:
            b = blocks[self._next_block]
            role = "system" if b.role == "system" else ("tool" if b.role == "tool" else "user")
            blk = self.state.add_block(role, b.text, tool_name=b.tool, locked=b.locked)
            self._bind(f"b{b.index}", blk.address)
            self._next_block += 1

    def add_reminder(self, level: str) -> None:
        self.state.add_reminder(level, REMINDER_TEXT[level])

    def new_note_ref(self) -> str:
        ref = f"n{self.notes}"
        self.notes += 1
        return ref

    def finish_turn(self, t: int, output: str, ops: List[Op]) -> StepResult:
        """Execute the turn's output, then let the observations of turn ``t`` enter."""
        step = apply_output(self.state, output)
        self._bind_new_notes(step, ops)
        self._add_blocks_entering(t + 1)
        return step

    def _bind_new_notes(self, step: StepResult, ops: List[Op]) -> None:
        # ``ops`` are the ops kept by :meth:`compile`. Every op except a drop
        # has an envelope of its own, so the non-drop results line up with
        # the non-drop ops. Appends, and rewrites redirected to an append,
        # create notes.
        results = [r for r in step.results if r.edit.op != "drop"]
        for op, r in zip([op for op in ops if op.op != "drop"], results):
            if r.new_address is not None:
                if op.op == "append":
                    op.ref = op.ref or self.new_note_ref()
                    self._bind(op.ref, r.new_address)
                else:  # a rewrite redirected to an append
                    self._bind(f"r{r.new_address}", r.new_address)
            elif op.op == "rewrite" and r.status == "applied":
                self.rewritten.add(op.ref)

    # -- views -------------------------------------------------------------

    def tokens(self) -> int:
        return self.counter(render_text(self.state, self.fmt))

    def block_tokens(self, address: int) -> int:
        return self.counter(render_item(self.state.blocks[address], self.fmt))

    def live_refs(self) -> List[Tuple[str, int]]:
        return [(self.ref_of[b.address], b.address) for b in self.state.live_blocks()]

    def compile(self, ops: List[Op]) -> Tuple[List[str], List[Op]]:
        """Grammar envelopes for ``ops`` on the current state. Ops whose target
        no longer exists are left out; consecutive drops share one envelope."""
        envelopes: List[str] = []
        kept: List[Op] = []
        drops: List[int] = []

        def flush() -> None:
            if drops:
                envelopes.append(serialize([Drop(tuple(drops))]))
                drops.clear()

        for op in ops:
            if op.op == "drop":
                if op.ref in self.addr_of and self.addr_of[op.ref] in self.state.blocks:
                    drops.append(self.addr_of[op.ref])
                    kept.append(op)
                continue
            flush()
            if op.op == "rewrite":
                if op.ref not in self.addr_of:
                    continue
                envelopes.append(serialize([Rewrite(self.addr_of[op.ref], op.text)]))
            else:
                envelopes.append(serialize([Append(op.text)]))
            kept.append(op)
        flush()
        return envelopes, kept

    def measure(self, envelopes: List[str]) -> Tuple[int, int]:
        """Context size before and after the envelopes would execute."""
        before = self.tokens()
        trial = self.state.copy()
        parsed = parse_output("".join(envelopes))
        if any(r.executed for r in execute(trial, parsed.edits, parsed.raws)):
            trial.clear_reminders()
        return before, self.counter(render_text(trial, self.fmt))
