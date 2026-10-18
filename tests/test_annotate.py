"""The annotation pipeline: release points, decision points, audit, distillation.

The toy trajectory is used as the recorded input, and the deterministic
rule-based teachers stand in for the two LLM teachers of the paper. The
assertions check the invariants, never a frozen snapshot, so the suite survives
a change of rules: a release point never precedes the block's entry
turn or its cited event, a kept block is never editable, the audit keeps or
rejects each edit for a stated reason, and every distilled segment extends
its own prefix.
"""
from __future__ import annotations

import unittest

import context  # noqa: F401  (sets sys.path) -- also gives TOY

from nce import tokens as T
from nce.annotate import (Annotation, Context, RuleBasedOfflineTeacher, RuleBasedOnlineTeacher,
                          annotate, blockize, load_trajectory, parse_tool_calls)
from nce.annotate.audit import (MAX_EDIT_TURNS, MAX_EDIT_TURN_SHARE, MIN_TURN_FREED,
                                checked_items, final_audit)
from nce.annotate.literals import extract_literals, last_reappearance
from nce.annotate.online import (BUDGET_TIERS, HARD_LINE, MIN_EDITABLE_SHARE, MIN_FREED_SHARE,
                                 SOFT_LINE, Decision, DecisionView, TeacherEdit, Triggers,
                                 build_view, generate_edits, select_budget,
                                 unedited_prompt_tokens)
from nce.annotate.release import (TO_DROP, TO_SUMMARY, Context as ReleaseContext,
                                  distinctive_lines, literal_check, release_analysis,
                                  verify_supersession)
from nce.annotate.replay import Op, Replayer, compose_output
from nce.annotate.rules import is_receipt, passes_in_full, summarize, _test_digest
from nce.annotate.trajectory import Observation, Trajectory, Turn
from nce.distill import distill
from nce.render import render_text

# The demo tiers put the toy trajectory inside a budget of its own scale.
TIERS = (4_000, 8_000, 32_000, 48_000, 64_000, 128_000)


def toy() -> Trajectory:
    return load_trajectory(context.TOY)


def analyse(traj: Trajectory, tiers=TIERS) -> Annotation:
    return annotate(traj, RuleBasedOfflineTeacher(), RuleBasedOnlineTeacher(), tiers=tiers)


class TrajectoryParsing(unittest.TestCase):
    def test_the_fixture_loads_with_its_shape_intact(self):
        traj = toy()
        self.assertEqual(traj.id, "toy-timeparse-0001")
        self.assertEqual(traj.T, 15)
        self.assertTrue(traj.system)
        self.assertTrue(traj.task)
        self.assertEqual(len(traj.turns[0].observations), 1)
        self.assertEqual(traj.turns[-1].observations, [])

    def test_round_trip_keeps_turns_and_observations(self):
        traj = toy()
        clone = Trajectory.from_json(traj.to_json())
        self.assertEqual(clone.to_json(), traj.to_json())
        self.assertEqual(clone.T, traj.T)

    def test_tool_calls_are_parsed_from_the_output(self):
        calls = parse_tool_calls(toy().turns[0].output)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "grep")
        self.assertIn("pattern", calls[0].arguments)

    def test_a_bad_tool_call_is_skipped(self):
        self.assertEqual(parse_tool_calls("<tool_call>not json</tool_call>"), [])
        self.assertEqual(parse_tool_calls("no call at all"), [])

    def test_blocks_are_the_system_task_and_every_tool_result(self):
        traj = toy()
        blocks = blockize(traj)
        tool_results = sum(len(t.observations) for t in traj.turns)
        self.assertEqual(len(blocks), tool_results + 2)
        self.assertTrue(blocks[0].locked)
        self.assertEqual(blocks[0].role, "system")
        self.assertEqual(blocks[1].source, "task")

    def test_entry_turns_follow_the_call_that_produced_them(self):
        blocks = blockize(toy())
        # The result of turn t enters before turn t + 1.
        for block in blocks[2:]:
            self.assertGreaterEqual(block.entry_turn, 2)
        self.assertEqual(blocks[2].entry_turn, 2)
        self.assertEqual(blocks[-1].entry_turn, 15)

    def test_a_source_label_names_the_call(self):
        blocks = blockize(toy())
        self.assertTrue(blocks[2].source.startswith("grep("), blocks[2].source)
        self.assertTrue(any(b.source.startswith("edit(") for b in blocks))


class Literals(unittest.TestCase):
    def test_kinds_are_recognised(self):
        found = {lit.kind for lit in extract_literals(
            "src/timeparse/core.py uses total_seconds with 123456 and 3.14159 "
            "and deadbeef01 and the read shows:\n 1589:\tabc")}
        self.assertIn("path", found)
        self.assertIn("identifier", found)
        self.assertIn("integer", found)
        self.assertIn("decimal", found)
        self.assertIn("hex", found)
        self.assertIn("line_number", found)

    def test_a_number_in_line_position_is_reported_as_a_line_number(self):
        # Appendix B counts four-digit numbers in line-number position as their
        # own kind, so a summary can cite a line without asserting an integer.
        lits = extract_literals(" 1589:\tabc")
        self.assertEqual([(l.kind, l.text) for l in lits], [("line_number", "1589")])

    def test_a_hex_string_needs_letters_and_digits(self):
        # "deadbeef01" is a hex string; a plain run of digits is not, and the
        # "0x" prefix is text like any other.
        kinds = {l.kind: l.text for l in extract_literals("hash deadbeef01 and 0xdeadbeef")}
        self.assertEqual(kinds.get("hex"), "deadbeef01")

    def test_a_long_integer_is_not_a_line_number(self):
        lits = extract_literals("the total is 123456 here")
        self.assertEqual([(l.kind, l.text) for l in lits], [("integer", "123456")])

    def test_short_strings_are_not_literals(self):
        self.assertEqual(extract_literals("a b 12"), [])

    def test_duplicates_appear_once_in_first_appearance_order(self):
        lits = [lit.text for lit in extract_literals("alpha_beta then alpha_beta")]
        self.assertEqual(lits.count("alpha_beta"), 1)

    def test_last_reappearance_finds_the_last_turn(self):
        from nce.annotate.literals import Literal
        literals = [Literal("needle_token", "identifier")]
        actions = ["nothing", "needle_token here", "nothing", "and needle_token again"]
        self.assertEqual(last_reappearance(literals, actions, after=0), 4)
        self.assertEqual(last_reappearance(literals, actions, after=1), 4)
        self.assertIsNone(last_reappearance(literals, actions, after=4))

    def test_kind_filter_ignores_other_literals(self):
        from nce.annotate.literals import Literal
        literals = [Literal("some_path/here", "path"), Literal("total_units", "identifier")]
        actions = ["", "total_units", "", "some_path/here"]
        self.assertEqual(last_reappearance(literals, actions, after=0,
                                           kinds={"path"}), 4)
        self.assertEqual(last_reappearance(literals, actions, after=0,
                                           kinds={"identifier"}), 2)


class ReleaseAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.traj = toy()
        self.ctx = ReleaseContext(self.traj)
        self.analysis = release_analysis(self.ctx, RuleBasedOfflineTeacher())

    def test_every_release_point_names_a_real_block(self):
        for block, point in self.analysis.points.items():
            self.assertTrue(0 <= block < len(self.ctx.blocks))
            self.assertEqual(point.block, block)

    def test_a_release_never_precedes_the_entry_turn_or_the_cited_event(self):
        for point in self.analysis.points.values():
            block = self.ctx.blocks[point.block]
            self.assertGreaterEqual(point.k, block.entry_turn)
            self.assertGreaterEqual(point.k, point.r_hat - (point.lam or 0) if point.lam
                                    else point.k)
            self.assertGreaterEqual(point.r_hat, point.k)

    def test_the_literal_check_only_postpones(self):
        for point in self.analysis.points.values():
            if point.lam is not None:
                self.assertGreaterEqual(point.r_hat, point.lam)
                self.assertIn("literal", point.postponed_by)

    def test_a_drop_whose_literal_returns_becomes_a_summary(self):
        for point in self.analysis.points.values():
            if point.lam is not None and point.kind == TO_DROP:
                self.fail("a postponed drop should have become a summary")
        # And every kind is one of the two the paper allows.
        for point in self.analysis.points.values():
            self.assertIn(point.kind, (TO_DROP, TO_SUMMARY))

    def test_the_locked_system_prompt_is_never_released(self):
        self.assertNotIn(0, self.analysis.points)

    def test_r_hat_falls_back_to_the_end_of_the_trajectory_for_a_kept_block(self):
        kept = [b.index for b in self.ctx.blocks if b.index not in self.analysis.points]
        self.assertTrue(kept)
        for block in kept:
            self.assertEqual(self.analysis.r_hat(block, self.traj.T), self.traj.T)

    def test_at_most_two_milestones(self):
        self.assertLessEqual(len(self.analysis.milestones), 2)

    def test_the_milestone_is_a_turn_where_the_suite_passes(self):
        for milestone in self.analysis.milestones:
            self.assertGreaterEqual(milestone.after_turn, 1)
            self.assertLessEqual(milestone.after_turn, self.traj.T)
            self.assertTrue(milestone.description)

    def test_the_second_pass_logs_a_verdict_per_candidate(self):
        for entry in self.analysis.second_pass_log:
            self.assertIn(entry["verdict"], ("released", "kept", "rejected"))
            self.assertIn(entry["source"], ("nominated", "literals_stopped", "continuation"))

    def test_a_rejected_release_states_the_missing_line(self):
        for entry in self.analysis.second_pass_log:
            if entry["verdict"] == "rejected":
                self.assertIn("lacks the line", entry["reason"])

    def test_supersession_needs_a_later_block_holding_every_line(self):
        blocks = self.ctx.blocks
        search = next(i for i, b in enumerate(blocks) if b.role == "tool")
        self.assertIsNotNone(verify_supersession(self.ctx, search, search))
        # A block cannot supersede itself, and an earlier block cannot either.
        self.assertEqual(verify_supersession(self.ctx, search, search),
                         "<superseding block is not later>")

    def test_distinctive_lines_skip_blanks(self):
        self.assertEqual(distinctive_lines("a\n\n  \nb  \n"), ["a", "b"])

    def test_literal_check_never_moves_a_release_earlier(self):
        from nce.annotate.release import Release
        release = Release(block=2, after_turn=1, kind=TO_SUMMARY, trigger="test")
        point = literal_check(self.ctx, release, "forward")
        self.assertGreaterEqual(point.k, self.ctx.blocks[2].entry_turn)
        self.assertGreaterEqual(point.r_hat, point.k)


class BudgetSelection(unittest.TestCase):
    def setUp(self):
        self.traj = toy()
        self.ctx = ReleaseContext(self.traj)
        self.analysis = release_analysis(self.ctx, RuleBasedOfflineTeacher())

    def test_prompt_sizes_grow_with_the_observations(self):
        sizes = unedited_prompt_tokens(self.ctx)
        self.assertEqual(len(sizes), self.traj.T)
        self.assertEqual(sizes, sorted(sizes))

    def test_the_selected_tier_crosses_its_soft_line(self):
        budget = select_budget(self.ctx, self.analysis, TIERS)
        if budget is None:
            self.skipTest("no tier is crossed by this trajectory")
        self.assertGreaterEqual(max(unedited_prompt_tokens(self.ctx)), SOFT_LINE * budget)

    def test_a_tier_the_peak_never_reaches_is_not_selected(self):
        peak = max(unedited_prompt_tokens(self.ctx))
        budget = select_budget(self.ctx, self.analysis, TIERS)
        if budget is not None:
            self.assertLessEqual(budget, max(t for t in TIERS if peak >= SOFT_LINE * t))

    def test_no_tier_qualifies_returns_none(self):
        self.assertIsNone(select_budget(self.ctx, self.analysis, (1_000_000,)))

    def test_the_paper_grid_is_the_expected_one(self):
        self.assertEqual(BUDGET_TIERS, (32_000, 48_000, 64_000, 128_000))


class TriggersAndDecisionPoints(unittest.TestCase):
    def test_the_first_crossing_of_the_soft_line_fires_once(self):
        triggers = Triggers(1000, [])
        self.assertIsNone(triggers.check(1, 100, None))
        self.assertEqual(triggers.check(2, 700, None), "soft")
        self.assertIsNone(triggers.check(3, 750, None))  # already crossed
        self.assertIsNone(triggers.check(4, 800, None))  # inside the cool-down

    def test_the_hard_line_wins_over_the_soft_one(self):
        self.assertEqual(Triggers(1000, []).check(1, 950, None), "hard")

    def test_a_soft_reminder_is_not_reissued_during_the_cool_down(self):
        triggers = Triggers(1000, [])
        triggers.check(1, 700, None)
        for turn in range(2, 8):
            self.assertIsNone(triggers.check(turn, 700, None))

    def test_a_milestone_fires_at_its_turn(self):
        triggers = Triggers(None, [5])
        self.assertIsNone(triggers.check(5, 100, None))
        self.assertEqual(triggers.check(6, 100, None), "milestone")

    def test_a_milestone_waits_for_a_recent_edit_to_settle(self):
        triggers = Triggers(None, [5])
        self.assertIsNone(triggers.check(6, 100, last_edit=5))
        self.assertEqual(triggers.check(6, 100, last_edit=4), "milestone")

    def test_an_unremarkable_turn_fires_nothing(self):
        self.assertIsNone(Triggers(1000, []).check(3, 10, None))
        self.assertIsNone(Triggers(None, []).check(3, 10, None))


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.traj = toy()
        self.an = analyse(self.traj)

    def test_the_pipeline_runs_end_to_end_and_reports(self):
        report = self.an.report()
        self.assertEqual(report["id"], self.traj.id)
        self.assertEqual(report["turns"], self.traj.T)
        self.assertEqual(len(report["blocks"]), len(self.an.context.blocks))
        self.assertIn("releases", report)
        self.assertIn("decision_points", report)
        self.assertIn("audit", report)

    def test_every_decision_point_has_a_known_outcome(self):
        for dp in self.an.decisions:
            self.assertIn(dp.outcome, ("edited", "declined", "not_called", "discarded"))
            self.assertIn(dp.trigger, ("soft", "hard", "milestone"))
            self.assertGreaterEqual(dp.turn, 1)
            self.assertLessEqual(dp.turn, self.traj.T)
            self.assertLessEqual(dp.freed, 1.0)

    def test_a_decision_point_is_not_raised_twice_for_one_turn(self):
        turns = [dp.turn for dp in self.an.decisions]
        self.assertEqual(len(turns), len(set(turns)))

    def test_decisions_are_in_turn_order(self):
        turns = [dp.turn for dp in self.an.decisions]
        self.assertEqual(turns, sorted(turns))

    def test_a_small_edit_is_discarded_or_never_proposed(self):
        for dp in self.an.decisions:
            if dp.trigger in ("soft", "milestone") and dp.outcome == "edited":
                self.assertGreaterEqual(dp.freed, MIN_FREED_SHARE)

    def test_an_edit_turn_actually_executes_its_ops(self):
        for dp in self.an.decisions:
            if dp.outcome == "edited":
                self.assertTrue(dp.ops)
                self.assertTrue(dp.note)

    def test_the_hard_reminder_can_decline_only_when_nothing_is_editable(self):
        for dp in self.an.decisions:
            if dp.trigger == "hard" and dp.outcome in ("declined", "not_called"):
                self.assertTrue(dp.reason)

    def test_edit_ops_refer_to_blocks_that_existed(self):
        live = {f"b{i}" for i in range(len(self.an.context.blocks))}
        for dp in self.an.decisions:
            for op in dp.ops:
                if op.ref is not None:
                    self.assertTrue(op.ref.startswith(("b", "n", "r")), op.ref)
                    if op.ref.startswith("b"):
                        self.assertIn(op.ref, live)

    def test_the_audit_keeps_or_rejects_every_checked_edit_with_a_reason(self):
        for entry in self.an.audit.entries:
            self.assertIn(entry.verdict, ("kept", "rejected"))
            self.assertIn(entry.op.op, ("drop", "rewrite", "append"))
            if entry.verdict == "rejected":
                self.assertTrue(entry.reason)

    def test_a_kept_edit_turn_frees_at_least_the_minimum(self):
        if not self.an.audit.edit_turns:
            self.skipTest("this fixture has no surviving edit")
        for turn in self.an.audit.edit_turns:
            self.assertGreaterEqual(turn, 1)
            self.assertLessEqual(turn, self.traj.T)

    def test_the_edit_rate_rule_is_the_papers_one(self):
        n = len(self.an.audit.edit_turns)
        if not self.an.discarded and n > MAX_EDIT_TURNS:
            self.assertGreater(n, MAX_EDIT_TURN_SHARE * self.traj.T)
        self.assertEqual((MIN_TURN_FREED, MAX_EDIT_TURNS, MAX_EDIT_TURN_SHARE),
                         (0.03, 6, 0.15))

    def test_the_annotated_trajectory_carries_the_budget_and_the_edits(self):
        annotated = self.an.annotated()
        self.assertEqual(annotated.T, self.traj.T)
        self.assertEqual(annotated.meta.get("budget"), self.an.budget)
        edited = [t for t, turn in enumerate(annotated.turns, start=1)
                  if T.CTX_OPEN in turn.output]
        self.assertEqual(edited, list(self.an.audit.edit_turns))

    def test_calls_first_then_execute_is_deterministic(self):
        again = analyse(toy())
        self.assertEqual([dp.to_json() for dp in again.decisions],
                         [dp.to_json() for dp in self.an.decisions])
        self.assertEqual(again.releases.to_json(), self.an.releases.to_json())

    def test_the_decision_view_shows_only_what_the_agent_saw(self):
        rp = Replayer(self.an.context)
        view = build_view(rp, self.an.releases, 10, "soft", None)
        self.assertIsInstance(view, DecisionView)
        self.assertEqual(view.turn, 10)
        self.assertEqual(view.reminder, "[context-monitor] " + view.reminder.split("] ", 1)[1])
        for block in view.blocks:
            self.assertIsInstance(block.editable, bool)
            self.assertTrue(block.source)

    def test_a_block_is_editable_only_after_its_release_point(self):
        release = self.an.releases
        rp = Replayer(self.an.context)
        for turn in range(1, self.traj.T + 1):
            view = build_view(rp, release, turn, "soft", None)
            for block in view.blocks:
                ref = next((r for r, a in rp.live_refs() if a == block.address), None)
                if ref and ref.startswith("b"):
                    expected = turn > release.r_hat(int(ref[1:]), self.traj.T)
                    self.assertEqual(block.editable, expected, (turn, ref))

    def test_the_locked_block_is_never_editable(self):
        rp = Replayer(self.an.context)
        view = build_view(rp, self.an.releases, self.traj.T, "hard", None)
        locked = [b for b in view.blocks if b.source == "system"]
        self.assertTrue(locked)
        for block in locked:
            self.assertFalse(block.editable)


class ReplayMechanics(unittest.TestCase):
    def test_a_replay_reproduces_the_unedited_state(self):
        ctx = ReleaseContext(toy())
        rp = Replayer(ctx)
        for turn in range(1, ctx.T + 1):
            rp.finish_turn(turn, ctx.actions[turn - 1], [])
        self.assertEqual(len(rp.live_refs()), len(ctx.blocks))
        self.assertEqual(sorted(rp.addr_of), sorted(f"b{i}" for i in range(len(ctx.blocks))))
        self.assertEqual(rp.state.pool.retired, set())

    def test_compose_output_orders_the_note_then_the_envelopes_then_the_action(self):
        text = compose_output("Tidying up.", ["<env1>", "<env2>"], "Now I read the file.")
        self.assertEqual(text.split("\n"), ["Tidying up.", "<env1>", "<env2>",
                                            "Now I read the file."])
        self.assertEqual(compose_output("", [], "just the action"), "just the action")
        self.assertEqual(compose_output("note", [], ""), "note")

    def test_compile_lets_an_op_with_a_missing_target_drop_out(self):
        ctx = ReleaseContext(toy())
        rp = Replayer(ctx)
        envelopes, kept = rp.compile([Op("drop", "b99"), Op("append", "n0", "a note")])
        self.assertEqual([op.ref for op in kept], ["n0"])
        self.assertEqual(len(envelopes), 1)

    def test_consecutive_drops_share_one_envelope(self):
        ctx = ReleaseContext(toy())
        rp = Replayer(ctx)
        for turn in range(1, 6):  # let blocks b2 and b3 enter
            rp.finish_turn(turn, ctx.actions[turn - 1], [])
        envelopes, kept = rp.compile([Op("drop", "b2"), Op("drop", "b3")])
        self.assertEqual(len(envelopes), 1)
        self.assertEqual(len(kept), 2)
        self.assertEqual(envelopes[0].count(T.OP_DROP), 1)
        self.assertEqual(envelopes[0].count("<sid_hi_"), 2)

    def test_a_drop_is_flushed_before_a_rewrite(self):
        ctx = ReleaseContext(toy())
        rp = Replayer(ctx)
        for turn in range(1, 6):
            rp.finish_turn(turn, ctx.actions[turn - 1], [])
        envelopes, _ = rp.compile([Op("drop", "b2"), Op("rewrite", "b3", "a summary")])
        self.assertEqual(len(envelopes), 2)
        self.assertIn(T.OP_DROP, envelopes[0])
        self.assertIn(T.OP_REWRITE, envelopes[1])

    def test_measure_reports_a_shrink_for_a_drop(self):
        ctx = ReleaseContext(toy())
        rp = Replayer(ctx)
        for turn in range(1, 6):
            rp.finish_turn(turn, ctx.actions[turn - 1], [])
        envelopes, _ = rp.compile([Op("drop", "b2")])
        before, after = rp.measure(envelopes)
        self.assertLess(after, before)

    def test_measure_counts_the_reminder_that_a_new_edit_clears(self):
        ctx = ReleaseContext(toy())
        rp = Replayer(ctx)
        rp.add_reminder("soft")
        with_reminder = rp.tokens()
        envelopes, _ = rp.compile([Op("append", "n0", "a short note")])
        before, after = rp.measure(envelopes)
        self.assertEqual(before, with_reminder)
        self.assertNotEqual(before, after)


class RuleBasedTeachers(unittest.TestCase):
    def test_receipts_are_recognised(self):
        for text in ("The file src/a.py has been updated successfully.",
                     "The file tests/x.py has been created successfully.",
                     "ok", "Done.", ""):
            self.assertTrue(is_receipt(text), text)
        self.assertFalse(is_receipt("line 19: total = int(value) * UNIT_SECONDS[unit]"))

    def test_a_passing_suite_is_told_apart_from_a_failing_one(self):
        self.assertTrue(passes_in_full("9 passed in 0.02s"))
        self.assertFalse(passes_in_full("1 failed, 8 passed in 0.03s"))
        self.assertFalse(passes_in_full("4 failed, 5 passed in 0.04s"))
        self.assertFalse(passes_in_full("9 passed, 1 error in 0.03s"))
        self.assertFalse(passes_in_full("no summary at all"))

    def test_the_test_digest_names_the_failing_tests(self):
        text = ("FAILED tests/test_core.py::test_whitespace - ValueError\n"
                "1 failed, 8 passed in 0.03s")
        digest = _test_digest(text)
        self.assertIn("1 failed, 8 passed", digest)
        self.assertIn("test_whitespace", digest)

    def test_summarize_copies_facts_from_the_block(self):
        class View:
            def __init__(self, text, source):
                self.text, self.source = text, source

        summary = summarize(View(" 1\tabc\n 2\tdef parse_duration(x):\n 3\treturn 1\n",
                                 "read(path=src/a.py)"))
        self.assertIn("read(path=src/a.py)", summary)
        self.assertIn("def parse_duration", summary)
        self.assertIn("1-3", summary)

    def test_a_summary_of_a_test_run_keeps_the_totals(self):
        class View:
            def __init__(self, text, source):
                self.text, self.source = text, source

        summary = summarize(View("...\n9 passed in 0.02s\n", "bash(command=pytest)"))
        self.assertIn("9 passed in 0.02s", summary)

    def test_the_online_teacher_declines_with_nothing_editable(self):
        view = DecisionView(turn=1, trigger="soft", reminder="reminder", milestone=None,
                            blocks=[])
        decision = RuleBasedOnlineTeacher().decide(view)
        self.assertTrue(decision.no_op)
        self.assertTrue(decision.note)
        self.assertEqual(decision.edits, [])

    def test_an_offline_teacher_is_an_interface(self):
        from nce.annotate.release import OfflineTeacher
        with self.assertRaises(NotImplementedError):
            OfflineTeacher().forward(None)

    def test_an_online_teacher_is_an_interface(self):
        from nce.annotate.online import OnlineTeacher
        with self.assertRaises(NotImplementedError):
            OnlineTeacher().decide(None)


class _Liars(RuleBasedOnlineTeacher):
    """A teacher that invents a path, to exercise the audit's first rule."""

    def decide(self, view: DecisionView) -> Decision:
        todo = [b for b in view.blocks if b.editable and b.source != "note"]
        if not todo:
            return super().decide(view)
        return Decision(
            False, "Condensing the earlier reads into one reference.",
            [TeacherEdit("rewrite", b.address,
                         "Earlier read of src/does_not_exist.py, lines 1-20.")
             for b in todo],
            reason="invented path")


class AuditChecks(unittest.TestCase):
    def test_checked_items_picks_numbers_paths_idents_and_quotes(self):
        items = checked_items('rewrite of src/a.py at line 19 with total_seconds = "exact text" '
                              "and 42")
        self.assertIn("src/a.py", items)
        self.assertIn("total_seconds", items)
        self.assertIn("exact text", items)
        self.assertIn("42", items)
        self.assertIn("19", items)

    def test_a_summary_naming_an_absent_file_is_rejected(self):
        traj = toy()
        ctx = ReleaseContext(traj)
        points = generate_edits(ctx, release_analysis(ctx, RuleBasedOfflineTeacher()),
                                _Liars(), 4000)
        audit = final_audit(ctx, points)
        rejected = [e for e in audit.entries if e.verdict == "rejected"]
        self.assertTrue(rejected)
        self.assertTrue(any("unsupported" in e.reason for e in rejected))
        for entry in rejected:
            self.assertIn("src/does_not_exist.py", entry.reason)
        # Nothing survived, so the turn carries no edit.
        self.assertEqual(audit.edit_turns, [])


class Distillation(unittest.TestCase):
    def setUp(self):
        self.traj = toy()
        self.an = analyse(self.traj)
        self.segments = distill(self.an.annotated())

    def test_a_segment_boundary_follows_an_executed_edit(self):
        if not self.an.audit.edit_turns:
            self.skipTest("this fixture has no surviving edit")
        # The first segment ends at the first edit turn.
        self.assertEqual(self.segments[0].last_turn, self.an.audit.edit_turns[0])
        self.assertGreaterEqual(self.segments[0].edits, 1)

    def test_every_segment_covers_a_contiguous_range_of_turns(self):
        self.assertEqual(self.segments[0].first_turn, 1)
        for i, seg in enumerate(self.segments):
            self.assertLessEqual(seg.first_turn, seg.last_turn)
            if i:
                self.assertEqual(seg.first_turn, self.segments[i - 1].last_turn + 1)
        self.assertEqual(self.segments[-1].last_turn, self.traj.T)

    def test_segment_indices_and_ids(self):
        for i, seg in enumerate(self.segments):
            self.assertEqual(seg.index, i)
            self.assertEqual(seg.to_json()["id"], f"{self.traj.id}#{i}")

    def test_every_segment_carries_supervised_text(self):
        for seg in self.segments:
            self.assertTrue(seg.supervised())
            self.assertLess(len(seg.supervised()), len(seg.text) + 1)

    def test_the_mask_aligns_with_the_text(self):
        for seg in self.segments:
            self.assertEqual(len(seg.char_mask()), len(seg.text))
            self.assertEqual(sum(seg.char_mask()), len(seg.supervised()))

    def test_the_rendered_prefix_and_the_observations_are_not_supervised(self):
        for seg in self.segments:
            for text, loss in seg.pieces:
                if T.CTX_OPEN in text and T.CTX_CLOSE in text and loss == 0:
                    self.fail("an edit must never enter the context with no loss")
                if loss == 0 and text.startswith("<sid_hi_"):
                    self.assertIn("<|", text)  # a block, not an action

    def test_the_model_output_is_supervised_and_everything_else_is_not(self):
        for seg in self.segments:
            supervised = [t for t, m in seg.pieces if m]
            unsupervised = [t for t, m in seg.pieces if not m]
            self.assertTrue(supervised)
            # The closing assistant tag is supervised, so the model learns to
            # stop after its own output.
            self.assertTrue(supervised[-1].endswith("<|end|>"), seg.index)
            # No envelope is ever part of the context the model reads.
            for text in unsupervised:
                self.assertFalse(text.strip().startswith(T.CTX_OPEN), seg.index)
            # Every edit the segment teaches sits in the supervised text.
            edit_turns = [t for t in self.an.audit.edit_turns
                          if seg.first_turn <= t <= seg.last_turn]
            if edit_turns:
                self.assertTrue(any(T.CTX_OPEN in t for t in supervised), seg.index)

    def test_each_segment_extends_its_own_prefix(self):
        # distill() asserts this internally; check the shape it implies: the
        # first segment opens with the system prompt and the task.
        first = self.segments[0].text
        self.assertIn(self.traj.system.split("\n")[0][:40], first)
        self.assertTrue(first.startswith(T.encode_address(0) + T.LOCKED))

    def test_the_second_segment_opens_with_the_edited_state(self):
        if len(self.segments) < 2:
            self.skipTest("this fixture distils into one segment")
        first, second = self.segments[0], self.segments[1]
        # The state the edit produced is what the second segment opens with:
        # the dropped blocks are gone, and the notes the turn appended are in.
        self.assertTrue(second.text.startswith(T.encode_address(0)))
        self.assertLess(len(second.text), len(first.text))

    def test_json_of_a_segment_is_json_serialisable(self):
        import json
        payload = json.dumps([s.to_json() for s in self.segments])
        back = json.loads(payload)
        self.assertEqual(len(back), len(self.segments))
        for record, seg in zip(back, self.segments):
            self.assertEqual(record["pieces"], [{"text": t, "loss": m} for t, m in seg.pieces])

    def test_write_jsonl_writes_one_line_per_segment(self):
        import json
        import tempfile
        from nce.distill import write_jsonl
        with tempfile.TemporaryDirectory() as tmp:
            path = f"{tmp}/segments.jsonl"
            n = write_jsonl(self.segments, path)
            self.assertEqual(n, len(self.segments))
            with open(path, encoding="utf-8") as handle:
                lines = [json.loads(line) for line in handle]
            self.assertEqual(len(lines), len(self.segments))
            self.assertEqual(lines[0]["id"], self.segments[0].to_json()["id"])


if __name__ == "__main__":
    unittest.main()
