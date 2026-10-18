"""Generate the conformance fixtures in tests/fixtures/.

Run from the repository root:

    python3 tests/make_fixtures.py

The fixtures are plain JSON so a second implementation can read them without
importing this package. Regenerating them is deterministic.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nce import tokens as T  # noqa: E402
from nce.grammar import parse_output  # noqa: E402
from nce.render import DEFAULT_FORMAT, render_text  # noqa: E402
from nce.runtime import execute  # noqa: E402
from nce.state import State  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "fixtures")

# ---------------------------------------------------------------- the state

def session() -> State:
    """A session with a locked system prompt, a task, and three tool results."""
    state = State()
    state.add_block("system", "You are a coding agent working in a repository at /workspace.",
                    locked=True)
    state.add_block("user", "The failing test expects parse_duration(\"1h30m\") == 5400.")
    state.add_block("tool", "src/timeparse/core.py:19: total = int(value) * UNIT_SECONDS[unit]",
                    tool_name="grep")
    state.add_block("tool", "The file src/timeparse/core.py has been updated successfully.",
                    tool_name="edit")
    state.add_block("tool", "9 passed in 0.02s", tool_name="bash")
    return state


def state_fixture() -> dict:
    state = session()
    state.drop(3)                      # the receipt is retired
    state.rewrite(2, "The parser at src/timeparse/core.py, lines 9-27: it accumulates "
                     "per unit and the unit table is correct.")
    state.append_note("The fix is in and the suite passes.")   # address 5
    state.add_action("The loop overwrote the total instead of accumulating it.")
    return {
        "name": "session_after_turn_3",
        "description": "A session after one editing turn: a receipt dropped, a read "
                       "rewritten, a note appended, and the action of the turn recorded.",
        "state": state.to_json(),
        "rendered": render_text(state, DEFAULT_FORMAT),
        "expected": {
            "live_addresses": [b.address for b in state.live_blocks()],
            "retired": sorted(state.pool.retired),
            "next_address": state.pool.next_address,
            "counts": {"blocks": len(state.live_blocks()),
                       "actions": len(state.actions()),
                       "reminders": len(state.reminders())},
        },
    }


# ------------------------------------------------------------- edit cases

def edits_fixture() -> dict:
    """One entry per rule: scripted output, and the verdict on each envelope."""
    cases = []

    def add(name, output, note=""):
        state = session()
        before = state.to_json()
        parsed = _parse(output)
        results = execute(state, parsed.edits, parsed.raws)
        cases.append({
            "name": name,
            "note": note,
            "output": output,
            "action_text": parsed.action_text,
            "stray_tokens": parsed.stray_tokens,
            "results": [r.to_json() for r in results],
            "state_before": before,
            "state_after": state.to_json(),
        })

    a0, a2, a3, a4 = (T.encode_address(n) for n in (0, 2, 3, 4))

    add("drop_one", "Tidying up.\n" + _env(f"{T.OP_DROP}{a2}"),
        "A plain drop of a live block, with the rationale kept around it.")
    add("drop_many", _env(f"{T.OP_DROP}{a2}{a4}"),
        "One envelope naming two blocks; both are removed.")
    add("drop_repeated_address", _env(f"{T.OP_DROP}{a2}{a2}"),
        "A repeated address counts once.")
    add("rewrite_live", _env(f"{T.OP_REWRITE}{a2} The parser at src/timeparse/core.py, "
                             f"lines 9-27, accumulates per unit."),
        "A rewrite keeps the address and replaces the text.")
    add("append", _env(f"{T.OP_APPEND} The fix is in and the suite passes."),
        "An append takes the next address.")
    add("three_edits_in_order", _env(f"{T.OP_APPEND} tested ") + _env(f"{T.OP_DROP}{a3}")
        + _env(f"{T.OP_REWRITE}{a2} a summary of the read "),
        "Edits run in the order they were written.")
    add("locked_block", _env(f"{T.OP_DROP}{a0}"),
        "The locked system prompt may not be dropped.")
    add("locked_block_blocks_the_others", _env(f"{T.OP_DROP}{a2}{a0}"),
        "A locked target blocks the whole edit, so the live target survives.")
    add("unknown_address", _env(f"{T.OP_DROP}{T.encode_address(99)}"),
        "The address was never issued.")
    add("retired_address", _env(f"{T.OP_DROP}{a3}") + _env(f"{T.OP_DROP} {a3} "),
        "The first drop retires the address; the second, written differently, is not_live.")
    add("duplicate_verbatim", _env(f"{T.OP_DROP}{a2}") + _env(f"{T.OP_DROP}{a2}"),
        "The envelope repeats verbatim, so it executes once.")
    add("malformed_missing_address", _env(T.OP_DROP),
        "A drop with no address.")
    add("malformed_bad_address", _env(f"{T.OP_DROP}{T.ADDR_HI[3]}"),
        "A high digit with no low digit.")
    add("malformed_empty_text", _env(f"{T.OP_APPEND}   "),
        "An append with no text.")
    add("malformed_token_in_text",
        _env(f"{T.OP_APPEND} a note {T.OP_DROP} with a token inside"),
        "A token inside the append text.")
    add("malformed_unexpected_content", _env(f"{T.OP_DROP}{a2} trailing words"),
        "Trailing text after a drop list.")
    add("rewrite_of_a_dead_block",
        _env(f"{T.OP_DROP}{a3}") + _env(f"{T.OP_REWRITE}{a3} summary of the receipt "),
        "The second envelope rewrites a block the first one dropped: kept as a note.")
    add("stray_token", f"I will drop it later. {T.OP_DROP} For now I run the suite.",
        "A token outside any envelope is discarded and counted.")

    return {
        "name": "edit_cases",
        "description": "Scripted model outputs run against the session fixture, one per "
                       "rule of spec/grammar.md and spec/semantics.md.",
        "initial_state": session().to_json(),
        "cases": cases,
    }


def _env(body: str) -> str:
    return T.CTX_OPEN + body + T.CTX_CLOSE


def _parse(output: str):
    return parse_output(output)


def vocabulary_fixture() -> dict:
    """The token table, with the addresses of a few blocks spelled out."""
    return {
        "name": "vocabulary",
        "description": "The 70 tokens and the address code of spec/tokens.md.",
        "tokens": list(T.NCE_TOKENS),
        "groups": {"high": T.ADDR_HI, "low": T.ADDR_LO, "operators": T.OPERATORS,
                   "envelope": [T.CTX_OPEN, T.CTX_CLOSE], "lock": [T.LOCKED]},
        "counts": {"total": len(T.NCE_TOKENS), "capacity": T.ADDR_CAPACITY,
                   "base": T.ADDR_BASE},
        "addresses": {str(n): T.encode_address(n) for n in (0, 1, 7, 31, 32, 33, 71, 1023)},
    }


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    written = []
    for name, payload in (("vocabulary.json", vocabulary_fixture()),
                          ("session.json", state_fixture()),
                          ("edits.json", edits_fixture())):
        path = os.path.join(OUT, name)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=1, sort_keys=False)
            handle.write("\n")
        written.append(path)
    for path in written:
        print(f"wrote {path} ({os.path.getsize(path)} bytes)")


if __name__ == "__main__":
    main()
