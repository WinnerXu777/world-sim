"""World facade: the narrow surface systems, actions and powers use instead of ``ctx["engine"]`` and ``map_geo`` globals.

A ``World`` owns: named tensor ``Table`` s (columns by name, stable ids per row), the clock, counter-based RNG streams, a
``SpaceFrame`` and a ``SpatialIndex``, an ``EffectApplier``, an ``EventLedger`` and an item store. It can be built from a few
tensors for a unit test (``World.synthetic``) or wrap the running legacy engine (``adapter.EngineWorld``). Two worlds can live
in one process: nothing here uses module globals.

Rows are identified by *stable ids* (strings such as ``h_000003``); slot indices are an implementation detail that effects and
selectors re-resolve at apply time, so a row reused by another entity is never mistaken for the old one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

import numpy as np
import torch

from .effects import EffectApplier
from .events import EventLedger, RadiusPerceiver
from .frame import SpaceFrame
from .items import DictItemStore
from .tasks import DictTaskStore
from .rng import Stream, normal_for_ids, rng as make_rng, uniform_for_ids
from .spatial_index import SpatialIndex


@dataclass(frozen=True)
class FieldSpec:
    """Bounds and write policy of one column. ``mode`` is what a Set outside [lo, hi] does: ``clamp`` or ``reject``."""
    lo: Optional[float] = None
    hi: Optional[float] = None
    integer: bool = False
    mode: str = "clamp"


class Table:
    """A tensor of rows (one entity per row) with named columns and stable ids."""

    def __init__(self, name: str, tensor: torch.Tensor, columns: dict, *, type_col: str, ids: Optional[list] = None,
                 pos_cols: Optional[tuple] = None, space_col: Optional[str] = None, id_prefix: str = "e",
                 field_specs: Optional[dict] = None, indexed: bool = False):
        if type_col not in columns:
            raise ValueError(f"type column {type_col!r} is not in the column map of table {name!r}")
        self.name, self.tensor, self.columns = name, tensor, dict(columns)
        self.type_col, self.pos_cols, self.space_col = type_col, pos_cols, space_col
        self._ids = ids if ids is not None else [None] * tensor.shape[0]
        self._ids_provider = None            # the Engine adapter points this at the engine's live id list
        self.id_prefix, self.field_specs, self.indexed = id_prefix, dict(field_specs or {}), indexed
        self._next_uid = 1
        if len(self._ids) != tensor.shape[0]:
            raise ValueError("ids must have one entry per tensor row")

    @property
    def ids(self) -> list:
        """Stable id per row (``None`` = no entity). Shared with the engine's own list when wrapped by the adapter."""
        return self._ids_provider() if self._ids_provider is not None else self._ids

    # columns -----------------------------------------------------------------
    def col(self, field_name: str) -> int:
        try:
            return self.columns[field_name]
        except KeyError:
            raise KeyError(f"table {self.name!r} has no field {field_name!r}") from None

    def spec(self, field_name: str) -> FieldSpec:
        return self.field_specs.get(field_name, FieldSpec())

    # rows --------------------------------------------------------------------
    @property
    def rows(self) -> int:
        return self.tensor.shape[0]

    def live_mask(self) -> torch.Tensor:
        return self.tensor[:, self.col(self.type_col)] > 0

    def live_slots(self) -> list:
        return self.live_mask().nonzero(as_tuple=False).flatten().tolist()

    def slot_of(self, entity_id) -> Optional[int]:
        try:
            slot = self.ids.index(entity_id)
        except ValueError:
            return None
        return slot

    def slots_of(self, entity_ids: Sequence) -> tuple:
        """``(slots, missing)``: slot per id that currently exists (live or not), and the ids that do not exist."""
        lookup = {eid: s for s, eid in enumerate(self.ids) if eid is not None}
        slots, missing = [], []
        for eid in entity_ids:
            if eid in lookup:
                slots.append(lookup[eid])
            else:
                missing.append(eid)
        return slots, missing

    def is_live_slot(self, slot: int) -> bool:
        return bool(self.tensor[slot, self.col(self.type_col)] > 0)

    def free_slot(self) -> Optional[int]:
        free = ((self.tensor[:, self.col(self.type_col)] == 0)).nonzero(as_tuple=False).flatten().tolist()
        for slot in free:
            if self.ids[slot] is None:
                return slot
        return None

    def new_id(self) -> str:
        existing = set(i for i in self.ids if i is not None)
        while True:
            candidate = f"{self.id_prefix}_{self._next_uid:06d}"
            self._next_uid += 1
            if candidate not in existing:
                return candidate

    def get(self, entity_id, field_name: str) -> float:
        slot = self.slot_of(entity_id)
        if slot is None:
            raise KeyError(entity_id)
        return float(self.tensor[slot, self.col(field_name)])

    def position(self, slot: int) -> Optional[tuple]:
        if not self.pos_cols:
            return None
        return (float(self.tensor[slot, self.col(self.pos_cols[0])]), float(self.tensor[slot, self.col(self.pos_cols[1])]))


class Clock:
    def __init__(self, tick: int = 0, ticks_per_second: int = 20):
        self.tick, self.ticks_per_second = int(tick), int(ticks_per_second)

    def advance(self, n: int = 1) -> int:
        self.tick += int(n)
        return self.tick

    @property
    def game_seconds(self) -> float:
        return self.tick / self.ticks_per_second


class World:
    """See module docstring. Subclasses (the Engine adapter) override ``tick``/``clock`` sourcing, not the interface."""

    def __init__(self, seed: int, tables: Sequence[Table], *, frame: Optional[SpaceFrame] = None, clock: Optional[Clock] = None,
                 items=None, perceiver_table: str = "humans", view_centre: Optional[tuple] = None, allow_item_creation: bool = False,
                 tasks=None):
        self.seed = int(seed)
        self.tables = {t.name: t for t in tables}
        self.frame = frame or SpaceFrame()
        self._clock = clock or Clock()
        self.items = items if items is not None else DictItemStore()
        self.tasks = tasks if tasks is not None else DictTaskStore()          # tasks of durative actions (Task effect)
        self.config: dict = {}                       # world-specific constants powers need (e.g. "resource_model"); empty = none
        self.view_centre = view_centre
        self.revision = 0
        self.index = SpatialIndex(self.frame.chunk_units)
        self.residents: dict = {}                       # stable id -> record dict (profile, memory, ...)
        self.events = EventLedger(self)
        self.events.perceiver = RadiusPerceiver(self, perceiver_table) if perceiver_table in self.tables else None
        self.effects = EffectApplier(self, allow_item_creation=allow_item_creation)
        self._revision_listeners: list[Callable[[int], None]] = []
        for table in self.tables.values():
            if table.indexed:
                self.reindex(table.name)

    @classmethod
    def synthetic(cls, seed: int = 1, humans: int = 16, entities: int = 32, **kwargs) -> "World":
        """A tiny world for unit tests: ``humans`` and ``entities`` tables with a few named columns and no legacy engine."""
        h_cols = {"type": 0, "x": 1, "y": 2, "hp": 3, "hunger": 4, "stamina": 5, "mood": 6, "space": 7}
        e_cols = {"type": 0, "x": 1, "y": 2, "hp": 3, "food": 4, "space": 5}
        specs_h = {"hp": FieldSpec(0.0, 100.0), "hunger": FieldSpec(0.0, 100.0), "stamina": FieldSpec(0.0, 100.0),
                   "mood": FieldSpec(0.0, 100.0), "type": FieldSpec(0, 8, integer=True, mode="reject")}
        specs_e = {"hp": FieldSpec(0.0, 100.0), "food": FieldSpec(0.0, 1000.0), "type": FieldSpec(0, 100, integer=True, mode="reject")}
        tables = [Table("humans", torch.zeros((humans, 8)), h_cols, type_col="type", pos_cols=("x", "y"), space_col="space",
                        id_prefix="h", field_specs=specs_h, indexed=True),
                  Table("entities", torch.zeros((entities, 6)), e_cols, type_col="type", pos_cols=("x", "y"), space_col="space",
                        id_prefix="e", field_specs=specs_e, indexed=True)]
        return cls(seed, tables, **kwargs)

    # time and randomness -------------------------------------------------------
    @property
    def clock(self) -> Clock:
        return self._clock

    @property
    def tick(self) -> int:
        return self._clock.tick

    def rng(self, system: str, entity_id=0) -> Stream:
        return make_rng(self.seed, self.tick, system, entity_id)

    def uniform_for_ids(self, system: str, ids, salt: int = 0) -> np.ndarray:
        return uniform_for_ids(self.seed, self.tick, system, ids, salt)

    def normal_for_ids(self, system: str, ids, salt: int = 0) -> np.ndarray:
        return normal_for_ids(self.seed, self.tick, system, ids, salt)

    # space ---------------------------------------------------------------------
    def table(self, name: str) -> Table:
        try:
            return self.tables[name]
        except KeyError:
            raise KeyError(f"world has no table {name!r}; known: {sorted(self.tables)}") from None

    def bounds(self) -> Optional[tuple]:
        """Finite local bounds ``(x0, y0, x1, y1)`` or ``None`` for an unbounded world."""
        return self.frame.bounds

    def centre(self) -> tuple:
        """The finite world's centre, else the view centre (player/camera), else the window origin."""
        frame_centre = self.frame.centre()
        if frame_centre is not None:
            return frame_centre
        return self.view_centre if self.view_centre is not None else (0.0, 0.0)

    def clamp(self, x: float, y: float) -> tuple:
        return self.frame.clamp(float(x), float(y))

    def reindex(self, table_name: str, slots: Optional[Sequence[int]] = None) -> None:
        """Bring the spatial index in line with the tensor for the given rows (all live rows if ``slots`` is None)."""
        table = self.table(table_name)
        if not (table.indexed and table.pos_cols):
            return
        for slot in (table.live_slots() if slots is None else slots):
            entity_id = table.ids[slot]
            if entity_id is None:
                continue
            if not table.is_live_slot(slot):
                self.index.remove(entity_id)
                continue
            x, y = table.position(slot)
            space = int(table.tensor[slot, table.col(table.space_col)]) if table.space_col else self.frame.space
            self.index.insert(entity_id, space, self.frame.to_absolute(x, y))

    def within(self, table_name: str, x: float, y: float, radius: float, space: Optional[int] = None, exclude=()) -> list:
        """Stable ids of ``table_name`` rows within ``radius`` of a local point, in id order.

        Uses the spatial index for indexed tables; for tables the engine mutates behind our back (the adapter) it scans the live
        rows directly, so the answer is never stale. Both paths measure in float64 (exact at any offset).
        """
        table = self.table(table_name)
        skip = set(exclude)
        if table.indexed:
            wanted = self.frame.space if space is None else space
            members = {i for i in table.ids if i is not None}
            ids = self.index.query_radius(wanted, self.frame.to_absolute(x, y), radius, skip)
            return [i for i in ids if i in members]
        xs = table.tensor[:, table.col(table.pos_cols[0])].double()
        ys = table.tensor[:, table.col(table.pos_cols[1])].double()
        near = table.live_mask() & (((xs - x) ** 2 + (ys - y) ** 2) <= float(radius) ** 2)
        if space is not None and table.space_col:
            near &= table.tensor[:, table.col(table.space_col)].long() == int(space)
        ids = [table.ids[s] for s in near.nonzero(as_tuple=False).flatten().tolist() if table.ids[s] is not None and table.ids[s] not in skip]
        return sorted(ids, key=str)

    # state revision ------------------------------------------------------------
    def bump_revision(self) -> int:
        self.revision += 1
        for listener in self._revision_listeners:
            listener(self.revision)
        return self.revision

    def on_revision(self, listener: Callable[[int], None]) -> None:
        self._revision_listeners.append(listener)

    # convenience ---------------------------------------------------------------
    def apply(self, effects, **kwargs):
        return self.effects.apply(effects, **kwargs)

    def add_row(self, table_name: str, entity_id: Optional[str] = None, **fields) -> str:
        """Direct test/setup helper: put a live row into a free slot (bypasses effects; not for systems)."""
        table = self.table(table_name)
        slot = table.free_slot()
        if slot is None:
            raise RuntimeError(f"table {table_name!r} is full")
        entity_id = entity_id or table.new_id()
        table.tensor[slot] = 0.0
        for key, value in fields.items():
            table.tensor[slot, table.col(key)] = float(value)
        if table.tensor[slot, table.col(table.type_col)] <= 0:
            table.tensor[slot, table.col(table.type_col)] = 1.0
        table.ids[slot] = entity_id
        self.reindex(table_name, [slot])
        return entity_id

    def observe_counts(self) -> dict:
        return {name: len(t.live_slots()) for name, t in self.tables.items()}
