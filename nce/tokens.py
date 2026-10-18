"""The 70 dedicated tokens of NCE and the two-token address code.

Every block address is a pair ``<sid_hi_hh><sid_lo_ll>``. Block ``n`` (counted
from zero in order of creation) receives ``hh = n // 32`` and ``ll = n % 32``,
so 64 address tokens name 1,024 blocks. Six more tokens complete the
vocabulary: three operators, the two envelope delimiters, and the lock marker.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Tuple

ADDR_BASE = 32
ADDR_CAPACITY = ADDR_BASE * ADDR_BASE  # 1,024 addresses

ADDR_HI: List[str] = [f"<sid_hi_{i:02d}>" for i in range(ADDR_BASE)]
ADDR_LO: List[str] = [f"<sid_lo_{i:02d}>" for i in range(ADDR_BASE)]

OP_DROP = "<op_drop>"
OP_REWRITE = "<op_rewrite>"
OP_APPEND = "<op_append>"
OPERATORS: List[str] = [OP_DROP, OP_REWRITE, OP_APPEND]

CTX_OPEN = "<ctx>"
CTX_CLOSE = "</ctx>"
LOCKED = "<m_ro>"

CONTROL_TOKENS: List[str] = OPERATORS + [CTX_OPEN, CTX_CLOSE, LOCKED]
NCE_TOKENS: List[str] = ADDR_HI + ADDR_LO + CONTROL_TOKENS
assert len(NCE_TOKENS) == 70

_HI_INDEX = {t: i for i, t in enumerate(ADDR_HI)}
_LO_INDEX = {t: i for i, t in enumerate(ADDR_LO)}
_TOKEN_SET = frozenset(NCE_TOKENS)

# Matches exactly the 70 token strings and nothing else: `<sid_hi_1>`,
# `<sid_hi_32>` or `List<T>` are ordinary text.
TOKEN_RE = re.compile(
    r"<(?:sid_(?:hi|lo)_(?:[012][0-9]|3[01])|op_(?:drop|rewrite|append)|/?ctx|m_ro)>"
)
MAX_TOKEN_LEN = max(len(t) for t in NCE_TOKENS)


def encode_address(n: int) -> str:
    """Return the two-token address of block ``n``."""
    hi, lo = encode_address_pair(n)
    return hi + lo


def encode_address_pair(n: int) -> Tuple[str, str]:
    if not 0 <= n < ADDR_CAPACITY:
        raise ValueError(f"address {n} outside 0..{ADDR_CAPACITY - 1}")
    hi, lo = divmod(n, ADDR_BASE)
    return ADDR_HI[hi], ADDR_LO[lo]


def decode_address(hi_token: str, lo_token: str) -> int:
    """Inverse of :func:`encode_address_pair`."""
    try:
        return _HI_INDEX[hi_token] * ADDR_BASE + _LO_INDEX[lo_token]
    except KeyError:
        raise ValueError(f"not an address: {hi_token!r}{lo_token!r}") from None


def is_nce_token(s: str) -> bool:
    return s in _TOKEN_SET


def is_hi(s: str) -> bool:
    return s in _HI_INDEX


def is_lo(s: str) -> bool:
    return s in _LO_INDEX


def split_tokens(text: str) -> List[str]:
    """Split ``text`` into NCE tokens and the ordinary text between them."""
    out, pos = [], 0
    for m in TOKEN_RE.finditer(text):
        if m.start() > pos:
            out.append(text[pos:m.start()])
        out.append(m.group())
        pos = m.end()
    if pos < len(text):
        out.append(text[pos:])
    return out


def contains_nce_token(text: str) -> bool:
    return TOKEN_RE.search(text) is not None


def add_nce_tokens(tokenizer, model=None) -> int:
    """Register the 70 tokens with a Hugging Face tokenizer (optional helper).

    Each string becomes one atomic special token, so the model targets a block
    by copying exactly two tokens. If ``model`` is given, its embedding matrix
    is resized to the new vocabulary. Returns the number of tokens added.
    ``transformers`` is never imported here; any object with the usual
    ``add_special_tokens`` method works.
    """
    added = tokenizer.add_special_tokens(
        {"additional_special_tokens": list(NCE_TOKENS)},
        replace_additional_special_tokens=False,
    )
    if model is not None and added:
        model.resize_token_embeddings(len(tokenizer))
    return added


def check_tokenizer(tokenizer, tokens: Iterable[str] = NCE_TOKENS) -> List[str]:
    """Return the NCE tokens that the tokenizer does not keep atomic."""
    bad = []
    for t in tokens:
        ids = tokenizer.encode(t, add_special_tokens=False)
        if len(ids) != 1:
            bad.append(t)
    return bad
