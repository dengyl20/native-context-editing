"""Context state ``S_t = (B_t, A_t)`` in interaction order.

A state is one ordered list of items. Blocks carry an address and text;
actions are the agent's earlier outputs with their envelopes removed;
reminders are transient runtime messages. ``Render`` walks this list, so
blocks and actions interleave exactly as they arrived.

Addresses come from an :class:`AddressPool` that only counts upward: a
dropped address is retired for good and never names another block.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Set, Union

from .tokens import ADDR_CAPACITY

ROLES = ("system", "user", "tool", "note")


class AddressExhausted(Exception):
    pass


@dataclass
class Block:
    address: int
    role: str                       # system | user | tool | note
    text: str
    tool_name: Optional[str] = None
    locked: bool = False
    history: List[str] = field(default_factory=list)  # earlier texts, oldest first
    meta: Dict = field(default_factory=dict)           # free slot for callers

    def to_json(self) -> dict:
        d = {"type": "block", "address": self.address, "role": self.role, "text": self.text}
        if self.tool_name is not None:
            d["tool_name"] = self.tool_name
        if self.locked:
            d["locked"] = True
        if self.history:
            d["history"] = list(self.history)
        return d


@dataclass
class Action:
    text: str

    def to_json(self) -> dict:
        return {"type": "action", "text": self.text}


@dataclass
class Reminder:
    level: str                      # soft | hard
    text: str

    def to_json(self) -> dict:
        return {"type": "reminder", "level": self.level, "text": self.text}


Item = Union[Block, Action, Reminder]


class AddressPool:
    """Hands out 0, 1, 2, ... and remembers which addresses were retired."""

    def __init__(self, next_address: int = 0, retired: Optional[Set[int]] = None):
        self.next_address = next_address
        self.retired: Set[int] = set(retired or ())

    def allocate(self) -> int:
        if self.next_address >= ADDR_CAPACITY:
            raise AddressExhausted(f"all {ADDR_CAPACITY} addresses are in use or retired")
        n = self.next_address
        self.next_address += 1
        return n

    def retire(self, n: int) -> None:
        self.retired.add(n)

    def was_issued(self, n: int) -> bool:
        return 0 <= n < self.next_address


class State:
    def __init__(self) -> None:
        self.items: List[Item] = []
        self.blocks: Dict[int, Block] = {}  # live blocks by address
        self.pool = AddressPool()

    # -- growth (the runtime's side of Eq. 1) ---------------------------------

    def add_block(self, role: str, text: str, *, tool_name: Optional[str] = None,
                  locked: bool = False, meta: Optional[dict] = None) -> Block:
        if role not in ROLES:
            raise ValueError(f"unknown role {role!r}")
        blk = Block(self.pool.allocate(), role, text, tool_name=tool_name,
                    locked=locked, meta=dict(meta or {}))
        self.items.append(blk)
        self.blocks[blk.address] = blk
        return blk

    def add_action(self, text: str) -> Action:
        act = Action(text)
        self.items.append(act)
        return act

    def add_reminder(self, level: str, text: str) -> Reminder:
        rem = Reminder(level, text)
        self.items.append(rem)
        return rem

    def clear_reminders(self) -> None:
        self.items = [it for it in self.items if not isinstance(it, Reminder)]

    # -- the three transitions (called by runtime.execute after its checks) ---

    def drop(self, address: int) -> None:
        blk = self.blocks.pop(address)
        self.items.remove(blk)
        self.pool.retire(address)

    def rewrite(self, address: int, text: str) -> None:
        blk = self.blocks[address]
        blk.history.append(blk.text)
        blk.text = text

    def append_note(self, text: str) -> Block:
        return self.add_block("note", text)

    # -- views ------------------------------------------------------------------

    def live_blocks(self) -> List[Block]:
        return [it for it in self.items if isinstance(it, Block)]

    def actions(self) -> List[Action]:
        return [it for it in self.items if isinstance(it, Action)]

    def reminders(self) -> List[Reminder]:
        return [it for it in self.items if isinstance(it, Reminder)]

    def __iter__(self) -> Iterator[Item]:
        return iter(self.items)

    # -- (de)serialization, used by the conformance fixtures --------------------

    def to_json(self) -> dict:
        return {
            "items": [it.to_json() for it in self.items],
            "retired": sorted(self.pool.retired),
            "next_address": self.pool.next_address,
        }

    @classmethod
    def from_json(cls, d: dict) -> "State":
        s = cls()
        for it in d.get("items", []):
            kind = it["type"]
            if kind == "block":
                blk = Block(it["address"], it["role"], it["text"],
                            tool_name=it.get("tool_name"), locked=it.get("locked", False),
                            history=list(it.get("history", [])))
                if blk.address in s.blocks:
                    raise ValueError(f"address {blk.address} appears twice")
                s.items.append(blk)
                s.blocks[blk.address] = blk
            elif kind == "action":
                s.items.append(Action(it["text"]))
            elif kind == "reminder":
                s.items.append(Reminder(it["level"], it["text"]))
            else:
                raise ValueError(f"unknown item type {kind!r}")
        used = set(s.blocks) | set(d.get("retired", []))
        s.pool = AddressPool(d.get("next_address", max(used, default=-1) + 1),
                             set(d.get("retired", [])))
        if any(a >= s.pool.next_address for a in used):
            raise ValueError("next_address must exceed every live or retired address")
        if set(s.blocks) & s.pool.retired:
            raise ValueError("a live block cannot carry a retired address")
        return s

    def copy(self) -> "State":
        return State.from_json(self.to_json())
