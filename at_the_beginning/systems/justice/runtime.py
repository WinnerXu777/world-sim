"""The docket of a services object (shared by the runner and the affordance engine, like the other books)."""
from __future__ import annotations

from .docket import Docket


def of(services) -> Docket:
    book = services.__dict__.get("_docket")
    if book is None:
        book = services.__dict__["_docket"] = Docket()
    return book
