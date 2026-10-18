#!/usr/bin/env python3
"""Cut an annotated trajectory into training segments.

Supervision comes from the annotated trajectory of examples/03. The
trajectory is replayed forward through the runtime: every turn with an
executed edit closes a segment, and the next segment opens with the state
those edits produced. Inside a segment the model's own output is supervised
and everything it reads — the rendered prefix, the observations, the
reminders — is not.

Each segment reports its pieces with their loss flags, the share that is
supervised, and an assertion that the pieces still spell out the rendering
of the current state. Standard library only; run from the repository root:

    python3 examples/05_distill_segments.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nce import tokens as T  # noqa: E402
from nce.annotate import (RuleBasedOfflineTeacher, RuleBasedOnlineTeacher,  # noqa: E402
                          annotate, load_trajectory)
from nce.distill import distill  # noqa: E402
from nce.render import TraceWriter, wants_color, strip_ansi, truncate_ansi, wrap  # noqa: E402

W = TraceWriter(color=wants_color())
SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "toy_trajectory.json")
TIERS = (4_000, 8_000, 32_000, 48_000, 64_000, 128_000)


def para(text: str, indent: str = "  ") -> None:
    for line in wrap(text, W.width, indent=indent):
        print(line)


def piece_label(text: str, loss: int) -> str:
    """Name a piece by what it carries."""
    if not loss:
        return "prefix" if (T.CTX_OPEN in text or "system" in text) else "observation"
    if T.contains_nce_token(text):
        return "rationale + edit"
    if text.strip().startswith("<|end|>"):
        return "closing tag"
    return "rationale + action"


def show_segment(seg) -> tuple:
    supervised = len(seg.supervised())
    total = len(seg.text)
    print(W.rule(f"segment {seg.index} · turns {seg.first_turn}-{seg.last_turn} · "
                 f"{seg.edits} edit(s) in the closing turn"))
    print()
    print(f"  {len(seg.pieces)} pieces, {total} characters, "
          f"{supervised} supervised ({supervised / total:.1%})")
    print()
    for i, (text, loss) in enumerate(seg.pieces):
        label = piece_label(text, loss)
        tag = W._paint("loss=1", fg="good", bold=True) if loss \
            else W._paint("loss=0", fg="muted")
        kind = W._paint(f"{i:>2} {label:<18}", fg="accent" if loss else "muted")
        head = " ".join(text.split())[:W.width - 32]
        print(f"    {kind} {tag} {len(text):>6}  "
              f"{truncate_ansi(head, W.width - 34)}")
    return supervised, total


def show_mask(seg) -> None:
    """The character-level mask, as a row of blocks."""
    mask = seg.char_mask()
    width = min(len(mask), W.width - 6)
    row = "".join("█" if mask[int(i * len(mask) / width)] else "·" for i in range(width))
    print("    " + W._paint(row, fg="accent"))
    print("    " + W._paint(f"█ supervised · not supervised, downsampled to {width} cells "
                            f"over {len(mask)} characters", fg="muted"))


def main() -> None:
    print(W.rule("nce · distillation with evolving contexts"))
    print()
    para("An annotated trajectory is replayed forward through the runtime. Every turn whose "
         "edits execute closes a segment; the next segment opens with the rendering of the "
         "state those edits produced, so its prefix reflects every earlier edit. A segment is "
         "an ordinary causal sequence.")

    traj = load_trajectory(SOURCE)
    an = annotate(traj, RuleBasedOfflineTeacher(), RuleBasedOnlineTeacher(), tiers=TIERS)
    annotated = an.annotated()
    segments = distill(annotated)

    print()
    print(W.rule(f"the trajectory: {annotated.T} turns, "
                 f"{len(an.audit.edit_turns)} of them carry edits"))
    print()
    print(f"  {len(segments)} segment(s)")

    total_sup = 0
    total_chars = 0
    for seg in segments:
        print()
        sup, chars = show_segment(seg)
        show_mask(seg)
        total_sup += sup
        total_chars += chars

    print()
    print(W.rule("what the segment boundary means"))
    para("The edit never appears in the following context: a dropped block is gone, and a "
         "rewritten block carries only its new text. So the segments after an editing turn "
         "train on the state the edit produced, and a prefix cache stays valid inside a "
         "segment.")
    print()
    for i, seg in enumerate(segments):
        opens = seg.pieces[0][0]
        print(f"  segment {i} opens with {len(opens)} characters of rendered prefix "
              f"({len(opens.split())} words)")
    print()
    print(f"  {total_chars} characters of training text, {total_sup} supervised "
          f"({total_sup / total_chars:.1%})")

    print()
    print(W.rule("the loss flags by piece kind"))
    kinds = {}
    for seg in segments:
        for text, loss in seg.pieces:
            k = kinds.setdefault(piece_label(text, loss), [0, 0])
            k[0] += 1
            k[1] += len(text) if loss else 0
    print(f"  {'piece':<20} {'count':>6} {'supervised chars':>17}")
    for label, (count, chars) in sorted(kinds.items()):
        print(f"  {label:<20} {count:>6} {chars:>17}")
    print()
    para("Only the model's own output is supervised. The rendered prefix, the observations "
         "and the runtime's reminders reach the model as context and contribute no loss.")

    print()
    print(W.rule())
    print("  Every segment asserted that its pieces still spell out the rendering of the "
          "state at every turn.")


if __name__ == "__main__":
    main()
