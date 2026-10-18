# Token vocabulary

NCE reserves **70 dedicated tokens** and adds them to the vocabulary of the
base model. Every one of them is a single token: the model targets a block by
copying exactly two tokens, and no token string ever spans a token boundary.

The role tags that open a block in the rendering (`<|system|>`, `<|tool|>` and
so on) are the existing tokens of the base chat template. They are not part of
the 70.

## The 70 tokens

| Group | String form | Count | Role |
|---|---|---|---|
| High address digit | `<sid_hi_hh>`, `hh` = `00`…`31`, zero-padded | 32 | high-order digit of a block address |
| Low address digit | `<sid_lo_ll>`, `ll` = `00`…`31`, zero-padded | 32 | low-order digit of a block address |
| Operators | `<op_drop>`, `<op_rewrite>`, `<op_append>` | 3 | which transition an edit denotes |
| Envelope delimiters | `<ctx>`, `</ctx>` | 2 | delimit one edit |
| Lock marker | `<m_ro>` | 1 | marks a block that may not be edited |
| | | **70** | |

The padding is part of the string. `<sid_hi_1>` and `<sid_hi_32>` are not
tokens: the first is not zero-padded, the second has no high digit 32. Both are
ordinary text, as is anything of the shape `<ctxv>` or `List<T>`.

## Addresses

A block address is a pair of tokens, a high digit followed by a low digit:

```
addr(n) = <sid_hi_ floor(n / 32) > <sid_lo_ n mod 32 >
```

Block `n` is counted from zero in order of creation. The pair therefore names

```
32 × 32 = 1,024
```

distinct blocks. Worked examples:

| `n` | hi | lo | written |
|---|---|---|---|
| 0 | 0 | 0 | `<sid_hi_00><sid_lo_00>` |
| 7 | 0 | 7 | `<sid_hi_00><sid_lo_07>` |
| 31 | 0 | 31 | `<sid_hi_00><sid_lo_31>` |
| 32 | 1 | 0 | `<sid_hi_01><sid_lo_00>` |
| 71 | 2 | 7 | `<sid_hi_02><sid_lo_07>` |
| 1,023 | 31 | 31 | `<sid_hi_31><sid_lo_31>` |

The pair is written with no separator, and the two tokens are adjacent in the
rendering and in every edit an implementation emits. An implementation MUST
also accept whitespace between the two tokens in an envelope it parses, since
`grammar.md` gives whitespace between tokens no meaning.

### Address issuance

* Addresses are issued in order: the `k`-th block created in a session gets the
  `k`-th address, counting from zero.
* An address MUST NOT be reused within a session. Once a block is dropped its
  address is **retired** for the rest of the session and never names another
  block. Address `n` therefore has one of three states at any moment: *not yet
  issued*, *live*, or *retired*.
* A rewrite keeps the address of the block it rewrites.
* An append issues the next address.

Because addresses only ever go up, a session that creates more than 1,024
blocks exhausts the space. An implementation MUST report exhaustion, and MUST
NOT wrap around. The reference implementation raises `AddressExhausted`.

### Address of the second token

The low digit is what makes the pair an address. A high digit that is not
followed by a low digit is **not** an address, and neither is a low digit on
its own. This matters for a `drop` list (see `grammar.md`): a broken pair makes
the whole edit malformed, and it does not merely shorten the list.

## The lock marker

`<m_ro>` is written immediately after the address of a locked block, before the
role tag:

```
<sid_hi_00><sid_lo_00><m_ro><|system|>You are a coding agent. ...
```

The marker says the block may not be edited. It is a rendering detail and never
appears inside an envelope: an edit names a locked block the ordinary way, and
the runtime refuses the edit (`semantics.md`).

## Reserved strings

No other string of this shape is reserved. In particular, an implementation MAY
define its own special tokens; it MUST NOT rename, split, or re-purpose any of
the 70, because their strings are part of the checkpoint's vocabulary.
