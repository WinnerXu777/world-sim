"""EventLedger: every effect that matters becomes an event with a causal id, a place, a visibility and witnesses.

This generalises ``systems/god/events.py`` (one causal id per event, perceived only by witnesses, remembered once per
witness) from god powers to everything. Witnesses come from a pluggable *perceiver*: the default ``RadiusPerceiver`` uses the
world's position tables, and the Engine adapter plugs in ``systems.god.state.witnesses`` (same-map-and-radius rule). The ledger
itself never mutates world state; subscribers (memory, gossip, goal generation, the Tier 1 trigger detector, the client log)
react in ``dispatch()``, once per event, in registration order.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

VISIBILITY = ("local", "global", "private")


@dataclass
class Event:
    id: str
    tick: int
    type: str
    actors: tuple = ()                 # stable ids of the entities involved (the first is the subject)
    place: Optional[tuple] = None      # (x, y) in the world's local frame, or None
    space: int = 0
    visibility: str = "local"          # local: witnesses within radius; global: everyone; private: actors only
    radius: float = 80.0
    witnesses: tuple = ()
    payload: dict = field(default_factory=dict)
    cause: str = ""

    def to_dict(self) -> dict:
        return {"id": self.id, "tick": self.tick, "type": self.type, "actors": list(self.actors),
                "place": None if self.place is None else [round(self.place[0], 3), round(self.place[1], 3)], "space": self.space,
                "visibility": self.visibility, "radius": self.radius, "witnesses": list(self.witnesses),
                "payload": dict(self.payload), "cause": self.cause}

    @classmethod
    def from_dict(cls, data: dict) -> "Event":
        return cls(id=data["id"], tick=int(data["tick"]), type=data["type"], actors=tuple(data.get("actors", ())),
                   place=None if data.get("place") is None else tuple(data["place"]), space=int(data.get("space", 0)),
                   visibility=data.get("visibility", "local"), radius=float(data.get("radius", 80.0)),
                   witnesses=tuple(data.get("witnesses", ())), payload=dict(data.get("payload", {})), cause=data.get("cause", ""))


class RadiusPerceiver:
    """Default witness rule for synthetic worlds: living members of ``table`` in the same space within ``radius``.

    Distances are computed in float64 on the stored (window-local) positions, so they are exact at any offset.
    """

    def __init__(self, world, table: str = "humans"):
        self.world, self.table_name = world, table

    def witnesses(self, place, radius: float, space: int = 0, always: Iterable = ()) -> list:
        table = self.world.table(self.table_name)
        found = {a for a in always}
        if place is not None and table.pos_cols:
            px, py = place
            xs = table.tensor[:, table.col(table.pos_cols[0])].double()
            ys = table.tensor[:, table.col(table.pos_cols[1])].double()
            near = table.live_mask() & (((xs - px) ** 2 + (ys - py) ** 2) <= radius * radius)
            if table.space_col:
                near &= table.tensor[:, table.col(table.space_col)].long() == int(space)
            for slot in near.nonzero(as_tuple=False).flatten().tolist():
                if table.ids[slot] is not None:
                    found.add(table.ids[slot])
        return sorted(found, key=str)

    def everyone(self) -> list:
        table = self.world.table(self.table_name)
        return sorted((table.ids[s] for s in table.live_slots() if table.ids[s] is not None), key=str)


class EventLedger:
    def __init__(self, world=None, history: int = 4096, perceiver=None):
        self.world = world
        self.perceiver = perceiver
        self.history_limit = int(history)
        self._next_uid = 1
        self._history: list[Event] = []
        self._by_id: dict[str, Event] = {}
        self._pending: list[Event] = []
        self._subscribers: list[tuple[Optional[frozenset], Callable[[Event], None]]] = []

    # emission ----------------------------------------------------------------
    def new_id(self) -> str:
        event_id = f"ev_{self._next_uid:06d}"
        self._next_uid += 1
        return event_id

    def emit(self, type: str, *, actors: Iterable = (), place=None, space: int = 0, visibility: str = "local", radius: float = 80.0,
             payload: Optional[dict] = None, witnesses: Optional[Iterable] = None, event_id: Optional[str] = None,
             cause: str = "", tick: Optional[int] = None) -> Event:
        """Record an event. Passing an existing ``event_id`` is idempotent (returns the stored event, adds new witnesses only)."""
        if visibility not in VISIBILITY:
            raise ValueError(f"visibility must be one of {VISIBILITY}")
        actors = tuple(actors)
        found = self._witnesses(visibility, place, radius, space, actors) if witnesses is None else tuple(sorted(set(witnesses), key=str))
        if event_id is not None and event_id in self._by_id:
            existing = self._by_id[event_id]
            fresh = tuple(w for w in found if w not in existing.witnesses)
            existing.witnesses = existing.witnesses + fresh
            return existing
        event = Event(id=event_id or self.new_id(), tick=self._tick() if tick is None else int(tick), type=str(type), actors=actors,
                      place=None if place is None else (float(place[0]), float(place[1])), space=int(space), visibility=visibility,
                      radius=float(radius), witnesses=tuple(found), payload=dict(payload or {}), cause=cause)
        self._by_id[event.id] = event
        self._history.append(event)
        self._pending.append(event)
        while len(self._history) > self.history_limit:
            old = self._history.pop(0)
            self._by_id.pop(old.id, None)
        return event

    def _tick(self) -> int:
        return int(self.world.tick) if self.world is not None else 0

    def _witnesses(self, visibility, place, radius, space, actors) -> tuple:
        if visibility == "private" or self.perceiver is None:
            return tuple(sorted(set(actors), key=str))
        if visibility == "global":
            return tuple(self.perceiver.everyone())
        return tuple(self.perceiver.witnesses(place, radius, space, always=actors))

    # subscription ------------------------------------------------------------
    def subscribe(self, callback: Callable[[Event], None], types: Optional[Iterable[str]] = None) -> None:
        self._subscribers.append((None if types is None else frozenset(types), callback))

    def dispatch(self) -> int:
        """Deliver pending events to subscribers in order; returns how many events were delivered."""
        pending, self._pending = self._pending, []
        for event in pending:
            for types, callback in list(self._subscribers):
                if types is None or event.type in types:
                    callback(event)
        return len(pending)

    # queries -----------------------------------------------------------------
    def get(self, event_id: str) -> Optional[Event]:
        return self._by_id.get(event_id)

    def events(self, *, type: Optional[str] = None, since_tick: Optional[int] = None, actor=None, witness=None) -> list[Event]:
        out = []
        for e in self._history:
            if type is not None and e.type != type:
                continue
            if since_tick is not None and e.tick < since_tick:
                continue
            if actor is not None and actor not in e.actors:
                continue
            if witness is not None and witness not in e.witnesses:
                continue
            out.append(e)
        return out

    def witnessed_by(self, entity_id) -> list[Event]:
        return self.events(witness=entity_id)

    @property
    def pending(self) -> int:
        return len(self._pending)

    # persistence -------------------------------------------------------------
    def to_dict(self) -> dict:
        return {"next_uid": self._next_uid, "events": [e.to_dict() for e in self._history]}

    @classmethod
    def from_dict(cls, data: dict, world=None, perceiver=None) -> "EventLedger":
        ledger = cls(world=world, perceiver=perceiver)
        ledger._next_uid = int(data.get("next_uid", 1))
        for raw in data.get("events", []):
            event = Event.from_dict(raw)
            ledger._history.append(event)
            ledger._by_id[event.id] = event
        return ledger
