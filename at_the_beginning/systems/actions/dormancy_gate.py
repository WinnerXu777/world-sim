"""Interim dormancy (``EDEN_WINDOW_DORMANCY``, harness plane, ``1008_dormancy_gap.md``) as the model plane sees it: a resident whose chunk is not integrated does nothing here either.

The predicate is the harness's: ``engine._dormant_h[slot]`` (a bool tensor refreshed at the start of every step; absent or all False with the flag off, so every function below is then a
no-op). While a resident is dormant the agent driver does not decide for it, walk it, start or advance a ladder errand, or apply an action for it, and the periodic passes (market keepers,
repayment, reports, enforcement) skip it. On the first tick it is awake again it is treated as newly arrived: the stale plan state is dropped (``wake``) and Tier 1 re-plans from where it is.
"""
from __future__ import annotations


def dormant(engine, slot) -> bool:
    mask = engine.__dict__.get("_dormant_h")
    if mask is None or slot is None or slot < 0 or slot >= len(mask):
        return False
    return bool(mask[slot])


def asleep(engine, human_id: str) -> bool:
    """True when this resident is dormant right now."""
    if engine.__dict__.get("_dormant_h") is None:
        return False
    return dormant(engine, engine._human_slot_for_id(human_id))


def filter_slots(driver, engine, slots: list) -> list:
    """The agent driver's roster slots minus the dormant ones; residents that just woke are reset."""
    mask = engine.__dict__.get("_dormant_h")
    if (mask is None or not bool(mask.any())) and not driver.dormant:
        return slots                                                      # the flag is off (or nobody is outside the frame): nothing to do, nothing changes
    awake, now_dormant = [], set()
    for slot in slots:
        human_id = engine._human_uid_by_slot[slot]
        if dormant(engine, slot):
            now_dormant.add(human_id)
        else:
            awake.append(slot)
    for human_id in sorted(driver.dormant - now_dormant):
        wake(driver, engine, human_id)
    for human_id in sorted(now_dormant - driver.dormant):
        driver.routed["dormancy.sleep"] += 1
    driver.dormant = now_dormant
    return awake


def wake(driver, engine, human_id: str) -> None:
    """Treat the resident as newly arrived: drop what it was doing (goal, errand, cached decision, movement plan); it re-plans from its actual position."""
    from systems.roster.driver import runtime
    driver.cache.pop(human_id, None)
    driver.last_goal.pop(human_id, None)
    driver.last_hp.pop(human_id, None)
    driver.task_seen.pop(human_id, None)
    driver.ladder.errands.pop(human_id, None)
    state = runtime(engine)
    for table in (state.mover.plans, state.mover.no_path):
        for key in [k for k in table if (k[1] if isinstance(k, tuple) else k) == human_id]:
            del table[key]
    driver.routed["dormancy.wake"] += 1
