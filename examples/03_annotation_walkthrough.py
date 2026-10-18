#!/usr/bin/env python3
"""Turn a recorded trajectory into the edit script a teacher produces.

This is the labelling demo. A recorded trajectory contains no edits. The
offline teacher reads all of it and decides, from hindsight, when each block
may be edited; the online teacher then plays the agent at each decision
point, seeing only what the agent saw, and writes the edits; a final audit
drops edits that fail a mechanical check. What comes out is the annotated
trajectory the paper trains on.

The trajectory in examples/data/toy_trajectory.json is a hand-written
coding-agent session: an agent fixes a duration parser in a small Python
package. Standard library only; run from the repository root:

    python3 examples/03_annotation_walkthrough.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nce import tokens as T  # noqa: E402
from nce.annotate import (Annotation, Context, RuleBasedOfflineTeacher,  # noqa: E402
                          RuleBasedOnlineTeacher, annotate, load_trajectory)
from nce.annotate.online import select_budget, unedited_prompt_tokens  # noqa: E402
from nce.annotate.release import TO_DROP, TO_SUMMARY, ReleasePoint  # noqa: E402
from nce.render import TraceWriter, wants_color, strip_ansi, truncate_ansi, wrap  # noqa: E402

W = TraceWriter(color=wants_color())
SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "toy_trajectory.json")

# The four budget tiers of the paper. A trajectory shorter than the smallest
# tier still gets its decision points from the forward pass milestones, so the
# demo adds a smaller tier to keep it inside the example's own budget.
TIERS = (4_000, 8_000, 32_000, 48_000, 64_000, 128_000)


def para(text: str, indent: str = "  ") -> None:
    for line in wrap(text, W.width, indent=indent):
        print(line)


def show_trajectory(traj) -> None:
    print(W.rule("1. the recorded trajectory"))
    para(f"{traj.T} turns. The agent locates the parser, reads it, runs the suite, finds the "
         f"accumulation bug, fixes it, has to swallow whitespace as well, then adds "
         f"regression tests.")
    print()
    print("  system prompt (locked, abridged)")
    para(" ".join(traj.system.split())[:220] + " …", indent="      ")
    print()
    print("  task")
    para(" ".join(traj.task.split()), indent="      ")


def show_blocks(ctx: Context) -> None:
    print()
    print(W.rule("2. every tool result becomes a block"))
    para("Blocks are numbered in order of creation. Entering before turn t means the block is "
         "in context when the agent writes its output for turn t.")
    print()
    print(f"  {'block':>5}  {'enters':>6}  {'kind':<6} {'source':<38} {'chars':>6}")
    for b in ctx.blocks:
        lock = " LOCKED" if b.locked else ""
        print(f"  {b.index:>5}  {b.entry_turn:>6}  {b.role:<6} {b.source[:38]:<38} "
              f"{len(b.text):>6}{lock}")


def show_releases(an: Annotation) -> None:
    print()
    print(W.rule("3. the offline teacher assigns release points"))
    para("The teacher keeps every block unless it can cite the event that ended its use, at "
         "turn k. A mechanical literal check then traces the block's rare literals through the "
         "later actions; a literal that comes back postpones the release to the turn lambda it "
         "reappears, and turns a drop into a summary.")
    print()
    print(f"  {'block':>5}  {'k':>4}  {'lambda':>6}  {'r_hat':>5}  {'kind':<10} "
          f"{'stage':<11} {'cause':<44} postponed by")
    for p in an.releases.points.values():
        lam = "—" if p.lam is None else str(p.lam)
        kind = p.kind.replace("to_", "to ")
        print(f"  {p.block:>5}  {p.k:>4}  {lam:>6}  {p.r_hat:>5}  {kind:<10} "
              f"{p.stage:<11} {p.trigger[:44]:<44} "
              f"{', '.join(p.postponed_by) or '—'}")
    kept = [b.index for b in an.context.blocks
            if b.index not in an.releases.points]
    print()
    para(f"Blocks {kept} are kept: nothing in the trajectory ended their use. A kept block is "
         f"never editable, so it stays in every context of the session.")
    print()
    for m in an.releases.milestones:
        print(f"  milestone after turn {m.after_turn}: {m.description}")
    if len(an.releases.milestones) == 1:
        print("  (a trajectory carries at most two milestones; they raise a decision point "
              "of their own, on top of what the budget asks for)")


def show_second_pass(an: Annotation) -> None:
    log = an.releases.second_pass_log
    if not log:
        return
    print()
    print(W.rule("4. the second pass revisits the kept blocks"))
    para("Candidates come from the teacher's nominations and from a mechanical rule: a tool "
         "result whose rare literals stop reappearing at least three turns before the end. A "
         "review must cite an event, and a claim that a later block supersedes the candidate is "
         "checked by looking for every distinctive line of the candidate in that block.")
    print()
    print(f"  {'block':>5}  {'source':<16} {'verdict':<10} reason")
    for entry in log:
        print(f"  {entry['block']:>5}  {entry['source']:<16} {entry['verdict']:<10} "
              f"{entry.get('reason', '')[:60]}")


def show_budget(ctx: Context, an: Annotation) -> None:
    print()
    print(W.rule("5. the budget tier"))
    sizes = unedited_prompt_tokens(ctx)
    peak = max(sizes)
    print(f"  unedited context over the session: {sizes[0]} → {peak} tokens "
          f"(peak at turn {sizes.index(peak) + 1})")
    print()
    print(f"  {'tier':>7}  {'soft 70%':>9}  {'hard 95%':>9}  crosses?")
    for tier in TIERS:
        crosses = "yes" if peak >= 0.70 * tier else "no"
        note = "  ← selected" if tier == an.budget else ""
        print(f"  {tier:>7}  {int(0.70 * tier):>9}  {int(0.95 * tier):>9}  {crosses}{note}")
    if an.budget is None:
        para("No tier of the paper's grid (32K and up) is crossed by a trajectory this short, "
             "so the session runs without a budget and its decision points come from the "
             "milestones of the forward pass. The tiers above 32K are shown for scale.")
    print()
    if an.budget is not None:
        para(f"Tier {an.budget} is the largest one whose soft line the peak crosses while the "
             f"incompressible floor — the final context with every released block removed — "
             f"still fits.")


def show_decisions(an: Annotation) -> None:
    print()
    print(W.rule("6. the online teacher writes the edits"))
    para("At a decision point the teacher plays the agent at that turn. It sees the trigger "
         "and every block still in context, each marked editable when the release point has "
         "passed, and nothing else. Its edits execute at once, so the next decision point sees "
         "the rewritten blocks.")
    if not an.decisions:
        para("This session raises no decision point.")
        return
    for dp in an.decisions:
        print()
        print(f"  {W._paint(f'turn {dp.turn}', fg='accent', bold=True)}   "
              f"trigger {dp.trigger}   {dp.tokens} tokens   "
              f"{W._paint(dp.outcome, fg='good' if dp.outcome == 'edited' else 'muted')}")
        if dp.note:
            para(dp.note, indent="      ")
        if dp.reason:
            print(f"      {W._paint(dp.reason, fg='muted', dim=True)}")
        if dp.ops:
            print(f"      {W._paint(f'freed {dp.freed:.1%} of the context', fg='good')}")
        for op in dp.ops:
            kind = {"drop": "drop", "rewrite": "rewrite", "append": "append"}[op.op]
            tint = {"drop": "drop_fg", "rewrite": "rewrite_fg", "append": "append_fg"}[op.op]
            target = "" if op.ref is None else f" {op.ref}"
            body = " ".join((op.text or "").split())
            print(f"      {W._paint(kind.ljust(8), fg=tint, bold=True)}{target:<4} "
                  f"{truncate_ansi(body, W.width - 22)}")


def show_edit_script(an: Annotation) -> None:
    print()
    print(W.rule("7. the edit script the teacher produced"))
    para("This is what a model would have written at that turn, in the grammar of the 70 "
         "tokens. The rationale comes first, the envelopes follow, and the recorded action of "
         "the turn goes last.")
    from nce.annotate.replay import Replayer, compose_output

    rp = Replayer(an.context)
    for t in range(1, an.context.T + 1):
        dp = next((d for d in an.decisions if d.turn == t), None)
        ops = dp.ops if dp is not None and dp.outcome == "edited" else []
        envelopes, ops = rp.compile(ops)
        output = compose_output(dp.note if ops and dp is not None else "",
                                envelopes, an.context.actions[t - 1])
        rp.finish_turn(t, output, ops)
        if not envelopes:
            continue
        print(f"  {W._paint(f'output of turn {t}', fg='accent', bold=True)}")
        for line in output.split("\n"):
            if T.contains_nce_token(line):
                for row in wrap(strip_ansi(line), W.width - 2, indent="      ", first="    "):
                    print(W.chip_line(row, indent=""))
            else:
                print("    " + W._paint(truncate_ansi(line, W.width - 6), fg="base"))
        print()


def show_audit(an: Annotation) -> None:
    print(W.rule("8. the final audit"))
    para("A summary may not assert a number, path, identifier or quoted string that its source "
         "does not carry; a literal the edit removes may not reappear later unless it was "
         "written down first; and a turn must free at least 3% of the context.")
    entries = an.audit.entries
    kept = sum(1 for e in entries if e.verdict == "kept")
    print()
    print(f"  {len(entries)} edits checked, {kept} kept, {len(entries) - kept} rejected")
    for e in entries:
        if e.verdict == "rejected":
            print(f"    turn {e.turn} {e.op.op}{' ' + str(e.op.ref) if e.op.ref else ''}: "
                  f"{e.reason}")
    print()
    print(f"  edit turns: {an.audit.edit_turns} of {an.context.T}")
    if an.discarded:
        print(f"  trajectory discarded: {an.audit.discard_reason}")
    else:
        print("  trajectory kept: an edit in a hard-reminder turn and an edit rate above "
              "six turns and 15% of turns are the two reasons to discard one")


def show_result(an: Annotation) -> None:
    print()
    print(W.rule("9. the annotated trajectory"))
    annotated = an.annotated()
    print(f"  {annotated.T} turns, budget {annotated.meta.get('budget')}, "
          f"{len(an.audit.edit_turns)} of them carry edits")
    print()
    for t, turn in enumerate(annotated.turns, start=1):
        if t not in an.audit.edit_turns:
            continue
        text = turn.output
        head = " ".join(text.split("\n")[0].split())
        print(f"  turn {t}: {truncate_ansi(head, W.width - 12)}")
        print(f"    {text.count(T.CTX_OPEN)} envelope(s), "
              f"{len(text)} characters")
    print()
    para("From here nce.distill cuts the trajectory into training segments and marks every "
         "character with a loss flag; examples/05_distill_segments.py shows that step.")


def main() -> None:
    print(W.rule("nce · how a trajectory is labelled"))
    print()
    traj = load_trajectory(SOURCE)
    show_trajectory(traj)
    ctx = Context(traj)
    show_blocks(ctx)

    an = annotate(traj, RuleBasedOfflineTeacher(), RuleBasedOnlineTeacher(), tiers=TIERS)
    show_releases(an)
    show_second_pass(an)
    show_budget(ctx, an)
    show_decisions(an)
    show_edit_script(an)
    show_audit(an)
    show_result(an)

    print()
    print(W.rule())
    print("  The whole annotation ran offline from deterministic rules. Swap in any "
          "OfflineTeacher and\n  OnlineTeacher that satisfy the interfaces and the pipeline "
          "is unchanged.")


if __name__ == "__main__":
    main()
