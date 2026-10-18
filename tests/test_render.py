"""Rendering: what the model reads and what the terminal shows.

The rendering is the contract between the state and a chat template, so the
tests pin the exact text: two address tokens, the lock marker, the role tag,
the text, and one separator. The terminal view is checked on its plain text,
with the colour codes stripped.
"""
from __future__ import annotations

import os
import unittest

import context  # noqa: F401  (sets sys.path)

from nce import tokens as T
from nce.render import (COLORS, ChatFormat, TraceWriter, approx_tokens, chip, chip_line,
                        op_of, paint, render_item, render_messages, render_text, strip_ansi,
                        terminal_width, truncate_ansi, wants_color, wrap)
from nce.state import State


def build_state() -> State:
    state = State()
    state.add_block("system", "You are a coding agent.", locked=True)     # 0
    state.add_block("user", "Fix parse_duration.")                        # 1
    state.add_block("tool", "line 19: total = ...", tool_name="grep")     # 2
    state.add_action("The loop overwrites the total.")                    # no address
    state.add_reminder("soft", "[context-monitor] tidy up")
    state.add_block("note", "The failure is in the accumulation loop.")   # 3
    return state


class BlockRendering(unittest.TestCase):
    def test_a_block_opens_with_its_address_and_role_tag(self):
        state = State()
        block = state.add_block("user", "task")
        self.assertEqual(render_item(block),
                         T.encode_address(0) + "<|user|>task\n")

    def test_a_locked_block_carries_the_lock_marker(self):
        state = State()
        block = state.add_block("system", "prompt", locked=True)
        self.assertEqual(render_item(block),
                         T.encode_address(0) + T.LOCKED + "<|system|>prompt\n")

    def test_the_block_body_is_not_closed_by_a_token(self):
        # No closing token: the next address marks where a block ends.
        state = State()
        state.add_block("user", "one")
        state.add_block("tool", "two", tool_name="read")
        text = render_text(state)
        self.assertEqual(text, T.encode_address(0) + "<|user|>one\n"
                         + T.encode_address(1) + "<|tool|>read\ntwo\n")
        self.assertNotIn("</", text)

    def test_a_tool_block_names_its_tool_on_the_first_line(self):
        state = State()
        state.add_block("tool", "result text", tool_name="bash")
        self.assertIn("<|tool|>bash\nresult text", render_text(state))

    def test_a_tool_block_without_a_name_is_still_rendered(self):
        state = State()
        state.add_block("tool", "result text")
        self.assertIn("<|tool|>result text", render_text(state))

    def test_a_note_uses_the_note_role_tag(self):
        state = State()
        state.append_note("what was learned")
        self.assertIn("<|note|>what was learned", render_text(state))

    def test_actions_and_reminders_carry_no_address(self):
        state = State()
        state.add_block("user", "task")
        state.add_action("I read the file.")
        state.add_reminder("soft", "tidy up")
        text = render_text(state)
        self.assertIn("<|assistant|>I read the file.<|end|>\n", text)
        self.assertIn("<|user|>tidy up\n", text)
        # Only the one block address appears.
        self.assertEqual(text.count("<sid_"), 2)

    def test_interaction_order_is_preserved(self):
        state = build_state()
        text = render_text(state)
        positions = [text.index(marker) for marker in
                     (T.encode_address(0), T.encode_address(1), T.encode_address(2),
                      "<|assistant|>", "tidy up", T.encode_address(3))]
        self.assertEqual(positions, sorted(positions))

    def test_generation_prompt_opens_the_assistant_turn(self):
        state = State()
        state.add_block("user", "task")
        self.assertTrue(render_text(state, add_generation_prompt=True).endswith("<|assistant|>"))
        self.assertFalse(render_text(state, add_generation_prompt=False).endswith("<|assistant|>"))

    def test_the_address_of_every_block_is_reachable_in_the_text(self):
        state = build_state()
        text = render_text(state)
        for address in state.blocks:
            self.assertIn(T.encode_address(address), text)


class CustomFormats(unittest.TestCase):
    def test_a_format_replaces_the_role_tags_and_the_separator(self):
        fmt = ChatFormat(role_tags={"system": "<s>", "user": "<u>", "tool": "<t>", "note": "<n>"},
                         assistant_open="<a>", assistant_close="<e>",
                         reminder_tag="<r>", separator="")
        state = State()
        state.add_block("user", "task")
        state.add_action("work")
        state.add_reminder("soft", "tidy up")
        self.assertEqual(render_text(state, fmt),
                         T.encode_address(0) + "<u>task" + "<a>work<e>" + "<r>tidy up")

    def test_block_body_can_be_overridden(self):
        class Upper(ChatFormat):
            def block_body(self, block):
                return block.text.upper()

        state = State()
        state.add_block("user", "task")
        self.assertIn("<|user|>TASK", render_text(state, Upper()))


class MessageRendering(unittest.TestCase):
    def test_roles_and_names(self):
        state = build_state()
        messages = render_messages(state)
        self.assertEqual([m["role"] for m in messages],
                         ["system", "user", "tool", "assistant", "user", "user"])
        self.assertEqual(messages[2]["name"], "grep")
        self.assertNotIn("name", messages[1])

    def test_every_block_content_starts_with_its_address(self):
        state = build_state()
        for message in render_messages(state):
            if message["role"] in ("system", "tool"):
                self.assertTrue(message["content"].startswith("<sid_"), message)

    def test_a_note_travels_as_a_user_message(self):
        state = State()
        state.append_note("a note")
        self.assertEqual(render_messages(state),
                         [{"role": "user", "content": T.encode_address(0) + "a note"}])


class TokenCounting(unittest.TestCase):
    def test_each_token_string_counts_one(self):
        self.assertEqual(approx_tokens(T.CTX_OPEN + T.OP_DROP
                                       + T.encode_address(0) + T.CTX_CLOSE), 5)

    def test_words_and_punctuation_count(self):
        self.assertEqual(approx_tokens("one two three"), 3)
        self.assertEqual(approx_tokens("a, b."), 4)
        self.assertEqual(approx_tokens(""), 0)
        self.assertEqual(approx_tokens("   "), 0)

    def test_a_token_string_is_not_counted_word_by_word(self):
        self.assertEqual(approx_tokens(T.OP_REWRITE), 1)
        self.assertEqual(approx_tokens(T.LOCKED), 1)

    def test_rendering_the_same_state_twice_gives_the_same_count(self):
        state = build_state()
        self.assertEqual(approx_tokens(render_text(state)),
                         approx_tokens(render_text(state)))
        self.assertGreater(approx_tokens(render_text(state)), 20)


class PaletteAndChips(unittest.TestCase):
    def test_the_palette_matches_the_project_colours(self):
        # The chip colours of the paper and the style guide.
        self.assertEqual(COLORS["addr_bg"].upper(), "#DCE7F7")
        self.assertEqual(COLORS["addr_fg"].upper(), "#1C4A86")
        self.assertEqual(COLORS["drop_bg"].upper(), "#F7D3D1")
        self.assertEqual(COLORS["drop_fg"].upper(), "#A1282A")
        self.assertEqual(COLORS["rewrite_bg"].upper(), "#FAE1B0")
        self.assertEqual(COLORS["rewrite_fg"].upper(), "#7A4A00")
        self.assertEqual(COLORS["append_bg"].upper(), "#D6EDDA")
        self.assertEqual(COLORS["append_fg"].upper(), "#2C6A3B")
        self.assertEqual(COLORS["envelope_bg"].upper(), "#3A4352")

    def test_paint_emits_24_bit_colour_and_resets(self):
        text = paint("x", fg="accent")
        self.assertTrue(text.startswith("\033[38;2;36;80;138m"))
        self.assertTrue(text.endswith("\033[0m"))
        self.assertEqual(strip_ansi(text), "x")

    def test_paint_of_an_unknown_name_is_plain_text(self):
        self.assertEqual(paint("x", fg="chartreuse"), "x")
        self.assertEqual(paint("", fg="accent"), "")
        self.assertEqual(paint("x", fg="text_bg"), "x")  # a None entry

    def test_a_chip_pads_the_token(self):
        self.assertEqual(strip_ansi(chip(T.OP_DROP, name="drop")), f" {T.OP_DROP} ")
        self.assertEqual(chip(T.OP_DROP, name="drop", color=False), f" {T.OP_DROP} ")

    def test_a_chip_guesses_its_group(self):
        self.assertEqual(strip_ansi(chip(T.encode_address(0))),
                         f" {T.encode_address(0)} ")
        for op in T.OPERATORS:
            self.assertEqual(strip_ansi(chip(op, name=op_of("<ctx>" + op + "</ctx>"))),
                             f" {op} ")

    def test_op_of_finds_the_operator(self):
        for op in T.OPERATORS:
            self.assertEqual(op_of(f"{T.CTX_OPEN}{op} x {T.CTX_CLOSE}"),
                             op.replace("<op_", "").replace(">", ""))
        self.assertEqual(op_of("no operator here"), "")

    def test_chip_line_rewrites_every_token(self):
        line = f"drop {T.CTX_OPEN}{T.OP_DROP}{T.encode_address(2)}{T.CTX_CLOSE} now"
        colourful = chip_line(line)
        # Every token gains its chip padding; the ordinary text is untouched.
        # The two tokens of an address become two adjacent chips.
        self.assertEqual(strip_ansi(colourful), f"drop " + "".join(
            f" {tok} " for tok in (T.CTX_OPEN, T.OP_DROP, T.ADDR_HI[0], T.ADDR_LO[2],
                                   T.CTX_CLOSE)) + " now")
        self.assertIn("\033", colourful)
        plain = chip_line(line, color=False)
        self.assertNotIn("\033", plain)
        self.assertEqual(strip_ansi(colourful), plain)  # same text, minus colour
        self.assertEqual(chip_line(line, indent="  ", color=False), "  " + plain)

    def test_truncate_ansi_keeps_the_width_and_closes_the_run(self):
        text = paint("a" * 40, fg="accent")
        cut = truncate_ansi(text, 10)
        self.assertEqual(len(strip_ansi(cut)), 10)
        self.assertTrue(cut.endswith("\033[0m"))
        self.assertEqual(truncate_ansi("short", 40), "short")
        self.assertEqual(truncate_ansi("plain text", 5, tail="...").strip(), "pl...")
        self.assertEqual(truncate_ansi("anything", 0), "")

    def test_wrap_respects_the_width_and_the_indents(self):
        lines = wrap("one two three four five six seven", 14, indent="    ", first="  ")
        self.assertTrue(lines[0].startswith("  "))
        self.assertTrue(all(ln.startswith("    ") for ln in lines[1:]))
        for line in lines:
            self.assertLessEqual(len(line), 14 + 2)
        self.assertEqual(" ".join(ln.strip() for ln in lines),
                         "one two three four five six seven")

    def test_wrap_of_an_empty_string_still_returns_a_line(self):
        self.assertEqual(wrap("", 10, indent="  "), ["  "])

    def test_wrap_does_not_split_a_long_word(self):
        lines = wrap("a " + "x" * 30, 12)
        self.assertIn("x" * 30, lines[-1])


class TraceWriterOutput(unittest.TestCase):
    def test_colour_can_be_switched_off(self):
        plain = TraceWriter(color=False)
        self.assertNotIn("\033", plain.tokens(f"{T.CTX_OPEN}{T.OP_APPEND} note {T.CTX_CLOSE}"))
        self.assertNotIn("\033", plain.rule("turn 1"))
        self.assertNotIn("\033", plain.chip_line("<op_drop>"))
        colourful = TraceWriter(color=True)
        self.assertIn("\033", colourful.chip_line("<op_drop>"))

    def test_tokens_keeps_the_token_string_recoverable(self):
        for writer in (TraceWriter(color=False), TraceWriter(color=True)):
            rendered = writer.tokens(f"{T.CTX_OPEN}{T.OP_APPEND} note {T.CTX_CLOSE}")
            self.assertEqual(strip_ansi(rendered),
                             f" {T.CTX_OPEN}  {T.OP_APPEND}  note  {T.CTX_CLOSE} ")

    def test_the_rule_is_as_wide_as_the_writer(self):
        writer = TraceWriter(width=60, color=False)
        self.assertEqual(len(writer.rule()), 54)
        self.assertTrue(writer.rule("turn 3").startswith("TURN 3"))

    def test_chip_line_defaults_to_the_writers_indent(self):
        writer = TraceWriter(color=False, indent=">>")
        self.assertTrue(writer.chip_line("<op_drop>").startswith(">>"))

    def test_block_line_shows_the_address_role_and_preview(self):
        state = State()
        block = state.add_block("tool", "x" * 300, tool_name="read")
        line = strip_ansi(TraceWriter(color=False).block_line(block))
        self.assertIn(T.encode_address(0), line)
        self.assertIn("tool", line)
        self.assertIn("…", line)

    def test_terminal_width_has_a_floor(self):
        self.assertGreaterEqual(terminal_width(), 48)


class ColorPolicy(unittest.TestCase):
    """The no-color.org convention, and the stream the decision is made on."""

    class Stream:
        def __init__(self, tty):
            self.tty = tty

        def isatty(self):
            return self.tty

    def test_a_terminal_gets_colour(self):
        self.assertTrue(wants_color(self.Stream(True)))

    def test_a_pipe_does_not(self):
        self.assertFalse(wants_color(self.Stream(False)))

    def test_a_stream_without_isatty_does_not(self):
        self.assertFalse(wants_color(object()))
        self.assertFalse(wants_color(_BrokenStream()))

    def test_no_color_wins_over_a_terminal(self):
        os.environ["NO_COLOR"] = "1"
        try:
            self.assertFalse(wants_color(self.Stream(True)))
        finally:
            del os.environ["NO_COLOR"]

    def test_an_empty_no_color_is_ignored(self):
        os.environ["NO_COLOR"] = ""
        try:
            self.assertTrue(wants_color(self.Stream(True)))
        finally:
            del os.environ["NO_COLOR"]


class _BrokenStream:
    def isatty(self):
        raise ValueError("closed")


if __name__ == "__main__":
    unittest.main()
