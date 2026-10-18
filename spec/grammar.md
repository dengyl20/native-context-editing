# Composition rules

An edit is one envelope around one operator:

```
edit ::= <ctx> <op_drop>    addr+   </ctx>
       | <ctx> <op_rewrite> addr x  </ctx>
       | <ctx> <op_append>  x       </ctx>

addr ::= <sid_hi_hh><sid_lo_ll>          hh, ll ∈ 00..31
x    ::= text containing none of the 70 tokens
```

A turn's output is ordinary text interleaved with zero or more edits. The text
is the rationale and the action; it carries no semantics for the runtime.

## Well-formedness

A **well-formed** edit satisfies every rule for its operator. Any violation
makes the edit **malformed**; a malformed edit executes as a no-op, and the
runtime MUST report why (`semantics.md`).

### Structural rules for all three operators

| # | Rule |
|---|---|
| S1 | The envelope opens with `<ctx>` and closes with `</ctx>`. An envelope left open at the end of the output is malformed (`unterminated`). |
| S2 | The first NCE token inside the envelope is exactly one of the three operators. |
| S3 | Whitespace between tokens carries no meaning. The text after the last token is stripped, so leading and trailing whitespace never makes an edit malformed. |
| S4 | The envelope MUST contain no second operator and no nested envelope. |

### `<op_drop>`

| # | Rule |
|---|---|
| D1 | At least one address follows the operator. An operator with no address is malformed (`missing_address`). |
| D2 | Every address after the operator is a complete pair: a high digit immediately followed by a low digit. A high digit with no low digit, a low digit on its own, or two high digits in a row is malformed (`bad_address`). |
| D3 | Nothing but addresses and whitespace follows the operator. Trailing ordinary text is malformed (`unexpected_content`). |
| D4 | An address MAY be repeated within one edit. The repeat counts once. |

### `<op_rewrite>`

| # | Rule |
|---|---|
| R1 | Exactly one address follows the operator. |
| R2 | Text follows the address, and it MUST be non-empty after stripping. An empty replacement is malformed (`empty_text`). |
| R3 | The text MUST contain none of the 70 tokens. Any token in the text, including a second address, is malformed (`token_in_text`). |

### `<op_append>`

| # | Rule |
|---|---|
| A1 | Text follows the operator directly, and it MUST be non-empty after stripping (`empty_text`). |
| A2 | The text MUST contain none of the 70 tokens (`token_in_text`). |

An append names no block: the runtime issues the next address for it.

## The text `x`

`x` is ordinary text in the base model's vocabulary. It MAY contain any
character or byte sequence that is not one of the 70 token strings, and it MAY
contain strings that look like tokens without being tokens: `<sid_hi_1>` is
unpadded and `<sid_hi_32>` is out of range, so both are ordinary text, in `x`
and in an envelope's token stream alike.

Whitespace inside `x` is part of `x` up to the leading and trailing strip. A
rewrite therefore replaces the block's text with the exact `x` the model wrote,
minus its outer whitespace.

## One edit, one envelope

An envelope holds exactly one operator, so a model that wants to drop three
blocks writes either one envelope naming three addresses or three envelopes;
both are well-formed. A model that wants to rewrite two blocks writes two
envelopes; `<op_rewrite>` with two addresses is malformed under R3, because the
second address is a token inside the replacement text.

The reference implementation groups consecutive drops into one envelope when it
serializes a teacher's decisions, since D1–D4 permit it. This is a writing
convention, not a rule of the grammar: a runtime MUST accept one drop per
envelope as well.

## A repeated envelope

Two envelopes within one turn that are identical byte for byte are the same
edit. The runtime executes the first and refuses the rest (`semantics.md`).

## Canonical text

Every well-formed edit has one canonical written form, used when an
implementation re-emits an edit it parsed:

```
<op_drop>      <ctx><op_drop>addr_1...addr_m</ctx>
<op_rewrite>   <ctx><op_rewrite>addr x</ctx>
<op_append>    <ctx><op_append> x </ctx>
```

The addresses keep the order they were written in, and `x` is the stripped
text. A runtime MUST NOT reorder, deduplicate, or merge the addresses of a drop.
