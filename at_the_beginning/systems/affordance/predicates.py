"""Legality predicates: one per verb, pure functions of a ``Situation`` and the call's parameters, returning a ``Verdict``.

The affordance engine enumerates candidate parameter sets with ``candidates`` and judges each with the verb's predicate; the action
runner calls the same predicate again at apply time, so "can this happen" has exactly one answer. A predicate validates *all* of
its parameters (an id the actor does not perceive, a quantity of zero, a wrong type), which is what makes a hallucinated
argument a rejection instead of an effect.

Each verb is declared once with ``@verb(id, predicate_id=...)``; ``VERBS`` maps id -> ``VerbDef`` (predicate + candidate generator).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Optional

from . import config
from .verdicts import Verdict, no, yes

VERBS: dict = {}


@dataclass(frozen=True)
class VerbDef:
    id: str
    predicate_id: str
    check: Callable            # (S, **params) -> Verdict
    candidates: Callable       # (S) -> list[dict]


def verb(verb_id: str, predicate_id: str, candidates: Callable = lambda S: [{}]):
    def wrap(fn):
        VERBS[verb_id] = VerbDef(verb_id, predicate_id, fn, candidates)
        return fn
    return wrap


class Situation:
    """One resident's observation plus the tools predicates need (world, services, reachability). Built once per resident per query."""

    def __init__(self, world, services, reach, obs, exact: bool = True):
        self.world, self.services, self.reach, self.obs = world, services, reach, obs
        self.exact = exact          # False: only "reachable or not" is needed (the mask), so a connected-component answer is enough

    @property
    def actor(self) -> str:
        return self.obs.actor

    def walk_to(self, x: float, y: float, entity: Optional[str] = None) -> Verdict:
        """Can the actor walk to this point (or to the nearest standable point beside ``entity``)?"""
        result = self.reach.check(self.obs.pos, (x, y), goal_entity=entity, need_length=self.exact)
        if not result.ok:
            return Verdict(False, result.reason or "unreachable", {}, result.mode)
        return yes(reachability=result.mode, distance=result.length)

    def interact(self, x: float, y: float, entity: Optional[str] = None, radius: Optional[float] = None) -> Verdict:
        """Range plus clear line (``systems.commission.access.interaction_ok``): the standard check for an immediate interaction."""
        from systems.commission.access import interaction_ok
        boxes = self.services.interaction_boxes(entity)
        r = interaction_ok(self.obs.pos, (x, y), radius if radius is not None else config.RADIUS["interact"], boxes)
        return yes(distance=r["distance"]) if r["ok"] else Verdict(False, r["reason"], {}, "", r["distance"])


def _alive(S) -> Optional[Verdict]:
    return None if S.obs.alive else no("dead")


def _target(S, target, *, radius: Optional[float] = None):
    """``(Neighbour, None)`` for a perceived, living, other resident, else ``(None, Verdict)`` with the reason."""
    if not isinstance(target, str) or not target:
        return None, no("invalid_params", field="target")
    if target == S.actor:
        return None, no("self_target")
    n = S.obs.neighbour(target)
    if n is None:
        return None, no("no_target", target=target)
    if not n.alive:
        return None, no("target_dead", target=target)
    if radius is not None and n.dist > radius:
        return None, no("out_of_range", distance=round(n.dist, 2))
    return n, None


def _positive_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return no("invalid_params", field=name)
    return None


def _nearest_neighbours(S, limit=6):
    return [n for n in S.obs.neighbours if n.alive][:limit]


# -- survival ---------------------------------------------------------------------------------------------------------
def _food_places(S) -> list:
    out = []
    site = S.obs.sites.get("food")
    if site is not None:
        out.append(("site", site.id, site.x, site.y, None))
    for fact in S.services.typed_resources("food", S.obs.x, S.obs.y, config.RADIUS["resource"]):
        out.append(("entity", fact.id, fact.x, fact.y, fact.id))
    return out


def _water_places(S) -> list:
    out = []
    site = S.obs.sites.get("water")
    if site is not None:
        out.append(("site", site.id, site.x, site.y, None))
    for fact in S.services.typed_resources("water", S.obs.x, S.obs.y, config.RADIUS["resource"]):
        out.append(("entity", fact.id, fact.x, fact.y, fact.id))
    return out


def _candidates_eat(S):
    if not S.obs.alive:
        return []
    out = [{"item": k} for k in config.EDIBLE_ITEMS if S.obs.inventory.get(k, 0) >= 1]
    out += [{"place": place[1]} for place in _food_places(S)]
    return out


@verb("eat", "can_eat", _candidates_eat)
def can_eat(S, item: str = "", place: str = "") -> Verdict:
    dead = _alive(S)
    if dead:
        return dead
    if S.obs.hunger < config.NEED_MIN:
        return no("not_needed", hunger=round(S.obs.hunger, 1))
    if item:
        if item not in config.EDIBLE_ITEMS:
            return no("invalid_params", field="item", allowed=list(config.EDIBLE_ITEMS))
        return yes({"source": "pack", "item": item}) if S.obs.inventory.get(item, 0) >= 1 else no("no_item", item=item)
    if not place:
        for k in config.EDIBLE_ITEMS:
            if S.obs.inventory.get(k, 0) >= 1:
                return yes({"source": "pack", "item": k})
    last = None
    for kind, pid, x, y, entity in _food_places(S):
        if place and pid != place:
            continue
        walk = S.walk_to(x, y, entity)
        if walk.ok:
            return Verdict(True, "", {"source": kind, "place": pid}, walk.reachability, walk.distance)
        last = walk
    if last is not None:
        return last
    return no("invalid_params", field="place") if place else no("no_edible")


def _candidates_drink(S):
    return [{"place": p[1]} for p in _water_places(S)] if S.obs.alive else []


@verb("drink", "can_drink", _candidates_drink)
def can_drink(S, place: str = "") -> Verdict:
    dead = _alive(S)
    if dead:
        return dead
    if S.obs.thirst < config.NEED_MIN:
        return no("not_needed", thirst=round(S.obs.thirst, 1))
    last = None
    for kind, pid, x, y, entity in _water_places(S):
        if place and pid != place:
            continue
        walk = S.walk_to(x, y, entity)
        if walk.ok:
            return Verdict(True, "", {"source": kind, "place": pid}, walk.reachability, walk.distance)
        last = walk
    if last is not None:
        return last
    return no("invalid_params", field="place") if place else no("no_source")


@verb("rest", "can_rest")
def can_rest(S) -> Verdict:
    dead = _alive(S)
    if dead:
        return dead
    deficit = max(100.0 - S.obs.stamina, 100.0 - S.obs.hp)
    return yes({"deficit": round(deficit, 1)}) if deficit >= config.REST_MIN_DEFICIT else no("not_needed", deficit=round(deficit, 1))


def _shelter_places(S) -> list:
    """Known safe places: the roster sleep/home anchors (remembered), then beds the resident sees. (id, x, y, entity id or None)."""
    out, seen = [], set()
    for key in ("sleep", "home"):
        a = S.obs.anchors.get(key)
        if a is not None and a.id not in seen:
            seen.add(a.id)
            out.append((a.id, a.x, a.y, None))
    for e in S.obs.entities:
        if e.fact.kind in config.BED_KINDS and e.fact.alive and e.dist <= config.RADIUS["safe"] and e.fact.id not in seen:
            seen.add(e.fact.id)
            out.append((e.fact.id, e.fact.x, e.fact.y, e.fact.id))
    return out


def _first_reachable(S, places, wanted: str = "") -> Verdict:
    last = None
    for pid, x, y, entity in places:
        if wanted and pid != wanted:
            continue
        walk = S.walk_to(x, y, entity)
        if walk.ok:
            return Verdict(True, "", {"place": pid}, walk.reachability, walk.distance)
        last = walk
    if wanted and last is None:
        return no("invalid_params", field="place")
    return last if last is not None else no("no_site")


def _candidates_shelter(S):
    return [{"place": p[0]} for p in _shelter_places(S)] if S.obs.alive else []


@verb("sleep", "can_sleep", _candidates_shelter)
def can_sleep(S, place: str = "") -> Verdict:
    dead = _alive(S)
    if dead:
        return dead
    if S.obs.threat >= config.THREAT_BLOCKS_SLEEP:
        return no("threatened", threat=round(S.obs.threat, 1))
    return _first_reachable(S, _shelter_places(S), place)


@verb("seek_shelter", "shelter_reachable", _candidates_shelter)
def seek_shelter(S, place: str = "") -> Verdict:
    dead = _alive(S)
    if dead:
        return dead
    return _first_reachable(S, _shelter_places(S), place)


@verb("hide", "can_hide", _candidates_shelter)
def can_hide(S, place: str = "") -> Verdict:
    return seek_shelter(S, place)


@verb("flee_to", "can_flee", _candidates_shelter)
def can_flee(S, place: str = "", **_unused) -> Verdict:
    return seek_shelter(S, place)


# -- work -------------------------------------------------------------------------------------------------------------
def _work_anchor(S):
    return S.obs.anchors.get("work")


def _candidates_go_to_work(S):
    a = _work_anchor(S)
    return [{"place": a.id}] if S.obs.alive and a is not None else []


@verb("go_to_work", "has_work_anchor", _candidates_go_to_work)
def go_to_work(S, place: str = "") -> Verdict:
    dead = _alive(S)
    if dead:
        return dead
    a = _work_anchor(S)
    if a is None:
        return no("no_anchor", key="work")
    if place and place != a.id:
        return no("invalid_params", field="place")
    here = math.hypot(a.x - S.obs.x, a.y - S.obs.y)
    if here <= config.AT_WORK_TOLERANCE:
        return no("already_there", distance=round(here, 2))
    walk = S.walk_to(a.x, a.y)
    return Verdict(True, "", {"place": a.id}, walk.reachability, walk.distance) if walk.ok else walk


@verb("work_shift", "can_work")
def work_shift(S) -> Verdict:
    dead = _alive(S)
    if dead:
        return dead
    a = _work_anchor(S)
    if a is None:
        return no("no_anchor", key="work")
    if not S.obs.occupation or S.obs.occupation == "none":
        return no("wrong_occupation")
    here = math.hypot(a.x - S.obs.x, a.y - S.obs.y)
    if here > config.AT_WORK_TOLERANCE:
        return no("out_of_range", distance=round(here, 2), needed=config.AT_WORK_TOLERANCE)
    return yes({"occupation": S.obs.occupation, "place": a.id}, distance=here)


def _candidates_gather(S):
    if not S.obs.alive:
        return []
    return [{"source": e.fact.id} for e in S.obs.entities if e.fact.kind in config.GATHER_NODES and e.fact.alive
            and e.dist <= config.RADIUS["resource"]]


@verb("gather_resource", "resource_reachable", _candidates_gather)
def gather_resource(S, source: str = "", qty: int = 1) -> Verdict:
    dead = _alive(S)
    if dead:
        return dead
    bad = _positive_int(qty, "qty")
    if bad:
        return bad
    if not isinstance(source, str) or not source:
        return no("invalid_params", field="source")
    e = S.obs.entity(source)
    if e is None or e.fact.kind not in config.GATHER_NODES:
        return no("no_source", source=source)
    if not e.fact.alive:
        return no("no_source", source=source, why="depleted")
    if e.dist > config.RADIUS["resource"]:
        return no("out_of_range", distance=round(e.dist, 2))
    walk = S.walk_to(e.fact.x, e.fact.y, e.fact.id)
    if not walk.ok:
        return walk
    return Verdict(True, "", {"item": config.GATHER_NODES[e.fact.kind]}, walk.reachability, walk.distance)


# -- crafting, storage ------------------------------------------------------------------------------------------------
def _recipes_for(S) -> list:
    from systems.crafting.resolver import crafting_recipe_ids, crafting_recipe_occupation_tags
    return [r for r in crafting_recipe_ids() if S.obs.occupation and S.obs.occupation in crafting_recipe_occupation_tags(r)]


def _candidates_craft(S):
    return [{"recipe": r} for r in _recipes_for(S)] if S.obs.alive else []


@verb("craft", "recipe_craftable", _candidates_craft)
def craft(S, recipe: str = "", qty: int = 1) -> Verdict:
    from systems.crafting.resolver import (crafting_output_kind, crafting_recipe_def, crafting_recipe_ids, crafting_recipe_ingredients,
                                           crafting_recipe_occupation_tags, crafting_recipe_required_tool_tags,
                                           crafting_recipe_station_kind)
    dead = _alive(S)
    if dead:
        return dead
    bad = _positive_int(qty, "qty")
    if bad:
        return bad
    if recipe not in crafting_recipe_ids():
        return no("no_recipe", recipe=str(recipe))
    if S.obs.occupation not in crafting_recipe_occupation_tags(recipe):
        return no("wrong_occupation", occupation=S.obs.occupation)
    missing = [{"item": i["item_kind"], "missing": int(i.get("quantity", 1)) * qty - S.obs.inventory.get(i["item_kind"], 0)}
               for i in crafting_recipe_ingredients(recipe) if S.obs.inventory.get(i["item_kind"], 0) < int(i.get("quantity", 1)) * qty]
    if missing:
        return no("missing_ingredients", missing=missing)
    lacking = [t for t in crafting_recipe_required_tool_tags(recipe) if S.obs.inventory.get(t, 0) < 1]
    if lacking:
        return no("missing_tool", tools=lacking)
    station = crafting_recipe_station_kind(recipe)
    if station and station != "none":
        near = [e for e in S.obs.entities if e.fact.kind == station and e.fact.alive]
        if not near:
            return no("no_station", station=station)
        reach = S.interact(near[0].fact.x, near[0].fact.y, near[0].fact.id, near[0].fact.interact_radius)
        if not reach.ok:
            return no("no_station", station=station, why=reach.reason, distance=round(near[0].dist, 2))
    output = crafting_output_kind(recipe)
    quantity = int(crafting_recipe_def(recipe).get("output_quantity", 1)) * qty
    room = S.world.items.room(S.actor, output)
    if room is not None and room < quantity:
        return no("no_room", item=output, room=room)
    return yes({"output": output, "quantity": quantity})


def _storage_near(S):
    return [e for e in S.obs.entities if e.fact.kind in config.STORAGE_KINDS and e.fact.alive
            and e.dist <= max(e.fact.interact_radius, config.RADIUS["interact"])]


def _candidates_store(S):
    if not S.obs.alive:
        return []
    items = sorted(k for k, q in S.obs.inventory.items() if q > 0 and k != "coin")
    return [{"item": k, "container": e.fact.id} for e in _storage_near(S) for k in items]


@verb("store_item", "storage_reachable", _candidates_store)
def store_item(S, item: str = "", qty: int = 1, container: str = "") -> Verdict:
    dead = _alive(S)
    if dead:
        return dead
    bad = _positive_int(qty, "qty")
    if bad:
        return bad
    if S.obs.inventory.get(item, 0) < qty:
        return no("no_item", item=str(item))
    e = S.obs.entity(container)
    if e is None or e.fact.kind not in config.STORAGE_KINDS or not e.fact.alive:
        return no("no_target", container=str(container))
    reach = S.interact(e.fact.x, e.fact.y, e.fact.id, e.fact.interact_radius)
    return yes(distance=reach.distance) if reach.ok else Verdict(False, reach.reason, {"container": container}, "", reach.distance)


def _candidates_fetch(S):
    if not S.obs.alive:
        return []
    out = []
    for e in _storage_near(S):
        for kind, q in sorted(S.services.inventory(e.fact.id).items()):
            if q > 0:
                out.append({"item": kind, "container": e.fact.id})
    return out


@verb("fetch_item", "item_in_storage", _candidates_fetch)
def fetch_item(S, item: str = "", qty: int = 1, container: str = "") -> Verdict:
    dead = _alive(S)
    if dead:
        return dead
    bad = _positive_int(qty, "qty")
    if bad:
        return bad
    e = S.obs.entity(container)
    if e is None or e.fact.kind not in config.STORAGE_KINDS or not e.fact.alive:
        return no("no_target", container=str(container))
    if S.services.inventory(e.fact.id).get(item, 0) < qty:
        return no("no_item", item=str(item), container=container)
    reach = S.interact(e.fact.x, e.fact.y, e.fact.id, e.fact.interact_radius)
    if not reach.ok:
        return Verdict(False, reach.reason, {"container": container}, "", reach.distance)
    room = S.world.items.room(S.actor, item)
    if room is not None and room < qty:
        return no("no_room", item=item, room=room)
    return yes(distance=reach.distance)


# -- economy ----------------------------------------------------------------------------------------------------------
def _candidates_give(S):
    if not S.obs.alive:
        return []
    items = sorted(k for k, q in S.obs.inventory.items() if q > 0)
    return [{"target": n.id, "item": k, "qty": 1} for n in _nearest_neighbours(S) if n.dist <= config.RADIUS["interact"] for k in items]


@verb("give_item", "can_give", _candidates_give)
def give_item(S, target: str = "", item: str = "", qty: int = 1) -> Verdict:
    dead = _alive(S)
    if dead:
        return dead
    bad = _positive_int(qty, "qty")
    if bad:
        return bad
    n, problem = _target(S, target)
    if problem:
        return problem
    if S.obs.inventory.get(item, 0) < qty:
        return no("no_item", item=str(item), have=S.obs.inventory.get(item, 0))
    reach = S.interact(n.x, n.y)
    if not reach.ok:
        return Verdict(False, reach.reason, {"target": target}, "", reach.distance)
    room = S.world.items.room(target, item)
    if room is not None and room < qty:
        return no("no_room", target=target, item=item, room=room)
    return yes(distance=reach.distance)


def _candidates_request(S):
    if not S.obs.alive:
        return []
    return [{"target": n.id, "item": "", "qty": 1} for n in _nearest_neighbours(S) if n.dist <= config.RADIUS["interact"]]


@verb("request_item", "can_request", _candidates_request)
def request_item(S, target: str = "", item: str = "", qty: int = 1) -> Verdict:
    """Ask a neighbour in interaction range for an item. Whether they hold it is *their* business (the resident cannot know), so
    it is not a legality condition: a holder refuses with ``refuse_no_item`` instead."""
    dead = _alive(S)
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
    reach = S.interact(n.x, n.y)
    return yes(distance=reach.distance) if reach.ok else Verdict(False, reach.reason, {"target": target}, "", reach.distance)


def _prices(S) -> dict:
    return S.services.commission_config().get("prices", {})


def _smiths(S):
    """Neighbours whose occupation could craft a commissionable recipe (the resident can see a smith's trade)."""
    from systems.crafting.resolver import crafting_recipe_occupation_tags
    out = []
    for n in _nearest_neighbours(S):
        record = S.services.record(n.id) or {}
        kind = str((record.get("occupation") or {}).get("kind", ""))
        for recipe in _prices(S):
            if kind and kind in crafting_recipe_occupation_tags(recipe):
                out.append((n, recipe))
    return out


def _candidates_commission(S):
    if not S.obs.alive:
        return []
    return [{"target": n.id, "recipe": r} for n, r in _smiths(S) if n.dist <= config.RADIUS["interact"]]


@verb("commission_item", "can_commission", _candidates_commission)
def commission_item(S, target: str = "", recipe: str = "") -> Verdict:
    from systems.crafting.resolver import crafting_recipe_occupation_tags
    dead = _alive(S)
    if dead:
        return dead
    if recipe not in _prices(S):
        return no("no_recipe", recipe=str(recipe))
    n, problem = _target(S, target)
    if problem:
        return problem
    kind = str(((S.services.record(target) or {}).get("occupation") or {}).get("kind", ""))
    if kind not in crafting_recipe_occupation_tags(recipe):
        return no("wrong_occupation", occupation=kind)
    reach = S.interact(n.x, n.y)
    return yes(distance=reach.distance) if reach.ok else Verdict(False, reach.reason, {"target": target}, "", reach.distance)


# -- social and conflict ----------------------------------------------------------------------------------------------
def _talk_candidates(S):
    return [{"target": n.id} for n in _nearest_neighbours(S)] if S.obs.alive else []


def _social(S, target, radius=None) -> Verdict:
    dead = _alive(S)
    if dead:
        return dead
    n, problem = _target(S, target, radius=radius if radius is not None else config.RADIUS["social"])
    if problem:
        return problem
    walk = S.walk_to(n.x, n.y)
    return Verdict(True, "", {}, walk.reachability, walk.distance) if walk.ok else walk


@verb("greet", "can_talk", _talk_candidates)
def greet(S, target: str = "") -> Verdict:
    return _social(S, target)


@verb("warn", "can_talk", _talk_candidates)
def warn(S, target: str = "") -> Verdict:
    return _social(S, target)


@verb("chat", "can_talk", _talk_candidates)
def chat(S, target: str = "", topic: str = "") -> Verdict:
    if not isinstance(topic, str):
        return no("invalid_params", field="topic")
    return _social(S, target)


@verb("follow", "target_reachable", _talk_candidates)
def follow(S, target: str = "") -> Verdict:
    return _social(S, target)


@verb("attack", "can_attack", _talk_candidates)
def attack(S, target: str = "") -> Verdict:
    return _social(S, target)


@verb("avoid", "target_in_perception", _talk_candidates)
def avoid(S, target: str = "") -> Verdict:
    dead = _alive(S)
    if dead:
        return dead
    _, problem = _target(S, target, radius=config.RADIUS["social"])
    return problem or yes()


@verb("ask_for_help", "can_call_help", lambda S: [{}] if S.obs.alive and any(n.alive for n in S.obs.neighbours) else [])
def ask_for_help(S, target: str = "") -> Verdict:
    dead = _alive(S)
    if dead:
        return dead
    if target:
        _, problem = _target(S, target, radius=config.RADIUS["social"])
        return problem or yes()
    return yes() if any(n.alive for n in S.obs.neighbours) else no("no_target")


def _candidates_comfort(S):
    return [{"target": n.id} for n in _nearest_neighbours(S) if n.mood <= config.MOOD_LOW] if S.obs.alive else []


@verb("comfort", "can_comfort", _candidates_comfort)
def comfort(S, target: str = "") -> Verdict:
    base = _social(S, target)
    if not base.ok:
        return base
    n = S.obs.neighbour(target)
    return base if n.mood <= config.MOOD_LOW else no("not_needed", mood=round(n.mood, 1))


def _candidates_defend(S):
    from systems.guard import enabled
    if enabled():                                        # EDEN_DEFEND: stand guard over a neighbour or an own place (affordance/guard_predicates.py)
        from .guard_predicates import candidates
        return candidates(S)
    return [{}] if S.obs.alive else []


@verb("defend", "can_defend", _candidates_defend)
def defend(S, target: str = "", place: str = "") -> Verdict:
    from systems.guard import enabled
    if enabled():
        from .guard_predicates import judge
        return judge(S, target, place)
    if target or place:
        return no("not_wired", why="EDEN_DEFEND is off")
    dead = _alive(S)
    if dead:
        return dead
    if any(n.alive for n in S.obs.neighbours) or S.obs.anchors.get("home") is not None or S.obs.anchors.get("sleep") is not None:
        return yes()
    return no("no_target")


# -- exploration ------------------------------------------------------------------------------------------------------
HEADINGS = {"N": (0.0, -1.0), "E": (1.0, 0.0), "S": (0.0, 1.0), "W": (-1.0, 0.0)}


def _candidates_explore(S):
    return [{"heading": h} for h in HEADINGS if explore_toward(S, h).ok] if S.obs.alive else []


@verb("explore_toward", "can_move", _candidates_explore)
def explore_toward(S, heading: str = "N") -> Verdict:
    dead = _alive(S)
    if dead:
        return dead
    if heading not in HEADINGS:
        return no("invalid_params", field="heading", allowed=sorted(HEADINGS))
    dx, dy = HEADINGS[heading]
    gx, gy = S.obs.x + dx * config.RADIUS["explore_step"], S.obs.y + dy * config.RADIUS["explore_step"]
    contract = S.services.contract()
    if contract is not None:
        from systems.movement.spatial import snap_to_standable
        snapped = snap_to_standable((gx, gy), contract)
        if snapped is None:
            return no("blocked", heading=heading)
        gx, gy = snapped
    bounds = S.world.bounds()
    if bounds is not None and not (bounds[0] <= gx <= bounds[2] and bounds[1] <= gy <= bounds[3]):
        return no("blocked", heading=heading, why="edge")
    walk = S.walk_to(gx, gy)
    return Verdict(True, "", {"to": [round(gx, 1), round(gy, 1)]}, walk.reachability, walk.distance) if walk.ok else walk


@verb("build_structure", "can_build")
def build_structure(S, kind: str = "", site: str = "") -> Verdict:
    dead = _alive(S)
    if dead:
        return dead
    needs = (S.obs.record or {}).get("construction_needs") or []
    return yes({"needs": len(needs)}) if needs else no("no_site", why="no_construction_need")


@verb("repair", "can_repair")
def repair(S, target: str = "") -> Verdict:
    dead = _alive(S)
    return dead or no("system_missing", why="no repair task exists in systems/tasks")


# -- cognitive control ------------------------------------------------------------------------------------------------
def _plans(S) -> list:
    return [p for p in ((S.obs.record or {}).get("plans") or []) if str(p.get("status", "active")) == "active"]


@verb("idle", "alive")
def idle(S) -> Verdict:
    return _alive(S) or yes()


@verb("USE_BRAIN", "can_think")
def use_brain(S, reason: str = "") -> Verdict:
    return _alive(S) or yes()


@verb("REPLAN", "plan_exists")
def replan(S, reason: str = "") -> Verdict:
    dead = _alive(S)
    if dead:
        return dead
    return yes({"plans": len(_plans(S))}) if _plans(S) else no("no_plan")


@verb("continue_plan_step", "plan_active")
def continue_plan_step(S) -> Verdict:
    dead = _alive(S)
    if dead:
        return dead
    if not _plans(S):
        return no("no_plan")
    state = (S.obs.record or {}).get("planning_state") or {}
    return no("no_plan", why="review_needed") if state.get("review_needed") else yes()


PLOT_GOALS = ("retaliate", "steal_when_safe")


@verb("PLOT", "has_plot_motive", lambda S: [{}] if S.obs.alive and plot_motive(S).ok else [])
def plot_motive(S, target: str = "") -> Verdict:
    dead = _alive(S)
    if dead:
        return dead
    record = S.obs.record or {}
    if any(g.get("kind") in PLOT_GOALS and g.get("status", "active") == "active" for g in record.get("goals") or []):
        return yes()
    if any("rival" in (r.get("tags") or []) for r in (record.get("relationships") or {}).values()):
        return yes()
    return no("no_motive")


# -- map resource nodes (G-005, EDEN_MAP_RESOURCES=1) -----------------------------------------------------------------
# Instant effects on a node row (type 27) the actor stands at (the node's circle plus ``harness.resources.REACH``). The judgement is
# ``harness.resources.eat_from_node`` / ``gather`` itself, so the predicate and the effect builder cannot disagree. Walking to the node is
# not part of the verb (like ``craft`` at the forge): the verbs are legal only in reach.
_NODE_REASON = {"not_a_node": "no_source", "not_edible": "no_edible", "too_far": "out_of_range", "empty": "no_source", "not_hungry": "not_needed",
                "bad_qty": "invalid_params", "unknown_item": "invalid_params", "no_actor": "dead", "no_room": "no_room"}


def _node_refusal(refused) -> Verdict:
    return no(_NODE_REASON.get(refused.reason, "no_source"), node_reason=refused.reason, why=refused.detail)


def _nodes_in_reach(S) -> list:
    """Ids of live resource-node rows the actor is in reach of (empty when the flag is off, the world has no node column or none is near)."""
    from harness import resources
    from systems.map import resources as map_resources
    if not map_resources.enabled() or not S.obs.alive:
        return []
    try:
        table = S.world.table("entities")
        m, col, ids = table.tensor, table.columns, table.ids
        types, x, y, scale = m[:, col["type"]], m[:, col["x"]], m[:, col["y"]], m[:, col["scale"]]
    except (KeyError, AttributeError):
        return []
    import genesis_config as cfg
    near = (types == float(cfg.M_RESOURCE_NODE)) & (((x - S.obs.x) ** 2 + (y - S.obs.y) ** 2).sqrt() <= scale + resources.REACH)
    return [ids[s] for s in near.nonzero(as_tuple=False).flatten().tolist() if ids[s]]


def _candidates_nodes(S):
    return [{"node": node} for node in _nodes_in_reach(S)]


def _flag_off():
    from systems.map import resources as map_resources
    return None if map_resources.enabled() else no("not_wired", why="EDEN_MAP_RESOURCES is off")


@verb("eat_from_node", "can_eat_from_node", _candidates_nodes)
def can_eat_from_node(S, node: str = "") -> Verdict:
    from harness import resources
    dead = _alive(S) or _flag_off()
    if dead:
        return dead
    if not isinstance(node, str) or not node:
        return no("invalid_params", field="node")
    try:
        draft = resources.eat_from_node(S.world, S.actor, node)
    except resources.ResourceRefused as refused:
        return _node_refusal(refused)
    return yes({"node": node, "hunger_relief": draft.preview["hunger_relief"]})


@verb("gather_from_node", "can_gather", _candidates_nodes)
def can_gather(S, node: str = "", qty: int = 1) -> Verdict:
    from harness import resources
    dead = _alive(S) or _flag_off()
    if dead:
        return dead
    bad = _positive_int(qty, "qty")
    if bad:
        return bad
    if not isinstance(node, str) or not node:
        return no("invalid_params", field="node")
    try:
        draft = resources.gather(S.world, S.actor, node, qty)
    except resources.ResourceRefused as refused:
        return _node_refusal(refused)
    return yes({"node": node, "item": draft.preview["item"]})


def _live_nodes(S) -> list:
    """``(id, x, y, distance, reach_limit)`` of every node row with stock the actor can see (``RADIUS["resource"]``), nearest first; empty with the flag off."""
    from harness import resources
    from systems.map import resources as map_resources
    if not map_resources.enabled() or not S.obs.alive:
        return []
    try:
        table = S.world.table("entities")
        m, col, ids = table.tensor, table.columns, table.ids
        types, x, y, scale = m[:, col["type"]], m[:, col["x"]], m[:, col["y"]], m[:, col["scale"]]
        stock = m[:, col["food"]] + m[:, col["node_stock"]]
        burning = m[:, col["burning"]]
    except (KeyError, AttributeError):
        return []
    import genesis_config as cfg
    dist = ((x - S.obs.x) ** 2 + (y - S.obs.y) ** 2).sqrt()
    near = (types == float(cfg.M_RESOURCE_NODE)) & (stock > 0) & (burning == 0) & (dist <= config.RADIUS["resource"])
    rows = [(float(dist[s]), ids[s], float(x[s]), float(y[s]), float(scale[s]) + resources.REACH) for s in near.nonzero(as_tuple=False).flatten().tolist() if ids[s]]
    return [(i, nx, ny, d, limit) for d, i, nx, ny, limit in sorted(rows)]


def _candidates_approach(S):
    return [{"node": i} for i, _, _, d, limit in _live_nodes(S) if d > limit][:3]


@verb("approach_node", "can_approach_node", _candidates_approach)
def can_approach_node(S, node: str = "") -> Verdict:
    """Walk to a resource node that has stock and is in sight but not yet in reach (the verbs ``eat_from_node`` / ``gather_from_node`` are legal only in reach)."""
    dead = _alive(S) or _flag_off()
    if dead:
        return dead
    if not isinstance(node, str) or not node:
        return no("invalid_params", field="node")
    found = next((row for row in _live_nodes(S) if row[0] == node), None)
    if found is None:
        return no("no_source", node=node)
    _, nx, ny, distance, limit = found
    if distance <= limit:
        return no("in_reach", node=node, distance=round(distance, 2))
    walk = S.walk_to(nx, ny, entity=node)
    if not walk.ok:
        return walk
    return yes({"node": node, "x": nx, "y": ny}, reachability=walk.reachability, distance=round(distance, 2))


# -- S-1 batch 2: trade, theft, news (1008_actions.md section 10.14) --------------------------------------------------
# Nothing here reads another resident's pack or memory (Observation's rule): whether the other side holds the item, accepts the swap or has not
# heard the news yet is *their* business, answered by their rules at op time or refused by the Action with a stable ``refused:<reason>``.
def _candidates_trade(S):
    """Swap offers a resident could make: its largest surplus stack against an edible it does not hold, to each neighbour in reach."""
    if not S.obs.alive:
        return []
    mine = S.obs.inventory
    lacking = [k for k in config.EDIBLE_ITEMS if mine.get(k, 0) < 1]
    surplus = sorted((k for k, q in mine.items() if q > 1 and k != "coin"), key=lambda k: (-mine[k], k))
    if not lacking or not surplus:
        return []
    return [{"target": n.id, "give": surplus[0], "want": lacking[0]} for n in _nearest_neighbours(S) if n.dist <= config.RADIUS["interact"]][:3]


@verb("offer_trade", "can_trade", _candidates_trade)
def offer_trade(S, target: str = "", give: str = "", want: str = "", give_qty: int = 1, want_qty: int = 1) -> Verdict:
    dead = _alive(S)
    if dead:
        return dead
    for value, name in ((give_qty, "give_qty"), (want_qty, "want_qty")):
        bad = _positive_int(value, name)
        if bad:
            return bad
    if not isinstance(give, str) or not give:
        return no("invalid_params", field="give")
    if not isinstance(want, str) or not want or want == give:
        return no("invalid_params", field="want")
    n, problem = _target(S, target)
    if problem:
        return problem
    if S.obs.inventory.get(give, 0) < give_qty:
        return no("no_item", item=give, have=S.obs.inventory.get(give, 0))
    reach = S.interact(n.x, n.y)
    if not reach.ok:
        return Verdict(False, reach.reason, {"target": target}, "", reach.distance)
    room = S.world.items.room(S.actor, want)
    if room is not None and room < want_qty:
        return no("no_room", item=want, room=room)
    return yes(distance=reach.distance)


def _candidates_offer(S):
    from systems.actions.offers import offers_of
    return [{"offer": o["id"]} for o in offers_of(S.services).open_for(S.actor, S.obs.tick)] if S.obs.alive else []


@verb("accept_trade", "offer_open", _candidates_offer)
def accept_trade(S, offer: str = "") -> Verdict:
    from systems.actions.offers import offers_of
    dead = _alive(S)
    if dead:
        return dead
    if not isinstance(offer, str) or not offer:
        return no("invalid_params", field="offer")
    found = offers_of(S.services).get(offer, tick=S.obs.tick)
    if found is None:
        return no("no_offer", offer=offer)
    if found["taker"] != S.actor:
        return no("not_addressed", offer=offer)
    n, problem = _target(S, found["giver"])
    if problem:
        return problem
    reach = S.interact(n.x, n.y)
    if not reach.ok:
        return Verdict(False, reach.reason, {"target": found["giver"]}, "", reach.distance)
    if S.world.items.quantity(found["giver"], found["give"]) < found["give_qty"]:
        return no("no_item", item=found["give"], owner=found["giver"])
    if S.obs.inventory.get(found["want"], 0) < found["want_qty"]:
        return no("no_item", item=found["want"])
    for owner, item, qty in ((S.actor, found["give"], found["give_qty"]), (found["giver"], found["want"], found["want_qty"])):
        room = S.world.items.room(owner, item)
        if room is not None and room < qty:
            return no("no_room", item=item, owner=owner, room=room)
    return yes({"offer": found}, distance=reach.distance)


def _witnesses_near(S, *, excluding=()) -> list:
    """Living residents other than the actor (and ``excluding``) within help range: anyone who would see a theft."""
    return [n.id for n in S.obs.neighbours if n.alive and n.id not in excluding and n.dist <= config.RADIUS["help"]]


def _candidates_steal(S):
    if not S.obs.alive or _witnesses_near(S):
        return []
    out = []
    for e in _storage_near(S):
        for kind, q in sorted(S.services.inventory(e.fact.id).items()):
            if q > 0 and kind != "coin":
                out.append({"container": e.fact.id, "item": kind})
    return out[:4]


@verb("steal_when_safe", "can_steal", _candidates_steal)
def steal_when_safe(S, target: str = "", container: str = "", item: str = "", qty: int = 1) -> Verdict:
    """Take an item from a neighbour's pack or an open container when nobody else within help range would see it."""
    dead = _alive(S)
    if dead:
        return dead
    bad = _positive_int(qty, "qty")
    if bad:
        return bad
    if not isinstance(item, str) or not item:
        return no("invalid_params", field="item")
    if bool(target) == bool(container):
        return no("invalid_params", field="target or container", why="exactly one of target / container")
    if target:
        n, problem = _target(S, target)
        if problem:
            return problem
        reach = S.interact(n.x, n.y)
        if not reach.ok:
            return Verdict(False, reach.reason, {"target": target}, "", reach.distance)
        seen = _witnesses_near(S, excluding=(target,))
    else:
        e = S.obs.entity(container)
        if e is None or e.fact.kind not in config.STORAGE_KINDS or not e.fact.alive:
            return no("no_target", container=str(container))
        if S.services.inventory(e.fact.id).get(item, 0) < qty:
            return no("no_item", item=item, container=container)
        reach = S.interact(e.fact.x, e.fact.y, e.fact.id, e.fact.interact_radius)
        if not reach.ok:
            return Verdict(False, reach.reason, {"container": container}, "", reach.distance)
        seen = _witnesses_near(S)
    if seen:
        return no("watched", by=seen[0], witnesses=len(seen))
    room = S.world.items.room(S.actor, item)
    if room is not None and room < qty:
        return no("no_room", item=item, room=room)
    return yes(distance=reach.distance)


def _known_events(S, since: int = 600) -> list:
    """Ledger events the actor itself witnessed in the last ``since`` ticks, newest first (a resident knows what it saw)."""
    ledger = getattr(S.world, "events", None)
    if ledger is None or not S.obs.alive:
        return []
    return sorted(ledger.events(witness=S.actor, since_tick=max(0, S.obs.tick - since)), key=lambda e: (-e.tick, e.id))


def _candidates_news(S):
    events = _known_events(S)
    if not events:
        return []
    return [{"target": n.id, "event": e.id} for n in _nearest_neighbours(S) if n.dist <= config.RADIUS["social"]
            for e in events[:2] if n.id not in e.witnesses][:4]


def _news_check(S, target: str, event_id: str) -> Verdict:
    dead = _alive(S)
    if dead:
        return dead
    if not isinstance(event_id, str) or not event_id:
        return no("invalid_params", field="event")
    ledger = getattr(S.world, "events", None)
    found = ledger.get(event_id) if ledger is not None else None
    if found is None:
        return no("no_event", event=event_id)
    if S.actor not in found.witnesses:
        return no("not_witnessed", event=event_id)
    n, problem = _target(S, target, radius=config.RADIUS["social"])
    if problem:
        return problem
    if target in found.witnesses:
        return no("already_knows", event=event_id, target=target)
    walk = S.walk_to(n.x, n.y)
    return Verdict(True, "", {"kind": found.type}, walk.reachability, walk.distance) if walk.ok else walk


@verb("share_news", "knows_event", _candidates_news)
def share_news(S, target: str = "", event: str = "") -> Verdict:
    return _news_check(S, target, event)


def _candidates_gossip(S):
    events = _known_events(S)
    out = []
    for n in _nearest_neighbours(S):
        if n.dist > config.RADIUS["social"]:
            continue
        for e in events:
            about = next((a for a in e.actors if a not in (S.actor, n.id) and S.world.table("humans").slot_of(a) is not None), None)
            if about is not None and n.id not in e.witnesses:
                out.append({"target": n.id, "about": about})
                break
    return out[:4]


@verb("gossip", "knows_event", _candidates_gossip)
def gossip(S, target: str = "", about: str = "") -> Verdict:
    dead = _alive(S)
    if dead:
        return dead
    if not isinstance(about, str) or not about or about in (S.actor, target):
        return no("invalid_params", field="about")
    event = next((e for e in _known_events(S) if about in e.actors and target not in e.witnesses), None)
    if event is None:
        return no("nothing_to_tell", about=about)
    verdict = _news_check(S, target, event.id)
    return Verdict(True, "", {**verdict.detail, "event": event.id}, verdict.reachability, verdict.distance) if verdict.ok else verdict


from . import market_predicates  # noqa: E402,F401 - registers buy / sell / set_price (EDEN_MARKET)

from . import credit_predicates  # noqa: E402,F401 - registers borrow_item / lend_item / pay_debt (EDEN_CREDIT)

from . import labour_predicates  # noqa: E402,F401 - registers work_for / collect_wage (EDEN_LABOUR)
from . import justice_predicates  # noqa: E402,F401 - registers report_theft / levy_damages (EDEN_JUSTICE)
from . import bonds_predicates  # noqa: E402,F401 - registers court / befriend / apologise / forgive (EDEN_BONDS)
from . import places_predicates  # noqa: E402,F401 - registers mark_place / remember_place / ask_directions (EDEN_PLACES)
from . import rob_predicates  # noqa: E402,F401 - registers rob / arrest_or_restrain (EDEN_ROB)
from . import care_predicates  # noqa: E402,F401 - registers light_fire / treat_wound (EDEN_TEMPERATURE / EDEN_WOUNDS)
from . import economy_predicates  # noqa: E402,F401 - opt-in owned farm harvest
