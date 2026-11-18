"""The market book of a services object, and what counts as a stall.

Like the offer book, the ``MarketBook`` lives on the services object the runner and the affordance engine share, so the legality predicates and the verbs
read the same prices. A **stall** is a storage entity that was registered with ``register_stall`` (scenario data, a settlement list) or whose id's local part
starts with ``market`` or ``stall`` (``town:market_1``, ``family:stall``): its goods and its till (coin) are the entity's inventory.
"""
from __future__ import annotations

from .book import MarketBook

STALL_PREFIXES = ("market", "stall")


def of(services) -> MarketBook:
    book = services.__dict__.get("_market_book")
    if book is None:
        from systems.actions.offers import item_value
        book = services.__dict__["_market_book"] = MarketBook(item_value)
    return book


def register_stall(services, entity_id: str):
    """Mark an existing storage entity as a stall (its household is the prefix of the id)."""
    return of(services).stall(entity_id)


def is_stall(services, entity_id: str) -> bool:
    if entity_id in of(services).stalls:
        return True
    local = str(entity_id or "").split(":", 1)[-1]
    return local.startswith(STALL_PREFIXES)


def owner_household(entity_id: str) -> str:
    return str(entity_id or "").split(":", 1)[0].removesuffix("_interior")
