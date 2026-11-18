"""Theft, reputation and the community's answer (``EDEN_REPUTATION=1``, default off). Design: ``1008_market_justice_design.md`` section 4.

A successful ``steal_when_safe`` calls ``record_theft`` (through the ``theft_consequence`` record op). From there everything is event-driven and
deterministic (every draw is ``world.rng(system, id)``, a pure function of seed, tick, system and id):

1. **Detection.** A victim resident notices at once with a probability that depends on its alertness (then it knows the culprit: the thief was in reach); otherwise, and for a
   container, the household finds the loss after a delay (120..360 ticks) and traces the culprit with probability ``0.35 + 0.4 * caution`` (a stand-in for tracks, a door seen
   open, who was around). A loss whose culprit is not found is still a ledger event (``loss_discovered``): no theft is silent.
2. **Consequences for each knower of a known culprit.** Closeness to the thief drops (more for a valuable item, less for a merciful knower), the relation gets the tag
   ``thief``, a memory note is written, and the knower picks a response by personality: ``avoid`` (passive: it refuses the thief), ``confront`` (a ``warn`` and a demand for
   restitution), ``retaliate`` (an intent is logged; violence is not built), or ``wary``.
3. **Gossip.** A knower tells friends in social range (``gossip``: they become witnesses of the same ledger event and their opinion of the thief moves), at most three tellings,
   300 ticks apart.
4. **Refusals.** A responder refuses a ``thief``-tagged requester or trader (``refuse_thief`` in ``verbs.economy``) and the ladder does not beg from one.
5. **Restitution and forgiveness.** A thief with a conscience above 0.1 that is no longer starving returns the item (errand to the victim, then ``give_item``); the victim's
   closeness recovers and the tag goes when it reaches 0. Without restitution the grudge decays toward 0 (faster for the merciful).

State is runtime only (``Reputation`` on the engine); the saved effects are relationships, memory notes and the ledger.
"""
from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from .gameclock import DAY_TICKS, day_ticks      # one game day in ticks (``day_ticks()`` follows the calendar flag)

ENV = "EDEN_REPUTATION"
DELAY_MIN, DELAY_SPAN = 120, 240
GOSSIP_GAP, GOSSIP_MAX = 300, 3
CONFRONT_GAP = 600
DECAY_PERIOD = DAY_TICKS // 4     # forgiveness steps four times a game day; the rates below are per step, so the half-life in game days does not depend on the day length (the legacy value; ``decay_period()`` is what the pass reads)
DECAY_RATE = {"merciful": 0.026, "other": 0.010}
OPINION_BASE, OPINION_PER_VALUE = 0.12, 0.02
RESTITUTION_MIN_CONSCIENCE = 0.1
RESTITUTION_MAX_HUNGER = 40.0
THIEF = "thief"


def enabled() -> bool:
    return os.environ.get(ENV, "") == "1"


@dataclass
class Theft:
    event_id: str
    thief: str
    owner_kind: str            # container | resident
    owner: str
    household: str
    item: str
    qty: int
    value: float
    tick: int
    discover_at: int
    culprit_known: bool
    discovered: bool = False
    knowers: list = field(default_factory=list)
    restituted: bool = False
    tellings: dict = field(default_factory=dict)     # knower -> (count, last tick)
    confronted: set = field(default_factory=set)
    violent: bool = False                            # EDEN_ROB: taken by force, face to face (the culprit is known at once)


@dataclass
class Reputation:
    thefts: list = field(default_factory=list)
    counts: Counter = field(default_factory=Counter)
    log: list = field(default_factory=list)
    last_decay: int = 0

    def note(self, tick: int, kind: str, **detail) -> None:
        self.counts[kind] += 1
        if len(self.log) < 4000:
            self.log.append({"tick": tick, "kind": kind, **detail})


def of(engine) -> Reputation:
    found = engine.__dict__.get("_reputation")
    if found is None:
        found = engine.__dict__["_reputation"] = Reputation()
    return found


# -- helpers ---------------------------------------------------------------------------------------------------------------------
def _traits(engine, human_id: str) -> dict:
    from systems.personality.assign import get_personality_traits
    return get_personality_traits(((engine.resident_store.get(human_id) or {}).get("personality")))


def _household_members(engine, household: str) -> list:
    from systems.actions.ladder import household_of_resident
    out = []
    for human_id in engine._human_uid_by_slot:
        if not human_id:
            continue
        roster = (engine.resident_store.get(human_id) or {}).get("roster") or {}
        if household_of_resident(roster.get("key", "")) == household and _alive(engine, human_id):
            out.append(human_id)
    return sorted(out)


def _alive(engine, human_id: str) -> bool:
    import genesis_config as cfg
    slot = engine._human_slot_for_id(human_id)
    return slot is not None and slot >= 0 and float(engine.state.h_tensor[slot, cfg.HP]) > 0


def _position(engine, human_id: str) -> tuple:
    import genesis_config as cfg
    slot = engine._human_slot_for_id(human_id)
    return float(engine.state.h_tensor[slot, cfg.X]), float(engine.state.h_tensor[slot, cfg.Y])


def _draw(world, system: str, entity: str) -> float:
    return float(world.rng(system, entity).random())


def tags_of(record: dict, other: str) -> list:
    return list(((record or {}).get("relationships") or {}).get(other, {}).get("tags") or [])


def refuses(record: Optional[dict], requester: str) -> bool:
    """A responder refuses a requester it holds as a thief (the tag is only ever set under ``EDEN_REPUTATION``)."""
    relation = ((record or {}).get("relationships") or {}).get(requester) or {}
    return THIEF in (relation.get("tags") or []) and float(relation.get("closeness", 0.0)) < 0.0


# -- a theft happened ------------------------------------------------------------------------------------------------------------
def record_theft(engine, world, thief: str, owner_kind: str, owner: str, item: str, qty: int, event_id: str, tick: int, violent: bool = False) -> dict:
    """Called by the ``theft_consequence`` record op right after the Transfer. Decides how the loss comes to light and schedules it."""
    from systems.actions.ladder import household_of_entity, household_of_resident
    from systems.actions.offers import item_value
    state = of(engine)
    if owner_kind == "resident":
        victim = owner
        roster = (engine.resident_store.get(victim) or {}).get("roster") or {}
        household = household_of_resident(roster.get("key", ""))
        caution = float(_traits(engine, victim).get("caution", 0.5))
        import genesis_config as cfg
        hunger = float(engine.state.h_tensor[engine._human_slot_for_id(victim), cfg.HUNGER])
        p_notice = max(0.0, min(1.0, 0.25 + 0.4 * (1.0 - hunger / 100.0) + 0.2 * caution))
        noticed = _draw(world, "theft_notice", victim) < p_notice
        discover_at = tick if noticed else tick + DELAY_MIN + int(_draw(world, "theft_delay", victim) * DELAY_SPAN)
        known = noticed
        if violent:                                       # EDEN_ROB: the victim was robbed to its face
            discover_at, known = tick, True
    else:
        household = household_of_entity(owner)
        members = _household_members(engine, household)
        discoverer = members[0] if members else ""
        caution = float(_traits(engine, discoverer).get("caution", 0.5)) if discoverer else 0.5
        discover_at = tick + DELAY_MIN + int(_draw(world, "theft_delay", owner) * DELAY_SPAN)
        known = _draw(world, "theft_trace", owner) < 0.35 + 0.4 * caution
    theft = Theft(event_id, thief, owner_kind, owner, household, item, int(qty), item_value(item) * int(qty), tick, discover_at, known, violent=bool(violent))
    state.thefts.append(theft)
    state.note(tick, "theft", thief=thief, owner=owner, item=item, qty=int(qty), discover_at=discover_at, culprit_known=known)
    return {"ok": True, "discover_at": discover_at, "culprit_known": known}


# -- the per-tick step -----------------------------------------------------------------------------------------------------------
def decay_period() -> int:
    """Forgiveness step: the module's legacy ``DECAY_PERIOD`` (a quarter of the 2400-tick day, or whatever a test sets) unless ``EDEN_CALENDAR=1``, then a quarter of the calendar day."""
    from harness import calendar
    return DECAY_PERIOD if not calendar.calendar_enabled() else day_ticks() // 4


def step(driver, engine, tick: int) -> None:
    state = of(engine)
    period = decay_period()
    if not state.thefts and tick - state.last_decay < period:
        return
    runner = driver.runner(engine)
    for theft in list(state.thefts):
        if not theft.discovered and tick >= theft.discover_at:
            _discover(engine, runner, state, theft, tick)
        if theft.discovered and theft.culprit_known:
            _respond(driver, engine, runner, state, theft, tick)
            _restitute(driver, engine, runner, state, theft, tick)
    if tick - state.last_decay >= period:
        state.last_decay = tick
        _decay(engine, state, tick)


def _discover(engine, runner, state: Reputation, theft: Theft, tick: int) -> None:
    theft.discovered = True
    if theft.owner_kind == "resident":
        members = [theft.owner] if _alive(engine, theft.owner) else []
    else:
        members = _household_members(engine, theft.household)
    world = runner.world
    actors = (members[0] if members else theft.owner, theft.owner) + ((theft.thief,) if theft.culprit_known else ())
    world.events.emit("loss_discovered", actors=tuple(dict.fromkeys(actors)), place=None, visibility="private", payload={
        "item": theft.item, "qty": theft.qty, "culprit_known": theft.culprit_known, "theft": theft.event_id}, witnesses=members)
    world.events.emit("theft", actors=(theft.thief, theft.owner), visibility="private", event_id=theft.event_id,
                      witnesses=members if theft.culprit_known else ())             # the household learns who (idempotent: adds witnesses)
    theft.knowers = list(members)
    state.note(tick, "discovered", thief=theft.thief, owner=theft.owner, culprit_known=theft.culprit_known, knowers=len(members))
    for member in members:
        engine.resident_store.record_event(
            member, tick, "robbed" if theft.culprit_known else "loss_noticed",
            note=(f"{theft.item} x{theft.qty} was taken from {theft.owner}" + (f" by {theft.thief}" if theft.culprit_known else "")),
            other_human_id=theft.thief if theft.culprit_known else None, extra={"about_event": theft.event_id})
        if theft.culprit_known:
            _opinion(engine, state, member, theft, tick)


def _opinion(engine, state: Reputation, knower: str, theft: Theft, tick: int) -> None:
    """The knower's closeness to the thief drops and the relation is tagged; the response is chosen by personality."""
    traits = _traits(engine, knower)
    delta = -(OPINION_BASE + OPINION_PER_VALUE * theft.value) * (1.0 - 0.5 * float(traits.get("mercy", 0.5)))
    if theft.violent:
        from systems.rob import OPINION_FACTOR
        delta *= OPINION_FACTOR
    record = engine.resident_store.get(knower)
    existing = ((record or {}).get("relationships") or {}).get(theft.thief) or {}
    engine.resident_store.update_relationship(knower, theft.thief, str(existing.get("kind") or "known"), delta, tick)
    relation = engine.resident_store.get(knower)["relationships"][theft.thief]
    if THIEF not in relation["tags"]:
        relation["tags"].append(THIEF)
    engine.resident_store.touch_resident(knower)
    state.note(tick, "opinion_drop", knower=knower, thief=theft.thief, delta=round(delta, 3), closeness=relation["closeness"], response=response_of(traits))


def response_of(traits: dict) -> str:
    t = lambda name: float(traits.get(name, 0.5))  # noqa: E731
    if t("vengefulness") > 0.7 and t("mercy") < 0.4:
        return "retaliate"
    if t("protectiveness") > 0.6 or t("pride") > 0.6:
        return "confront"
    if t("fearfulness") > 0.6 or t("caution") > 0.6:
        return "avoid"
    return "wary"


def _respond(driver, engine, runner, state: Reputation, theft: Theft, tick: int) -> None:
    """Gossip to friends, confront in person, log retaliation intent. Rate-limited, a few actions per tick at most."""
    for knower in theft.knowers:
        if not _alive(engine, knower) or knower == theft.thief:
            continue
        traits = _traits(engine, knower)
        kind = response_of(traits)
        count, last = theft.tellings.get(knower, (0, -10 ** 9))
        if count < GOSSIP_MAX and tick - last >= GOSSIP_GAP:
            for option in runner.aff.options(knower, verbs=("gossip",)):
                if option.params.get("about") != theft.thief:
                    continue
                relation = ((engine.resident_store.get(knower) or {}).get("relationships") or {}).get(option.params["target"], {})
                if float(relation.get("closeness", 0.0)) < -0.05:
                    continue
                result = runner.run(knower, "gossip", option.params, proposer="tier1:reputation")
                driver.routed[f"reputation.gossip:{'ok' if result.ok else result.code}"] += 1
                state.note(tick, "gossip", knower=knower, listener=option.params["target"], ok=result.ok, code=result.code)
                theft.tellings[knower] = (count + (1 if result.ok else 0), tick)
                if result.ok:
                    listener = option.params["target"]
                    if listener not in theft.knowers:
                        theft.knowers.append(listener)
                        engine.resident_store.record_event(listener, tick, "heard_theft", note=f"{knower} told me {theft.thief} took {theft.item}",
                                                           other_human_id=knower, extra={"about_event": theft.event_id})
                break
        if kind == "confront" and knower not in theft.confronted and tick - theft.tick >= CONFRONT_GAP // 3:
            for option in runner.aff.options(knower, verbs=("warn",)):
                if option.params.get("target") == theft.thief:
                    result = runner.run(knower, "warn", option.params, proposer="tier1:reputation")
                    driver.routed[f"reputation.confront:{'ok' if result.ok else result.code}"] += 1
                    state.note(tick, "confront", knower=knower, thief=theft.thief, ok=result.ok, code=result.code)
                    theft.confronted.add(knower)
                    break
        elif kind == "retaliate" and knower not in theft.confronted:
            theft.confronted.add(knower)
            state.note(tick, "retaliation_intent", knower=knower, thief=theft.thief)      # violence is not built: the intent is the record


def _restitute(driver, engine, runner, state: Reputation, theft: Theft, tick: int) -> None:
    """A thief with a conscience that is fed again walks to the victim and gives the item back."""
    import genesis_config as cfg
    from systems.actions.ladder import Errand
    from systems.actions import ladder as ladder_module
    if not ladder_module.enabled() or theft.restituted or not _alive(engine, theft.thief) or theft.thief in driver.ladder.errands:
        return
    traits = _traits(engine, theft.thief)
    from systems.actions.ladder import conscience
    if conscience(traits) <= RESTITUTION_MIN_CONSCIENCE:
        return
    slot = engine._human_slot_for_id(theft.thief)
    if float(engine.state.h_tensor[slot, cfg.HUNGER]) >= RESTITUTION_MAX_HUNGER:
        return
    pack = runner.services.inventory(theft.thief)
    item = theft.item if pack.get(theft.item, 0) >= 1 else next((k for k in ("rations", "crop_bundle", "fish_catch", "berries", "mushrooms") if pack.get(k, 0) >= 1), "")
    if not item:
        return
    victims = [m for m in theft.knowers if m != theft.thief and _alive(engine, m)]
    if not victims:
        return
    victim = victims[0]
    driver.ladder.errands[theft.thief] = Errand("restitution", "restitution", _position(engine, victim), victim, "give_item",
                                                {"target": victim, "item": item, "qty": min(theft.qty, pack.get(item, 1))}, tick + 1500)
    driver.ladder.note(tick, theft.thief, "restitution", "walk", "errand", target=victim)


def restituted(engine, thief: str, victim: str, tick: int) -> None:
    """The thief gave something back: the victim's closeness recovers and, at 0 or above, the tag goes."""
    state = of(engine)
    record = engine.resident_store.get(victim) or {}
    relation = (record.get("relationships") or {}).get(thief)
    if relation is None:
        return
    engine.resident_store.update_relationship(victim, thief, str(relation.get("kind") or "known"), 0.15, tick)
    relation = engine.resident_store.get(victim)["relationships"][thief]
    if float(relation["closeness"]) >= 0.0 and THIEF in relation["tags"]:
        relation["tags"].remove(THIEF)
    engine.resident_store.touch_resident(victim)
    for theft in state.thefts:
        if theft.thief == thief and not theft.restituted and victim in theft.knowers:
            theft.restituted = True
    state.note(tick, "restitution", thief=thief, victim=victim, closeness=relation["closeness"], tag_removed=THIEF not in relation["tags"])


def _decay(engine, state: Reputation, tick: int) -> None:
    """Forgiveness over time: hostile closeness to a thief moves toward 0, faster for the merciful; at 0 the tag goes."""
    for human_id in engine._human_uid_by_slot:
        record = engine.resident_store.get(human_id) if human_id else None
        if not record:
            continue
        mercy = float(_traits(engine, human_id).get("mercy", 0.5))
        for other, relation in (record.get("relationships") or {}).items():
            if THIEF not in (relation.get("tags") or []):
                continue
            if float(relation.get("closeness", 0.0)) >= 0.0:      # befriended again by other means: the tag ends with the grudge (design 4.2), it must not linger
                relation["tags"].remove(THIEF)
                state.note(tick, "forgiven", knower=human_id, thief=other)
                engine.resident_store.touch_resident(human_id)
                continue
            rate = DECAY_RATE["merciful"] if mercy >= 0.5 else DECAY_RATE["other"]
            relation["closeness"] = round(min(0.0, float(relation["closeness"]) * (1.0 - rate)), 6)    # 6 places: at 3 a small grudge rounded back to itself and was never forgiven
            if relation["closeness"] > -0.01:
                relation["closeness"] = 0.0
                relation["tags"].remove(THIEF)
                state.note(tick, "forgiven", knower=human_id, thief=other)
            engine.resident_store.touch_resident(human_id)
