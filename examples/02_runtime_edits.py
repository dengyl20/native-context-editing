#!/usr/bin/env python3
"""Drive the NCE runtime over a short agent session.

Blocks enter the context, the agent edits them with drop, rewrite and
append, and the runtime executes each edit against the state. Every step
prints the context before and after with its token count, including the
cases where an edit is rejected and where a rewrite of a dead block is kept
as a note. Standard library only; run from the repository root:

    python3 examples/02_runtime_edits.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nce import tokens as T  # noqa: E402
from nce.render import TraceWriter, wants_color, render_item, render_text, truncate_ansi  # noqa: E402
from nce.runtime import Runtime  # noqa: E402
from nce.state import Block  # noqa: E402

W = TraceWriter(color=wants_color())
BUDGET = 4_000


def preview(block: Block, chars: int = 58) -> str:
    text = " ".join(block.text.split())
    if len(text) > chars:
        text = text[:chars] + "…"
    lock = f" {T.LOCKED}" if block.locked else ""
    return f"{T.encode_address(block.address)}{lock}  {block.role:6} {text}"


def dump(rt: Runtime, label: str) -> None:
    """Print the live blocks and the context size.

    The state is dumped between turns, so it is what the next prompt renders:
    the turn's edit has run and the turn's observation has entered.
    """
    total = rt.context_tokens()
    print(f"  {W._paint(label, fg='accent', bold=True)}   "
          f"{len(rt.state.live_blocks())} blocks, {total} tokens")
    for block in rt.state.live_blocks():
        line = preview(block)
        colour = {"system": "muted", "note": "note_on"}.get(block.role, "base")
        print("    " + W._paint(line, fg=colour, dim=block.role == "system"))


def run_turn(rt: Runtime, output: str, observations=()) -> None:
    print()
    print("  " + W._paint("model output", fg="muted", bold=True))
    for line in output.split("\n"):
        print("    " + truncate_ansi(W.tokens(line), W.width - 6))
    before = rt.context_tokens()
    step = rt.step(output)
    after = rt.context_tokens()
    for result in step.results:
        verdict = {"applied": ("good", "executed"),
                   "applied_as_append": ("good", "executed as an append (the block was gone)"),
                   "rejected": ("bad", "rejected")}[result.status]
        note = f" — {result.reason}" if result.reason else ""
        if result.new_address is not None:
            note += f", new note at {T.encode_address(result.new_address)}"
        print(f"  {W._paint(verdict[1], fg=verdict[0], bold=True)}{note}")
    print(f"  {W._paint('context', fg='muted')} {before} → {after} tokens "
          f"({after - before:+d})")
    if step.stray_tokens:
        print("  " + W._paint(f"{step.stray_tokens} NCE token(s) outside any envelope: "
                              f"discarded, the text stays", fg="muted", dim=True))
    for obs in observations:
        rt.add_block(obs[0], obs[1], tool_name=obs[2] if len(obs) > 2 else None)
    if not step.executed:
        print("  " + W._paint("no edit executed: the next prompt extends this one and "
                              "keeps its prefix cache", fg="muted", dim=True))


def main() -> None:
    print(W.rule("nce · runtime"))
    print("  A session with a 4,000-token budget and no reminder policy, so every edit "
          "below is the\n  agent's own choice.")

    rt = Runtime(budget=BUDGET)
    rt.add_block("system",
                 "You are a coding agent working in a repository at /workspace. Edit your "
                 "context with drop, rewrite and append.",
                 locked=True)
    rt.add_block("user", "The failing test expects parse_duration(\"1h30m\") == 5400. "
                         "Find the cause and fix it.")
    print()
    dump(rt, "state for turn 1")

    # ---- 1. a tool result enters, the agent appends a note -------------------
    run_turn(
        rt,
        "Two results disagree, so I will record what matters before going on.\n"
        "<ctx><op_append> The failure is in the accumulation loop of parse_duration; "
        "the unit table is correct.</ctx>",
        observations=[("tool", "src/timeparse/core.py:19: total = int(value) * UNIT_SECONDS[unit]\n"
                               "src/timeparse/core.py:23: pos = match.end()", "grep")],
    )
    dump(rt, "state for turn 2")

    # ---- 2. a rewrite ------------------------------------------------------
    run_turn(
        rt,
        "The read is long and I only need its shape from here on.\n"
        "<ctx><op_rewrite><sid_hi_00><sid_lo_02> Exploration snippet "
        "(src/timeparse/core.py, ~lines 15-27): parse_duration accumulates per unit; "
        "the whitespace guard is missing.</ctx>",
    )
    dump(rt, "state for turn 3")

    # ---- 3. a drop of the read the note now replaces ----------------------
    run_turn(
        rt,
        "The note keeps what the read told me, so the read itself can go.\n"
        "<ctx><op_drop><sid_hi_00><sid_lo_03></ctx>",
        observations=[("tool", "The file src/timeparse/core.py has been updated successfully.",
                       "edit")],
    )
    dump(rt, "state for turn 4")

    # ---- 4. a second drop, and the address is retired for good -------------
    run_turn(
        rt,
        "The edit receipt has served its purpose.\n"
        "<ctx><op_drop><sid_hi_00><sid_lo_04></ctx>",
        observations=[("tool", "9 passed in 0.02s", "bash")],
    )
    dump(rt, "state for turn 5")

    # ---- 5. rejected: the locked block ------------------------------------
    run_turn(
        rt,
        "Trying to clear the system prompt.\n"
        "<ctx><op_drop><sid_hi_00><sid_lo_00></ctx>",
    )

    # ---- 6. rejected: an address that was never issued ---------------------
    unissued = rt.state.pool.next_address + 3  # no block has ever had it
    run_turn(
        rt,
        "Dropping a block that does not exist.\n"
        f"<ctx><op_drop>{T.encode_address(unissued)}</ctx>",
    )

    # ---- 7. rejected: the address was retired ------------------------------
    retired = next(iter(sorted(rt.state.pool.retired)))
    run_turn(
        rt,
        "Dropping an old block again.\n"
        f"<ctx><op_drop>{T.encode_address(retired)}</ctx>",
    )

    # ---- 8. rejected: the same envelope twice in one turn -----------------
    live = rt.state.live_blocks()[-1].address
    dup = f"<ctx><op_drop>{T.encode_address(live)}</ctx>"
    run_turn(rt, "Dropping the last block, written twice by mistake.\n" + dup + dup)

    # ---- 9. malformed ------------------------------------------------------
    run_turn(
        rt,
        "A malformed attempt.\n<ctx><op_rewrite><sid_hi_00></ctx>",
    )

    # ---- 10. a stray token -------------------------------------------------
    run_turn(rt, "I will drop something later. <op_drop> For now, running the suite.")

    # ---- 11. a rewrite whose target is gone -------------------------------
    run_turn(
        rt,
        "The block I summarised is gone, so the text becomes a note.\n"
        f"<ctx><op_rewrite>{T.encode_address(retired)} Summary of a block that was dropped "
        "earlier.</ctx>",
    )
    dump(rt, "state for turn 12")

    print()
    print(W.rule("what the transcript keeps"))
    print("  Edits never enter the context. The action history keeps the text around them, "
          "so the next\n  turn reads the rationale and the action without the envelopes:")
    for i, action in enumerate(rt.state.actions(), start=1):
        text = " ".join(action.text.split())
        print(f"    turn {i}: " + truncate_ansi(W._paint(text[:W.width - 16], fg="base"),
                                                W.width - 14))
    print()
    print("  The retired addresses stay retired:")
    print(f"    live    {[b.address for b in rt.state.live_blocks()]}")
    print(f"    retired {sorted(rt.state.pool.retired)}")
    print(f"    next    {rt.state.pool.next_address} (the pool only counts upward, so a "
          f"reused address can never name a new block)")
    print()
    print(W.rule())


if __name__ == "__main__":
    main()
