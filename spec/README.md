# The NCE grammar

A precise, implementation-neutral specification of the edit language of
**Native Context Editing (NCE)**, as the paper states it in §3 ("A Native
Grammar for Context Editing") and Appendix A ("The NCE Grammar and Runtime").

The spec is written so that two independent implementations agree on what a
well-formed edit is and on what it does to the context. It fixes the token
strings, the composition rules, the transition each edit denotes, and the
rendering the model reads. It says nothing about how a runtime is built.

* `tokens.md` — the 70 dedicated tokens and the two-token address code.
* `grammar.md` — the composition rules for a well-formed edit.
* `semantics.md` — the context state, `Execute`, the checks, and `Render`.
* `conformance.md` — the fixtures, and the claims this repository's
  implementation makes about them.

The reference implementation of all of this is the `nce` package in this
repository; `conformance.md` records where it agrees with the paper and the
two places where it deliberately goes further.

## Normative summary

The keywords **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are used in the
usual sense.

**Tokens.** An implementation MUST reserve exactly 70 tokens with the strings
in `tokens.md`. Each MUST be a single atomic token, so a model copies a block
address as exactly two tokens.

**Edits.** One edit is one envelope around exactly one operator
(`grammar.md`). A turn's output MAY hold any number of edits, interleaved with
ordinary text. The ordinary text carries no semantics; it is the rationale and
the action.

**Execution.** The runtime MUST execute the edits of a turn in the order they
were written (`semantics.md`). Each edit is atomic: if any of its checks
fails, it MUST change nothing. An edit MUST NOT touch a locked block, and each
address MUST name a live block. The one exception is a rewrite of a block that
is no longer live, which MUST be applied as an append so its text is kept.

**Rendering.** `Render` MUST open each block with its two address tokens, the
lock marker if the block is locked, and the block text in the chat format of
the base model. It MUST NOT emit a closing token for a block: the next address
marks where a block ends. Actions MUST carry no address. The directives
themselves MUST NOT be part of the rendering.

**Retirement.** An address MUST never be reused within a session, so a dropped
block can never be confused with a later one.
