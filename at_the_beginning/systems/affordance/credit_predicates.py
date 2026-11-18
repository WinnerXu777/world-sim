"""Legality of the credit verbs ``borrow_item``, ``lend_item`` and ``pay_debt`` (``EDEN_CREDIT=1``; flag off: ``not_wired`` and no candidates). Imported at the end of ``predicates.py``."""
from __future__ import annotations

from . import config
from .predicates import Verdict, _alive, _nearest_neighbours, _positive_int, _target, no, verb, yes


def _flag_off():
    from systems.credit import enabled
    return None if enabled() else no("not_wired", why="EDEN_CREDIT is off")


def _loans(S):
    from systems.credit import runtime
    return runtime.of(S.services)


# -- borrow_item --------------------------------------------------------------------------------------------------------------------
def _candidates_borrow(S):
    from systems.credit import enabled
    if not enabled() or not S.obs.alive or _loans(S).open_of(S.actor):
        return []
    return [{"target": n.id, "item": "", "qty": 1} for n in _nearest_neighbours(S) if n.dist <= config.RADIUS["interact"]]


@verb("borrow_item", "can_borrow", _candidates_borrow)
def borrow_item(S, target: str = "", item: str = "", qty: int = 1) -> Verdict:
    dead = _alive(S) or _flag_off()
    if dead:
        return dead
    bad = _positive_int(qty, "qty")
    if bad:
        return bad
    if not isinstance(item, str):
        return no("invalid_params", field="item")
    n, problem = _target(S, target)
    if problem:
        return problem
    if _loans(S).open_of(S.actor):
        return no("already_indebted")
    reach = S.interact(n.x, n.y)
    return yes(distance=reach.distance) if reach.ok else Verdict(False, reach.reason, {"target": target}, "", reach.distance)


# -- lend_item (called by the lender) ---------------------------------------------------------------------------------------------------
@verb("lend_item", "can_lend", lambda S: [])
def lend_item(S, target: str = "", item: str = "", qty: int = 1) -> Verdict:
    dead = _alive(S) or _flag_off()
    if dead:
        return dead
    bad = _positive_int(qty, "qty")
    if bad:
        return bad
    if not isinstance(item, str) or not item:
        return no("invalid_params", field="item")
    n, problem = _target(S, target)
    if problem:
        return problem
    if S.obs.inventory.get(item, 0) < qty:
        return no("no_item", item=item, have=S.obs.inventory.get(item, 0))
    if _loans(S).between(target, S.actor) is not None:
        return no("already_indebted", target=target)
    reach = S.interact(n.x, n.y)
    if not reach.ok:
        return Verdict(False, reach.reason, {"target": target}, "", reach.distance)
    room = S.world.items.room(target, item)
    if room is not None and room < qty:
        return no("no_room", target=target, item=item, room=room)
    return yes(distance=reach.distance)


# -- pay_debt -----------------------------------------------------------------------------------------------------------------------
def _candidates_pay(S):
    from systems.credit import enabled
    if not enabled() or not S.obs.alive:
        return []
    book, out = _loans(S), []
    near = {n.id for n in _nearest_neighbours(S) if n.dist <= config.RADIUS["interact"]}
    for loan in book.open_of(S.actor):
        if loan.lender not in near:
            continue
        for kind in sorted([loan.item, "coin"], key=lambda k: (S.obs.inventory.get(k, 0) <= 0, k)):
            have = S.obs.inventory.get(kind, 0)
            if have > 0:
                out.append({"target": loan.lender, "item": kind, "qty": min(have, book.units_needed(loan, kind))})
                break
    return out


@verb("pay_debt", "has_debt", _candidates_pay)
def pay_debt(S, target: str = "", item: str = "", qty: int = 1) -> Verdict:
    dead = _alive(S) or _flag_off()
    if dead:
        return dead
    bad = _positive_int(qty, "qty")
    if bad:
        return bad
    if not isinstance(item, str) or not item:
        return no("invalid_params", field="item")
    n, problem = _target(S, target)
    if problem:
        return problem
    loan = _loans(S).between(S.actor, target)
    if loan is None:
        return no("no_debt", target=target)
    if S.obs.inventory.get(item, 0) < qty:
        return no("no_item", item=item, have=S.obs.inventory.get(item, 0))
    reach = S.interact(n.x, n.y)
    if not reach.ok:
        return Verdict(False, reach.reason, {"target": target}, "", reach.distance)
    room = S.world.items.room(target, item)
    if room is not None and room < qty:
        return no("no_room", target=target, item=item, room=room)
    return yes({"loan": loan.id, "owed": loan.owed}, distance=reach.distance)
