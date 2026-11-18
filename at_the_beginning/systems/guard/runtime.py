"""The guard book of a services object (shared by the runner, the affordance engine and the guard pass, like the other books)."""
from __future__ import annotations

from .book import GuardBook


def of(services) -> GuardBook:
    book = services.__dict__.get("_guard_book")
    if book is None:
        book = services.__dict__["_guard_book"] = GuardBook()
    return book
