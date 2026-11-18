"""Opt-in harvesting of existing, owned farm food; no changes to regrowth."""
import math

from .predicates import Verdict, _alive, no, verb, yes


def owned_farms(S, radius=220.0):
    from systems.actions.market_day import balance_enabled
    from systems.actions.ladder import household_of_entity, household_of_resident
    from systems.map import resources
    import genesis_config as cfg
    if not balance_enabled() or not resources.enabled() or not S.obs.alive:
        return []
    household = household_of_resident(((S.obs.record or {}).get("roster") or {}).get("key", ""))
    if not household:
        return []
    table = S.world.table("entities")
    out = []
    m, col = table.tensor, table.columns
    if not {"type", "food", "burning", "x", "y"} <= col.keys():
        return []
    distance = ((m[:, col["x"]] - S.obs.x) ** 2 + (m[:, col["y"]] - S.obs.y) ** 2).sqrt()
    mask = (m[:, col["type"]] == cfg.M_FARM) & (m[:, col["food"]] >= 1) & (m[:, col["burning"]] == 0) & (distance <= radius)
    for slot in mask.nonzero(as_tuple=False).flatten().tolist():
        uid = table.ids[slot]
        if not uid or household_of_entity(uid) != household:
            continue
        stock = int(table.get(uid, "food"))
        x, y = float(table.get(uid, "x")), float(table.get(uid, "y"))
        distance = math.hypot(x - S.obs.x, y - S.obs.y)
        if stock > 0 and distance <= radius:
            out.append((distance, uid, x, y, stock))
    return sorted(out)


def _candidates(S):
    return [{"farm": uid, "qty": 1} for _, uid, _, _, _ in owned_farms(S) if harvest_farm(S, uid, 1).ok]


@verb("harvest_farm", "can_harvest_farm", _candidates)
def harvest_farm(S, farm="", qty=1):
    from systems.actions.market_day import balance_enabled
    from systems.actions.ladder import household_of_entity, household_of_resident
    from systems.map import resources
    import genesis_config as cfg
    dead = _alive(S)
    if dead:
        return dead
    if not balance_enabled() or not resources.enabled():
        return no("not_wired")
    if not isinstance(farm, str) or not farm or type(qty) is not int or qty <= 0:
        return no("invalid_params")
    table = S.world.table("entities")
    if table.slot_of(farm) is None or int(table.get(farm, "type")) != cfg.M_FARM:
        return no("no_source")
    household = household_of_resident(((S.obs.record or {}).get("roster") or {}).get("key", ""))
    if not household or household_of_entity(farm) != household:
        return no("not_owner")
    fact = next((f for f in S.services.entities() if f.id == farm), None)
    if table.get(farm, "burning") > 0 or fact is None or not fact.alive:
        return no("no_source")
    if table.get(farm, "food") < qty:
        return no("no_item")
    reach = S.interact(float(table.get(farm, "x")), float(table.get(farm, "y")), farm, 16.0)
    if not reach.ok:
        return Verdict(False, reach.reason, {"farm": farm}, "", reach.distance)
    room = S.world.items.room(S.actor, "crop_bundle")
    if room is not None and room < qty:
        return no("no_room")
    return yes({"farm": farm, "qty": qty}, distance=reach.distance)
