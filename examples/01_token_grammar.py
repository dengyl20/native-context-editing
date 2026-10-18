#!/usr/bin/env python3
"""Walk the NCE token grammar over a short synthetic conversation.

Shows how the 70 dedicated tokens divide up, how a context state is written
out as text, how an agent output is split into ordinary text and edit
envelopes, and how the streaming parser behaves when an envelope arrives in
pieces. Standard library only; run from the repository root:

    python3 examples/01_token_grammar.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nce import tokens as T  # noqa: E402
from nce.grammar import EnvelopeDone, StreamParser, TextChunk, parse_output, serialize  # noqa: E402
from nce.grammar import Append, Drop, Rewrite  # noqa: E402
from nce.render import TraceWriter, wants_color, truncate_ansi  # noqa: E402
from nce.state import State  # noqa: E402
from nce.render import render_text  # noqa: E402

W = TraceWriter(color=wants_color())


def head(title: str, blurb: str = "") -> None:
    print()
    print(W.rule(title))
    for line in blurb.splitlines():
        print("  " + line)


def show_vocabulary() -> None:
    head("1. the vocabulary", "70 dedicated tokens, added to the base model's vocabulary.")
    groups = [
        ("high address digit  <sid_hi_00>..<sid_hi_31>", T.ADDR_HI),
        ("low address digit   <sid_lo_00>..<sid_lo_31>", T.ADDR_LO),
        ("operators", T.OPERATORS),
        ("envelope delimiters", [T.CTX_OPEN, T.CTX_CLOSE]),
        ("lock marker", [T.LOCKED]),
    ]
    total = 0
    for label, tokens in groups:
        # Three chips are enough to read the pattern; the count is the point.
        sample = "".join(f" {t} " for t in tokens[:3])
        more = f"  …(+{len(tokens) - 3})" if len(tokens) > 3 else ""
        print(f"  {label:46} {len(tokens):3}   {sample}{more}")
        total += len(tokens)
    print(f"  {'total':46} {total:3}")
    assert total == len(T.NCE_TOKENS) == 70

    print()
    print("  A block is named by a high token and a low token:")
    for n in (0, 31, 32, 33, 1023):
        hi, lo = T.encode_address_pair(n)
        back = T.decode_address(hi, lo)
        print(f"    block {n:5} -> {hi}{lo}   decodes to {back}")
    print(f"  Block n uses hi = n // 32 and lo = n % 32, so 32 x 32 = {T.ADDR_CAPACITY} "
          "addresses are reachable.")
    print("  Six more tokens carry meaning:")
    for tok, role in ((T.CTX_OPEN, "opens one edit"), (T.CTX_CLOSE, "closes it"),
                      (T.OP_DROP, "remove blocks"), (T.OP_REWRITE, "replace one block's text"),
                      (T.OP_APPEND, "add a note block"),
                      (T.LOCKED, "marks a block that may not be edited")):
        print(f"    {tok:14} {role}")


def show_rendering() -> None:
    head("2. rendering a context", "Every block opens with its address; actions carry none.")
    state = State()
    state.add_block("system", "You are a coding agent. Answer with one tool call per turn.",
                    locked=True)
    state.add_block("user", "The failing test expects parse_duration(\"1h30m\") to be 5400.")
    state.add_block("tool", "src/timeparse/core.py:19: total = int(value) * UNIT_SECONDS[unit]",
                    tool_name="grep")
    state.add_action("The loop overwrites the total instead of accumulating it.")
    state.add_block("tool", "The file src/timeparse/core.py has been updated successfully.",
                    tool_name="edit")
    state.add_block("note", "The failure is in the accumulation loop of parse_duration.")

    for block in state.live_blocks():
        lock = f" {T.LOCKED}" if block.locked else ""
        addr = T.encode_address(block.address)
        one = " ".join(block.text.split())[:64]
        print(f"  {addr}{lock} → {block.role:6} {one}")
    print()
    print("  The rendered context the model reads, first two blocks only:")
    for line in render_text(state).splitlines()[:2]:
        print("  " + W.tokens(truncate_ansi(line, W.width - 4)))
    print("  Actions are assistant turns without an address, so an edit can reach the "
          "observations and the\n  agent's own reasoning stays intact.")


def show_parsing() -> None:
    head("3. one agent output", "Ordinary text plus zero or more envelopes, executed in order.")
    output = (
        "The root cause is fixed and the suite passes, so I am clearing out the "
        "intermediate reads.\n"
        "<ctx><op_drop><sid_hi_00><sid_lo_02></ctx>"
        "<ctx><op_drop><sid_hi_00><sid_lo_04><sid_hi_00><sid_lo_05></ctx>"
        "<ctx><op_rewrite><sid_hi_00><sid_lo_03> The parser at src/timeparse/core.py, "
        "lines 9-27: accumulates per unit; keyed by UNIT_SECONDS.</ctx>"
        "<ctx><op_append> Edit receipts of the fix dropped; two regression tests added.</ctx>"
        "\nNext I will run the full suite once more."
    )
    print(W.tokens(output))
    print()
    parsed = parse_output(output)
    print(f"  {len(parsed.edits)} envelopes, {len(parsed.well_formed)} well formed, "
          f"{parsed.stray_tokens} stray tokens, "
          f"{len(parsed.text_pieces)} text pieces")
    for edit in parsed.edits:
        if isinstance(edit, Drop):
            detail = f"drops blocks {list(edit.addresses)}"
        elif isinstance(edit, Rewrite):
            detail = f"rewrites block {edit.address} to {len(edit.text)} characters"
        else:
            detail = f"appends a note of {len(edit.text)} characters"
        print(f"    {edit.op:9} {detail}")
    print()
    print("  The envelopes never enter the context. What the transcript keeps is the text "
          "around them:")
    for line in parsed.action_text.split("\n"):
        print("    " + line)


def show_streaming() -> None:
    head("4. the same output in chunks",
         "A token string may be split across chunks and is still recognised.")
    output = "<ctx><op_append> a note </ctx>"
    print(f"  output: {output}")

    # Split in the middle of the <sid_lo_00> token string of a second envelope.
    chunks = ["<ctx><op_append> a note </ctx>Then I drop block 7.\n",
              "<ctx><op_drop><sid_hi_00", "><sid_lo_07></ctx>"]
    parser = StreamParser()
    for i, chunk in enumerate(chunks, start=1):
        events = parser.feed(chunk)
        kinds = ", ".join(
            f"{type(e).__name__}({e.edit.op})" if isinstance(e, EnvelopeDone) else "TextChunk"
            for e in events) or "(nothing yet — a partial token is being held back)"
        print(f"  chunk {i}: {chunk!r}")
        print(f"           -> {kinds}")
    events = parser.close()
    for e in events:
        print(f"  close  : {type(e).__name__}"
              + (f"({e.edit.op})" if isinstance(e, EnvelopeDone) else ""))
    assert parser.stray_tokens == 0

    print()
    print("  A token outside any envelope has no target and is discarded and counted:")
    parser = StreamParser()
    events = parser.feed("Dropping the stale reads now. <op_drop> Then I continue.")
    print(f"  stray_tokens = {parser.stray_tokens}, "
          f"text = {''.join(e.text for e in events if isinstance(e, TextChunk))!r}")

    print()
    print("  An envelope left open when the output ends is malformed, and executes as a no-op:")
    parser = StreamParser()
    events = parser.feed("<ctx><op_drop><sid_hi_00><sid_lo_02>")
    events += parser.close()
    for e in events:
        if isinstance(e, EnvelopeDone):
            print(f"    {type(e.edit).__name__} reason={e.edit.reason!r} "
                  f"raw={e.raw!r}")


def show_canonical_text() -> None:
    head("5. canonical text", "Every edit has one written form, used when it is re-emitted.")
    edits = [Drop((2, 4, 5)), Rewrite(3, "The parser, lines 9-27: accumulates per unit."),
             Append("Receipts dropped; two regression tests added.")]
    for edit in edits:
        for line in str(edit.to_text()).split("\n"):
            print(W.tokens("  " + line))
    print()
    print(f"  serialize() concatenates them into one output: "
          f"{len(serialize(edits))} characters, {len(parse_output(serialize(edits)).edits)} "
          "envelopes round-tripped")


if __name__ == "__main__":
    print(W.rule("nce · the 70-token grammar"))
    show_vocabulary()
    show_rendering()
    show_parsing()
    show_streaming()
    show_canonical_text()
    print()
    print(W.rule())
    print("  All five sections produced output; every assertion above held.")
