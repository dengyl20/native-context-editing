"""Conformance: the fixtures in tests/fixtures/ against the specification.

The fixtures are plain JSON, one per file, holding the scripted outputs and
the expected verdicts of spec/grammar.md and spec/semantics.md. A second
implementation can read the same files without importing this package, so the
assertions here are deliberately about the file contents and stay clear of this
package's internals.

Regenerate the fixtures with ``python3 tests/make_fixtures.py``.
"""
from __future__ import annotations

import json
import os
import unittest

import context  # noqa: F401  (sets sys.path and gives DATA)

from nce import tokens as T
from nce.grammar import parse_output
from nce.render import DEFAULT_FORMAT, render_text
from nce.runtime import execute
from nce.state import State

FIXTURES = context.DATA

# The verdicts the spec allows, and which of them count as executed.
STATUSES = {"applied", "applied_as_append", "rejected"}
EXECUTED = {"applied", "applied_as_append"}

# One expected verdict per named case, written out here so a change of the
# fixtures has to be justified in two places.
EXPECTED = {
    "drop_one": ["applied"],
    "drop_many": ["applied"],
    "drop_repeated_address": ["applied"],
    "rewrite_live": ["applied"],
    "append": ["applied"],
    "three_edits_in_order": ["applied", "applied", "applied"],
    "locked_block": ["rejected"],
    "locked_block_blocks_the_others": ["rejected"],
    "unknown_address": ["rejected"],
    "retired_address": ["applied", "rejected"],
    "duplicate_verbatim": ["applied", "rejected"],
    "malformed_missing_address": ["rejected"],
    "malformed_bad_address": ["rejected"],
    "malformed_empty_text": ["rejected"],
    "malformed_token_in_text": ["rejected"],
    "malformed_unexpected_content": ["rejected"],
    "rewrite_of_a_dead_block": ["applied", "applied_as_append"],
    "stray_token": [],
}

# The reason the spec requires for each refused edit, where it fixes one.
EXPECTED_REASON = {
    "locked_block": "locked",
    "locked_block_blocks_the_others": "locked",
    "unknown_address": "unknown_address",
    "retired_address": "not_live",
    "duplicate_verbatim": "duplicate",
    "malformed_missing_address": "missing_address",
    "malformed_bad_address": "bad_address",
    "malformed_empty_text": "empty_text",
    "malformed_token_in_text": "token_in_text",
    "malformed_unexpected_content": "unexpected_content",
}

# Cases whose refusal is a valid outcome of a different kind: the rewrite of a
# dead block is kept as a note, and the reason rides on that result.
EXPECTED_NOTE = {"rewrite_of_a_dead_block": "not_live"}


def load(name: str) -> dict:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


# Strings that must never appear in a published fixture. Assembled from
# fragments so this test file does not contain them either, which would make
# the leak scan fire on the test that exists to keep the fixtures clean.
FORBIDDEN = ["dolphin" + "fs", "/mnt" + "/", "hadoop-" + "aipnlp", "/home" + "/",
             "sanku" + "ai", "view" + "fs" + "://"]


class FixtureFiles(unittest.TestCase):
    def test_every_expected_file_is_present_and_parses(self):
        for name in ("vocabulary.json", "session.json", "edits.json"):
            with self.subTest(name=name):
                payload = load(name)
                self.assertIn("name", payload)
                self.assertIn("description", payload)

    def test_the_edit_cases_cover_the_named_rules(self):
        payload = load("edits.json")
        self.assertEqual(sorted(c["name"] for c in payload["cases"]), sorted(EXPECTED))

    def test_the_fixtures_carry_no_internal_paths(self):
        for name in ("vocabulary.json", "session.json", "edits.json"):
            with self.subTest(name=name):
                with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
                    text = handle.read()
                for needle in FORBIDDEN:
                    self.assertNotIn(needle, text, needle)


class VocabularyFixture(unittest.TestCase):
    def setUp(self):
        self.payload = load("vocabulary.json")

    def test_the_token_table_matches_the_package(self):
        self.assertEqual(self.payload["tokens"], list(T.NCE_TOKENS))
        self.assertEqual(len(self.payload["tokens"]), 70)

    def test_the_group_sizes_are_the_papers(self):
        groups = self.payload["groups"]
        self.assertEqual(len(groups["high"]), 32)
        self.assertEqual(len(groups["low"]), 32)
        self.assertEqual(len(groups["operators"]), 3)
        self.assertEqual(len(groups["envelope"]), 2)
        self.assertEqual(len(groups["lock"]), 1)
        flat = [t for group in groups.values() for t in group]
        self.assertEqual(sorted(flat), sorted(self.payload["tokens"]))

    def test_the_addresses_match_the_formula(self):
        for key, written in self.payload["addresses"].items():
            n = int(key)
            with self.subTest(block=n):
                self.assertEqual(written, T.encode_address(n))
                hi, lo = T.encode_address_pair(n)
                self.assertEqual(hi, f"<sid_hi_{n // 32:02d}>")
                self.assertEqual(lo, f"<sid_lo_{n % 32:02d}>")

    def test_the_appendix_witness_row(self):
        # "The 72nd block is represented by <sid_hi_02><sid_lo_07>" -- the
        # block numbered 71, counted from zero.
        self.assertEqual(self.payload["addresses"]["71"], "<sid_hi_02><sid_lo_07>")

    def test_every_token_string_is_a_single_token_shaped_string(self):
        for token in self.payload["tokens"]:
            with self.subTest(token=token):
                self.assertTrue(token.startswith("<") and token.endswith(">"))
                self.assertNotIn(" ", token)
                self.assertNotIn("\n", token)


class SessionFixture(unittest.TestCase):
    def setUp(self):
        self.payload = load("session.json")
        self.state = State.from_json(self.payload["state"])

    def test_the_state_loads_and_matches_its_expected_summary(self):
        expected = self.payload["expected"]
        self.assertEqual([b.address for b in self.state.live_blocks()],
                         expected["live_addresses"])
        self.assertEqual(sorted(self.state.pool.retired), expected["retired"])
        self.assertEqual(self.state.pool.next_address, expected["next_address"])
        self.assertEqual({"blocks": len(self.state.live_blocks()),
                          "actions": len(self.state.actions()),
                          "reminders": len(self.state.reminders())},
                         expected["counts"])

    def test_the_state_is_internally_consistent(self):
        self.assertTrue(set(self.state.blocks) & set(self.state.pool.retired) == set())
        self.assertTrue(all(b.address < self.state.pool.next_address
                            for b in self.state.live_blocks()))

    def test_the_rendered_text_is_what_the_file_records(self):
        self.assertEqual(render_text(self.state, DEFAULT_FORMAT), self.payload["rendered"])

    def test_the_rendering_opens_every_block_with_its_address(self):
        rendered = self.payload["rendered"]
        for block in self.state.live_blocks():
            with self.subTest(address=block.address):
                self.assertIn(T.encode_address(block.address), rendered)

    def test_the_locked_block_carries_the_marker_and_the_others_do_not(self):
        rendered = self.payload["rendered"]
        self.assertEqual(rendered.count(T.LOCKED), 1)
        self.assertIn(T.encode_address(0) + T.LOCKED, rendered)

    def test_a_dropped_block_leaves_no_trace(self):
        dropped = [a for a in self.payload["expected"]["retired"]]
        recorded = self.payload["state"]
        for address in dropped:
            self.assertNotIn(address, [item["address"] for item in recorded["items"]
                                       if item["type"] == "block"])

    def test_the_state_round_trips_through_json(self):
        clone = State.from_json(json.loads(json.dumps(self.payload["state"])))
        self.assertEqual(clone.to_json(), self.state.to_json())


class EditCases(unittest.TestCase):
    def setUp(self):
        self.payload = load("edits.json")

    def case(self, name: str) -> dict:
        return next(c for c in self.payload["cases"] if c["name"] == name)

    def test_the_initial_state_is_the_unedited_session(self):
        # Every case starts from the same state: the five blocks of the session
        # before any edit, with no address retired.
        initial = self.payload["initial_state"]
        self.assertEqual(initial["retired"], [])
        self.assertEqual(initial["next_address"], 5)
        self.assertEqual([i["address"] for i in initial["items"] if i["type"] == "block"],
                         [0, 1, 2, 3, 4])
        self.assertTrue(initial["items"][0]["locked"])

    def test_the_session_fixture_records_a_state_that_replays_from_the_initial_one(self):
        # session.json is the same session after a fuller editing turn: a
        # receipt dropped, a read rewritten, a note appended, and the action of
        # the turn recorded. Replaying that turn must produce exactly it.
        initial = State.from_json(self.payload["initial_state"])
        recorded = load("session.json")["state"]
        dropped = set(recorded["retired"])
        self.assertEqual(dropped, {3})
        for address in (2,):
            before = initial.blocks[address].text
            after = State.from_json(recorded).blocks[address].text
            self.assertNotEqual(before, after)

    def test_every_case_has_a_recorded_verdict(self):
        for case in self.payload["cases"]:
            with self.subTest(case=case["name"]):
                self.assertEqual([r["status"] for r in case["results"]],
                                 EXPECTED[case["name"]])
                for result in case["results"]:
                    self.assertIn(result["status"], STATUSES)
                    self.assertIn("op", result["edit"])

    def test_every_refusal_states_a_reason(self):
        for case in self.payload["cases"]:
            for result in case["results"]:
                with self.subTest(case=case["name"], status=result["status"]):
                    if result["status"] == "rejected":
                        self.assertTrue(result["reason"])

    def test_the_reasons_are_the_ones_the_spec_fixes(self):
        for name, reason in EXPECTED_REASON.items():
            results = self.case(name)["results"]
            reasons = [r.get("reason") for r in results if r["status"] == "rejected"]
            with self.subTest(case=name):
                self.assertIn(reason, reasons)

    def test_a_redirected_edit_states_why_it_was_redirected(self):
        for name, reason in EXPECTED_NOTE.items():
            results = self.case(name)["results"]
            with self.subTest(case=name):
                redirected = [r for r in results if r["status"] == "applied_as_append"]
                self.assertTrue(redirected)
                self.assertTrue(all(r.get("reason") == reason for r in redirected))

    def test_a_failed_edit_changes_nothing(self):
        for case in self.payload["cases"]:
            if all(r["status"] == "rejected" for r in case["results"]) and case["results"]:
                with self.subTest(case=case["name"]):
                    self.assertEqual(case["state_after"], case["state_before"])

    def test_an_executed_edit_changes_the_state(self):
        for case in self.payload["cases"]:
            if any(r["status"] in EXECUTED for r in case["results"]):
                with self.subTest(case=case["name"]):
                    self.assertNotEqual(case["state_after"], case["state_before"])

    def test_the_recorded_state_after_replays_from_the_case(self):
        for case in self.payload["cases"]:
            with self.subTest(case=case["name"]):
                state = State.from_json(case["state_before"])
                parsed = parse_output(case["output"])
                execute(state, parsed.edits, parsed.raws)
                self.assertEqual(state.to_json(), case["state_after"])

    def test_no_envelope_is_retained_in_the_action_text(self):
        for case in self.payload["cases"]:
            with self.subTest(case=case["name"]):
                self.assertNotIn(T.CTX_OPEN, case["action_text"])
                self.assertNotIn(T.CTX_CLOSE, case["action_text"])

    def test_every_recorded_state_after_loads(self):
        for case in self.payload["cases"]:
            with self.subTest(case=case["name"]):
                self.assertIsInstance(State.from_json(case["state_after"]), State)

    def test_the_addresses_retired_by_a_case_stay_retired(self):
        for case in self.payload["cases"]:
            with self.subTest(case=case["name"]):
                after = case["state_after"]
                retired = set(after["retired"])
                live = {item["address"] for item in after["items"]
                        if item["type"] == "block"}
                self.assertEqual(retired & live, set())
                if retired:
                    self.assertGreaterEqual(after["next_address"], max(retired) + 1)

    def test_the_drop_that_lands_retires_the_address(self):
        case = self.case("drop_many")
        after = case["state_after"]
        self.assertEqual(sorted(after["retired"]), [2, 4])
        self.assertNotIn(2, {i["address"] for i in after["items"] if i["type"] == "block"})

    def test_the_rewrite_keeps_the_address_and_replaces_the_text(self):
        case = self.case("rewrite_live")
        after = case["state_after"]
        block = next(i for i in after["items"] if i["type"] == "block" and i["address"] == 2)
        before = next(i for i in case["state_before"]["items"]
                      if i["type"] == "block" and i["address"] == 2)
        self.assertNotEqual(block["text"], before["text"])
        self.assertIn("accumulates per unit", block["text"])

    def test_the_append_takes_the_next_address(self):
        case = self.case("append")
        after = case["state_after"]
        taken = {i["address"] for i in after["items"] if i["type"] == "block"}
        self.assertIn(5, taken)
        self.assertEqual(after["next_address"], 6)

    def test_the_stray_token_case_keeps_the_text_and_counts_the_token(self):
        case = self.case("stray_token")
        self.assertEqual(case["stray_tokens"], 1)
        self.assertEqual(case["results"], [])
        self.assertNotIn(T.OP_DROP, case["action_text"])
        self.assertEqual(case["state_after"], case["state_before"])

    def test_the_rewrite_of_a_dead_block_is_kept_as_a_note(self):
        case = self.case("rewrite_of_a_dead_block")
        results = case["results"]
        self.assertEqual(results[1]["status"], "applied_as_append")
        self.assertEqual(results[1]["reason"], "not_live")
        new_address = results[1]["new_address"]
        block = next(i for i in case["state_after"]["items"]
                     if i["type"] == "block" and i["address"] == new_address)
        self.assertEqual(block["role"], "note")
        self.assertIn("summary of the receipt", block["text"])

    def test_the_locked_block_survives_every_case(self):
        for case in self.payload["cases"]:
            with self.subTest(case=case["name"]):
                live = {i["address"] for i in case["state_after"]["items"]
                        if i["type"] == "block"}
                self.assertIn(0, live)


if __name__ == "__main__":
    unittest.main()
