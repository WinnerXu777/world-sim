"""The loan book: who owes whom what, and the arithmetic of terms and payments. Pure data, no engine.

A loan is denominated in the *value* of the item lent (``systems.inventory`` item values), so it can be paid back in the same item, another food or coin. Terms: a friend (closeness
>= ``FRIEND``) is lent at par; anyone else owes ``1 + STRANGER_INTEREST``. One open loan per borrower-lender pair. A loan falls due after ``TERM_DAYS`` game days; one more
``GRACE_DAYS`` and an unpaid loan is in default.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Optional

TERM_DAYS = 1.0
GRACE_DAYS = 1.0
FRIEND = 0.4
STRANGER_INTEREST = 0.25
KEEP = 1                       # a lender keeps at least this many units for itself
PAID_EPS = 1e-6


def owed_value(unit_value: float, qty: int, closeness: float) -> float:
    rate = 1.0 if closeness >= FRIEND else 1.0 + STRANGER_INTEREST
    return round(float(unit_value) * int(qty) * rate, 6)


@dataclass
class Loan:
    id: str
    lender: str
    borrower: str
    item: str
    qty: int
    owed: float                # value still to pay
    opened: int
    due: int
    status: str = "open"       # open | repaid | defaulted
    noted_overdue: bool = False
    paid: float = 0.0


class LoanBook:
    def __init__(self, value: Callable[[str], float]):
        self.value = value
        self.loans: dict = {}
        self.counts: Counter = Counter()
        self.log: list = []
        self._next = 1

    def open(self, lender: str, borrower: str, item: str, qty: int, closeness: float, tick: int, day_ticks: int) -> Loan:
        loan = Loan(f"loan_{self._next:05d}", lender, borrower, item, int(qty), owed_value(self.value(item), qty, closeness), int(tick), int(tick) + int(TERM_DAYS * day_ticks))
        self._next += 1
        self.loans[loan.id] = loan
        self.counts["opened"] += 1
        self.note(tick, "opened", loan)
        return loan

    def between(self, borrower: str, lender: str) -> Optional[Loan]:
        return next((l for l in self.loans.values() if l.status == "open" and l.borrower == borrower and l.lender == lender), None)

    def open_of(self, borrower: str) -> list:
        return [l for l in self.loans.values() if l.status == "open" and l.borrower == borrower]

    def defaulted(self, borrower: str, lender: str) -> bool:
        return any(l.status == "defaulted" and l.borrower == borrower and l.lender == lender for l in self.loans.values())

    def pay(self, loan_id: str, item: str, qty: int, tick: int) -> Optional[Loan]:
        loan = self.loans.get(loan_id)
        if loan is None or loan.status != "open":
            return None
        amount = self.value(item) * int(qty)
        loan.paid = round(loan.paid + amount, 6)
        loan.owed = round(loan.owed - amount, 6)
        if loan.owed <= PAID_EPS:
            loan.owed, loan.status = 0.0, "repaid"
            self.counts["repaid"] += 1
            self.note(tick, "repaid", loan)
        else:
            self.counts["part_paid"] += 1
        return loan

    def units_needed(self, loan: Loan, item: str) -> int:
        """Whole units of ``item`` that clear what is still owed."""
        import math
        return max(1, int(math.ceil(loan.owed / max(self.value(item), 1e-9) - PAID_EPS)))

    def overdue(self, tick: int, day_ticks: int) -> tuple:
        """``(newly overdue, newly in default)`` open loans at ``tick``."""
        late = [l for l in self.loans.values() if l.status == "open" and tick >= l.due and not l.noted_overdue]
        gone = [l for l in self.loans.values() if l.status == "open" and tick >= l.due + int(GRACE_DAYS * day_ticks)]
        return late, gone

    def default(self, loan: Loan, tick: int) -> None:
        loan.status = "defaulted"
        self.counts["defaulted"] += 1
        self.note(tick, "defaulted", loan)

    def note(self, tick: int, what: str, loan: Loan) -> None:
        if len(self.log) < 2000:
            self.log.append({"tick": int(tick), "what": what, "loan": loan.id, "lender": loan.lender, "borrower": loan.borrower, "item": loan.item, "qty": loan.qty,
                             "owed": loan.owed})
