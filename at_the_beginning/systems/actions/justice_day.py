"""The justice pass (``EDEN_JUSTICE=1``, needs ``EDEN_REPUTATION``), called from ``AgentDriver.step`` every ``JUSTICE_PERIOD`` ticks.

* **Reports.** A theft whose culprit is known (``reputation``: discovered, ``culprit_known``) and not yet reported is reported by its victim (else the first knower) to the nearest
  authority, unless the reporter's temperament is to retaliate. The reporter walks to the authority (the ladder's ``report`` errand follows them) and calls ``report_theft``; the
  authority answers by rules and a yes opens a case.
* **Enforcement.** An authority with an open case goes to the thief (the ``enforce`` errand follows the thief) and calls ``levy_damages`` when it stands by them.
* **Lapse.** A case nobody could serve within ``CASE_TTL_DAYS`` game days lapses. Runtime state only; no authority in the village means the pass does nothing.
"""
from __future__ import annotations

from .dormancy_gate import asleep

JUSTICE_PERIOD = 100


def _alive(engine, human_id: str) -> bool:
    import genesis_config as cfg
    slot = engine._human_slot_for_id(human_id)
    return slot is not None and slot >= 0 and float(engine.state.h_tensor[slot, cfg.HP]) > 0 and not asleep(engine, human_id)      # a dormant resident is not available either


def authorities(engine) -> list:
    """Alive residents who hold authority (``law.is_authority``), in slot order."""
    from systems.justice import law
    return [h for h in engine._human_uid_by_slot if h and law.is_authority(engine.resident_store.get(h) or {}) and _alive(engine, h)]


def _distance(engine, a: str, b: str) -> float:
    import math
    import genesis_config as cfg
    h = engine.state.h_tensor
    sa, sb = engine._human_slot_for_id(a), engine._human_slot_for_id(b)
    return math.hypot(float(h[sa, cfg.X]) - float(h[sb, cfg.X]), float(h[sa, cfg.Y]) - float(h[sb, cfg.Y]))


def step(driver, engine, tick: int) -> None:
    from systems.justice import enabled, runtime
    if not enabled() or tick % JUSTICE_PERIOD != 0:
        return
    runner = driver.runner(engine)
    docket = runtime.of(runner.services)
    for case in docket.lapse(tick):
        runner.world.events.emit("case_lapsed", actors=(case.authority, case.thief), visibility="private", payload={"case": case.id})
    judges = authorities(engine)
    if not judges:
        return
    _reports(driver, engine, runner, docket, judges, tick)
    _enforcement(driver, engine, runner, docket, tick)


def _reports(driver, engine, runner, docket, judges: list, tick: int) -> None:
    from . import reputation
    state = reputation.of(engine)
    for theft in state.thefts:
        if not theft.discovered or not theft.culprit_known or theft.restituted or theft.event_id in docket.reported:
            continue
        victims = [m for m in ([theft.owner] if theft.owner_kind == "resident" else []) + list(theft.knowers) if m != theft.thief and _alive(engine, m)]
        reporter = next((m for m in victims if m not in driver.ladder.errands), None)
        if reporter is None or not _alive(engine, theft.thief):
            continue
        if reputation.response_of(reputation._traits(engine, reporter)) == "retaliate":
            continue
        judge = min((j for j in judges if j not in (reporter, theft.thief)), key=lambda j: _distance(engine, reporter, j), default=None)
        if judge is None:
            continue
        docket.reported.add(theft.event_id)
        driver.ladder.start_report(driver, engine, runner, reporter, judge, theft, tick)


def _enforcement(driver, engine, runner, docket, tick: int) -> None:
    for case in docket.open_cases():
        if case.authority in driver.ladder.errands or not _alive(engine, case.authority) or not _alive(engine, case.thief):
            continue
        driver.ladder.start_enforce(driver, engine, runner, case, tick)
