#!/usr/bin/env python3
"""Render an edit trace as readable coloured terminal output.

The terminal view uses the same palette as the paper's token chips, so a
reader can follow a turn without decoding the token strings: addresses in
blue, envelopes in ink, drop in red, rewrite in amber, append in green. The
trace below is the annotated turn of the toy trajectory, plus the block
table before and after it.

Colour is emitted only when stdout is a terminal, so this script pipes
cleanly into a file. Force either behaviour with ``--color`` / ``--no-color``.
Standard library only; run from the repository root:

    python3 examples/04_trace_render.py
    python3 examples/04_trace_render.py --no-color | less
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nce import tokens as T  # noqa: E402
from nce.annotate import (Context, RuleBasedOfflineTeacher, RuleBasedOnlineTeacher,  # noqa: E402
                          annotate, load_trajectory)
from nce.annotate.replay import Replayer, compose_output  # noqa: E402
from nce.grammar import parse_output  # noqa: E402
from nce.render import TraceWriter, strip_ansi, wants_color, wrap  # noqa: E402

SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "toy_trajectory.json")
TIERS = (4_000, 8_000, 32_000, 48_000, 64_000, 128_000)


def parse_argv() -> bool:
    """--color and --no-color win over the terminal, NO_COLOR, and a pipe."""
    if "--color" in sys.argv:
        return True
    if "--no-color" in sys.argv:
        return False
    return wants_color()


def block_table(W: TraceWriter, header: str, rows) -> None:
    """A table of blocks: address, role, size, and what happened to the block."""
    print()
    print("  " + W._paint(header, fg="accent", bold=True))
    width = max((len(r[0]) for r in rows), default=12)
    for label, role, tokens, note, tint in rows:
        tag = W._paint(label.ljust(width), fg=tint or "base")
        print(f"    {tag}  {role:<7} {tokens:>6}  {W._paint(note, fg='muted')}")


def replay_to(W: TraceWriter, an, turn: int) -> Replayer:
    """The state as it stands when the agent writes the output of ``turn``."""
    rp = Replayer(an.context)
    for t in range(1, turn):
        dp = next((d for d in an.decisions if d.turn == t), None)
        ops = list(dp.ops) if dp is not None and dp.outcome == "edited" else []
        envelopes, ops = rp.compile(ops)
        rp.finish_turn(t, compose_output("", envelopes, an.context.actions[t - 1]), ops)
    return rp


def show_turn(W: TraceWriter, an) -> None:
    """The annotated editing turn, with its envelopes drawn as chips."""
    turn = next(d for d in an.decisions if d.outcome == "edited")
    rp = replay_to(W, an, turn.turn)

    print(W.rule(f"turn {turn.turn}: {turn.trigger} trigger, {turn.tokens} tokens"))
    print()
    for line in wrap(turn.note, W.width - 2, indent="    ", first="  "):
        print(W._paint(line, fg="base", italic=True))

    envelopes, ops = rp.compile(list(turn.ops))
    print()
    print("  " + W._paint(f"{len(envelopes)} envelopes, "
                          f"freed {turn.freed:.1%} of the context", fg="muted"))
    print()
    from nce.grammar import parse_output
    for env in envelopes:
        parsed = parse_output(env)
        kind = W._paint(f"{parsed.edits[0].op:<7}", bold=True,
                        fg={"drop": "drop_fg", "rewrite": "rewrite_fg",
                            "append": "append_fg"}[parsed.edits[0].op])
        body = strip_ansi(W.chip_line(env, indent=""))
        rows = wrap(body, W.width - 13, indent=" " * 11, first="  ")
        for i, row in enumerate(rows):
            print((kind if i == 0 else " " * 7) + row)


def show_state(W: TraceWriter, an) -> None:
    """Blocks before the turn, what happens to each, and the totals."""
    turn = next(d for d in an.decisions if d.outcome == "edited")
    ctx = an.context
    rp = replay_to(W, an, turn.turn)

    fate = {op.ref: op.op for op in turn.ops}
    rows = []
    for ref, address in rp.live_refs():
        block = rp.state.blocks[address]
        tokens = rp.block_tokens(address)
        what = fate.get(ref)
        if what == "drop":
            note, tint = "dropped", "drop_fg"
        elif what == "rewrite":
            note, tint = "rewritten", "rewrite_fg"
        elif ref.startswith(("n", "r")):
            note, tint = "note, kept", "note_on"
        else:
            note, tint = "kept", None
        source = ctx.blocks[int(ref[1:])].source if ref.startswith("b") else "note"
        rows.append((f"{ref} {T.encode_address(address)}", block.role, tokens,
                     f"{note:<10} {source[:40]}", tint))
    block_table(W, f"the {len(rows)} live blocks when the turn begins", rows)

    envelopes, ops = rp.compile(list(turn.ops))
    before, after = rp.measure(envelopes)
    print()
    print(f"  {W._paint('total', fg='muted')} {before} → {after} tokens "
          f"({W._paint(f'{(after - before) / before:+.1%}', fg='good', bold=True)})")


def show_legend(W: TraceWriter) -> None:
    print(W.rule("the chip palette"))
    print()
    rows = [
        ("address", W.chip_line("<sid_hi_00><sid_lo_03>", indent=""),
         "names one block; always two chips side by side"),
        ("envelope", W.chip_line("<ctx> ... </ctx>", indent=""), "delimits one edit"),
        ("lock", W.chip_line("<m_ro>", indent=""), "the block may not be edited"),
        ("drop", W.chip_line("<op_drop>", indent=""), "remove blocks"),
        ("rewrite", W.chip_line("<op_rewrite>", indent=""), "replace one block's text"),
        ("append", W.chip_line("<op_append>", indent=""), "add a note block"),
    ]
    for label, chips, meaning in rows:
        print(f"    {W._paint(label.ljust(9), fg='muted')} {chips}  "
              f"{W._paint(meaning, fg='base')}")


def show_sizes(W: TraceWriter, an) -> None:
    """A bar per turn: the context the agent reads under the traced session."""
    print()
    print(W.rule("context over the session"))
    rp = Replayer(an.context)
    sizes = []
    edits = {}
    for t in range(1, an.context.T + 1):
        sizes.append(rp.tokens())
        dp = next((d for d in an.decisions if d.turn == t), None)
        ops = list(dp.ops) if dp is not None and dp.outcome == "edited" else []
        envelopes, ops = rp.compile(ops)
        if envelopes:
            edits[t] = dp
        rp.finish_turn(t, compose_output("", envelopes, an.context.actions[t - 1]), ops)
    peak = max(sizes)
    for t, size in enumerate(sizes, start=1):
        bar = "█" * max(1, int(round(size / peak * (W.width - 24))))
        dp = edits.get(t)
        marker = ("  " + W._paint("edit", fg="rewrite_fg", bold=True)) if dp else ""
        colour = "rewrite_fg" if dp else "accent"
        print(f"    t{t:>2} {size:>5}  {W._paint(bar, fg=colour)}{marker}")


def main() -> None:
    W = TraceWriter(color=parse_argv())
    print(W.rule("nce · an edit trace"))
    print()
    print("  " + W._paint("colours are on" if W.color else
                          "colours are off (piping or --no-color)", fg="muted"))

    traj = load_trajectory(SOURCE)
    an = annotate(traj, RuleBasedOfflineTeacher(), RuleBasedOnlineTeacher(), tiers=TIERS)

    show_legend(W)
    print()
    print(W.rule())
    show_turn(W, an)
    show_state(W, an)
    show_sizes(W, an)
    print()
    print(W.rule())


if __name__ == "__main__":
    main()
