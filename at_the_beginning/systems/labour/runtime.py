"""The job book of a services object (shared by the runner and the affordance engine, like the offer, market and loan books)."""
from __future__ import annotations

from .book import JobBook


def of(services) -> JobBook:
    book = services.__dict__.get("_job_book")
    if book is None:
        from systems.actions.offers import item_value
        book = services.__dict__["_job_book"] = JobBook(item_value)
    return book
