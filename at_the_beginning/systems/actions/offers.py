"""Open trade offers between residents (``offer_trade`` / ``accept_trade``).

An offer is a short-lived, non-saved promise: ``giver`` gives ``give`` x ``give_qty`` for ``want`` x ``want_qty`` from ``taker``. It lives on the
services object the runner and the affordance engine share (``offers_of(services)``), so the legality predicate ``offer_open`` and the action see
the same book. Nothing is reserved: both packs are checked again when the offer is accepted (the Transfers are atomic and conservation-checked).
"""
from __future__ import annotations

OFFER_TTL_TICKS = 60            # an unanswered offer lapses after this many ticks
FAIRNESS = 0.9                  # rules: accept when the value received is at least this share of the value given up


class OfferBook:
    def __init__(self):
        self._offers: dict = {}
        self._next = 1

    def open(self, giver: str, taker: str, give: str, give_qty: int, want: str, want_qty: int, tick: int) -> str:
        offer_id = f"offer_{self._next:05d}"
        self._next += 1
        self._offers[offer_id] = {"id": offer_id, "giver": giver, "taker": taker, "give": give, "give_qty": int(give_qty),
                                  "want": want, "want_qty": int(want_qty), "tick": int(tick), "expires": int(tick) + OFFER_TTL_TICKS}
        return offer_id

    def get(self, offer_id: str, tick: int | None = None):
        offer = self._offers.get(offer_id)
        if offer is None or (tick is not None and tick >= offer["expires"]):
            return None
        return offer

    def close(self, offer_id: str) -> None:
        self._offers.pop(offer_id, None)

    def open_for(self, taker: str, tick: int) -> list:
        return [o for o in self._offers.values() if o["taker"] == taker and tick < o["expires"]]

    def __len__(self) -> int:
        return len(self._offers)


def offers_of(services) -> OfferBook:
    """The offer book of a services object (created on first use; synthetic and engine services alike)."""
    book = services.__dict__.get("_offer_book")
    if book is None:
        book = services.__dict__["_offer_book"] = OfferBook()
    return book


def item_value(kind: str) -> float:
    from systems.inventory.schema import item_kind_def
    return float(item_kind_def(kind).get("value", 1.0))
