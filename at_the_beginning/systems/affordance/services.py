"""What the affordance engine needs besides the harness ``World``: resident records, anchors, authored entities, inventories,
the movement contract and the commission order book.

``Services`` is the interface, ``EngineServices`` reads the running legacy engine (read-only: nothing here writes or creates
state), ``StaticServices`` is a plain-dict implementation for unit tests on a synthetic world. Systems are never imported at module
level from the engine side, so importing this module costs nothing and works without a booted engine.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Anchor:
    id: str
    key: str            # roster key: spawn, work, talk, sleep, home
    x: float
    y: float


@dataclass(frozen=True)
class EntityFact:
    id: str
    kind: str
    x: float
    y: float
    alive: bool = True
    interact_radius: float = 16.0
    hp: float = 100.0
    food: float = 0.0       # typed (tensor) resource entities only
    water: float = 0.0


class Services:
    """Default implementation: an empty world. Subclasses override what they can answer."""

    def record(self, actor: str) -> Optional[dict]:
        return None

    def anchors(self, actor: str) -> dict:
        return {}

    def sites(self, actor: str) -> dict:
        """``{"water": Anchor | None, "food": Anchor | None}``: where this resident goes to drink and eat when it has no pack food."""
        return {"water": None, "food": None}

    def entities(self) -> list:
        """Every authored entity (forge, well, bed, storage, ...) with liveness; the engine's own list, not a perception result."""
        return []

    def typed_resources(self, kind: str, x: float, y: float, radius: float) -> list:
        """Tensor entities carrying a ``food`` or ``water`` resource within ``radius`` (nearest first, at most a few)."""
        return []

    def inventory(self, owner: str) -> dict:
        """``{item kind: quantity}`` held by a resident or a container; empty when unknown. Never creates a record."""
        return {}

    def hostile_count(self, x: float, y: float, radius: float) -> int:
        """Living predators (tigers, wolves) within ``radius`` of a point."""
        return 0

    def contract(self) -> Optional[dict]:
        """Movement contract (``actor_radius``, ``bounds``, ``boxes``) or None for a map without walls."""
        return None

    def contract_revision(self) -> str:
        return ""

    def interaction_boxes(self, ignore_entity: Optional[str] = None) -> list:
        """Wall boxes for a range-plus-line check, without the footprint of ``ignore_entity``."""
        contract = self.contract()
        return [] if contract is None else list(contract["boxes"])

    def portal_toward(self, position: tuple, goal: tuple) -> Optional[tuple]:
        """``(from_point, to_point)`` of the portal to take when ``goal`` is on another placed map, else None."""
        return None

    def orders(self, smith_id: str) -> list:
        """Open commission orders of a smith (dicts as stored by ``systems.commission``)."""
        return []

    def commission_config(self) -> dict:
        return {}


class StaticServices(Services):
    """Dict-backed services for tests and synthetic worlds."""

    def __init__(self, *, records=None, anchors=None, sites=None, entities=(), inventories=None, contract=None, orders=None,
                 config=None, portals=None, hostiles=()):
        self._records = dict(records or {})
        self._anchors = {k: dict(v) for k, v in (anchors or {}).items()}
        self._sites = {k: dict(v) for k, v in (sites or {}).items()}
        self._entities = list(entities)
        self._inventories = {k: dict(v) for k, v in (inventories or {}).items()}
        self._contract = contract
        self._orders = {k: list(v) for k, v in (orders or {}).items()}
        self._config = dict(config or {})
        self._portals = list(portals or [])
        self._hostiles = [tuple(h) for h in hostiles]

    def record(self, actor):
        return self._records.get(actor)

    def anchors(self, actor):
        return dict(self._anchors.get(actor, {}))

    def sites(self, actor):
        found = self._sites.get(actor, {})
        return {"water": found.get("water"), "food": found.get("food")}

    def entities(self):
        return list(self._entities)

    def inventory(self, owner):
        return dict(self._inventories.get(owner, {}))

    def hostile_count(self, x, y, radius):
        import math
        return sum(1 for hx, hy in self._hostiles if math.hypot(hx - x, hy - y) <= radius)

    def contract(self):
        return self._contract

    def contract_revision(self):
        return "static" if self._contract is not None else ""

    def portal_toward(self, position, goal):
        for portal in self._portals:
            if portal["here"](position) and not portal["here"](goal):
                return portal["from"], portal["to"]
        return None

    def orders(self, smith_id):
        return list(self._orders.get(smith_id, []))

    def commission_config(self):
        return dict(self._config)


class EngineServices(Services):
    """Read-only view of the running legacy ``Engine``. The movement contract is cached per tick (walls broken later in the same
    tick show up next tick); entity liveness is always read fresh."""

    def __init__(self, engine):
        self.engine = engine
        self._tick_cache: dict = {}
        self._cache_tick = None
        self._static: list = []
        self._static_key = None

    def _cached(self, key, build):
        tick = int(self.engine.tick)
        if tick != self._cache_tick:
            self._tick_cache, self._cache_tick = {}, tick
        if key not in self._tick_cache:
            self._tick_cache[key] = build()
        return self._tick_cache[key]

    # residents ----------------------------------------------------------------
    def record(self, actor):
        return self.engine.resident_store.get(actor)

    def anchors(self, actor):
        record = self.record(actor)
        roster = (record or {}).get("roster")
        if not roster:
            return {}
        from systems.roster.driver import anchor_positions
        positions = anchor_positions(self.engine, roster)
        return {key: Anchor(roster["anchors"][key], key, float(pos[0]), float(pos[1])) for key, pos in positions.items()}

    def sites(self, actor):
        record = self.record(actor)
        roster = (record or {}).get("roster")
        out = {"water": None, "food": None}
        if not roster:
            return out
        from systems.roster.needs import settings, site_position
        needs, has_sites = settings(roster)
        for kind in ("water", "food"):
            position = site_position(self.engine, needs, kind, has_sites)
            if position is not None:
                out[kind] = Anchor(needs[kind]["anchor"], kind, float(position[0]), float(position[1]))
        return out

    # entities -----------------------------------------------------------------
    def _static_entities(self):
        """Authored entity definitions of the placed maps (fixed while the map is loaded), cached per map."""
        from systems.movement.map_contract import placed_group
        name = getattr(self.engine, "_map_name", None)
        group = placed_group(name)
        key = (name, id(group[0]) if group else 0, sum(len(e.get("entities", ())) for e in group))
        if self._static_key != key:
            self._static = [(e["id"], str(e["kind"]), float(e["position"][0]), float(e["position"][1]),
                             float(e.get("interact_radius") or 16.0)) for entry in group for e in entry.get("entities", ())]
            self._static_key = key
        return self._static

    def entities(self):
        """Authored entities with liveness read *now* (a forge wrecked this tick counts at once); only definitions are cached."""
        import genesis_config as cfg
        engine = self.engine
        m = engine.state.m_tensor
        slots = {uid: s for s, uid in enumerate(engine._entity_uid_by_slot) if uid}
        out = []
        for eid, kind, px, py, radius in self._static_entities():
            slot = slots.get(eid)
            x, y, alive, hp = px, py, False, 0.0
            if slot is not None:
                hp = float(m[slot, cfg.M_HP])
                alive = int(m[slot, cfg.M_TYPE]) > 0 and hp > 0.0
                x, y = float(m[slot, cfg.CX]), float(m[slot, cfg.CY])
            out.append(EntityFact(eid, kind, x, y, alive, radius, hp))
        return out

    def typed_resources(self, kind, x, y, radius):
        import genesis_config as cfg
        import torch
        spec = type(self.engine)._task_resource_type_ids(kind)
        if spec is None:
            return []
        types, column = spec
        m = self.engine.state.m_tensor
        mtype = m[:, cfg.M_TYPE]
        mask = torch.isin(mtype, torch.tensor(sorted(types), dtype=mtype.dtype)) & (m[:, column] > 0) & (m[:, cfg.M_HP] > 0)
        if not bool(mask.any()):
            return []
        dx, dy = m[:, cfg.CX].double() - x, m[:, cfg.CY].double() - y
        dist = torch.sqrt(dx * dx + dy * dy)
        mask &= dist <= radius
        slots = mask.nonzero(as_tuple=False).flatten().tolist()
        slots.sort(key=lambda s: (float(dist[s]), s))
        out = []
        for s in slots[:4]:
            uid = self.engine._entity_uid_by_slot[s] or f"slot:{s}"
            out.append(EntityFact(uid, f"type:{int(m[s, cfg.M_TYPE])}", float(m[s, cfg.CX]), float(m[s, cfg.CY]), True, 16.0,
                                  float(m[s, cfg.M_HP]), float(m[s, cfg.M_RESOURCE_FOOD]), float(m[s, cfg.M_RESOURCE_WATER])))
        return out

    # inventory ----------------------------------------------------------------
    def inventory(self, owner):
        owner = str(owner)
        key = f"human:{owner}" if owner.startswith("h_") else f"container:{owner}"
        record = self.engine.inventory_state.get("inventories", {}).get(key)
        if record is None:
            return {}
        out: dict = {}
        for stack in record.get("items", []):
            kind = str(stack.get("kind", ""))
            out[kind] = out.get(kind, 0) + int(stack.get("quantity", 0))
        return out

    def hostile_count(self, x, y, radius):
        import genesis_config as cfg
        import torch
        m = self.engine.state.m_tensor
        mtype = m[:, cfg.M_TYPE]
        from systems.creatures import table                      # hostile species: tiger and wolf while EDEN_CREATURES is off, the table's ``hostile`` rows with it
        hostile = torch.tensor(sorted(table.hostile_types()), dtype=mtype.dtype)
        mask = torch.isin(mtype, hostile) & (m[:, cfg.M_HP] > 0)
        if not bool(mask.any()):
            return 0
        dx, dy = m[mask, cfg.CX].double() - x, m[mask, cfg.CY].double() - y
        return int((torch.sqrt(dx * dx + dy * dy) <= radius).sum())

    # movement -----------------------------------------------------------------
    def contract(self):
        from systems.movement.map_contract import get_map_contract
        if get_map_contract(getattr(self.engine, "_map_name", None)) is None:
            return None
        from systems.movement.spatial import world_contract
        return self._cached("contract", lambda: world_contract(self.engine))

    def contract_revision(self):
        contract = self.contract()
        return "" if contract is None else str(contract["revision"])

    def interaction_boxes(self, ignore_entity=None):
        """Wall boxes for reach / interaction checks. Composed (and every box copied) once per tick per ignored entity: a mask of N residents asked
        for them hundreds of times, which was most of its cost. Read-only for callers."""
        def build():
            from systems.movement.spatial import map_wall_boxes, map_wall_boxes_ignoring
            boxes = map_wall_boxes_ignoring(self.engine, ignore_entity) if ignore_entity else map_wall_boxes(self.engine)
            return [] if boxes is None else boxes
        return self._cached(("boxes", ignore_entity), build)

    def portal_toward(self, position, goal):
        from systems.roster.driver import portal_toward
        return portal_toward(self.engine, position, goal)

    # commission ---------------------------------------------------------------
    def orders(self, smith_id):
        data = self.engine.inventory_state.get("work_orders") or {}
        from systems.commission.config import OPEN_STATES
        return [o for o in data.get("orders", {}).values() if o["smith_id"] == smith_id and o["state"] in OPEN_STATES]

    def commission_config(self):
        from systems.commission.config import COMMISSION_CONFIG
        return dict(COMMISSION_CONFIG)
