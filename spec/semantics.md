# Semantics

## The state

At turn `t` the state is `S_t = (B_t, A_t)`:

* `B_t` is the list of blocks currently retained, in interaction order. A block
  is a pair `(address, text)`. Every block also has a role, which the rendering
  turns into a role tag, and SHOULD carry whether it is locked.
* `A_t` is the action history, in order. An action is the agent's output for a
  turn with the envelopes removed.

The two lists interleave as the items arrived, and `Render` walks that one
interleaved sequence. A reminder is a third kind of item: a transient runtime
message that carries no address and is removed once an edit executes.

Block roles are `system`, `user`, `tool`, and `note`. Only the system prompt of
a session SHOULD be locked.

## Edits and the transition

An edit denotes exactly one transition of `B`:

| Operator | Transition |
|---|---|
| `drop(α₁…α_m)` | remove the named blocks from `B`, and retire their addresses for the rest of the session |
| `rewrite(α, x)` | replace the text of block `α` with `x`, keeping its address |
| `append(x)` | add a block with text `x` under the next address |

`Execute` applies the edits of one turn in the order they were written, and the
turn then appends the current action and the current observation:

```
S_{t+1} = Execute(S_t, e_t) ⊕ (a_t, b_t)
```

`⊕` appends `a_t` to `A` and `b_t` to `B`. With `e_t` empty the equation is the
ordinary growth of an agent's context.

## Checks

An edit is atomic: if any check fails, the edit MUST change nothing. The
runtime MUST report a reason for a refused edit.

Before an edit runs:

| Check | Reason | Applies to |
|---|---|---|
| The envelope is well formed (`grammar.md`) | the grammar's own reason, e.g. `missing_address` | all |
| The address was issued in this session | `unknown_address` | `drop`, `rewrite` |
| The block is still live | `not_live` | `drop` |
| The block is not locked | `locked` | `drop`, `rewrite` |
| The envelope was not already written verbatim in this turn | `duplicate` | all |

For a `drop` naming several blocks, every address must pass before any is
removed. A `drop` that lists a locked block therefore removes nothing.

The one exception to atomicity follows the paper: a rewrite of a block that is
no longer live is applied as an **append**, so its text survives. The runtime
MUST report this as a distinct outcome from a plain append.

A `drop` whose address was retired but was issued is `not_live`; a `drop` whose
address was never issued at all is `unknown_address`. An implementation SHOULD
keep the two apart so a reviewer can tell a stale address from an invented one.

## The output around the edits

The envelopes are not retained. After execution the runtime strips them from
the output, and the remaining text — the rationale and the action — enters the
action history and is what the model reads back on later turns. A token outside
any envelope has no target, MUST be discarded, and SHOULD be counted so a
misplaced edit does not pass unnoticed.

A reminder stays in the prompt until an edit executes, at which point the
runtime removes it. A turn with no executed edit leaves the reminder where it
is.

## Rendering

`Render(S_t)` writes each item in order:

**Block.** The two address tokens, then `<m_ro>` if the block is locked, then
the block text in the chat format of the base model, opened by its role tag:

```
<sid_hi_hh><sid_lo_ll>[<m_ro>]<role-tag><block text><separator>
```

No closing token is emitted for a block: the address of the next block marks
where a block ends. A tool block MAY name the tool that produced it on the
first line of its text.

**Action.** An ordinary assistant turn, with no address:

```
<assistant-open><action text><assistant-close><separator>
```

Because actions carry no address, an edit can reach the observations, the task,
and the notes, and leaves the agent's own actions intact.

**Reminder.** A transient user message with no address.

The role tags and separators belong to the base chat template, not to NCE. The
address tokens, the lock marker, and the envelope tokens do belong to NCE, and
they MUST survive whatever template is applied: a server that applies its own
template SHOULD receive the address as part of the block's text content.

### What the rendering implies

* A dropped block is excluded from every later rendering, so its text leaves
  the context and the cache together.
* A rewritten block renders under its own address with its new text, so the
  model can reach the same block again.
* The address pair lets the model copy a target exactly, without inventing a
  name for it.
* The rendering is a pure function of the state: two implementations that agree
  on the state and the chat format produce the same text.

## Reminders

Under a budget `W` the runtime appends a reminder to the prompt once the
context reaches 70% of `W` (**soft**) or 95% of `W` (**hard**).

* A soft reminder MAY be declined. After any reminder the runtime waits four
  turns before the next one, and eight after a declined soft reminder. It stops
  issuing soft reminders after two have been declined. Hard reminders are not
  limited.
* The reminder text carries no numbers, so the model cannot read off how much
  room is left. The same text serves NCE and tool-call editing.
* A reminder is transient: it leaves the prompt when an edit executes.

## Prefix reuse

If at least one edit executed, the state changed and the next prompt MUST be
rendered afresh from the new state. If no edit executed, the next prompt
extends the previous one, and its prefix cache stays valid. An implementation
SHOULD expose this so a serving layer can reuse the cache.
