# Tests

A `unittest` suite, standard library only. Run it from the repository root:

```
python3 -m unittest discover -s tests
```

`python3 -m unittest discover -s tests -v` prints one line per test, and
`python3 -m unittest discover -s tests -k grammar` runs a subset.

| Module | What it covers |
|---|---|
| `test_tokens.py` | Vocabulary integrity: exactly 70 tokens, the group sizes of Table A.1, the address formula `⌊n/32⌋`/`n mod 32` over all 1,024 addresses, the token regex, and registration with a tokenizer. |
| `test_grammar.py` | Well-formedness accept/reject for every rule, with the rejection reason asserted; canonical serialization and the JSON round trip; the streaming parse across chunk boundaries, including every two-way split of each envelope. |
| `test_state.py` | The state model and the transitions of `drop`, `rewrite`, and `append`; address issuance and retirement; the JSON round trip and the consistency checks it enforces. |
| `test_runtime.py` | `Execute`: the well-formedness, liveness, lock, and duplicate checks; atomicity; the rewrite-as-append rule; the turn step and what enters the action history; the reminder policy at its boundaries. |
| `test_annotate.py` | The annotation pipeline on the toy trajectory: blockization, the literal check, release points, budget selection, triggers, decision points, the audit, and distillation into segments. |
| `test_conformance.py` | The fixtures in `fixtures/` against `spec/`, driven from JSON so a second implementation can read the same cases. |
| `test_render.py` | The rendering contract, exact-string tests for blocks, actions, and reminders; the chip palette; the coloured terminal writer and its colour policy. |
| `test_package.py` | The package surface: `import nce` from a bare interpreter, the declared version, and the absence of third-party imports. |

## Fixtures

`fixtures/` holds three plain JSON files:

* `vocabulary.json` — the 70 token strings, their groups, and the addresses of
  a few blocks.
* `session.json` — a session after one editing turn: a receipt dropped, a read
  rewritten, a note appended, and the action of the turn recorded. It carries
  the state, the rendering, and a summary of the counts.
* `edits.json` — eighteen scripted model outputs, one per rule of
  `spec/grammar.md` and `spec/semantics.md`, each with the state before, the
  verdict on every envelope, the recorded action text, and the state after.

They are generated deterministically:

```
python3 tests/make_fixtures.py
```

`tests/context.py` puts the repository root on `sys.path` and locates the
fixtures, so the suite runs from any working directory.

## Determinism

The suite has no network access, no model calls, and no wall-clock dependency.
The annotation pipeline is exercised through the rule-based teachers in
`nce.annotate.rules`, so its outputs are reproducible; `test_annotate.py`
asserts that two runs over the same trajectory agree.
