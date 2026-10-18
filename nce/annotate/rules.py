"""Deterministic, rule-based teachers.

These stand in for the two LLM teachers of the paper so that the whole
pipeline runs offline and reproducibly. They follow the same contracts:
the offline teacher cites an event for every release and keeps a block when
it cannot, and the online teacher sees only the decision view. The rules
are written for coding-agent trajectories in the bundled tool format and
are meant as a readable baseline; plug in your own :class:`OfflineTeacher`
and :class:`OnlineTeacher` for real data.
"""
from __future__ import annotations

import re
from typing import List, Optional

from .literals import last_reappearance
from .online import Decision, DecisionView, OnlineTeacher, TeacherEdit, ViewBlock
from .release import (TO_DROP, TO_SUMMARY, Context, ForwardResult, Milestone, OfflineTeacher,
                      Release, call_path)

SEARCH_TOOLS = ("grep", "Grep", "glob", "Glob", "find", "search")
COMMAND_TOOLS = ("bash", "Bash", "shell")

RECEIPT_RE = re.compile(
    r"^\s*(?:the file \S+ )?(?:has been|was) (?:updated|created|written|deleted)"
    r"(?: successfully)?\.?\s*$|^\s*(?:ok|done|success)\W*\s*$|^\s*$", re.I)
TEST_SUMMARY_RE = re.compile(r"\b\d+ (?:passed|failed)\b")
FAILURE_RE = re.compile(r"\b\d+ (?:failed|errors?)\b")


def is_receipt(text: str) -> bool:
    lines = [ln for ln in text.strip().splitlines() if ln.strip()]
    return len(lines) <= 1 and bool(RECEIPT_RE.match(text.strip().replace("\n", " ")))


def is_test_run(text: str) -> bool:
    return bool(TEST_SUMMARY_RE.search(text))


def passes_in_full(text: str) -> bool:
    return is_test_run(text) and not FAILURE_RE.search(text)


def _command(ctx: Context, i: int) -> Optional[str]:
    call = ctx.blocks[i].call
    if call is not None and call.name in COMMAND_TOOLS:
        return call.arguments.get("command")
    return None


class RuleBasedOfflineTeacher(OfflineTeacher):
    """Releases with an explicit cause:

    * an operation receipt is released to drop right after it arrives;
    * a search result is released to summary at the first later read of a
      file it points to;
    * a command output is released to summary at the next run of the same
      command, which supersedes it.

    Milestones are the first turns after which a test run passes in full
    following a failing one (at most two). In the second pass the teacher
    nominates reads of files that are never edited, and its review cites a
    later read of the same file that supersedes the block, the last action
    that uses it, or, for a file read once and never edited, the turn that
    moves on from it.
    """

    def forward(self, ctx: Context) -> ForwardResult:
        out = ForwardResult()
        for b in ctx.blocks:
            if b.role != "tool" or b.call is None:
                continue
            t0 = b.entry_turn - 1  # the turn of the call that produced the block
            if is_receipt(b.text):
                out.releases.append(Release(
                    b.index, b.entry_turn, TO_DROP,
                    f"Pure success receipt of the {b.call.name} call at turn {t0}."))
            elif b.call.name in SEARCH_TOOLS:
                u = self._first_read_of_hit(ctx, b.index)
                if u is not None:
                    out.releases.append(Release(
                        b.index, u, TO_SUMMARY,
                        f"Turn {u} read {call_path(ctx.calls[u - 1][0])} in full; "
                        f"the hit list only pointed the way."))
            elif _command(ctx, b.index):
                cmd = _command(ctx, b.index)
                u = next((u for u in range(b.entry_turn, ctx.T + 1)
                          if any(c.name in COMMAND_TOOLS and c.arguments.get("command") == cmd
                                 for c in ctx.calls[u - 1])), None)
                if u is not None:
                    out.releases.append(Release(
                        b.index, u, TO_SUMMARY,
                        f"Superseded by the rerun of `{cmd}` at turn {u}."))
        out.milestones = self._milestones(ctx)
        return out

    def _first_read_of_hit(self, ctx: Context, i: int) -> Optional[int]:
        text = ctx.blocks[i].text
        for u in range(ctx.blocks[i].entry_turn, ctx.T + 1):
            for c in ctx.calls[u - 1]:
                p = call_path(c)
                if c.name in ctx.read_tools and p and p in text:
                    return u
        return None

    def _milestones(self, ctx: Context) -> List[Milestone]:
        out, failing = [], False
        for b in ctx.blocks:
            if b.role != "tool" or not is_test_run(b.text):
                continue
            if passes_in_full(b.text) and failing:
                out.append(Milestone(b.entry_turn - 1, "the fix passes the full test suite"))
            failing = not passes_in_full(b.text)
        return out[:2]

    def nominate(self, ctx: Context, kept: List[int]) -> List[int]:
        out = []
        for i in kept:
            path = ctx.read_path(i)
            if path is not None and ctx.last_edit_of(path) is None:
                out.append(i)
        return out

    def review(self, ctx: Context, block: int) -> Optional[Release]:
        b = ctx.blocks[block]
        if ctx.is_continuation(block):
            return Release(block, b.entry_turn, TO_DROP,
                           f"A bare continuation message at turn {b.entry_turn}.")
        path = ctx.read_path(block)
        if path is not None:
            later = next((j for j in range(block + 1, len(ctx.blocks))
                          if ctx.read_path(j) == path), None)
            if later is not None:
                return Release(block, ctx.blocks[later].entry_turn - 1, TO_SUMMARY,
                               f"Superseded by the read of {path} at turn "
                               f"{ctx.blocks[later].entry_turn - 1}.", superseded_by=later)
        u = self._last_use(ctx, block)
        if u is None and path is not None and ctx.last_edit_of(path) is None:
            # A file that is read once and never touched again: the next
            # action moved on.
            u = b.entry_turn
            return Release(block, u, TO_SUMMARY,
                           f"Turn {u} moves on from {path}, which is never edited.")
        if u is None:
            return None
        return Release(block, u, TO_SUMMARY,
                       f"Turn {u} ({ctx.calls[u - 1][0].name if ctx.calls[u - 1] else 'answer'}) "
                       f"is the last action that uses it.")

    def _last_use(self, ctx: Context, i: int) -> Optional[int]:
        b = ctx.blocks[i]
        last = last_reappearance(ctx.rare(i), ctx.actions, after=b.entry_turn - 1)
        path = ctx.read_path(i)
        if path is not None:
            for u in range(b.entry_turn, ctx.T + 1):
                if any(call_path(c) == path for c in ctx.calls[u - 1]):
                    last = max(last or 0, u)
        if last is None or last > ctx.T - 1:
            return None
        return last


# ------------------------------------------------------------- online


_LINENO_RE = re.compile(r"^\s*(\d+)\t(.*)$")
_SIGNATURE_RE = re.compile(r"^\s*(?:def|class|async def)\s+\w+")


def _numbered_lines(text: str):
    for ln in text.splitlines():
        m = _LINENO_RE.match(ln)
        if m:
            yield int(m.group(1)), m.group(2)


def _test_digest(text: str) -> str:
    """The final summary line of a test run and the tests that failed."""
    final = [ln.strip("= ").strip() for ln in text.splitlines() if TEST_SUMMARY_RE.search(ln)]
    failed = [ln.split()[1] for ln in text.splitlines()
              if ln.startswith(("FAILED ", "ERROR ")) and len(ln.split()) > 1]
    out = final[-1] if final else "test run"
    return out + (" (failing: " + ", ".join(failed) + ")" if failed else "")


def summarize(blk: ViewBlock) -> str:
    """An extractive summary: every fact is copied from the block."""
    text, source = blk.text, blk.source
    if is_test_run(text):
        return f"Earlier {source}: {_test_digest(text)}."
    numbered = list(_numbered_lines(text))
    if numbered:
        first, last = numbered[0][0], numbered[-1][0]
        sigs = [f"{n}: {body.strip()}" for n, body in numbered if _SIGNATURE_RE.match(body)]
        return (f"Earlier {source}, lines {first}-{last}. Definitions: "
                + ("; ".join(sigs) if sigs else "none") + ".")
    if any(source.startswith(t + "(") for t in SEARCH_TOOLS):
        hits = []
        for ln in text.splitlines():
            parts = ln.split(":", 2)
            if len(parts) == 3 and parts[1].isdigit():
                hits.append(f"{parts[0]}:{parts[1]}")
        return f"Earlier {source}: hits at " + ", ".join(hits) + "."
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return f"Earlier {source}: {first} [...]"


class RuleBasedOnlineTeacher(OnlineTeacher):
    """Edits every editable block at once, or none.

    Receipts are dropped. When two or more editable blocks are test runs,
    one note consolidates their results and the runs are dropped. Every
    other editable block is rewritten into an extractive summary, unless it
    already is one. With nothing to edit the teacher declines.
    """

    def decide(self, view: DecisionView) -> Decision:
        todo = [b for b in view.blocks if b.editable and not b.rewritten and b.source != "note"]
        if not todo:
            return Decision(True, "Everything still in context is in use, so I leave it as it is.",
                            reason="no editable block")
        edits: List[TeacherEdit] = []
        receipts = [b for b in todo if is_receipt(b.text)]
        tests = [b for b in todo if b not in receipts and is_test_run(b.text)]
        if len(tests) < 2:
            tests = []
        rewrites = []
        for b in todo:
            if b in receipts or b in tests:
                continue
            s = summarize(b)
            if len(s) < len(b.text):
                rewrites.append(TeacherEdit("rewrite", b.address, s))
        edits.extend(rewrites)
        if tests:
            edits.append(TeacherEdit("append", None, "Test history of the fix: " + "; then ".join(
                _test_digest(b.text) for b in tests) + "."))
        edits.extend(TeacherEdit("drop", b.address) for b in receipts + tests)
        if not edits:
            return Decision(True, "Nothing in the context is worth condensing yet, so I leave it "
                                  "as it is.", reason="summaries would not be shorter")
        return Decision(False, self._note(view, len(rewrites), len(receipts), len(tests)), edits,
                        reason=f"{len(todo)} editable blocks")

    @staticmethod
    def _note(view: DecisionView, n_rewrite: int, n_receipt: int, n_tests: int) -> str:
        if view.trigger == "milestone" and view.milestone:
            lead = view.milestone[0].upper() + view.milestone[1:]
        elif view.trigger == "hard":
            lead = "My context is close to its limit"
        else:
            lead = "My context has grown sizeable"
        parts = []
        if n_rewrite:
            parts.append(f"condense {_n(n_rewrite, 'earlier result')} into short references")
        if n_tests:
            parts.append(f"fold {_n(n_tests, 'test run')} into one note")
        if n_receipt:
            parts.append(f"drop {_n(n_receipt, 'edit receipt')}")
        body = ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]
        return f"{lead}, so I {body}."


def _n(k: int, noun: str) -> str:
    words = ["no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten"]
    return f"{words[k] if k < len(words) else k} {noun}{'' if k == 1 else 's'}"
