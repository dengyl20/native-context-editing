# Examples

Five small scripts that walk the NCE grammar, runtime, and annotation
pipeline end to end. Standard library only, no network, no model calls.
Each one is runnable from the repository root:

```
python3 examples/01_token_grammar.py
python3 examples/02_runtime_edits.py
python3 examples/03_annotation_walkthrough.py
python3 examples/04_trace_render.py
python3 examples/05_distill_segments.py
```

| Script | What it shows |
|---|---|
| `01_token_grammar.py` | The 70 tokens and the two-token address code; how a context renders; how one model output splits into text and edit envelopes; how the streaming parser handles an envelope split across chunks. |
| `02_runtime_edits.py` | `drop`, `rewrite`, and `append` applied to addressable blocks, with the context size before and after each turn, and the cases the runtime refuses: a locked block, an address never issued, a retired address, a verbatim repeat, a malformed envelope, and a stray token. |
| `03_annotation_walkthrough.py` | How a recorded trajectory is labelled: blocks, release points with their cited events, the second pass, the budget tier, decision points, the edit script a teacher writes, and the final audit. |
| `04_trace_render.py` | An edit trace as coloured terminal output, in the palette the paper's token chips use. Pass `--no-color` to pipe it into a file. |
| `05_distill_segments.py` | Cutting an annotated trajectory into training segments and marking every piece with a loss flag. |

Scripts `03`, `04`, and `05` read `examples/data/toy_trajectory.json`, a
hand-written coding-agent session: an agent fixes a duration parser in a small
Python package. The other two build their own synthetic conversations.

Colour is emitted only when stdout is a terminal and `NO_COLOR` is unset, so
every script pipes cleanly.
