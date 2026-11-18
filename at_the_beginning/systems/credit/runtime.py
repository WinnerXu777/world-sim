"""The loan book of a services object (shared by the runner and the affordance engine, like the offer book and the market book)."""
from __future__ import annotations

from .book import LoanBook


def of(services) -> LoanBook:
    book = services.__dict__.get("_loan_book")
    if book is None:
        from systems.actions.offers import item_value
        book = services.__dict__["_loan_book"] = LoanBook(item_value)
    return book
