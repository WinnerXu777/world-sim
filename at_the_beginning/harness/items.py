"""Item stores: where item quantities live, behind one small interface so ``Transfer`` can check conservation.

``DictItemStore`` is the synthetic implementation used by unit tests and tiny worlds. The Engine adapter supplies a store that
wraps the legacy inventory records (see ``adapter.py``); both satisfy the same duck-typed interface:

    quantity(owner, item) -> int          room(owner, item) -> int | None (None = unlimited)
    add(owner, item, qty) -> int added    remove(owner, item, qty) -> int removed
    total(item) -> int                    items() -> iterable of item names present
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Optional


class DictItemStore:
    def __init__(self, capacity_per_owner: Optional[int] = None):
        """``capacity_per_owner``: max total quantity (all items) one owner may hold; ``None`` = unlimited."""
        self._held: dict = defaultdict(lambda: defaultdict(int))
        self.capacity_per_owner = capacity_per_owner

    def quantity(self, owner, item: str) -> int:
        return self._held[owner][item] if owner in self._held else 0

    def held_total(self, owner) -> int:
        return sum(self._held[owner].values()) if owner in self._held else 0

    def room(self, owner, item: str) -> Optional[int]:
        if self.capacity_per_owner is None:
            return None
        return max(0, self.capacity_per_owner - self.held_total(owner))

    def add(self, owner, item: str, qty: int) -> int:
        room = self.room(owner, item)
        amount = qty if room is None else min(qty, room)
        if amount > 0:
            self._held[owner][item] += amount
        return max(0, amount)

    def remove(self, owner, item: str, qty: int) -> int:
        have = self.quantity(owner, item)
        amount = min(qty, have)
        if amount > 0:
            self._held[owner][item] -= amount
            if self._held[owner][item] == 0:
                del self._held[owner][item]
        return max(0, amount)

    def total(self, item: str) -> int:
        return sum(items.get(item, 0) for items in self._held.values())

    def items(self) -> Iterable[str]:
        return sorted({item for held in self._held.values() for item in held})

    def owners(self) -> list:
        return sorted((o for o, held in self._held.items() if held), key=str)
