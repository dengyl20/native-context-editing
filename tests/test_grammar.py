"""Grammar well-formedness, serialization, and the streaming parser.

Every rule of Appendix A.3 is exercised with a case that must be accepted
and cases that must be rejected, and the rejection reason is asserted so a
silent change of behaviour fails the suite.
"""
from __future__ import annotations

import unittest

import context  # noqa: F401  (sets sys.path)

from nce import tokens as T
from nce.grammar import (Append, Drop, EnvelopeDone, Malformed, Rewrite, StreamParser,
                         TextChunk, edit_from_json, edit_to_json, join_pieces,
                         parse_envelope, parse_output, serialize)


def env(body: str) -> str:
    return T.CTX_OPEN + body + T.CTX_CLOSE


# One representative well-formed envelope per operator shape.
WELL_FORMED = {
    "drop_one": env(T.OP_DROP + T.encode_address(3)),
    "drop_many": env(T.OP_DROP + "".join(T.encode_address(n) for n in (0, 1, 1023))),
    "rewrite": env(T.OP_REWRITE + T.encode_address(7) + " a shorter line "),
    "append": env(T.OP_APPEND + " a note that records what was learned "),
}


class WellFormedness(unittest.TestCase):
    def test_accepted_shapes(self):
        self.assertEqual(parse_envelope(WELL_FORMED["drop_one"]), Drop((3,)))
        self.assertEqual(parse_envelope(WELL_FORMED["drop_many"]), Drop((0, 1, 1023)))
        self.assertEqual(parse_envelope(WELL_FORMED["rewrite"]),
                         Rewrite(7, "a shorter line"))
        self.assertEqual(parse_envelope(WELL_FORMED["append"]),
                         Append("a note that records what was learned"))

    def test_drop_keeps_the_written_order(self):
        # Execution follows the order the addresses were written, so the
        # parser must not sort or deduplicate them.
        raw = env(T.OP_DROP + "".join(T.encode_address(n) for n in (7, 2, 7)))
        self.assertEqual(parse_envelope(raw), Drop((7, 2, 7)))

    def test_surrounding_whitespace_is_not_content(self):
        self.assertEqual(parse_envelope(env(" " + T.OP_DROP + " "
                                            + T.encode_address(5) + " ")),
                         Drop((5,)))
        self.assertEqual(parse_envelope(env(T.OP_APPEND + " \n  note  \n ")),
                         Append("note"))

    def test_text_may_contain_token_lookalikes(self):
        # Unpadded and malformed lookalikes are ordinary text and may appear
        # in an append.
        text = "the string <sid_hi_1> is not a token, nor is List<T>"
        self.assertEqual(parse_envelope(env(T.OP_APPEND + " " + text)),
                         Append(text))

    def test_rewrite_text_may_span_several_pieces(self):
        raw = env(T.OP_REWRITE + T.encode_address(2) + " line one and <b>bold</b> text ")
        self.assertEqual(parse_envelope(raw), Rewrite(2, "line one and <b>bold</b> text"))


class Malformedness(unittest.TestCase):
    # (raw envelope, expected reason)
    CASES = [
        ("missing_operator", env(" plain text with no operator ")),
        ("missing_operator", env("")),
        ("missing_address", env(T.OP_DROP)),
        ("bad_address", env(T.OP_DROP + T.ADDR_HI[4])),
        ("bad_address", env(T.OP_DROP + T.ADDR_LO[4] + T.ADDR_HI[4])),
        ("bad_address", env(T.OP_DROP + T.ADDR_HI[4] + T.ADDR_HI[5])),
        ("missing_address", env(T.OP_REWRITE + T.ADDR_LO[1] + " text ")),
        ("missing_address", env(T.OP_REWRITE)),
        ("bad_address", env(T.OP_REWRITE + T.ADDR_HI[1] + " text ")),
        ("empty_text", env(T.OP_REWRITE + T.encode_address(1) + "   ")),
        ("empty_text", env(T.OP_REWRITE + T.encode_address(1))),
        # A second address is a token, and a replacement text may not hold one.
        ("token_in_text", env(T.OP_REWRITE + T.encode_address(1) + T.encode_address(2)
                              + " two addresses ")),
        ("empty_text", env(T.OP_APPEND)),
        ("empty_text", env(T.OP_APPEND + "   \n  ")),
        ("token_in_text", env(T.OP_APPEND + " a note " + T.OP_DROP + " and a token ")),
        ("token_in_text", env(T.OP_APPEND + " " + T.ADDR_HI[0] + " starts with an address")),
        ("token_in_text", env(T.OP_REWRITE + T.encode_address(1) + " text "
                              + T.ADDR_LO[0] + " more ")),
        ("unexpected_content", env(T.OP_DROP + T.encode_address(1) + " trailing text ")),
        ("bad_address", env(T.OP_DROP + T.ADDR_HI[0])),
    ]

    def test_rejected_with_the_expected_reason(self):
        for expected, raw in self.CASES:
            with self.subTest(raw=raw):
                parsed = parse_envelope(raw)
                self.assertIsInstance(parsed, Malformed, raw)
                self.assertEqual(parsed.reason, expected)

    def test_a_malformed_envelope_keeps_its_raw_text(self):
        raw = env(T.OP_DROP)
        parsed = parse_envelope(raw)
        self.assertEqual(parsed.raw, raw)
        self.assertEqual(parsed.to_text(), raw)
        self.assertEqual(parsed.op, "malformed")

    def test_unterminated(self):
        for raw in (T.CTX_OPEN + T.OP_DROP + T.encode_address(1),
                    T.OP_DROP + T.encode_address(1) + T.CTX_CLOSE,
                    "", "<ctx>"):
            with self.subTest(raw=raw):
                self.assertEqual(parse_envelope(raw).reason, "unterminated")


class Serialization(unittest.TestCase):
    def test_canonical_forms(self):
        self.assertEqual(Drop((3,)).to_text(),
                         f"{T.CTX_OPEN}{T.OP_DROP}{T.encode_address(3)}{T.CTX_CLOSE}")
        self.assertEqual(Rewrite(2, " text ").to_text(),
                         f"{T.CTX_OPEN}{T.OP_REWRITE}{T.encode_address(2)} text {T.CTX_CLOSE}")
        self.assertEqual(Append(" text ").to_text(),
                         f"{T.CTX_OPEN}{T.OP_APPEND} text {T.CTX_CLOSE}")

    def test_round_trip_through_text(self):
        edits = [Drop((0, 1023)), Rewrite(5, "a summary of the read at lines 9-27"),
                 Append("the receipts of the fix were dropped")]
        for edit, parsed in zip(edits, parse_output(serialize(edits)).edits):
            self.assertEqual(edit, parsed)

    def test_serialize_concatenates_in_order(self):
        edits = [Append("first"), Drop((1,)), Append("second")]
        text = serialize(edits)
        self.assertEqual(text, "".join(e.to_text() for e in edits))
        self.assertEqual(parse_output(text).well_formed, edits)

    def test_json_round_trip(self):
        for edit in (Drop((4, 9)), Rewrite(1, "text"), Append("note")):
            self.assertEqual(edit_from_json(edit_to_json(edit)), edit)

    def test_json_of_a_malformed_edit(self):
        parsed = parse_envelope(env(T.OP_DROP))
        self.assertEqual(edit_to_json(parsed),
                         {"op": "malformed", "reason": "missing_address",
                          "raw": env(T.OP_DROP)})

    def test_unknown_op_is_refused(self):
        with self.assertRaises(ValueError):
            edit_from_json({"op": "replace"})


class WholeOutputs(unittest.TestCase):
    def test_text_pieces_exclude_the_envelopes(self):
        output = ("Cleaning up now.\n" + WELL_FORMED["drop_one"] + "\n"
                  "Next I run the suite.")
        parsed = parse_output(output)
        self.assertEqual(len(parsed.edits), 1)
        # Text pieces are stripped and joined by a newline; empty ones vanish.
        self.assertEqual(parsed.action_text, "Cleaning up now.\nNext I run the suite.")
        self.assertNotIn(T.CTX_OPEN, parsed.action_text)
        self.assertEqual(len(parsed.text_pieces), 2)  # the blank piece is dropped

    def test_empty_pieces_vanish_from_the_action_text(self):
        output = WELL_FORMED["append"] + "\n" + WELL_FORMED["drop_one"]
        self.assertEqual(parse_output(output).action_text, "")
        self.assertEqual(parse_output(WELL_FORMED["append"]).action_text, "")

    def test_well_formed_filters_malformed(self):
        output = WELL_FORMED["drop_one"] + env(T.OP_DROP) + WELL_FORMED["append"]
        parsed = parse_output(output)
        self.assertEqual(len(parsed.edits), 3)
        self.assertEqual(len(parsed.well_formed), 2)
        self.assertEqual(len(parsed.raws), 3)

    def test_join_pieces_normalises_blank_pieces(self):
        self.assertEqual(join_pieces(["a", "   ", "\nb\n"]), "a\nb")
        self.assertEqual(join_pieces([]), "")

    def test_plain_output_has_no_edits(self):
        parsed = parse_output("Just an ordinary answer with no tokens at all.")
        self.assertEqual(parsed.edits, [])
        self.assertEqual(parsed.action_text, "Just an ordinary answer with no tokens at all.")


class Stream(unittest.TestCase):
    def drain(self, chunks, close=True):
        parser = StreamParser()
        events = []
        for chunk in chunks:
            events.extend(parser.feed(chunk))
        if close:
            events.extend(parser.close())
        return events, parser

    def test_one_whole_output_in_a_single_chunk(self):
        for name, raw in WELL_FORMED.items():
            with self.subTest(name=name):
                events, _ = self.drain([raw])
                self.assertEqual(len(events), 1)
                self.assertIsInstance(events[0], EnvelopeDone)
                self.assertEqual(events[0].edit, parse_envelope(raw))
                self.assertEqual(events[0].raw, raw)

    def test_character_by_character_is_the_same_as_one_chunk(self):
        for name, raw in WELL_FORMED.items():
            with self.subTest(name=name):
                events, _ = self.drain(list(raw))
                self.assertEqual([e.raw for e in events], [raw])
                self.assertEqual(events[0].edit, parse_envelope(raw))

    def test_every_two_way_split_is_the_same_as_one_chunk(self):
        for name, raw in WELL_FORMED.items():
            for cut in range(len(raw) + 1):
                with self.subTest(name=name, cut=cut):
                    events, _ = self.drain([raw[:cut], raw[cut:]])
                    self.assertEqual([e.raw for e in events], [raw])
                    self.assertEqual(events[0].edit, parse_envelope(raw))

    def test_text_around_envelopes_survives_the_split(self):
        output = "Before. " + WELL_FORMED["drop_one"] + " Middle. " \
                 + WELL_FORMED["append"] + " After."
        for size in (1, 2, 3, 7, 13, 64):
            with self.subTest(size=size):
                chunks = [output[i:i + size] for i in range(0, len(output), size)]
                events, parser = self.drain(chunks)
                self.assertEqual(parser.stray_tokens, 0)
                parsed = parse_output("".join(chunks))
                edits = [e.edit for e in events if isinstance(e, EnvelopeDone)]
                self.assertEqual(edits, parsed.edits)
        self.assertEqual(parsed.action_text, "Before.\nMiddle.\nAfter.")

    def test_a_partial_token_is_held_back_not_emitted(self):
        parser = StreamParser()
        # The text up to the trailing "<sid_h" is emitted; that suffix could
        # still become a token, so it is held back.
        events = parser.feed("The next read is <sid_h")
        self.assertEqual([e.text for e in events if isinstance(e, TextChunk)],
                         ["The next read is "])
        self.assertEqual(parser.stray_tokens, 0)
        # The next chunk completes both the token string and its ">". The
        # token stands outside an envelope, so it is dropped and counted.
        events = parser.feed("i_00> the address")
        self.assertEqual("".join(e.text for e in events if isinstance(e, TextChunk)),
                         " the address")
        self.assertEqual(parser.stray_tokens, 1)
        self.assertEqual(parser.close(), [])

    def test_a_partial_token_string_without_its_bracket_is_text(self):
        # "<sid_hi_00" is a prefix of no token, so it is ordinary text.
        parser = StreamParser()
        events = parser.feed("The next read is <sid_h") + parser.feed("i_00 the address")
        self.assertEqual("".join(e.text for e in events if isinstance(e, TextChunk)),
                         "The next read is <sid_hi_00 the address")
        self.assertEqual(parser.stray_tokens, 0)

    def test_a_lone_angle_bracket_is_not_held_for_long(self):
        parser = StreamParser()
        events = parser.feed("compare a < b")
        self.assertEqual("".join(e.text for e in events if isinstance(e, TextChunk)),
                         "compare a < b")
        self.assertEqual(parser.close(), [])

    def test_partial_prefix_inside_an_envelope(self):
        parser = StreamParser()
        parser.feed(T.CTX_OPEN + T.OP_REWRITE + "<sid_hi_0")
        parser.feed("0><sid_lo_02> shorter ")
        events = parser.feed(T.CTX_CLOSE)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].edit, Rewrite(2, "shorter"))

    def test_stray_tokens_are_counted_and_dropped(self):
        events, parser = self.drain(["drop ", T.OP_DROP, " and ", T.ADDR_HI[0],
                                     T.ADDR_LO[0], " then continue"])
        self.assertEqual(parser.stray_tokens, 3)
        # Each stray token splits a text run, so the text arrives in pieces.
        self.assertEqual([e.text for e in events if isinstance(e, TextChunk)],
                         ["drop ", " and ", " then continue"])
        self.assertEqual("".join(e.text for e in events if isinstance(e, TextChunk)),
                         "drop  and  then continue")
        self.assertEqual(len([e for e in events if isinstance(e, EnvelopeDone)]), 0)

    def test_unterminated_envelope_at_close(self):
        events, parser = self.drain([T.CTX_OPEN + T.OP_DROP + T.encode_address(1)])
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], EnvelopeDone)
        self.assertIsInstance(events[0].edit, Malformed)
        self.assertEqual(events[0].edit.reason, "unterminated")

    def test_nested_open_closes_the_first_as_unterminated(self):
        events, _ = self.drain([T.CTX_OPEN, T.OP_DROP, T.encode_address(1),
                                T.CTX_OPEN, T.OP_APPEND, " note ", T.CTX_CLOSE])
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].edit.reason, "unterminated")
        self.assertEqual(events[1].edit, Append("note"))

    def test_feed_after_close_is_still_usable(self):
        parser = StreamParser()
        parser.feed(T.CTX_OPEN + T.OP_APPEND + " one ")
        events = parser.close()
        self.assertEqual(events[0].edit.reason, "unterminated")  # closed mid-envelope
        # A second envelope after close() starts clean.
        events = parser.feed(T.CTX_OPEN + T.OP_APPEND + " two " + T.CTX_CLOSE + " tail")
        self.assertEqual([e.edit for e in events if isinstance(e, EnvelopeDone)],
                         [Append("two")])
        self.assertEqual("".join(e.text for e in events if isinstance(e, TextChunk)), " tail")
        self.assertEqual(parser.stray_tokens, 0)

    def test_stream_and_batch_agree_on_a_long_output(self):
        pieces = []
        for i in range(12):
            pieces.append(f"Step {i}: I tidy the context.\n")
            pieces.append(WELL_FORMED["drop_one"])
            pieces.append(" then I continue.\n")
        output = "".join(pieces)
        expected = parse_output(output)
        for size in (1, 5, 17, 100, 4096, len(output) + 1):
            with self.subTest(size=size):
                chunks = [output[i:i + size] for i in range(0, len(output), size)]
                events, parser = self.drain(chunks)
                self.assertEqual(parser.stray_tokens, expected.stray_tokens)
                self.assertEqual([e.edit for e in events if isinstance(e, EnvelopeDone)],
                                 expected.edits)
                # Piece boundaries follow the chunks, so compare the
                # concatenation of the text, which must not depend on them.
                self.assertEqual("".join(e.text for e in events
                                         if isinstance(e, TextChunk)),
                                 "".join(expected.text_pieces))


if __name__ == "__main__":
    unittest.main()
