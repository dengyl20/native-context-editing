"""The state model and the transitions of the three operators.

Addresses are issued once and never reused, a drop retires an address for
good, a rewrite keeps the address and appends the previous text to its
history, and an append creates a note with the next address. The state also
survives a JSON round trip, which is what the conformance fixtures use.
"""
from __future__ import annotations

import unittest

import context  # noqa: F401  (sets sys.path)

from nce.state import Action, AddressExhausted, AddressPool, Block, Reminder, State
from nce.tokens import ADDR_CAPACITY


class AddressPoolBehaviour(unittest.TestCase):
    def test_issues_in_order_from_zero(self):
        pool = AddressPool()
        self.assertEqual([pool.allocate() for _ in range(4)], [0, 1, 2, 3])

    def test_a_retired_address_is_never_issued_again(self):
        pool = AddressPool()
        first = pool.allocate()
        pool.retire(first)
        rest = [pool.allocate() for _ in range(5)]
        self.assertNotIn(first, rest)
        self.assertEqual(rest, [1, 2, 3, 4, 5])

    def test_was_issued_distinguishes_unknown_from_retired(self):
        pool = AddressPool()
        pool.allocate()          # 0
        pool.allocate()          # 1
        pool.retire(1)
        self.assertTrue(pool.was_issued(0))
        self.assertTrue(pool.was_issued(1))   # issued, then retired
        self.assertFalse(pool.was_issued(2))  # never issued
        self.assertFalse(pool.was_issued(-1))

    def test_capacity_is_enforced(self):
        pool = AddressPool(next_address=ADDR_CAPACITY)
        with self.assertRaises(AddressExhausted):
            pool.allocate()

    def test_last_address_is_reachable(self):
        pool = AddressPool(next_address=ADDR_CAPACITY - 1)
        self.assertEqual(pool.allocate(), ADDR_CAPACITY - 1)
        with self.assertRaises(AddressExhausted):
            pool.allocate()


class StateGrowth(unittest.TestCase):
    def setUp(self):
        self.state = State()

    def test_blocks_get_consecutive_addresses(self):
        a = self.state.add_block("system", "prompt", locked=True)
        b = self.state.add_block("user", "task")
        c = self.state.add_block("tool", "result", tool_name="read")
        self.assertEqual([a.address, b.address, c.address], [0, 1, 2])
        self.assertEqual(self.state.pool.next_address, 3)

    def test_items_keep_interaction_order(self):
        self.state.add_block("user", "task")
        self.state.add_action("I will read the parser.")
        self.state.add_reminder("soft", "tidy up")
        self.state.add_block("tool", "result", tool_name="read")
        kinds = [type(i).__name__ for i in self.state]
        self.assertEqual(kinds, ["Block", "Action", "Reminder", "Block"])

    def test_views_partition_the_items(self):
        self.state.add_block("user", "task")
        self.state.add_action("one")
        self.state.add_reminder("soft", "tidy up")
        self.state.add_block("tool", "result", tool_name="read")
        self.assertEqual(len(self.state.live_blocks()), 2)
        self.assertEqual(len(self.state.actions()), 1)
        self.assertEqual(len(self.state.reminders()), 1)

    def test_unknown_role_is_refused(self):
        with self.assertRaises(ValueError):
            self.state.add_block("assistant", "text")

    def test_clear_reminders_keeps_everything_else(self):
        self.state.add_block("user", "task")
        self.state.add_reminder("soft", "one")
        self.state.add_action("work")
        self.state.add_reminder("hard", "two")
        self.state.clear_reminders()
        self.assertEqual(self.state.reminders(), [])
        self.assertEqual(len(self.state.items), 2)

    def test_note_blocks_carry_the_note_role(self):
        note = self.state.append_note("what was learned")
        self.assertEqual(note.role, "note")
        self.assertIn(note.address, self.state.blocks)


class DropTransition(unittest.TestCase):
    def setUp(self):
        self.state = State()
        self.a = self.state.add_block("user", "task")
        self.b = self.state.add_block("tool", "result", tool_name="read")
        self.c = self.state.add_block("tool", "receipt", tool_name="edit")

    def test_drop_removes_the_block_and_retires_its_address(self):
        self.state.drop(self.b.address)
        self.assertNotIn(self.b.address, self.state.blocks)
        self.assertNotIn(self.b, self.state.items)
        self.assertIn(self.b.address, self.state.pool.retired)
        self.assertEqual([blk.address for blk in self.state.live_blocks()],
                         [self.a.address, self.c.address])

    def test_dropped_blocks_leave_the_other_blocks_untouched(self):
        before = self.a.text
        self.state.drop(self.b.address)
        self.assertEqual(self.state.blocks[self.a.address].text, before)
        self.assertEqual(self.state.blocks[self.c.address].address, self.c.address)

    def test_a_new_block_never_takes_a_retired_address(self):
        self.state.drop(self.b.address)
        new = self.state.add_block("tool", "later result", tool_name="bash")
        self.assertEqual(new.address, 3)
        self.assertNotIn(new.address, self.state.pool.retired)

    def test_dropping_twice_is_an_error_at_the_state_layer(self):
        # The runtime checks liveness first; the state layer is strict, so a
        # double drop cannot silently pass through it.
        self.state.drop(self.b.address)
        with self.assertRaises(KeyError):
            self.state.drop(self.b.address)

    def test_every_block_can_be_dropped_but_the_pool_keeps_counting(self):
        for block in (self.a, self.b, self.c):
            self.state.drop(block.address)
        self.assertEqual(self.state.live_blocks(), [])
        self.assertEqual(self.state.items, [])
        self.assertEqual(self.state.pool.next_address, 3)
        self.assertEqual(sorted(self.state.pool.retired), [0, 1, 2])


class RewriteTransition(unittest.TestCase):
    def setUp(self):
        self.state = State()
        self.block = self.state.add_block("tool", "the original read", tool_name="read")

    def test_rewrite_replaces_the_text_and_keeps_the_address(self):
        address = self.block.address
        self.state.rewrite(address, "a shorter summary")
        self.assertEqual(self.state.blocks[address].text, "a shorter summary")
        self.assertEqual(self.state.blocks[address].address, address)

    def test_rewrite_keeps_the_previous_text_as_history(self):
        address = self.block.address
        self.state.rewrite(address, "first summary")
        self.state.rewrite(address, "second summary")
        self.assertEqual(self.state.blocks[address].history,
                         ["the original read", "first summary"])
        self.assertEqual(self.state.blocks[address].text, "second summary")

    def test_rewrite_does_not_touch_the_address_pool(self):
        self.state.rewrite(self.block.address, "summary")
        self.assertEqual(self.state.pool.next_address, 1)
        self.assertEqual(self.state.pool.retired, set())

    def test_rewrite_does_not_reorder_the_items(self):
        self.state.add_block("tool", "later", tool_name="bash")
        self.state.rewrite(self.block.address, "summary")
        self.assertEqual(self.state.live_blocks()[0].text, "summary")

    def test_rewrite_keeps_the_locked_flag(self):
        state = State()
        block = state.add_block("system", "prompt", locked=True)
        state.rewrite(block.address, "still locked")
        self.assertTrue(state.blocks[block.address].locked)

    def test_rewrite_of_an_unknown_address_is_an_error(self):
        with self.assertRaises(KeyError):
            self.state.rewrite(9, "summary")


class AppendTransition(unittest.TestCase):
    def test_append_takes_the_next_address_and_ends_the_item_list(self):
        state = State()
        state.add_block("user", "task")
        note = state.append_note("what was learned")
        self.assertEqual(note.address, 1)
        self.assertEqual(note.role, "note")
        self.assertIs(state.items[-1], note)

    def test_appended_notes_survive_a_drop_of_the_block_they_describe(self):
        state = State()
        block = state.add_block("tool", "long read", tool_name="read")
        note = state.append_note("the read at lines 9-27: accumulates per unit")
        state.drop(block.address)
        self.assertEqual([b.text for b in state.live_blocks()],
                         ["the read at lines 9-27: accumulates per unit"])
        self.assertEqual(note.address, 1)

    def test_appended_notes_can_themselves_be_rewritten(self):
        state = State()
        note = state.append_note("short note")
        state.rewrite(note.address, "even shorter")
        self.assertEqual(state.live_blocks()[0].text, "even shorter")

    def test_address_exhaustion_is_reported(self):
        state = State()
        state.pool.next_address = ADDR_CAPACITY
        with self.assertRaises(AddressExhausted):
            state.append_note("no room left")


class StateSerialization(unittest.TestCase):
    def build(self) -> State:
        state = State()
        state.add_block("system", "prompt", locked=True)     # 0
        state.add_block("user", "task")                      # 1
        state.add_block("tool", "the read", tool_name="read")  # 2
        state.add_action("I will read the parser.")
        state.add_reminder("soft", "tidy up")
        state.rewrite(2, "a summary of the read")
        state.drop(1)
        state.append_note("the receipt of the edit was dropped")  # 3
        return state

    def test_round_trip_preserves_everything(self):
        state = self.build()
        clone = State.from_json(state.to_json())
        self.assertEqual(state.to_json(), clone.to_json())
        self.assertEqual([type(i).__name__ for i in clone], [type(i).__name__ for i in state])
        self.assertEqual(clone.pool.retired, state.pool.retired)
        self.assertEqual(clone.pool.next_address, state.pool.next_address)
        self.assertEqual(clone.blocks[2].history, ["the read"])
        self.assertEqual([b.text for b in clone.live_blocks()],
                         ["prompt", "a summary of the read",
                          "the receipt of the edit was dropped"])

    def test_a_copy_is_independent(self):
        state = self.build()
        clone = state.copy()
        clone.drop(2)
        clone.append_note("only in the copy")
        self.assertIn(2, state.blocks)
        self.assertNotIn(2, clone.blocks)
        self.assertEqual(len(clone.live_blocks()), len(state.live_blocks()))
        self.assertIn("only in the copy", [b.text for b in clone.live_blocks()])
        self.assertNotIn("only in the copy", [b.text for b in state.live_blocks()])

    def test_from_json_rejects_a_duplicate_address(self):
        with self.assertRaises(ValueError):
            State.from_json({"items": [
                {"type": "block", "address": 1, "role": "user", "text": "a"},
                {"type": "block", "address": 1, "role": "tool", "text": "b"},
            ], "retired": [], "next_address": 2})

    def test_from_json_rejects_a_live_block_with_a_retired_address(self):
        with self.assertRaises(ValueError):
            State.from_json({"items": [
                {"type": "block", "address": 1, "role": "user", "text": "a"},
            ], "retired": [1], "next_address": 2})

    def test_from_json_rejects_a_next_address_below_a_known_one(self):
        with self.assertRaises(ValueError):
            State.from_json({"items": [
                {"type": "block", "address": 5, "role": "user", "text": "a"},
            ], "retired": [], "next_address": 3})

    def test_from_json_rejects_an_unknown_item_type(self):
        with self.assertRaises(ValueError):
            State.from_json({"items": [{"type": "episode", "text": "a"}],
                             "retired": [], "next_address": 0})

    def test_optional_fields_are_omitted_from_the_json(self):
        state = State()
        state.add_block("user", "task")
        item = state.to_json()["items"][0]
        self.assertNotIn("tool_name", item)
        self.assertNotIn("locked", item)
        state.add_block("tool", "result", tool_name="read")
        self.assertEqual(state.to_json()["items"][1]["tool_name"], "read")

    def test_action_and_reminder_json_shapes(self):
        self.assertEqual(Action("work").to_json(), {"type": "action", "text": "work"})
        self.assertEqual(Reminder("hard", "now").to_json(),
                         {"type": "reminder", "level": "hard", "text": "now"})


if __name__ == "__main__":
    unittest.main()
