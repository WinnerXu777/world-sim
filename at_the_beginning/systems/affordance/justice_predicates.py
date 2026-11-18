"""Legality of the justice verbs ``report_theft`` and ``levy_damages`` (``EDEN_JUSTICE=1``; flag off: ``not_wired`` and no candidates). Imported at the end of ``predicates.py``."""
from __future__ import annotations

from . import config
from .predicates import Verdict, _alive, _nearest_neighbours, _positive_int, _target, no, verb, yes


def _flag_off():
    from systems.justice import enabled
    return None if enabled() else no("not_wired", why="EDEN_JUSTICE is off")


def _docket(S):
    from systems.justice import runtime
    return runtime.of(S.services)


# -- report_theft (a knower tells an authority; the ladder's report errand makes the call, the mask lists no candidates) -----------------------------
@verb("report_theft", "can_report_theft", lambda S: [])
def report_theft(S, target: str = "", about: str = "", item: str = "", qty: int = 1, victim: str = "") -> Verdict:
    dead = _alive(S) or _flag_off()
    if dead:
        return dead
    bad = _positive_int(qty, "qty")
    if bad:
        return bad
    if not all(isinstance(v, str) for v in (about, item, victim)) or not about or not item:
        return no("invalid_params", field="about/item")
    if about == S.actor or about == target:
        return no("invalid_params", field="about")
    n, problem = _target(S, target)
    if problem:
        return problem
    record = S.services.record(S.actor) or {}
    tags = ((record.get("relationships") or {}).get(about) or {}).get("tags") or []
    if "thief" not in tags:
        return no("no_grievance", about=about)                          # a resident only reports someone it holds as a thief
    reach = S.interact(n.x, n.y)
    return yes(distance=reach.distance) if reach.ok else Verdict(False, reach.reason, {"target": target}, "", reach.distance)


# -- levy_damages (the authority's own verb) ----------------------------------------------------------------------------------------------------
def _candidates_levy(S):
    from systems.justice import enabled
    if not enabled() or not S.obs.alive:
        return []
    cases = _docket(S).open_cases(S.actor)
    near = {n.id for n in _nearest_neighbours(S) if n.dist <= config.RADIUS["interact"]}
    return [{"target": c.thief} for c in cases if c.thief in near and S.obs.tick < c.expires]


@verb("levy_damages", "can_levy", _candidates_levy)
def levy_damages(S, target: str = "") -> Verdict:
    dead = _alive(S) or _flag_off()
    if dead:
        return dead
    from systems.actions.offers import item_value
    from systems.justice import law
    n, problem = _target(S, target)
    if problem:
        return problem
    if not law.is_authority(S.services.record(S.actor) or {}):
        return no("not_authority")
    case = _docket(S).for_authority(S.actor, target, S.obs.tick)
    if case is None:
        return no("no_case", target=target)
    reach = S.interact(n.x, n.y)
    if not reach.ok:
        return Verdict(False, reach.reason, {"target": target}, "", reach.distance)
    owed = law.damages(case.value)
    taken = law.levy(S.services.inventory(target), case.item, owed, item_value, config.EDIBLE_ITEMS)
    fitted = []
    for kind, qty in taken:                                              # the victim may not have room for all of it
        room = S.world.items.room(case.victim, kind)
        qty = qty if room is None else min(qty, int(room))
        if qty > 0:
            fitted.append((kind, qty))
    value = sum(item_value(k) * q for k, q in fitted)
    outcome = "paid" if value + 1e-9 >= owed else ("part_paid" if fitted else "nothing_to_levy")
    return yes({"case": {"id": case.id, "victim": case.victim, "thief": case.thief}, "levy": fitted, "outcome": outcome, "owed": owed}, distance=reach.distance)
