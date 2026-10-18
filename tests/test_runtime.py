"""Execution: the checks of Appendix A.3 and the turn step of Eq. 1.

An edit executes only if it is well formed, every address names a live
block, and no edit touches the locked block. A failed edit changes nothing,
a rewrite of a block that is no longer live is kept as an append, a repeated
envelope executes once, and the envelopes never enter the context.
"""
from __future__ import annotations

import unittest

import context  # noqa: F401  (sets sys.path)

from nce.grammar import Append, Drop, Malformed, Rewrite, parse_output, serialize
from nce.render import render_messages, render_text, ChatFormat, approx_tokens
from nce.runtime import (APPLIED, APPLIED_AS_APPEND, HARD_REMINDER, REJECTED, REMINDER_TEXT,
                         SOFT_REMINDER, EditResult, ReminderPolicy, Runtime, apply_output,
                         execute)
from nce.state import State
from nce import tokens as T


def envelope(text: str):
    parsed = parse_output(text)
    return parsed.edits, parsed.raws


class ExecutionChecks(unittest.TestCase):
    def setUp(self):
        self.state = State()
        self.system = self.state.add_block("system", "prompt", locked=True)   # 0
        self.task = self.state.add_block("user", "the task")                  # 1
        self.read = self.state.add_block("tool", "a long read", tool_name="read")   # 2
        self.receipt = self.state.add_block("tool", "updated successfully",
                                            tool_name="edit")                 # 3

    def run_edit(self, text: str):
        edits, raws = envelope(text)
        return execute(self.state, edits, raws)

    # -- accepted ------------------------------------------------------------

    def test_drop_of_a_live_block(self):
        result = self.run_edit(f"<ctx><op_drop>{T.encode_address(2)}</ctx>")[0]
        self.assertEqual(result.status, APPLIED)
        self.assertNotIn(2, self.state.blocks)
        self.assertIn(2, self.state.pool.retired)

    def test_drop_of_several_blocks_in_one_envelope(self):
        self.run_edit("<ctx><op_drop>" + T.encode_address(2) + T.encode_address(3) + "</ctx>")
        self.assertEqual(sorted(self.state.blocks), [0, 1])

    def test_a_repeated_address_in_one_drop_counts_once(self):
        result = self.run_edit("<ctx><op_drop>" + T.encode_address(2) * 2 + "</ctx>")[0]
        self.assertEqual(result.status, APPLIED)
        self.assertNotIn(2, self.state.blocks)

    def test_rewrite_of_a_live_block(self):
        result = self.run_edit(f"<ctx><op_rewrite>{T.encode_address(2)} a summary </ctx>")[0]
        self.assertEqual(result.status, APPLIED)
        self.assertEqual(self.state.blocks[2].text, "a summary")
        self.assertEqual(self.state.blocks[2].history, ["a long read"])

    def test_append_creates_a_note(self):
        result = self.run_edit("<ctx><op_append> the receipt can go </ctx>")[0]
        self.assertEqual(result.status, APPLIED)
        self.assertEqual(result.new_address, 4)
        self.assertEqual(self.state.blocks[4].role, "note")
        self.assertEqual(self.state.blocks[4].text, "the receipt can go")

    def test_several_edits_in_one_turn_run_in_order(self):
        text = ("<ctx><op_append> tested </ctx>"
                + f"<ctx><op_drop>{T.encode_address(3)}</ctx>"
                + f"<ctx><op_rewrite>{T.encode_address(2)} a summary </ctx>")
        results = self.run_edit(text)
        self.assertEqual([r.status for r in results], [APPLIED, APPLIED, APPLIED])
        self.assertEqual(self.state.blocks[4].text, "tested")
        self.assertNotIn(3, self.state.blocks)
        self.assertEqual(self.state.blocks[2].text, "a summary")

    # -- rejected ------------------------------------------------------------

    def test_an_edit_that_fails_changes_nothing(self):
        before = self.state.to_json()
        result = self.run_edit("<ctx><op_drop>"
                               + T.encode_address(2) + T.encode_address(9) + "</ctx>")[0]
        self.assertEqual(result.status, REJECTED)
        self.assertEqual(result.reason, "unknown_address")
        self.assertEqual(self.state.to_json(), before)

    def test_address_never_issued(self):
        self.assertEqual(self.run_edit(f"<ctx><op_drop>{T.encode_address(9)}</ctx>")[0].reason,
                         "unknown_address")

    def test_address_retired_by_an_earlier_edit_of_the_same_turn(self):
        # Written differently, so the duplicate rule does not fire first.
        text = (f"<ctx><op_drop>{T.encode_address(3)}</ctx>"
                + f"<ctx><op_drop> {T.encode_address(3)} </ctx>")
        results = self.run_edit(text)
        self.assertEqual(results[0].status, APPLIED)
        self.assertEqual((results[1].status, results[1].reason), (REJECTED, "not_live"))

    def test_the_locked_block_cannot_be_touched(self):
        for text in (f"<ctx><op_drop>{T.encode_address(0)}</ctx>",
                     f"<ctx><op_rewrite>{T.encode_address(0)} shorter </ctx>"):
            with self.subTest(text=text):
                state = State()
                state.add_block("system", "prompt", locked=True)
                result = execute(state, *envelope(text))[0]
                self.assertEqual((result.status, result.reason), (REJECTED, "locked"))
                self.assertIn(0, state.blocks)

    def test_a_locked_block_among_several_drop_targets_blocks_the_whole_edit(self):
        result = self.run_edit("<ctx><op_drop>"
                               + T.encode_address(2) + T.encode_address(0) + "</ctx>")[0]
        self.assertEqual((result.status, result.reason), (REJECTED, "locked"))
        self.assertIn(2, self.state.blocks)  # the first target was not dropped

    def test_a_malformed_envelope_is_a_no_op(self):
        before = self.state.to_json()
        result = self.run_edit("<ctx><op_drop></ctx>")[0]
        self.assertEqual((result.status, result.reason), (REJECTED, "missing_address"))
        self.assertIsInstance(result.edit, Malformed)
        self.assertEqual(self.state.to_json(), before)

    def test_a_repeated_envelope_executes_once(self):
        one = f"<ctx><op_drop>{T.encode_address(2)}</ctx>"
        results = self.run_edit(one + one)
        self.assertEqual(results[0].status, APPLIED)
        self.assertEqual((results[1].status, results[1].reason), (REJECTED, "duplicate"))

    def test_the_same_envelope_twice_in_one_turn_executes_once(self):
        # "Repeated verbatim" compares the envelope text, so two identical
        # appends in one turn create one note; the second is refused.
        text = "<ctx><op_append> note </ctx><ctx><op_append> note </ctx>"
        results = self.run_edit(text)
        self.assertEqual([r.status for r in results], [APPLIED, REJECTED])
        self.assertEqual(results[1].reason, "duplicate")
        self.assertEqual(len(self.state.live_blocks()), 5)

    def test_two_drops_of_different_blocks_both_execute(self):
        text = (f"<ctx><op_drop>{T.encode_address(2)}</ctx>"
                f"<ctx><op_drop>{T.encode_address(3)}</ctx>")
        results = self.run_edit(text)
        self.assertEqual([r.status for r in results], [APPLIED, APPLIED])
        self.assertEqual(sorted(self.state.blocks), [0, 1])

    def test_an_empty_edit_list_does_nothing(self):
        self.assertEqual(execute(self.state, [], []), [])

    def test_reason_is_recorded_for_the_reviewer(self):
        result = self.run_edit("<ctx><op_drop>" + T.encode_address(9) + "</ctx>")[0]
        self.assertFalse(result.executed)
        self.assertIn("unknown", result.to_json()["reason"])


class RewriteOfADeadBlock(unittest.TestCase):
    def setUp(self):
        self.state = State()
        self.state.add_block("system", "prompt", locked=True)
        self.state.add_block("tool", "a long read", tool_name="read")
        self.state.drop(1)

    def test_the_text_is_kept_as_an_append(self):
        result = execute(self.state, *envelope(
            f"<ctx><op_rewrite>{T.encode_address(1)} the read, summarised </ctx>"))[0]
        self.assertEqual(result.status, APPLIED_AS_APPEND)
        self.assertEqual(result.reason, "not_live")
        self.assertEqual(result.new_address, 2)
        self.assertEqual(self.state.blocks[2].text, "the read, summarised")
        self.assertEqual(self.state.blocks[2].role, "note")

    def test_the_retired_address_is_not_reused(self):
        execute(self.state, *envelope(
            f"<ctx><op_rewrite>{T.encode_address(1)} summary </ctx>"))
        self.assertEqual(self.state.pool.next_address, 3)
        self.assertIn(1, self.state.pool.retired)

    def test_a_locked_block_is_refused_instead(self):
        state = State()
        state.add_block("system", "prompt", locked=True)
        result = execute(state, *envelope(
            f"<ctx><op_rewrite>{T.encode_address(0)} summary </ctx>"))[0]
        self.assertEqual((result.status, result.reason), (REJECTED, "locked"))


class TurnStep(unittest.TestCase):
    def setUp(self):
        self.state = State()
        self.state.add_block("system", "prompt", locked=True)
        self.state.add_block("user", "the task")
        self.state.add_block("tool", "a long read", tool_name="read")

    def test_the_action_keeps_the_text_and_drops_the_envelopes(self):
        output = ("Cleaning up.\n"
                  f"<ctx><op_drop>{T.encode_address(2)}</ctx>"
                  "\nNow I run the suite.")
        step = apply_output(self.state, output)
        self.assertEqual(step.action_text, "Cleaning up.\nNow I run the suite.")
        self.assertNotIn(T.CTX_OPEN, self.state.actions()[-1].text)
        self.assertNotIn(T.OP_DROP, self.state.actions()[-1].text)

    def test_the_action_is_recorded_even_without_an_edit(self):
        step = apply_output(self.state, "Nothing worth dropping yet.")
        self.assertEqual(step.action_text, "Nothing worth dropping yet.")
        self.assertEqual(len(self.state.actions()), 1)
        self.assertFalse(step.executed)

    def test_prefix_reuse_follows_whether_an_edit_executed(self):
        quiet = apply_output(self.state, "Nothing worth dropping yet.")
        self.assertTrue(quiet.prefix_reusable)
        noisy = apply_output(self.state, "<ctx><op_append> a note </ctx>")
        self.assertTrue(noisy.executed)
        self.assertFalse(noisy.prefix_reusable)

    def test_stray_tokens_are_counted_on_the_step(self):
        step = apply_output(self.state, "I will drop it later. " + T.OP_DROP + " For now, no.")
        self.assertEqual(step.stray_tokens, 1)
        # A token outside an envelope is not an edit, and it does not stay.
        self.assertNotIn(T.OP_DROP, step.action_text)
        self.assertFalse(step.executed)

    def test_a_reminder_lasts_until_an_edit_executes(self):
        self.state.add_reminder("soft", SOFT_REMINDER)
        step = apply_output(self.state, "Everything here is still in use, so I decline.")
        self.assertEqual(len(self.state.reminders()), 1)
        self.assertFalse(step.executed)
        step = apply_output(self.state, "<ctx><op_append> a note </ctx>")
        self.assertTrue(step.executed)
        self.assertEqual(self.state.reminders(), [])

    def test_step_json_shape(self):
        step = apply_output(self.state, "<ctx><op_append> a note </ctx>")
        payload = step.to_json()
        self.assertEqual(set(payload), {"results", "action", "executed", "prefix_reusable"})
        self.assertTrue(payload["executed"])
        self.assertFalse(payload["prefix_reusable"])
        self.assertEqual(payload["results"][0]["status"], APPLIED)


class ReminderPolicyTests(unittest.TestCase):
    def test_the_soft_line_is_seventy_percent(self):
        policy = ReminderPolicy(budget=1000)
        self.assertIsNone(policy.due(699, 0))
        self.assertEqual(policy.due(700, 0), "soft")

    def test_the_hard_line_is_ninety_five_percent_and_wins(self):
        policy = ReminderPolicy(budget=1000)
        self.assertEqual(policy.due(950, 0), "hard")
        self.assertEqual(policy.due(1000, 0), "hard")

    def test_the_wait_after_any_reminder(self):
        policy = ReminderPolicy(budget=1000)
        policy.issued("hard", 10)
        self.assertEqual(policy.cooldown, 4)
        self.assertIsNone(policy.due(1000, 11))
        self.assertIsNone(policy.due(1000, 13))
        self.assertEqual(policy.due(1000, 14), "hard")

    def test_a_declined_soft_reminder_waits_longer(self):
        policy = ReminderPolicy(budget=1000)
        policy.issued("soft", 0)
        policy.outcome("soft", executed=False)
        self.assertEqual(policy.declined_soft, 1)
        self.assertEqual(policy.cooldown, 8)
        self.assertIsNone(policy.due(900, 4))
        self.assertIsNone(policy.due(900, 7))
        self.assertEqual(policy.due(900, 8), "soft")

    def test_soft_reminders_stop_after_two_declines(self):
        policy = ReminderPolicy(budget=1000)
        for turn in (0, 20):
            policy.issued("soft", turn)
            policy.outcome("soft", executed=False)
        self.assertEqual(policy.declined_soft, 2)
        self.assertIsNone(policy.due(900, 40))
        # The hard reminder is not limited by the declines.
        self.assertEqual(policy.due(960, 40), "hard")

    def test_an_executed_soft_reminder_does_not_count_as_a_decline(self):
        policy = ReminderPolicy(budget=1000)
        policy.issued("soft", 0)
        policy.outcome("soft", executed=True)
        self.assertEqual(policy.declined_soft, 0)
        self.assertEqual(policy.cooldown, 4)

    def test_reminder_texts_carry_no_numbers(self):
        for level, text in REMINDER_TEXT.items():
            with self.subTest(level=level):
                self.assertFalse(any(ch.isdigit() for ch in text))
                self.assertTrue(text.startswith("[context-monitor]"))

    def test_outcome_of_a_hard_reminder_does_not_add_a_decline(self):
        policy = ReminderPolicy(budget=1000)
        policy.issued("hard", 0)
        policy.outcome("hard", executed=False)
        self.assertEqual(policy.declined_soft, 0)
        self.assertEqual(policy.cooldown, 4)


class RuntimeSession(unittest.TestCase):
    def build(self, budget=None) -> Runtime:
        rt = Runtime(budget=budget)
        rt.add_block("system", "You are a coding agent.", locked=True)
        rt.add_block("user", "Fix parse_duration.")
        rt.add_block("tool", "src/timeparse/core.py:19: total = ...", tool_name="grep")
        return rt

    def test_prompt_renders_the_state_and_opens_the_assistant_turn(self):
        rt = self.build()
        prompt = rt.prompt()
        self.assertTrue(prompt.startswith(T.encode_address(0)
                                          + T.LOCKED + "<|system|>"))
        self.assertTrue(prompt.endswith("<|assistant|>"))
        self.assertIn(T.encode_address(2), prompt)
        self.assertIn("grep\nsrc/timeparse/core.py:19", prompt)

    def test_no_policy_means_no_reminder(self):
        rt = self.build()
        rt.prompt()
        self.assertEqual(rt.state.reminders(), [])

    def build_tight(self, budget: int, repeats: int = 3) -> Runtime:
        """A session whose context lands in a chosen band of the budget."""
        rt = Runtime(budget=budget)
        rt.add_block("system", "You are a coding agent.", locked=True)
        rt.add_block("user", " ".join(["Fix parse_duration."] * repeats))
        return rt

    def test_a_soft_reminder_enters_the_prompt_once_crossed(self):
        # 70% <= context / budget < 95%: 30 tokens of a 40-token budget
        # lands in the soft band, below the hard line at 38.
        rt = self.build_tight(budget=40, repeats=3)
        self.assertTrue(0.70 <= rt.context_tokens() / 40 < 0.95)
        prompt = rt.prompt()
        self.assertIn(SOFT_REMINDER, prompt)
        self.assertNotIn(HARD_REMINDER, prompt)
        self.assertEqual([r.level for r in rt.state.reminders()], ["soft"])

    def test_a_soft_reminder_is_issued_once_per_due_point(self):
        rt = self.build_tight(budget=40, repeats=3)
        rt.prompt()
        first = rt.context_tokens()
        rt.prompt()  # the same turn, rendered again
        self.assertEqual(len(rt.state.reminders()), 1)
        self.assertEqual(rt.context_tokens(), first)

    def test_a_hard_reminder_at_the_limit(self):
        rt = self.build_tight(budget=30, repeats=3)
        self.assertGreaterEqual(rt.context_tokens(), 0.95 * 30)
        prompt = rt.prompt()
        self.assertIn(HARD_REMINDER, prompt)
        self.assertNotIn(SOFT_REMINDER, prompt)

    def test_a_declined_soft_reminder_is_recorded(self):
        rt = self.build_tight(budget=40, repeats=3)
        rt.prompt()
        step = rt.step("Everything here is still in use, so I leave it as it is.")
        self.assertFalse(step.executed)
        self.assertEqual(rt.policy.declined_soft, 1)
        self.assertEqual(rt.policy.cooldown, 8)

    def test_an_executing_turn_clears_the_reminder(self):
        rt = self.build_tight(budget=40, repeats=3)
        rt.prompt()
        step = rt.step("<ctx><op_append> the grep hit at core.py:19 is the place to look </ctx>")
        self.assertTrue(step.executed)
        self.assertEqual(rt.state.reminders(), [])

    def test_step_advances_the_turn_and_logs(self):
        rt = self.build()
        rt.prompt()
        rt.step("Reading the file.")
        self.assertEqual(rt.turn, 1)
        self.assertEqual(len(rt.log), 1)
        rt.step("Reading it again.")
        self.assertEqual(rt.turn, 2)
        self.assertEqual(len(rt.log), 2)

    def test_the_full_loop_of_the_docstring(self):
        rt = self.build(budget=4000)
        prompts = []
        for output in ("Reading the parser.\n<ctx><op_append> the bug is at line 19 </ctx>",
                       "Running the suite.",
                       "The fix is in, so the receipt can go.\n"
                       "<ctx><op_drop>" + T.encode_address(2) + "</ctx>"):
            prompts.append(rt.prompt())
            step = rt.step(output)
            rt.add_block("tool", "ok", tool_name="bash")
            self.assertIsInstance(step.executed, bool)
        self.assertEqual(rt.turn, 3)
        # The appended note entered with address 3 and is still live.
        self.assertIn(3, rt.state.blocks)
        self.assertNotIn(2, rt.state.blocks)
        self.assertEqual(len(prompts), 3)
        self.assertTrue(all(isinstance(p, str) for p in prompts))

    def test_context_tokens_counts_the_reminder_too(self):
        rt = Runtime(budget=400)
        rt.add_block("system", "You are a coding agent.", locked=True)
        rt.add_block("user", " ".join(["Fix parse_duration."] * 100))
        before = rt.context_tokens()
        self.assertTrue(0.70 <= before / 400 < 0.95)
        rt.prompt()
        self.assertIn(SOFT_REMINDER, render_text(rt.state))
        self.assertGreater(rt.context_tokens(), before)

    def test_render_messages_mirrors_the_rendering(self):
        rt = self.build()
        messages = render_messages(rt.state)
        self.assertEqual([m["role"] for m in messages], ["system", "user", "tool"])
        self.assertTrue(messages[0]["content"].startswith(T.encode_address(0) + T.LOCKED))
        self.assertEqual(messages[2]["name"], "grep")
        self.assertNotIn("name", messages[0])

    def test_a_custom_format_replaces_the_role_tags(self):
        fmt = ChatFormat(role_tags={"system": "<s>", "user": "<u>", "tool": "<t>", "note": "<n>"},
                         assistant_open="<a>", assistant_close="</a>", separator="")
        rt = Runtime(fmt=fmt)
        rt.add_block("system", "prompt", locked=True)
        rt.add_block("user", "task")
        text = render_text(rt.state, fmt)
        self.assertEqual(text, T.encode_address(0) + T.LOCKED + "<s>prompt"
                         + T.encode_address(1) + "<u>task")

    def test_approx_tokens_counts_each_token_string_as_one(self):
        self.assertEqual(approx_tokens(T.CTX_OPEN + T.OP_DROP + T.encode_address(2)), 4)
        self.assertGreaterEqual(approx_tokens("a short sentence"), 3)
        self.assertEqual(approx_tokens(""), 0)


if __name__ == "__main__":
    unittest.main()
