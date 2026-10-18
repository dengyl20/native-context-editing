"""Rare literals and the mechanical literal check (Appendix B).

A block's rare literals are the strings a later action would have to copy
if it still used the block: paths, identifiers containing an underscore,
long integers, hexadecimal strings, precise decimals, and four-digit numbers
in line-number position (``1589:``). A literal is rare if it is at least
four characters long and occurs at most eight times in the whole trajectory.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Set

MIN_LEN = 4
MAX_OCCURRENCES = 8

PATH_RE = re.compile(r"(?<![\w/.-])(?:\.{1,2}/|/)?[\w.-]+(?:/[\w.-]+)+")
IDENT_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
INT_RE = re.compile(r"(?<![\w.])\d{5,}(?![\w.])")
HEX_RE = re.compile(r"\b[0-9a-fA-F]{8,}\b")
DECIMAL_RE = re.compile(r"(?<![\w.])\d+\.\d{4,}(?![\w.])")
LINENO_RE = re.compile(r"(?m)(?:^|[\s:])(\d{4})(?=[:\t])")

KINDS = ("path", "identifier", "integer", "hex", "decimal", "line_number")


@dataclass(frozen=True)
class Literal:
    text: str
    kind: str


def extract_literals(text: str) -> List[Literal]:
    """Every literal candidate in ``text``, in order of first appearance.

    A string is reported under its most specific kind: a number in
    line-number position is a ``line_number``, not an ``integer``.
    """
    found: Dict[str, Literal] = {}

    def add(s: str, kind: str) -> None:
        if len(s) >= MIN_LEN and s not in found:
            found[s] = Literal(s, kind)

    for m in LINENO_RE.finditer(text):
        add(m.group(1), "line_number")
    for m in PATH_RE.finditer(text):
        add(m.group().rstrip("."), "path")
    for m in IDENT_RE.finditer(text):
        s = m.group()
        if "_" in s.strip("_") and any(c.isalpha() for c in s):
            add(s, "identifier")
    for m in INT_RE.finditer(text):
        add(m.group(), "integer")
    for m in HEX_RE.finditer(text):
        s = m.group()
        if any(c.isalpha() for c in s) and any(c.isdigit() for c in s):
            add(s, "hex")
    for m in DECIMAL_RE.finditer(text):
        add(m.group(), "decimal")
    return list(found.values())


class LiteralIndex:
    """Occurrence counts over every text of a trajectory."""

    def __init__(self, texts: Iterable[str]):
        self._texts = list(texts)
        self._cache: Dict[str, int] = {}

    def count(self, s: str) -> int:
        if s not in self._cache:
            self._cache[s] = sum(t.count(s) for t in self._texts)
        return self._cache[s]

    def rare(self, text: str) -> List[Literal]:
        return [lit for lit in extract_literals(text) if self.count(lit.text) <= MAX_OCCURRENCES]


def last_reappearance(literals: Iterable[Literal], actions: List[str], after: int,
                      kinds: Optional[Set[str]] = None) -> Optional[int]:
    """The last turn ``u > after`` whose action contains one of ``literals``.

    ``actions[u - 1]`` is the action of turn ``u``, tool-call arguments
    included. Returns None if none reappears.
    """
    lits = [lit.text for lit in literals if kinds is None or lit.kind in kinds]
    last = None
    for u in range(after + 1, len(actions) + 1):
        if any(s in actions[u - 1] for s in lits):
            last = u
    return last
