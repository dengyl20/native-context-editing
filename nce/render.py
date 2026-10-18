"""``Render(S)``: the text the model reads.

Each block is written as its two address tokens, the lock marker if the
block is locked, and its text opened by a role tag. No closing token is
needed: the next address marks where a block ends. Actions are ordinary
assistant turns without an address. Reminders are transient user messages
without an address.

The role tags belong to the chat format of the base model. This module ships
a neutral :data:`DEFAULT_FORMAT`; subclass :class:`ChatFormat` to match a
real chat template. The conformance fixtures use the default format.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List

from . import tokens as T
from .state import Action, Block, Reminder, State


@dataclass(frozen=True)
class ChatFormat:
    role_tags: Dict[str, str] = field(default_factory=lambda: {
        "system": "<|system|>",
        "user": "<|user|>",
        "tool": "<|tool|>",
        "note": "<|note|>",
    })
    assistant_open: str = "<|assistant|>"
    assistant_close: str = "<|end|>"
    reminder_tag: str = "<|user|>"
    separator: str = "\n"  # written after every item

    def block_body(self, blk: Block) -> str:
        if blk.role == "tool" and blk.tool_name:
            return f"{blk.tool_name}\n{blk.text}"
        return blk.text

    def render_block(self, blk: Block) -> str:
        head = T.encode_address(blk.address) + (T.LOCKED if blk.locked else "")
        return head + self.role_tags[blk.role] + self.block_body(blk) + self.separator

    def render_action(self, act: Action) -> str:
        return self.assistant_open + act.text + self.assistant_close + self.separator

    def render_reminder(self, rem: Reminder) -> str:
        return self.reminder_tag + rem.text + self.separator


DEFAULT_FORMAT = ChatFormat()


def render_item(item, fmt: ChatFormat = DEFAULT_FORMAT) -> str:
    if isinstance(item, Block):
        return fmt.render_block(item)
    if isinstance(item, Action):
        return fmt.render_action(item)
    return fmt.render_reminder(item)


def render_text(state: State, fmt: ChatFormat = DEFAULT_FORMAT,
                add_generation_prompt: bool = False) -> str:
    out = "".join(render_item(it, fmt) for it in state)
    return out + (fmt.assistant_open if add_generation_prompt else "")


def render_messages(state: State) -> List[dict]:
    """Render to chat messages, for servers that apply their own template.

    Block content is prefixed with its address (and lock marker), so the
    addresses reach the model through any template that passes text through.
    Notes and reminders travel as user messages.
    """
    msgs: List[dict] = []
    for it in state:
        if isinstance(it, Block):
            head = T.encode_address(it.address) + (T.LOCKED if it.locked else "")
            role = {"note": "user"}.get(it.role, it.role)
            msg = {"role": role, "content": head + it.text}
            if it.role == "tool" and it.tool_name:
                msg["name"] = it.tool_name
            msgs.append(msg)
        elif isinstance(it, Action):
            msgs.append({"role": "assistant", "content": it.text})
        else:
            msgs.append({"role": "user", "content": it.text})
    return msgs


# ------------------------------------------------------------ token counting

_WORD_RE = re.compile(r"\w+|[^\w\s]")


def approx_tokens(text: str) -> int:
    """A dependency-free token estimate: each NCE token counts one, every
    word or punctuation mark counts one. Pass a real tokenizer's counter
    wherever exact numbers matter."""
    n = 0
    for piece in T.split_tokens(text):
        n += 1 if T.is_nce_token(piece) else len(_WORD_RE.findall(piece))
    return n


Counter = Callable[[str], int]


def hf_counter(tokenizer) -> Counter:
    """Wrap a Hugging Face tokenizer as a counter."""
    return lambda text: len(tokenizer.encode(text, add_special_tokens=False))


# ------------------------------------------------------- readable terminal

# The colour code of the paper's token chips, as 24-bit RGB. Blocks are tinted
# by role: the locked system prompt is ink, tool results are a cool grey-blue,
# notes are green, and an argument makes the tint stronger.
COLORS: Dict[str, str] = {
    "base": "#1C2230", "muted": "#5B6474", "line": "#E6E3DC", "paper": "#FBFAF7",
    "accent": "#24508A", "accent_bg": "#EDF3FB",
    "addr_fg": "#1C4A86", "addr_bg": "#DCE7F7",
    "envelope_fg": "#FFFFFF", "envelope_bg": "#3A4352",
    "drop_fg": "#A1282A", "drop_bg": "#F7D3D1",
    "rewrite_fg": "#7A4A00", "rewrite_bg": "#FAE1B0",
    "append_fg": "#2C6A3B", "append_bg": "#D6EDDA",
    "system_bg": "#E9E7E2", "task_fg": "#1C4A86", "task_bg": "#EDF3FB",
    "tool_fg": "#41536F", "tool_bg": "#EFF3F9",
    "note_fg": "#2C6A3B", "note_bg": "#FFFFFF", "note_on": "#2C6A3B",
    "keeper_fg": "#24508A", "keeper_bg": "#EDF3FB",
    "text_bg": None, "text_fg": "#1C4A86",
    "think_fg": "#5B6474", "good": "#2C6A3B", "bad": "#A1282A",
}

__all__ = ["COLORS", "ChatFormat", "Counter", "DEFAULT_FORMAT", "TraceWriter",
           "approx_tokens", "address_label", "chip", "chip_line", "hf_counter", "op_of",
           "paint", "render_item", "render_messages", "render_text", "strip_ansi",
           "terminal_width", "truncate_ansi", "wants_color", "wrap"]

OP_BG = {"drop": "drop_bg", "rewrite": "rewrite_bg", "append": "append_bg"}
OP_FG = {"drop": "drop_fg", "rewrite": "rewrite_fg", "append": "append_fg"}

_ANSI = {
    "reset": "\033[0m", "bold": "\033[1m", "dim": "\033[2m", "italic": "\033[3m",
}
_HEX = re.compile(r"^#([0-9A-Fa-f]{6})$")


def _rgb(name: str, *, background: bool = False) -> str:
    """ANSI escape for a palette entry; empty for ``None`` or an unknown name."""
    value = COLORS.get(name)
    if not value:
        return ""
    m = _HEX.match(value)
    if m is None:
        return ""
    r, g, b = (int(m.group(1)[i:i + 2], 16) for i in (0, 2, 4))
    return f"\033[{'48' if background else '38'};2;{r};{g};{b}m"


def paint(text: str, *, fg: Optional[str] = None, bg: Optional[str] = None,
          bold: bool = False, dim: bool = False, italic: bool = False) -> str:
    """Colour ``text`` with the palette. An unknown name contributes nothing,
    and text that ends up with no escape at all is returned unchanged."""
    if not text:
        return text
    codes = ([_ANSI["bold"]] if bold else []) + ([_ANSI["dim"]] if dim else []) \
        + ([_ANSI["italic"]] if italic else [])
    for name, is_bg in ((bg, True), (fg, False)):
        if not name:
            continue
        code = _rgb(name, background=is_bg)
        if code:  # a None or unknown entry contributes no colour
            codes.append(code)
    if not codes:
        return text
    return "".join(codes) + text + _ANSI["reset"]


def op_of(text: str) -> str:
    """The operator of an envelope, or ``""`` if it carries none."""
    for op, token in (("drop", T.OP_DROP), ("rewrite", T.OP_REWRITE), ("append", T.OP_APPEND)):
        if token in text:
            return op
    return ""


def chip(token: str, *, name: Optional[str] = None, color: bool = True) -> str:
    """One token as a chip in the paper's palette."""
    if name is None:
        if token in T.ADDR_HI or token in T.ADDR_LO:
            name = "addr"
        elif token in (T.CTX_OPEN, T.CTX_CLOSE, T.LOCKED):
            name = "envelope"
    if not color:
        return f" {token} "
    if name in OP_BG:
        return paint(f" {token} ", fg=OP_FG[name], bg=OP_BG[name], bold=True)
    if name == "addr":
        return paint(f" {token} ", fg="addr_fg", bg="addr_bg")
    return paint(f" {token} ", fg="envelope_fg", bg="envelope_bg", bold=True)


def chip_line(text: str, *, indent: str = "", color: bool = True) -> str:
    """Rewrite every NCE token in ``text`` as a chip."""
    return indent + "".join(chip(p, name=op_of(p), color=color) if T.is_nce_token(p) else p
                            for p in T.split_tokens(text))


def strip_ansi(text: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", text)


def truncate_ansi(text: str, width: int, tail: str = "…") -> str:
    """Cut coloured text to ``width`` visible characters."""
    if width <= 0:
        return ""
    if len(strip_ansi(text)) <= width:
        return text
    out, visible, i = [], 0, 0
    while i < len(text) and visible < width - len(tail):
        if text[i] == "\033":
            end = text.find("m", i)
            if end == -1:
                break
            i = end + 1
            continue
        run = ""
        while i < len(text) and text[i] != "\033":
            run += text[i]
            i += 1
        room = width - len(tail) - visible
        out.append(run[:room])
        visible += len(run[:room])
        if visible >= width - len(tail):
            break
    return "".join(out) + tail + (_ANSI["reset"] if "\033" in text else "")


def wrap(text: str, width: int, indent: str = "", first: Optional[str] = None) -> List[str]:
    """Wrap ``text`` on spaces. ``indent`` opens every line, ``first`` the first."""
    lines: List[str] = []
    for para in text.split("\n"):
        if not para:
            lines.append(first if lines == [] and first is not None else indent)
            continue
        cur = ""
        for word in para.split(" "):
            trial = word if not cur else cur + " " + word
            room = width - len(indent if lines else (first if first is not None else indent))
            if len(trial) > room and cur:
                lines.append((first if lines == [] and first is not None else indent) + cur)
                cur = word
            else:
                cur = trial
        lines.append((first if lines == [] and first is not None else indent) + cur)
    return lines or ([first] if first is not None else [indent])


def wants_color(stream=None) -> bool:
    """True when a terminal can take colour and NO_COLOR is unset.

    The convention is the one at no-color.org: any non-empty NO_COLOR means the
    caller does not want colour, whatever the terminal is.
    """
    import os
    import sys
    if os.environ.get("NO_COLOR"):
        return False
    stream = stream if stream is not None else sys.stdout
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):  # a closed or replaced stream
        return False


def terminal_width(fallback: int = 88) -> int:
    import shutil
    try:
        return max(48, shutil.get_terminal_size((fallback, 24)).columns)
    except OSError:  # pragma: no cover - a terminal is not always present
        return fallback


ROLE_TINT = {"system": "system_bg", "user": "task_bg", "task": "task_bg",
             "tool": "tool_bg", "note": "note_bg"}


class TraceWriter:
    """Renders a turn, its edits, and the state around them to readable text.

    Everything goes through the palette above, so the terminal view, the
    paper, and the project page agree on what each token means. Colours are
    emitted only when ``color`` is true; the class is otherwise a plain
    text formatter and its output survives a pipe into a file.
    """

    def __init__(self, color: bool = True, indent: str = "  ", width: Optional[int] = None):
        self.color = color
        self.indent = indent
        self.width = width or terminal_width()

    # -- primitives ------------------------------------------------------

    def _paint(self, text: str, **kw) -> str:
        """The one place colour is decided: everything else calls this."""
        if not self.color or not text:
            return text
        return paint(text, **kw)

    def rule(self, title: str = "") -> str:
        bar = "─" * max(4, self.width - 6)
        if not title:
            return self._paint(bar, fg="line", dim=True)
        return (self._paint(title.upper(), fg="accent", bold=True) + " "
                + self._paint(bar[:max(4, self.width - 8 - len(title))], fg="line", dim=True))

    def section(self, title: str) -> str:
        return "\n" + self.rule(title)

    def tokens(self, text: str) -> str:
        """A model output with every NCE token drawn as a chip."""
        return self.chip_line(text, indent="")

    def chip_line(self, text: str, indent: Optional[str] = None) -> str:
        """A whole line with its NCE tokens drawn as chips."""
        out = []
        for piece in T.split_tokens(text):
            if T.is_nce_token(piece):
                out.append(chip(piece, name=op_of(piece), color=self.color))
            else:
                out.append(self._paint(piece, fg="base"))
        return (self.indent if indent is None else indent) + "".join(out)

    def envelope(self, raw: str) -> str:
        return self.chip_line(raw)

    def block_line(self, record, address: Optional[int] = None, note: str = "",
                   body_chars: int = 96) -> str:
        """One line of a block table: address, role, and a preview of the text.

        ``record`` is anything with ``address``, ``role``, ``text`` and an
        optional ``locked``; a block from the state or a callback-free record
        from the annotation pipeline both work.
        """
        n = record.address if address is None else address
        mark = f" {T.LOCKED}" if getattr(record, "locked", False) else ""
        head = (chip(T.encode_address(n), name="addr") if self.color
                else address_label(n)) + (mark if self.color else mark)
        text = " ".join(record.text.split())
        preview = text[:body_chars] + ("…" if len(text) > body_chars else "")
        role = self._paint(f"{record.role:6}", fg="muted")
        line = f"{self.indent}{head} {role}{preview}"
        if note:
            line += f"\n{self.indent}{' ' * 22}{self._paint(note, fg='muted', dim=True)}"
        return line


def address_label(n: int) -> str:
    """The address of block ``n`` as text, without colour."""
    return T.encode_address(n)
