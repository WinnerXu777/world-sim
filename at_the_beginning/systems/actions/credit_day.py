"""The credit pass (``EDEN_CREDIT=1``), called from ``AgentDriver.step`` every ``CREDIT_PERIOD`` ticks: repayment errands, overdue notes, defaults.

* **Repayment.** A borrower who holds enough to clear the debt (the item lent first, else coin), is not hungry, and has a conscience (``ladder.conscience`` above ``MIN_CONSCIENCE``)
  goes to the lender and pays (the ladder's ``repay`` errand follows the lender; ``Ladder.repay`` runs the ``pay_debt`` verb on arrival). A resident without a conscience does not pay
  until forced, which is how a loan goes bad.
* **Overdue / default.** Past its due tick the lender notes it (closeness down a little, once); one grace period later the loan is in default: closeness down a lot, the ``defaulter``
  tag on the lender's relation (``respond_to_loan`` refuses it), an event for the ledger. Runtime state only.
"""
from __future__ import annotations

from .dormancy_gate import asleep

CREDIT_PERIOD = 100
MIN_CONSCIENCE = -0.1
REPAY_MAX_HUNGER = 50.0
OVERDUE_CLOSENESS = -0.05
DEFAULT_CLOSENESS = -0.30


def _alive(engine, human_id: str) -> bool:
    import genesis_config as cfg
    slot = engine._human_slot_for_id(human_id)
    return slot is not None and slot >= 0 and float(engine.state.h_tensor[slot, cfg.HP]) > 0


def _nudge(engine, owner: str, other: str, delta: float, tick: int) -> None:
    existing = ((engine.resident_store.get(owner) or {}).get("relationships") or {}).get(other) or {}
    engine.resident_store.update_relationship(owner, other, str(existing.get("kind") or "known"), float(delta), tick)


def _tag(engine, owner: str, other: str, tag: str) -> None:
    relation = ((engine.resident_store.get(owner) or {}).get("relationships") or {}).get(other)
    if relation is not None and tag not in (relation.get("tags") or []):
        relation["tags"] = list(relation.get("tags") or []) + [tag]
        engine.resident_store.touch_resident(owner)


def step(driver, engine, tick: int) -> None:
    from systems.credit import enabled, runtime
    if not enabled() or tick % CREDIT_PERIOD != 0:
        return
    from .gameclock import day_ticks
    runner = driver.runner(engine)
    book = runtime.of(runner.services)
    if not book.loans:
        return
    late, gone = book.overdue(tick, day_ticks())
    for loan in late:
        loan.noted_overdue = True
        book.counts["overdue"] += 1
        _nudge(engine, loan.lender, loan.borrower, OVERDUE_CLOSENESS, tick)
        runner.world.events.emit("loan_overdue", actors=(loan.lender, loan.borrower), visibility="private", payload={"loan": loan.id, "item": loan.item, "qty": loan.qty})
        book.note(tick, "overdue", loan)
    for loan in gone:
        book.default(loan, tick)
        _nudge(engine, loan.lender, loan.borrower, DEFAULT_CLOSENESS, tick)
        _tag(engine, loan.lender, loan.borrower, "defaulter")
        runner.world.events.emit("loan_defaulted", actors=(loan.lender, loan.borrower), visibility="private", payload={"loan": loan.id, "item": loan.item, "qty": loan.qty})
    _repayments(driver, engine, runner, book, tick)


def _repayments(driver, engine, runner, book, tick: int) -> None:
    import genesis_config as cfg
    from systems.personality.assign import get_personality_traits
    from .ladder import conscience
    for loan in list(book.loans.values()):
        if loan.status != "open" or loan.borrower in driver.ladder.errands:
            continue
        borrower = loan.borrower
        if not _alive(engine, borrower) or not _alive(engine, loan.lender) or asleep(engine, borrower) or asleep(engine, loan.lender):
            continue
        slot = engine._human_slot_for_id(borrower)
        if float(engine.state.h_tensor[slot, cfg.HUNGER]) >= REPAY_MAX_HUNGER:
            continue
        record = engine.resident_store.get(borrower) or {}
        if conscience(get_personality_traits(record.get("personality"))) <= MIN_CONSCIENCE:
            continue
        pack = runner.services.inventory(borrower)
        if not any(pack.get(k, 0) >= book.units_needed(loan, k) for k in (loan.item, "coin")):
            continue
        driver.ladder.start_repay(driver, engine, runner, borrower, loan, tick)
