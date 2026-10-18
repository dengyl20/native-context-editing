"""Vocabulary integrity: exactly the 70 tokens of the paper's Table A.1.

The three counts, the address scheme, the token regex, and the round trip
between an address and its two tokens are all checked against constants
written out here independently of the implementation.
"""
from __future__ import annotations

import re
import unittest

import context  # noqa: F401  (sets sys.path)

from nce import tokens as T


class VocabularyCounts(unittest.TestCase):
    def test_exactly_seventy_tokens(self):
        self.assertEqual(len(T.NCE_TOKENS), 70)
        self.assertEqual(len(set(T.NCE_TOKENS)), 70)

    def test_group_sizes_match_the_paper(self):
        # Table A.1: 32 high digits, 32 low digits, 3 operators, 2 envelope
        # delimiters, 1 lock marker.
        self.assertEqual(len(T.ADDR_HI), 32)
        self.assertEqual(len(T.ADDR_LO), 32)
        self.assertEqual(len(T.OPERATORS), 3)
        self.assertEqual(len(T.CONTROL_TOKENS), 6)
        self.assertEqual(32 + 32 + 3 + 2 + 1, 70)

    def test_no_token_is_shared_between_groups(self):
        groups = [T.ADDR_HI, T.ADDR_LO, T.OPERATORS, [T.CTX_OPEN, T.CTX_CLOSE], [T.LOCKED]]
        seen = set()
        for group in groups:
            for token in group:
                self.assertNotIn(token, seen, f"{token} appears in two groups")
                seen.add(token)
        self.assertEqual(len(seen), 70)

    def test_high_and_low_digits_are_aligned(self):
        for i in range(32):
            self.assertEqual(T.ADDR_HI[i], f"<sid_hi_{i:02d}>")
            self.assertEqual(T.ADDR_LO[i], f"<sid_lo_{i:02d}>")

    def test_operator_and_marker_strings(self):
        self.assertEqual(sorted(T.OPERATORS),
                         ["<op_append>", "<op_drop>", "<op_rewrite>"])
        self.assertEqual((T.CTX_OPEN, T.CTX_CLOSE), ("<ctx>", "</ctx>"))
        self.assertEqual(T.LOCKED, "<m_ro>")

    def test_every_token_has_a_regex_role(self):
        # The token regex must recognise all 70 and nothing but them.
        for token in T.NCE_TOKENS:
            self.assertTrue(T.TOKEN_RE.fullmatch(token), token)
            self.assertTrue(T.is_nce_token(token), token)
        # A near miss that keeps the shape is not a token.
        for token in T.NCE_TOKENS:
            if "_" in token:
                self.assertFalse(T.is_nce_token(token.replace("_", "-")), token)
            self.assertFalse(T.is_nce_token(token + "x"), token)
            self.assertFalse(T.is_nce_token(token[:-1]), token)


class AddressScheme(unittest.TestCase):
    def test_capacity_is_thirty_two_squared(self):
        self.assertEqual(T.ADDR_CAPACITY, 1024)
        self.assertEqual(T.ADDR_BASE, 32)

    def test_block_n_is_hi_n_over_32_and_lo_n_mod_32(self):
        # The formula the paper states, with the witness rows of Table A.1.
        for n in (0, 1, 31, 32, 33, 100, 511, 1023):
            hi, lo = T.encode_address_pair(n)
            self.assertEqual(hi, T.ADDR_HI[n // 32])
            self.assertEqual(lo, T.ADDR_LO[n % 32])

    def test_witness_addresses(self):
        self.assertEqual(T.encode_address(0), "<sid_hi_00><sid_lo_00>")
        self.assertEqual(T.encode_address(31), "<sid_hi_00><sid_lo_31>")
        self.assertEqual(T.encode_address(32), "<sid_hi_01><sid_lo_00>")
        self.assertEqual(T.encode_address(1023), "<sid_hi_31><sid_lo_31>")

    def test_round_trip_over_the_entire_space(self):
        for n in range(T.ADDR_CAPACITY):
            hi, lo = T.encode_address_pair(n)
            self.assertEqual(T.decode_address(hi, lo), n)
        self.assertEqual(len({T.encode_address(n) for n in range(T.ADDR_CAPACITY)}),
                         T.ADDR_CAPACITY)

    def test_out_of_range_addresses_are_refused(self):
        for n in (-1, 1024, 10_000):
            with self.assertRaises(ValueError):
                T.encode_address(n)

    def test_decoding_rejects_non_addresses(self):
        with self.assertRaises(ValueError):
            T.decode_address("<sid_lo_00>", "<sid_lo_00>")
        with self.assertRaises(ValueError):
            T.decode_address("<sid_hi_00>", "<sid_hi_00>")
        with self.assertRaises(ValueError):
            T.decode_address("<sid_hi_00>", "<sid_lo_99>")

    def test_classification_helpers(self):
        self.assertTrue(T.is_hi("<sid_hi_31>"))
        self.assertFalse(T.is_hi("<sid_lo_31>"))
        self.assertTrue(T.is_lo("<sid_lo_31>"))
        self.assertFalse(T.is_lo("<sid_hi_31>"))
        self.assertFalse(T.is_nce_token("<sid_hi_32>"))


class TokenRegex(unittest.TestCase):
    def test_padded_tokens_only(self):
        # Unpadded indices are ordinary text, so the regex cannot eat them.
        for text in ("<sid_hi_1>", "<sid_lo_9>", "<sid_hi_32>", "<sid_lo_00x>",
                     "<op_dropx>", "<CTX>", "<m_ro_>", "List<T>", "<tool_call>"):
            self.assertIsNone(T.TOKEN_RE.search(text), text)

    def test_finds_every_token_in_a_mixed_string(self):
        text = "a<ctx>b<op_drop><sid_hi_01><sid_lo_31></ctx>c<m_ro>d"
        self.assertEqual(T.TOKEN_RE.findall(text),
                         ["<ctx>", "<op_drop>", "<sid_hi_01>", "<sid_lo_31>",
                          "</ctx>", "<m_ro>"])

    def test_split_tokens_keeps_the_text_between(self):
        text = "drop <ctx><op_drop><sid_hi_00><sid_lo_00></ctx> now"
        self.assertEqual(T.split_tokens(text),
                         ["drop ", "<ctx>", "<op_drop>", "<sid_hi_00>", "<sid_lo_00>",
                          "</ctx>", " now"])
        self.assertEqual("".join(T.split_tokens(text)), text)

    def test_split_tokens_on_pure_text(self):
        self.assertEqual(T.split_tokens("nothing to see"), ["nothing to see"])
        self.assertEqual(T.split_tokens(""), [])

    def test_contains_nce_token(self):
        self.assertTrue(T.contains_nce_token("x <op_append> y"))
        self.assertFalse(T.contains_nce_token("x <op-append> y"))
        self.assertFalse(T.contains_nce_token("plain text"))

    def test_max_token_len_covers_every_token(self):
        self.assertEqual(T.MAX_TOKEN_LEN, max(len(t) for t in T.NCE_TOKENS))


class SpecialTokenRegistration(unittest.TestCase):
    class FakeTokenizer:
        """Stands in for a Hugging Face tokenizer; no third-party import."""

        def __init__(self, atomic=()):
            self.atomic = set(atomic)
            self.added = []
            self._vocab = {t: i for i, t in enumerate(atomic)}

        def add_special_tokens(self, mapping, **kw):
            tokens = mapping["additional_special_tokens"]
            new = [t for t in tokens if t not in self.added]
            self.added.extend(new)
            for t in new:
                self._vocab[t] = len(self._vocab)
            self.atomic |= set(new)
            return len(new)

        def encode(self, text, add_special_tokens=True):
            return [self._vocab[text]] if text in self.atomic else [0] * len(text)

        def __len__(self):
            return len(self._vocab)

    def test_all_seventy_are_registered_at_once(self):
        tok = self.FakeTokenizer()
        self.assertEqual(T.add_nce_tokens(tok), 70)
        self.assertEqual(tok.added, T.NCE_TOKENS)
        self.assertEqual(T.check_tokenizer(tok), [])

    def test_registering_twice_adds_nothing(self):
        tok = self.FakeTokenizer()
        T.add_nce_tokens(tok)
        self.assertEqual(T.add_nce_tokens(tok), 0)

    def test_checker_reports_tokens_that_are_not_atomic(self):
        tok = self.FakeTokenizer(atomic=["<ctx>", "<op_drop>"])
        bad = T.check_tokenizer(tok)
        self.assertNotIn("<ctx>", bad)
        self.assertIn("<sid_hi_00>", bad)
        self.assertEqual(len(bad), 68)


if __name__ == "__main__":
    unittest.main()
