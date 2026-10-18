"""Native Context Editing (NCE): a reference implementation.

An agent edits its own context by writing edits in a small grammar of 70
dedicated tokens; a task-agnostic runtime executes them.
"""
from .tokens import (ADDR_CAPACITY, CTX_CLOSE, CTX_OPEN, LOCKED, NCE_TOKENS, OP_APPEND,
                     OP_DROP, OP_REWRITE, add_nce_tokens, check_tokenizer, decode_address,
                     encode_address)
from .grammar import (Append, Drop, Malformed, Rewrite, StreamParser, parse_envelope,
                      parse_output, serialize)
from .state import Action, Block, Reminder, State
from .render import (DEFAULT_FORMAT, ChatFormat, TraceWriter, approx_tokens, chip,
                     render_item, render_messages, render_text)
from .runtime import (REMINDER_TEXT, EditResult, ReminderPolicy, Runtime, StepResult,
                      apply_output, execute)

__version__ = "0.1.0"

__all__ = [
    # vocabulary
    "NCE_TOKENS", "ADDR_CAPACITY", "CTX_OPEN", "CTX_CLOSE", "LOCKED", "OP_APPEND",
    "OP_DROP", "OP_REWRITE", "encode_address", "decode_address", "add_nce_tokens",
    "check_tokenizer",
    # grammar
    "Append", "Drop", "Rewrite", "Malformed", "StreamParser", "parse_envelope",
    "parse_output", "serialize",
    # state
    "Action", "Block", "Reminder", "State",
    # rendering
    "ChatFormat", "DEFAULT_FORMAT", "TraceWriter", "approx_tokens", "chip",
    "render_item", "render_messages", "render_text",
    # runtime
    "REMINDER_TEXT", "EditResult", "ReminderPolicy", "Runtime", "StepResult",
    "apply_output", "execute",
]
