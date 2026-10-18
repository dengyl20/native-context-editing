"""The edit grammar: AST, (streaming) parser, and canonical serialization.

    e ::= <ctx> <op_drop>    addr addr* </ctx>
        | <ctx> <op_rewrite> addr text </ctx>
        | <ctx> <op_append>  text </ctx>

``addr`` is a two-token address ``<sid_hi_hh><sid_lo_ll>`` and ``text`` is
ordinary text that contains none of the 70 NCE tokens. A model output is
free text (the rationale and the action) with zero or more envelopes in it;
:func:`parse_output` separates the two. :class:`StreamParser` does the same
incrementally, for outputs that arrive chunk by chunk, and tolerates token
strings split across chunk boundaries.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Union

from . import tokens as T


# --------------------------------------------------------------------- AST


@dataclass(frozen=True)
class Drop:
    addresses: Tuple[int, ...]
    op = "drop"

    def to_text(self) -> str:
        addrs = "".join(T.encode_address(a) for a in self.addresses)
        return f"{T.CTX_OPEN}{T.OP_DROP}{addrs}{T.CTX_CLOSE}"


@dataclass(frozen=True)
class Rewrite:
    address: int
    text: str
    op = "rewrite"

    def to_text(self) -> str:
        return (f"{T.CTX_OPEN}{T.OP_REWRITE}{T.encode_address(self.address)}"
                f" {self.text.strip()} {T.CTX_CLOSE}")


@dataclass(frozen=True)
class Append:
    text: str
    op = "append"

    def to_text(self) -> str:
        return f"{T.CTX_OPEN}{T.OP_APPEND} {self.text.strip()} {T.CTX_CLOSE}"


@dataclass(frozen=True)
class Malformed:
    """An envelope that does not parse. It executes as a no-op."""
    raw: str
    reason: str
    op = "malformed"

    def to_text(self) -> str:
        return self.raw


Edit = Union[Drop, Rewrite, Append]
ParsedEdit = Union[Drop, Rewrite, Append, Malformed]


def serialize(edits: List[Edit]) -> str:
    """Canonical text of a list of edits, one envelope after another."""
    return "".join(e.to_text() for e in edits)


def edit_to_json(e: ParsedEdit) -> dict:
    if isinstance(e, Drop):
        return {"op": "drop", "addresses": list(e.addresses)}
    if isinstance(e, Rewrite):
        return {"op": "rewrite", "address": e.address, "text": e.text}
    if isinstance(e, Append):
        return {"op": "append", "text": e.text}
    return {"op": "malformed", "reason": e.reason, "raw": e.raw}


def edit_from_json(d: dict) -> Edit:
    op = d["op"]
    if op == "drop":
        return Drop(tuple(d["addresses"]))
    if op == "rewrite":
        return Rewrite(d["address"], d["text"])
    if op == "append":
        return Append(d["text"])
    raise ValueError(f"unknown op {op!r}")


# ---------------------------------------------------------- envelope body


def parse_envelope(raw: str) -> ParsedEdit:
    """Parse one complete envelope ``<ctx> ... </ctx>``."""
    if not (raw.startswith(T.CTX_OPEN) and raw.endswith(T.CTX_CLOSE)):
        return Malformed(raw, "unterminated")
    body = T.split_tokens(raw[len(T.CTX_OPEN):len(raw) - len(T.CTX_CLOSE)])
    # Whitespace between tokens carries no meaning; drop it.
    parts = [p for p in body if T.is_nce_token(p) or p.strip()]
    if not parts or parts[0] not in T.OPERATORS:
        return Malformed(raw, "missing_operator")
    op, rest = parts[0], parts[1:]

    if op == T.OP_DROP:
        addrs, i = _take_addresses(rest)
        if addrs is None:
            return Malformed(raw, "bad_address")
        if not addrs:
            return Malformed(raw, "missing_address")
        if i != len(rest):
            return Malformed(raw, "unexpected_content")
        return Drop(tuple(addrs))

    if op == T.OP_REWRITE:
        addrs, i = _take_addresses(rest[:2])
        if addrs is None or len(addrs) != 1:
            return Malformed(raw, "missing_address" if not rest or not T.is_hi(rest[0])
                             else "bad_address")
        text = _plain_text(rest[2:])
        if text is None:
            return Malformed(raw, "token_in_text")
        if not text:
            return Malformed(raw, "empty_text")
        return Rewrite(addrs[0], text)

    text = _plain_text(rest)  # append
    if text is None:
        return Malformed(raw, "token_in_text")
    if not text:
        return Malformed(raw, "empty_text")
    return Append(text)


def _take_addresses(parts: List[str]) -> Tuple[Optional[List[int]], int]:
    """Read leading address pairs. Returns (None, i) on a broken pair."""
    out, i = [], 0
    while i < len(parts) and T.is_hi(parts[i]):
        if i + 1 >= len(parts) or not T.is_lo(parts[i + 1]):
            return None, i
        out.append(T.decode_address(parts[i], parts[i + 1]))
        i += 2
    if i < len(parts) and T.is_lo(parts[i]):
        return None, i
    return out, i


def _plain_text(parts: List[str]) -> Optional[str]:
    if any(T.is_nce_token(p) for p in parts):
        return None
    return "".join(parts).strip()


# ----------------------------------------------------------- whole outputs


@dataclass
class TextChunk:
    text: str


@dataclass
class EnvelopeDone:
    edit: ParsedEdit
    raw: str


Event = Union[TextChunk, EnvelopeDone]


class StreamParser:
    """Incremental parser for a model output.

    ``feed(chunk)`` returns the events that are complete so far: runs of
    ordinary text (:class:`TextChunk`) and finished envelopes
    (:class:`EnvelopeDone`). Text that could still turn into a token, such as
    a trailing ``"<sid_h"``, is held back until the next chunk decides it.
    ``close()`` flushes the rest. An envelope still open at ``close()`` is
    reported as :class:`Malformed` (reason ``unterminated``). NCE tokens
    outside any envelope are discarded and counted in ``stray_tokens``.
    """

    def __init__(self) -> None:
        self._buf = ""
        self._env: Optional[str] = None  # raw text of the open envelope
        self.stray_tokens = 0

    def feed(self, chunk: str) -> List[Event]:
        self._buf += chunk
        return self._drain(final=False)

    def close(self) -> List[Event]:
        events = self._drain(final=True)
        if self._env is not None:
            events.append(EnvelopeDone(Malformed(self._env, "unterminated"), self._env))
            self._env = None
        return events

    def _drain(self, final: bool) -> List[Event]:
        events: List[Event] = []
        while True:
            m = T.TOKEN_RE.search(self._buf)
            if m is None:
                keep = 0 if final else _partial_token_suffix(self._buf)
                cut = len(self._buf) - keep
                self._emit_text(self._buf[:cut], events)
                self._buf = self._buf[cut:]
                return events
            self._emit_text(self._buf[:m.start()], events)
            tok = m.group()
            self._buf = self._buf[m.end():]
            if tok == T.CTX_OPEN:
                if self._env is not None:  # an envelope opened inside another
                    events.append(EnvelopeDone(Malformed(self._env, "unterminated"), self._env))
                self._env = tok
            elif self._env is not None:
                self._env += tok
                if tok == T.CTX_CLOSE:
                    events.append(EnvelopeDone(parse_envelope(self._env), self._env))
                    self._env = None
            else:
                self.stray_tokens += 1

    def _emit_text(self, text: str, events: List[Event]) -> None:
        if not text:
            return
        if self._env is not None:
            self._env += text
        elif events and isinstance(events[-1], TextChunk):
            events[-1].text += text
        else:
            events.append(TextChunk(text))


def _partial_token_suffix(buf: str) -> int:
    """Length of the longest suffix of ``buf`` that is a proper token prefix."""
    start = max(0, len(buf) - T.MAX_TOKEN_LEN + 1)
    for i in range(start, len(buf)):
        if buf[i] == "<":
            tail = buf[i:]
            if any(t.startswith(tail) for t in T.NCE_TOKENS):
                return len(buf) - i
    return 0


@dataclass
class ParsedOutput:
    """A model output split into its visible text and its edits."""
    edits: List[ParsedEdit] = field(default_factory=list)
    raws: List[str] = field(default_factory=list)  # envelope text as written, one per edit
    text_pieces: List[str] = field(default_factory=list)
    stray_tokens: int = 0

    @property
    def action_text(self) -> str:
        """What enters the action history: the rationale and the action.

        Text pieces between envelopes are stripped and joined by a newline;
        empty pieces vanish.
        """
        return join_pieces(self.text_pieces)

    @property
    def well_formed(self) -> List[Edit]:
        return [e for e in self.edits if not isinstance(e, Malformed)]


def join_pieces(pieces: List[str]) -> str:
    return "\n".join(p.strip() for p in pieces if p.strip())


def parse_output(output: str) -> ParsedOutput:
    parser = StreamParser()
    events = parser.feed(output) + parser.close()
    return collect(events, parser.stray_tokens)


def collect(events: List[Event], stray_tokens: int = 0) -> ParsedOutput:
    out = ParsedOutput(stray_tokens=stray_tokens)
    after_text = False  # the previous event was text: merge into its piece
    for ev in events:
        if isinstance(ev, TextChunk):
            if after_text:
                out.text_pieces[-1] += ev.text
            else:
                out.text_pieces.append(ev.text)
            after_text = True
        else:
            out.edits.append(ev.edit)
            out.raws.append(ev.raw)
            after_text = False
    return out
