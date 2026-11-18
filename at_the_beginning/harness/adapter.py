"""EngineWorld: the harness ``World`` over the running legacy ``Engine``, with no behaviour change.

The tables share the engine's own tensors and its live id lists (``_human_uid_by_slot`` / ``_entity_uid_by_slot``), so a write
through the harness is visible to every legacy system and the other way round. Nothing is copied, nothing in the tick loop
calls this yet: it is the seam new systems, actions and powers are written against, and the thing the golden trace and the
adapter tests prove is faithful.

* ``clock.tick`` is ``engine.tick``; ``rng`` streams are keyed by ``world.seed`` (default: ``EDEN_SEED`` or 0) and the tick.
* ``bounds()``/``centre()``/``clamp()`` are the legacy frame (``MAP_WIDTH x MAP_HEIGHT``) until the frame is made unbounded.
* Witnesses use ``systems.god.state.witnesses`` (same placed map AND within radius), the rule god events already use.
* Items go through the real inventory records (``systems.inventory.ops``), so a ``Transfer`` obeys slots and weight limits.
* ``world.revision`` is the harness's own counter for effects applied through it; legacy stale-result guards keep their own
  revisions (commission order revision, the tick).
"""
from __future__ import annotations

import os
from typing import Iterable, Optional

from .events import EventLedger
from .frame import SpaceFrame
from .legacy_tasks import LegacyTaskView
from .world import Clock, FieldSpec, Table, World

# harness column name -> genesis_config constant name
HUMAN_COLUMNS = {
    "x": "X", "y": "Y", "type": "TYPE", "hp": "HP", "strength": "H_STRENGTH", "fertility": "H_FERTILITY", "aggression": "H_AGGRESSION",
    "stamina": "H_STAMINA", "infection": "H_INFECTION", "shelter": "H_SHELTER", "sex": "H_SEX", "age": "H_AGE", "life_exp": "H_LIFE_EXP",
    "cooldown": "H_COOLDOWN", "hunger": "HUNGER", "threat": "THREAT", "mood": "MOOD", "critical_health": "CRITICAL_HEALTH",
    "escalation_flag": "ESCALATION_FLAG", "acquired_instinct_mask": "ACQUIRED_INSTINCT_MASK",
    "acquired_instinct_mask_1": "ACQUIRED_INSTINCT_MASK_1", "acquired_instinct_mask_2": "ACQUIRED_INSTINCT_MASK_2",
    "parent_instincts_1": "H_PARENT_INSTINCTS_1", "parent_instincts_2": "H_PARENT_INSTINCTS_2", "carrying": "H_CARRYING", "skill": "H_SKILL",
    "tribe": "H_TRIBE", "parent_instincts": "H_PARENT_INSTINCTS", "thirst": "THIRST"}
ENTITY_COLUMNS = {
    "x": "CX", "y": "CY", "type": "M_TYPE", "hp": "M_HP", "scale": "SCALE", "fertility": "M_FERTILITY", "elevation": "M_ELEVATION",
    "burning": "M_BURNING", "flooded": "M_FLOODED", "food": "M_RESOURCE_FOOD", "water": "M_RESOURCE_WATER", "growth_rate": "M_GROWTH_RATE",
    "node_kind": "M_NODE_KIND", "node_stock": "M_NODE_STOCK", "node_cap": "M_NODE_CAP", "depleted_tick": "M_DEPLETED_TICK"}   # G-005 resource nodes
# Bounds the legacy code itself enforces (instinct_stamina_tick clamps 0..100; god powers cap HP at 100). Others are unbounded
# here until measured: do not invent limits the engine does not have.
HUMAN_SPECS = {"hp": FieldSpec(0.0, 100.0), "stamina": FieldSpec(0.0, 100.0), "type": FieldSpec(0, 1, integer=True, mode="reject"),
               "hunger": FieldSpec(None, 100.0), "thirst": FieldSpec(None, 100.0), "mood": FieldSpec(0.0, None)}  # S3 drain (legacy clamps)


class LegacyItemStore:
    """Item quantities over ``engine.inventory_state``; owners are resident ids (``h_*``) and storage-case entity ids (``e_*``)."""

    def __init__(self, engine):
        self.engine = engine

    def _record(self, owner) -> dict:
        owner = str(owner)
        if owner.startswith("h_"):
            return self.engine._human_inventory_record(owner)
        return self.engine._storage_case_inventory_record(owner)

    def quantity(self, owner, item: str) -> int:
        from systems.inventory.queries import total_quantity
        return total_quantity(self._record(owner), item)

    def room(self, owner, item: str) -> Optional[int]:
        from systems.inventory.resolver import can_add_item
        record = self._record(owner)
        if can_add_item(record, item, 100000):
            return None
        lo, hi = 0, 100000
        while lo < hi:                      # largest quantity that still fits
            mid = (lo + hi + 1) // 2
            if can_add_item(record, item, mid):
                lo = mid
            else:
                hi = mid - 1
        return lo

    def add(self, owner, item: str, qty: int) -> int:
        from systems.inventory.ops import add_item
        return int(add_item(self._record(owner), item, qty)["added"])

    def remove(self, owner, item: str, qty: int) -> int:
        from systems.inventory.ops import remove_item
        return int(remove_item(self._record(owner), item, qty)["removed"])

    def _records(self):
        return self.engine.inventory_state.get("inventories", {}).values()

    def total(self, item: str) -> int:
        return sum(int(s.get("quantity", 0)) for r in self._records() for s in r.get("items", []) if str(s.get("kind", "")) == item)

    def items(self) -> Iterable[str]:
        return sorted({str(s.get("kind", "")) for r in self._records() for s in r.get("items", [])})


class GodWitnessPerceiver:
    """Witnesses by the rule god events use: same placed map and within the radius; ``always`` ids are included."""

    def __init__(self, engine):
        self.engine = engine

    def witnesses(self, place, radius: float, space: int = 0, always: Iterable = ()) -> list:
        from systems.god.state import witnesses
        if place is None:
            return sorted(set(always), key=str)
        return sorted(set(witnesses(self.engine, place, radius=radius, always=tuple(always))) | set(always), key=str)

    def everyone(self) -> list:
        from systems.god.state import live_residents
        return sorted(h for h, _, _ in live_residents(self.engine))


class EngineWorld(World):
    def __init__(self, engine, seed: Optional[int] = None):
        import genesis_config as cfg
        self.engine = engine
        humans = Table("humans", engine.state.h_tensor, {k: getattr(cfg, v) for k, v in HUMAN_COLUMNS.items()}, type_col="type",
                       pos_cols=("x", "y"), id_prefix="h", field_specs=HUMAN_SPECS)
        entities = Table("entities", engine.state.m_tensor, {k: getattr(cfg, v) for k, v in ENTITY_COLUMNS.items()}, type_col="type",
                         pos_cols=("x", "y"), id_prefix="e")
        humans._ids_provider = lambda: engine._human_uid_by_slot
        entities._ids_provider = lambda: engine._entity_uid_by_slot
        frame = SpaceFrame(bounds=(0.0, 0.0, float(cfg.MAP_WIDTH), float(cfg.MAP_HEIGHT)))
        super().__init__(int(os.environ.get("EDEN_SEED", "0")) if seed is None else int(seed), [humans, entities], frame=frame,
                         items=LegacyItemStore(engine), perceiver_table="humans")
        self.events.perceiver = GodWitnessPerceiver(engine)
        self.residents = _ResidentView(engine)
        self.legacy_tasks = LegacyTaskView(engine)       # bridge step 1: read-only view of resident["tasks"] in harness shape
        self.config["resource_model"] = {          # which entity types carry food/water/fertility, and their caps (legacy bounty/scarcity)
            "natural_types": sorted(int(t) for t in cfg.NATURAL_TYPES), "other_types": [int(cfg.M_FARM), int(cfg.M_WELL), int(cfg.M_RESOURCE_NODE)],
            "max_food": float(cfg.MAX_ENTITY_FOOD), "max_water": float(cfg.MAX_ENTITY_WATER), "max_fertility": 100.0}

    def apply(self, effects, **kwargs):
        """Apply effects, then resync the legacy population counter when humans were spawned or removed: the legacy spawn
        limit and the client read ``engine._pop_count``, which the generic applier knows nothing about."""
        report = self.effects.apply(effects, **kwargs)
        if any(table == "humans" for table, _ in report.spawned + report.despawned):
            self.engine._pop_count[0] = len(self.table("humans").live_slots())
        return report

    @property
    def clock(self) -> Clock:                         # type: ignore[override]
        return _EngineClock(self.engine)

    @property
    def tick(self) -> int:                            # type: ignore[override]
        return int(self.engine.tick)


class _EngineClock:
    def __init__(self, engine):
        self._engine = engine

    @property
    def tick(self) -> int:
        return int(self._engine.tick)

    @property
    def ticks_per_second(self) -> int:
        import genesis_config as cfg
        return int(cfg.TICK_RATE_HZ)

    def advance(self, n: int = 1):
        raise RuntimeError("the engine owns the clock; EngineWorld cannot advance it")


class _ResidentView:
    """Read access to resident records by stable id (``world.residents[id]``) without copying the store."""

    def __init__(self, engine):
        self._engine = engine

    def __getitem__(self, resident_id):
        record = self._engine.resident_store.get(resident_id)
        if record is None:
            raise KeyError(resident_id)
        return record

    def get(self, resident_id, default=None):
        record = self._engine.resident_store.get(resident_id)
        return default if record is None else record

    def __contains__(self, resident_id) -> bool:
        return self._engine.resident_store.get(resident_id) is not None
