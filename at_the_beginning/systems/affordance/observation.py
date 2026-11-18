"""``Observation``: what one resident perceives and remembers, the only input legality and features may use (H.3 item 12).

Perceived (bounded by radius): other residents within ``RADIUS["social"]``, authored entities within ``RADIUS["safe"]``.
Remembered (not bounded, a resident knows its own life): its own state, its pack, its roster anchors and need sites, its record
(goals, plans, relationships, personality). Nothing here reads another resident's pack or record: whether someone *has* an item is
something the resident can only find out by asking, so it is never an input.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from . import config


@dataclass(frozen=True)
class Neighbour:
    id: str
    x: float
    y: float
    dist: float
    hp: float
    hunger: float
    thirst: float
    mood: float
    alive: bool


@dataclass(frozen=True)
class SeenEntity:
    fact: object            # services.EntityFact
    dist: float


@dataclass
class Observation:
    actor: str
    tick: int
    exists: bool = True
    alive: bool = False
    x: float = 0.0
    y: float = 0.0
    hp: float = 0.0
    hunger: float = 0.0
    thirst: float = 0.0
    stamina: float = 100.0
    threat: float = 0.0
    mood: float = 50.0
    record: Optional[dict] = None
    occupation: str = ""
    inventory: dict = field(default_factory=dict)
    neighbours: list = field(default_factory=list)          # Neighbour, nearest first (ties by id)
    entities: list = field(default_factory=list)            # SeenEntity, nearest first (ties by id)
    anchors: dict = field(default_factory=dict)             # key -> services.Anchor
    sites: dict = field(default_factory=dict)               # "water"/"food" -> services.Anchor | None

    @property
    def pos(self) -> tuple:
        return (self.x, self.y)

    def neighbour(self, target_id) -> Optional[Neighbour]:
        for n in self.neighbours:
            if n.id == target_id:
                return n
        return None

    def entity(self, entity_id) -> Optional[SeenEntity]:
        for e in self.entities:
            if e.fact.id == entity_id:
                return e
        return None


def _get(table, slot, name, default=0.0) -> float:
    col = table.columns.get(name)
    return default if col is None else float(table.tensor[slot, col])


def observe(world, services, actor: str) -> Observation:
    """Build the observation of ``actor``. Read-only; a missing or dead actor gives ``alive=False`` and empty perception."""
    table = world.table("humans")
    tick = int(world.tick)
    slot = table.slot_of(actor)
    if slot is None:
        return Observation(actor=actor, tick=tick, exists=False)
    x, y = table.position(slot)
    hp = _get(table, slot, "hp")
    alive = table.is_live_slot(slot) and hp > 0.0
    obs = Observation(actor=actor, tick=tick, alive=alive, x=x, y=y, hp=hp, hunger=_get(table, slot, "hunger"),
                      thirst=_get(table, slot, "thirst"), stamina=_get(table, slot, "stamina", 100.0), threat=_get(table, slot, "threat"),
                      mood=_get(table, slot, "mood", 50.0))
    record = services.record(actor)
    obs.record = record
    obs.occupation = str(((record or {}).get("occupation") or {}).get("kind", ""))
    obs.inventory = services.inventory(actor)
    obs.anchors = services.anchors(actor)
    obs.sites = services.sites(actor)
    if not alive:
        return obs
    neighbours = []
    for other in world.within("humans", x, y, config.RADIUS["social"], exclude=(actor,)):
        oslot = table.slot_of(other)
        if oslot is None:
            continue
        ox, oy = table.position(oslot)
        ohp = _get(table, oslot, "hp")
        neighbours.append(Neighbour(other, ox, oy, math.hypot(ox - x, oy - y), ohp, _get(table, oslot, "hunger"),
                                    _get(table, oslot, "thirst"), _get(table, oslot, "mood", 50.0), table.is_live_slot(oslot) and ohp > 0.0))
    neighbours.sort(key=lambda n: (n.dist, n.id))
    obs.neighbours = neighbours
    radius = config.RADIUS["safe"]
    seen = []
    for fact in services.entities():
        d = math.hypot(fact.x - x, fact.y - y)
        if d <= radius:
            seen.append(SeenEntity(fact, d))
    seen.sort(key=lambda e: (e.dist, e.fact.id))
    obs.entities = seen
    return obs
