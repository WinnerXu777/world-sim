"""The care pass (``EDEN_TEMPERATURE=1`` and / or ``EDEN_WOUNDS=1``, needs ``EDEN_AGENT_ACTIONS``), called from ``AgentDriver.step`` every ``CARE_PERIOD`` ticks (``1008_actions.md`` section 10.21).

By rules, for a free, alive, awake resident (no errand): a wound is dressed first, its own and then a wounded neighbour's it holds at least ``KIN`` dear (or any wounded neighbour when it is an
authority); a resident that feels the cold (``cold >= COLD_FIRE`` degrees) and carries wood lights a fire where it stands when none burns near. Both go through the ordinary verbs (``treat_wound``,
``light_fire``), so the legality checks, the risk gate and the audit are the same as for a model's call. At most ``MAX_PER_PASS`` acts a pass.
"""
from __future__ import annotations

from .dormancy_gate import asleep

CARE_PERIOD = 10
MAX_PER_PASS = 6
COLD_FIRE = 6.0               # degrees under the comfort band before a resident burns its wood
KIN = 0.3


def _slot(engine, human_id: str):
    slot = engine._human_slot_for_id(human_id)
    return slot if slot is not None and slot >= 0 else None


def step(driver, engine, tick: int) -> None:
    from harness import temperature, wounds
    warm, hurt = temperature.enabled(), wounds.enabled()
    if (not warm and not hurt) or tick % CARE_PERIOD:
        return
    import genesis_config as cfg
    runner = driver.runner(engine)
    if "light_fire" not in runner.registry.actions and "treat_wound" not in runner.registry.actions:
        return
    h = engine.state.h_tensor
    acted = 0
    for human_id in engine._human_uid_by_slot:
        if acted >= MAX_PER_PASS:
            return
        slot = _slot(engine, human_id) if human_id else None
        if slot is None or float(h[slot, cfg.HP]) <= 0 or human_id in driver.ladder.errands or asleep(engine, human_id):
            continue
        held = runner.services.inventory(human_id)
        if hurt and any(held.get(kind, 0) for kind in ("bandage", "herb_bundle")):
            target = _wounded(engine, runner, driver, human_id)
            if target is not None:
                result = runner.run(human_id, "treat_wound", {} if target == human_id else {"target": target}, proposer="rules")
                acted += 1
                driver.ladder.note(tick, human_id, "care", "treat_wound", "ok" if result.ok else result.code, target=target)
                continue
        if warm and held.get("wood_bundle", 0) and temperature.cold_of(engine, slot) >= COLD_FIRE:
            result = runner.run(human_id, "light_fire", {}, proposer="rules")
            if result.ok:
                acted += 1
                driver.ladder.note(tick, human_id, "care", "light_fire", "ok")


def _wounded(engine, runner, driver, human_id: str):
    """Who to dress: oneself first, then the nearest wounded neighbour in reach that is held dear (or any, for an authority)."""
    from harness import wounds
    from . import guard_day
    from systems.affordance import config
    if wounds.wounded_of(engine, human_id):
        return human_id
    from systems.justice import law
    authority = law.is_authority(engine.resident_store.get(human_id) or {})
    best = None
    for other in engine._human_uid_by_slot:
        if not other or other == human_id or not wounds.wounded_of(engine, other) or _slot(engine, other) is None:
            continue
        distance = guard_day._distance(engine, human_id, other)
        if distance > config.RADIUS["interact"] or not (authority or guard_day._closeness(engine, human_id, other) >= guard_day._kin_closeness(engine, human_id, KIN)):
            continue
        if best is None or (distance, other) < best[:2]:
            best = (distance, other)
    return None if best is None else best[1]
