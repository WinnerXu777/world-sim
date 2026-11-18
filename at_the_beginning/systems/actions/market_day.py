"""The market's daily pass (``EDEN_MARKET=1``), called from ``AgentDriver.step``: fold the day into the scarcity factors, let each stall's keeper reprice.

Once per game day (``gameclock.DAY_TICKS``): the stalls' stock and the settlement's food nodes (a share of what stands in the nodes counts as daily outside supply, so a
blight or a drought that empties the nodes raises prices through the same formula as demand does) go into ``MarketBook.daily_update``. A **keeper** is a resident whose roster
record binds ``stall`` to a stall entity id; it sets the ask for each item on the shelf from the default ask and its own temperament (``greed`` raises it, ``mercy`` lowers
it), through the ``set_price`` verb, so the bounds and the audit apply. A keeper away from the stall gets an errand to walk there first (the ladder's errand machinery).
Runtime state only; with the flag off nothing here runs.
"""
from __future__ import annotations

import math
import os
from collections import Counter

from .gameclock import day_of

NODE_SUPPLY_SHARE = 0.1        # share of the food standing in the nodes that counts as one day's outside supply
KEEPER_SWING = 0.5             # how far temperament moves the keeper's ask from the default (greed 1.0, mercy 0.0 -> +25 %)
TILL_FLOAT = 2                # retain coin for stall purchases; surplus can fund the keeper's wages


def balance_enabled() -> bool:
    return os.environ.get("EDEN_ECONOMY_BALANCE", "") == "1"


def _collect_till(driver, engine, runner, human_id, fact, tick):
    """Move earned surplus through the existing checked verb, preserving the till float.

    One daily attempt, following the same bounded errand path as repricing. No
    inventory creation and no interference with an existing labour/needs errand.
    """
    if not balance_enabled() or human_id in driver.ladder.errands:
        return
    qty = max(0, int(runner.services.inventory(fact.id).get("coin", 0)) - TILL_FLOAT)
    room = runner.world.items.room(human_id, "coin")
    if room is not None:
        qty = min(qty, int(room))
    if qty <= 0:
        return
    params = {"container": fact.id, "item": "coin", "qty": qty}
    result = runner.run(human_id, "fetch_item", params, proposer="rules:shopkeeper")
    driver.routed[f"market.collect_till:{'ok' if result.ok else result.code}"] += 1
    if not result.ok and result.code in ("illegal:out_of_range", "illegal:blocked"):
        _walk_to_stall(driver, engine, human_id, fact, params, tick, verb="fetch_item")


def keeper_markup(traits: dict) -> float:
    t = lambda name: float(traits.get(name, 0.5))  # noqa: E731
    return 1.0 + KEEPER_SWING * ((t("greed") - 0.5) * 0.6 - (t("mercy") - 0.5) * 0.4)


from .dormancy_gate import asleep


def _stalls(runner) -> list:
    from systems.affordance import config
    from systems.market import runtime
    return [f for f in runner.services.entities() if f.kind in config.STORAGE_KINDS and f.alive and runtime.is_stall(runner.services, f.id)]


def outside_supply(runner) -> dict:
    """Food units standing in the settlement's resource nodes, as a daily supply per inventory kind (empty when the node tables are absent)."""
    import genesis_config as cfg
    from systems.map import resources as map_resources
    if not map_resources.enabled():
        return {}
    try:
        table = runner.world.table("entities")
        m, col = table.tensor, table.columns
        types, kind, stock = m[:, col["type"]], m[:, col["node_kind"]].long(), m[:, col["food"]] + m[:, col["node_stock"]]
    except (KeyError, AttributeError):
        return {}
    by_kind = {number: name for name, number in map_resources.NODE_KIND_IDS.items()}
    out = Counter()
    for s in (types == float(cfg.M_RESOURCE_NODE)).nonzero(as_tuple=False).flatten().tolist():
        name = by_kind.get(int(kind[s]))
        if name in map_resources.EDIBLE:
            out[map_resources.ITEM[name]] += float(stock[s]) * NODE_SUPPLY_SHARE
    return dict(out)


def step(driver, engine, tick: int) -> None:
    from systems.market import enabled, runtime
    if not enabled():
        return
    runner = driver.runner(engine)
    book = runtime.of(runner.services)
    day = day_of(tick)
    if book.last_day is not None and book.last_day >= day:
        return
    stalls = _stalls(runner)
    for fact in stalls:
        book.stall(fact.id)
    stock = Counter()
    for fact in stalls:
        for kind, q in runner.services.inventory(fact.id).items():
            if kind != "coin":
                stock[kind] += q
    changed = book.daily_update(day, dict(stock), outside_supply(runner))
    if changed:
        driver.market_log.append({"day": day, "tick": int(tick), "changed": {k: list(v) for k, v in sorted(changed.items())}})
    _keepers(driver, engine, runner, book, stalls, tick)


def _keepers(driver, engine, runner, book, stalls, tick: int) -> None:
    import genesis_config as cfg
    from systems.market.book import default_ask
    from systems.personality.assign import get_personality_traits
    from systems.roster.driver import roster_of
    by_stall = {f.id: f for f in stalls}
    for human_id in [u for u in engine._human_uid_by_slot if u]:
        roster, resident = roster_of(engine, human_id)
        stall_id = (roster or {}).get("stall")
        if stall_id not in by_stall:
            continue
        slot = engine._human_slot_for_id(human_id)
        if slot is None or slot < 0 or float(engine.state.h_tensor[slot, cfg.HP]) <= 0 or asleep(engine, human_id):
            continue
        traits = get_personality_traits((resident or {}).get("personality"))
        markup = keeper_markup(traits)
        _collect_till(driver, engine, runner, human_id, by_stall[stall_id], tick)
        for item, q in sorted(runner.services.inventory(stall_id).items()):
            if item == "coin" or q <= 0:
                continue
            lo, hi = book.bounds(item)
            want = max(lo, min(hi, int(math.ceil(default_ask(book.value(item), book.f(item)) * markup - 1e-9))))
            if want == book.ask(stall_id, item):
                continue
            params = {"container": stall_id, "item": item, "price": want}
            result = runner.run(human_id, "set_price", params, proposer="rules:shopkeeper")
            driver.routed[f"market.set_price:{'ok' if result.ok else result.code}"] += 1
            if not result.ok:
                if result.code in ("illegal:out_of_range", "illegal:blocked"):
                    _walk_to_stall(driver, engine, human_id, by_stall[stall_id], params, tick)
                break


def _walk_to_stall(driver, engine, human_id: str, fact, params: dict, tick: int, verb="set_price") -> None:
    from .ladder import ERRAND_TTL, Errand
    ladder = driver.ladder
    if human_id in ladder.errands:
        return
    rung = "till" if verb == "fetch_item" else "reprice"
    ladder.errands[human_id] = Errand(rung, "fetch", ladder.stand_point(engine, fact.x, fact.y), fact.id, verb, params, tick + ERRAND_TTL)
    ladder.note(tick, human_id, rung, "walk", "errand", target=fact.id, purpose=rung)
