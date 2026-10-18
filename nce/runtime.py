"""``Execute(S, e)`` and the turn step of Eq. 1.

    S_{t+1} = Execute(S_t, e_t) (+) (a_t, b_t)

:func:`execute` checks addresses and permissions and applies the edits of one
turn in the order they were written. :func:`apply_output` is the full turn
step for one model output: parse, execute, strip the envelopes, and append
the remaining text (the rationale and the action) to the action history. The
observation ``b_t`` then enters through :meth:`State.add_block`.

:class:`Runtime` wraps a state into an agent session with budget reminders.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .grammar import Append, Drop, Malformed, ParsedEdit, Rewrite, edit_to_json, parse_output
from .render import DEFAULT_FORMAT, ChatFormat, Counter, approx_tokens, render_text
from .state import AddressExhausted, Block, State

APPLIED = "applied"
APPLIED_AS_APPEND = "applied_as_append"
REJECTED = "rejected"


@dataclass
class EditResult:
    edit: ParsedEdit
    status: str                       # applied | applied_as_append | rejected
    reason: Optional[str] = None      # why it was rejected or redirected
    new_address: Optional[int] = None  # set when a block was created

    @property
    def executed(self) -> bool:
        return self.status in (APPLIED, APPLIED_AS_APPEND)

    def to_json(self) -> dict:
        d = {"edit": edit_to_json(self.edit), "status": self.status}
        if self.reason is not None:
            d["reason"] = self.reason
        if self.new_address is not None:
            d["new_address"] = self.new_address
        return d


def execute(state: State, edits: List[ParsedEdit],
            raws: Optional[List[str]] = None) -> List[EditResult]:
    """Apply the edits of one turn in order. Each edit is atomic: if any
    check fails it changes nothing.

    ``raws`` holds each envelope as it was written; an envelope repeated
    verbatim within the turn executes once and later copies are rejected
    with reason ``duplicate``. Without ``raws`` the canonical text is used.
    """
    results: List[EditResult] = []
    seen = set()
    for i, e in enumerate(edits):
        if isinstance(e, Malformed):
            results.append(EditResult(e, REJECTED, e.reason))
            continue
        key = raws[i] if raws is not None else e.to_text()
        if key in seen:
            results.append(EditResult(e, REJECTED, "duplicate"))
            continue
        seen.add(key)
        results.append(_execute_one(state, e))
    return results


def _check_target(state: State, n: int) -> Optional[str]:
    if not state.pool.was_issued(n):
        return "unknown_address"
    if n not in state.blocks:
        return "not_live"
    if state.blocks[n].locked:
        return "locked"
    return None


def _execute_one(state: State, e) -> EditResult:
    if isinstance(e, Drop):
        targets = list(dict.fromkeys(e.addresses))  # a repeated address counts once
        for n in targets:
            reason = _check_target(state, n)
            if reason:
                return EditResult(e, REJECTED, reason)
        for n in targets:
            state.drop(n)
        return EditResult(e, APPLIED)

    if isinstance(e, Rewrite):
        reason = _check_target(state, e.address)
        if reason == "not_live":
            # The block is gone; keep the text as a new note.
            res = _append(state, e, APPLIED_AS_APPEND)
            if res.status == APPLIED_AS_APPEND:
                res.reason = "not_live"
            return res
        if reason:
            return EditResult(e, REJECTED, reason)
        state.rewrite(e.address, e.text)
        return EditResult(e, APPLIED)

    if isinstance(e, Append):
        return _append(state, e, APPLIED)
    raise TypeError(e)


def _append(state: State, e, status: str) -> EditResult:
    try:
        blk = state.append_note(e.text)
    except AddressExhausted:
        return EditResult(e, REJECTED, "address_exhausted")
    return EditResult(e, status, new_address=blk.address)


@dataclass
class StepResult:
    action_text: str
    results: List[EditResult] = field(default_factory=list)
    stray_tokens: int = 0

    @property
    def executed(self) -> bool:
        return any(r.executed for r in self.results)

    @property
    def prefix_reusable(self) -> bool:
        """With no executed edit the next prompt extends the previous one, so
        its prefix cache stays valid; otherwise the prompt is rendered afresh."""
        return not self.executed

    def to_json(self) -> dict:
        return {
            "results": [r.to_json() for r in self.results],
            "action": self.action_text,
            "executed": self.executed,
            "prefix_reusable": self.prefix_reusable,
        }


def apply_output(state: State, output: str) -> StepResult:
    """One turn of Eq. 1 up to the observation: ``Execute(S_t, e_t) (+) a_t``.

    The edits never enter the context; only the text around them does. A
    reminder stays in the prompt until an edit executes.
    """
    parsed = parse_output(output)
    results = execute(state, parsed.edits, parsed.raws)
    step = StepResult(parsed.action_text, results, parsed.stray_tokens)
    if step.executed:
        state.clear_reminders()
    state.add_action(step.action_text)
    return step


# ----------------------------------------------------------------- reminders

SOFT_REMINDER = (
    "[context-monitor] Your context has grown sizeable; this is a good moment to tidy "
    "it up. If anything in it is no longer needed, condense or remove all of it in one "
    "pass — clear out everything that has served its purpose and leave the rest "
    "untouched; do not trim a little and save the rest for later. If there is very "
    "little worth cleaning up, or everything is still in use, you may explain why and "
    "decline — that is a reasonable choice."
)
HARD_REMINDER = (
    "[context-monitor] Your context is close to its limit and must be cleaned up now. "
    "Before anything else this turn, condense or remove everything that is no longer "
    "needed — clear all of it out and leave what you still rely on untouched. This is "
    "not optional; only if there is genuinely nothing that can be cleaned up may you "
    "explain why and skip it."
)
REMINDER_TEXT = {"soft": SOFT_REMINDER, "hard": HARD_REMINDER}


@dataclass
class ReminderPolicy:
    """Budget reminders at inference (Appendix A.4 of the paper).

    Soft at 70% of the budget, hard at 95%. After any reminder the runtime
    waits four turns, eight after a declined soft reminder, and it stops
    issuing soft reminders once two have been declined. The texts contain no
    numbers.
    """
    budget: int
    soft: float = 0.70
    hard: float = 0.95
    wait: int = 4
    wait_after_decline: int = 8
    max_declined_soft: int = 2
    last_turn: Optional[int] = None
    cooldown: int = 0
    declined_soft: int = 0

    def due(self, tokens: int, turn: int) -> Optional[str]:
        if self.last_turn is not None and turn - self.last_turn < self.cooldown:
            return None
        if tokens >= self.hard * self.budget:
            return "hard"
        if tokens >= self.soft * self.budget and self.declined_soft < self.max_declined_soft:
            return "soft"
        return None

    def issued(self, level: str, turn: int) -> None:
        self.last_turn, self.cooldown = turn, self.wait

    def outcome(self, level: str, executed: bool) -> None:
        if level == "soft" and not executed:
            self.declined_soft += 1
            self.cooldown = self.wait_after_decline


# ------------------------------------------------------------------- session


class Runtime:
    """One agent session: holds the state, issues reminders, executes edits.

        rt = Runtime(budget=64_000)
        rt.add_block("system", system_prompt, locked=True)
        rt.add_block("user", task)
        while True:
            out = model(rt.prompt())
            step = rt.step(out)               # edits executed, action recorded
            obs = env(step.action_text)
            rt.add_block("tool", obs, tool_name="bash")
    """

    def __init__(self, fmt: ChatFormat = DEFAULT_FORMAT, budget: Optional[int] = None,
                 counter: Counter = approx_tokens, policy: Optional[ReminderPolicy] = None):
        self.fmt = fmt
        self.counter = counter
        self.state = State()
        self.policy = policy or (ReminderPolicy(budget) if budget else None)
        self.turn = 0
        self._prompted_turn: Optional[int] = None
        self._pending: Optional[str] = None
        self.log: List[StepResult] = []

    def add_block(self, role: str, text: str, **kw) -> Block:
        return self.state.add_block(role, text, **kw)

    def context_tokens(self) -> int:
        return self.counter(render_text(self.state, self.fmt))

    def prompt(self) -> str:
        """Render the next prompt, adding a reminder first if one is due."""
        if self.policy is not None and self._prompted_turn != self.turn:
            level = self.policy.due(self.context_tokens(), self.turn)
            if level:
                self.state.add_reminder(level, REMINDER_TEXT[level])
                self.policy.issued(level, self.turn)
                self._pending = level
        self._prompted_turn = self.turn
        return render_text(self.state, self.fmt, add_generation_prompt=True)

    def step(self, output: str) -> StepResult:
        step = apply_output(self.state, output)
        if self._pending is not None:
            self.policy.outcome(self._pending, step.executed)
            self._pending = None
        self.turn += 1
        self.log.append(step)
        return step
