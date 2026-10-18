# Conformance

How the `nce` package in this repository relates to the specification in the
files above, and what the test suite checks.

Everything here is verifiable from the repository:

```
python3 -c "import nce"                  # the import surface
python3 -m unittest discover -s tests    # the suite
```

## Fixtures

`tests/fixtures/` holds the conformance fixtures. A fixture is either a
scripted model output paired with the state it runs against, or a recorded
state written in the JSON shape of `nce.state.State`. Both are plain JSON so a
second implementation can read them without importing this package.

`edits.json` holds one scripted output per rule of `grammar.md` and
`semantics.md`, with the state before, the verdict on every envelope, and the
state after, so a second implementation can replay each case and compare.
`vocabulary.json` holds the 70 token strings and a few addresses, and
`session.json` holds one state with its rendering.

Regenerate them with `python3 tests/make_fixtures.py`.

`tests/test_conformance.py` reads those three files and asserts their contents;
it does not depend on this package's internals beyond replaying the cases.
`tests/test_tokens.py`, `test_grammar.py`, `test_state.py`, `test_runtime.py`,
and `test_annotate.py` cover the same ground from inside the package, so a rule
that breaks shows up twice. `tests/README.md` lists every module.

## What matches the paper

| Spec | Paper | Where |
|---|---|---|
| 70 tokens; 32 high, 32 low, 3 operators, 2 delimiters, 1 lock marker | Appendix A.1, Table A.1 | `nce/tokens.py`; `tests/test_tokens.py` |
| `addr(n) = <sid_hi_⌊n/32⌋><sid_lo_(n mod 32)>`, 1,024 addresses | §3, Appendix A.1 | `encode_address_pair`; round trip over all 1,024 in the suite |
| `e ::= <ctx><op_drop>α⁺</ctx> \| <ctx><op_rewrite>α x</ctx> \| <ctx><op_append>x</ctx>` | §3, Appendix A.3 | `nce/grammar.py`; `tests/test_grammar.py` |
| One envelope, one operator | §3 | `parse_envelope` rejects a second operator |
| Drop retires addresses for good; rewrite keeps the address; append issues a fresh one | §3 | `nce/state.py`; `tests/test_state.py` |
| Edits execute in written order | Appendix A.3 | `execute`; ordering test |
| Only the locked block is off limits | Appendix A.3 | `locked` check; test per operator |
| A rewrite of a non-live block is applied as an append | Appendix A.3 | `APPLIED_AS_APPEND` |
| An edit repeated verbatim in a turn executes once | Appendix A.3 | `duplicate`; test |
| The envelopes do not enter the context | §3, Appendix A.3 | `apply_output`; test on the action history |
| Each block renders as address, lock marker, role tag, text | §3, Appendix A.2 | `render_text`; exact-string tests |
| Actions carry no address | §3, Appendix A.2 | `render_action` |
| Soft at 70%, hard at 95%; waits of 4 and 8; two declined soft reminders end them | Appendix A.4 | `ReminderPolicy`; tests at the boundaries |
| Reminder texts carry no numbers | Appendix A.4 | test over both texts |
| A reminder lasts until an edit executes | Appendix A.4 | test in `test_runtime.py` |
| Fresh render after an executed edit, reused prefix otherwise | Appendix A.3 | `StepResult.prefix_reusable` |

### A note on the witness address

§3 and Appendix A.1 write "the 72nd block is represented by
`<sid_hi_02><sid_lo_07>`". That is the block numbered **71**, the 72nd counting
from one, which is what the formula `⌊71/32⌋ = 2`, `71 mod 32 = 7` gives. The
implementation follows the formula. `spec/tokens.md` lists the same witness
row.

## Where this implementation goes further

Two things are in the package and not in the grammar appendix. Both are
additions, so neither changes what a well-formed edit means.

1. **Block history on a rewrite.** `Block.history` records the texts a block
   has held, oldest first, and `to_json` writes it. The paper keeps only the
   current text. The field is not rendered and not read by `Execute`; it exists
   so a rewrite is auditable after the fact, which the annotation pipeline uses
   when it checks a summary against its source.

2. **Stray-token counting.** A token outside any envelope is discarded, and the
   runtime reports how many it saw (`StepResult.stray_tokens`). The paper does
   not specify the case. Counting it turns a silently misplaced edit into
   something a reviewer can see.

## Where the implementation depends on a convention

These are choices the paper leaves open, resolved one way here and documented
so a second implementation can differ deliberately:

* **The chat format.** The role tags and separators of the base chat template
  are not part of NCE. The package ships a neutral default (`DEFAULT_FORMAT`,
  tags such as `<|system|>`) and a `ChatFormat` to subclass. Any template works
  as long as the address tokens and the lock marker reach the model.
* **Grouping consecutive drops.** `Replayer.compile` puts consecutive drops into
  one envelope. The grammar allows one drop per envelope too, and a runtime MUST
  accept both.
* **Tool-call syntax for the annotation pipeline.** `parse_tool_calls` reads
  `<tool_call>{"name": ..., "arguments": {...}}</tool_call>`. Only the
  annotation examples use it, and a caller can pass a parser of its own.
* **Token counting.** `approx_tokens` is a dependency-free estimate, used by the
  examples. Anything that reports a real number passes a tokenizer's counter
  through the `Counter` slot instead.
* **The teachers.** `nce.annotate.rules` implements both teachers as
  deterministic rules, standing in for the two LLM teachers of §3.2 so the
  pipeline runs offline. `OfflineTeacher` and `OnlineTeacher` are the
  interfaces; any implementation plugs in, and the pipeline is unchanged.

## Where the implementation is stricter than the spec

* `State.drop` and `State.rewrite` raise `KeyError` on an unknown address. The
  runtime checks liveness first and never passes one, so this is a state-layer
  guard against a programming error, and a caller cannot reach it through the
  grammar.
* `State.from_json` refuses a state whose `next_address` would let a retired
  address be issued again, or whose live blocks carry retired addresses. A
  fixture that violates the retirement rule fails to load, so it cannot load
  into an inconsistent state.
