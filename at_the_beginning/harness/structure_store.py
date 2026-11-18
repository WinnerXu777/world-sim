"""1008 dormant structure store (design: ``1008_structure_store_gap.md``): built structures leave the tensors with their chunk and come back with it.

Flag ``EDEN_STRUCTURE_STORE=1`` (default off, needs ``EDEN_WINDOW=1``). A structure the game built (type in ``STRUCTURE_TYPES``, a runtime uid such as
``e_000123``, not one of the chunk's generated features) is a row no chunk owns. Without the store it stays in ``m_tensor`` for good and counts against the
row budget. With it, ``WindowManager.unload`` calls ``stash``: the full row (every column but the position, generation and space), its geometry and the
inventory-seeding markers move into a record keyed by chunk, with the position as an offset from the chunk's corner (so a re-base needs no work), and the
row is released. ``integrate`` calls ``restore``: the rows are allocated again under the same uids, the columns written back, the geometry registered. The
chunk delta stays what it was (generated features only).

Saving (USER-DEC-6): a store with records is saved as world format 4 (``export`` / ``load`` / ``validate``): the window section gains a ``structures`` key and
``world_snapshot`` writes schema 4; an empty store saves as format 3, byte for byte as before. Positions are offsets from the chunk's corner, so a re-base between
the save and the load needs no work. Nothing in the store is touched with the flag off.
"""
from __future__ import annotations

import copy
import math
import os

try:
    import genesis_config as cfg
    import map_geo
    from . import calendar as _calendar
    from .numerics import window_enabled
    from systems.worldgen.rings import ChunkCoord
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg
    from at_the_beginning import map_geo
    from at_the_beginning.harness import calendar as _calendar
    from at_the_beginning.harness.numerics import window_enabled
    from at_the_beginning.systems.worldgen.rings import ChunkCoord

FLAG = "EDEN_STRUCTURE_STORE"
CHUNK_UNITS = 256.0

# What a dormant structure loses per game day while its chunk is away, and the floor it never drops below (fraction of its durability when it left).
# No live structure-decay rule exists in the tree yet (2.D1 adds it): the rate is data and zero until then.
DECAY_PER_DAY = 0.0
DECAY_FLOOR = 0.10

SKIP_COLUMNS = (cfg.CX, cfg.CY, cfg.M_GEN, cfg.M_SPACE)          # position (kept as an offset), generation (the slot's), space (always 0 here)

RECORD_KEYS = {"uid", "type", "cols", "offset", "tick", "geo", "seeded"}
INVALID_SECTION = "Invalid dormant structure store section"


def enabled() -> bool:
    """Read at call time. Needs the window: the store is keyed by chunk."""
    return os.environ.get(FLAG, "") == "1" and window_enabled()


class StructureStore:
    def __init__(self, manager):
        self.manager = manager
        self.records: dict = {}                       # ChunkCoord -> [record]
        self.counters = {"stashed": 0, "restored": 0}

    # -- queries ---------------------------------------------------------------------------------------------------------
    def estimate(self, coord) -> int:
        return len(self.records.get(coord, ())) if enabled() else 0

    def count(self) -> int:
        return sum(len(v) for v in self.records.values())

    # -- unload ----------------------------------------------------------------------------------------------------------
    def stash(self, coord, generated_uids) -> int:
        """Move the built structures standing in ``coord`` out of the tensors. Returns how many."""
        if not enabled():
            return 0
        engine = self.manager.engine
        m = engine.state.m_tensor
        bx, by = self.manager._local_origin(coord)
        types = m[:cfg.MAX_ENTITIES, cfg.M_TYPE]
        inside = ((types >= min(cfg.STRUCTURE_TYPES)) & (types <= max(cfg.STRUCTURE_TYPES)) & (m[:cfg.MAX_ENTITIES, cfg.M_SPACE] == 0)
                  & (m[:cfg.MAX_ENTITIES, cfg.CX] >= bx) & (m[:cfg.MAX_ENTITIES, cfg.CX] < bx + CHUNK_UNITS)
                  & (m[:cfg.MAX_ENTITIES, cfg.CY] >= by) & (m[:cfg.MAX_ENTITIES, cfg.CY] < by + CHUNK_UNITS))
        skip = set(generated_uids)
        slots = [s for s in inside.nonzero(as_tuple=False).flatten().tolist() if engine._entity_uid_by_slot[s] and engine._entity_uid_by_slot[s] not in skip]
        if not slots:
            return 0
        seeded = engine._inventory_seeded_containers
        records = []
        for slot in slots:
            uid = str(engine._entity_uid_by_slot[slot])
            row = m[slot].tolist()
            geo = map_geo.MAP_GEO.get(slot)
            records.append({
                "uid": uid, "type": row[cfg.M_TYPE], "cols": {i: v for i, v in enumerate(row) if i not in SKIP_COLUMNS and i != cfg.M_TYPE},
                "offset": [row[cfg.CX] - bx, row[cfg.CY] - by], "tick": int(engine.tick),
                "geo": None if geo is None else {"shape": geo["shape"], "r": float(geo["r"]),
                                                 "points": [[p[0] - bx, p[1] - by] for p in geo["points"]]},
                "seeded": [key for key in (uid, f"stock:{uid}") if key in seeded]})
        self.manager.allocator.release(slots)          # forgets geometry, uid caches, events; the record above is now the only copy
        self.records.setdefault(coord, []).extend(records)
        self.counters["stashed"] += len(records)
        return len(records)

    # -- integrate -------------------------------------------------------------------------------------------------------
    def restore(self, coord) -> int:
        """Bring the structures of ``coord`` back (after its generated rows). Returns how many."""
        records = self.records.pop(coord, None)
        if not records:
            return 0
        engine = self.manager.engine
        bx, by = self.manager._local_origin(coord)
        uids = [r["uid"] for r in records]
        columns: dict = {}
        for index, record in enumerate(records):
            for col, value in record["cols"].items():
                columns.setdefault(int(col), [0.0] * len(records))[index] = float(value)
        slots = self.manager.allocator.allocate(uids, [r["type"] for r in records], [bx + r["offset"][0] for r in records],
                                                [by + r["offset"][1] for r in records], columns)
        self.manager.allocator.owned.difference_update(slots)      # a built structure was never the window's row (the generated ones are)
        days = self._days_away(records)
        for slot, record, away in zip(slots, records, days):
            engine._inventory_seeded_containers.update(record["seeded"])
            geo = record["geo"]
            if geo is not None:
                m = engine.state.m_tensor
                map_geo.register_entity(slot, geo["shape"], float(m[slot, cfg.CX]), float(m[slot, cfg.CY]), geo["r"],
                                        [(bx + p[0], by + p[1]) for p in geo["points"]] or None, device=engine.state.device)
            self._catch_up(slot, record, away)
        self.counters["restored"] += len(records)
        return len(records)

    def _days_away(self, records) -> list:
        day = int(_calendar.active().day_ticks)
        now = int(self.manager.engine.tick)
        return [max(0, now - int(r["tick"])) // day for r in records]

    def _catch_up(self, slot, record, days) -> None:
        """Closed-form decay for the days away, never below ``DECAY_FLOOR`` of the durability the structure left with."""
        if DECAY_PER_DAY <= 0.0 or days <= 0:
            return
        m = self.manager.engine.state.m_tensor
        left_with = float(record["cols"].get(cfg.S_DURABILITY, 0.0))
        m[slot, cfg.S_DURABILITY] = max(min(left_with, float(m[slot, cfg.S_DURABILITY])) - DECAY_PER_DAY * days, DECAY_FLOOR * left_with)

    # -- save (world format 4) -------------------------------------------------------------------------------------------
    def export(self) -> list:
        """Plain data: ``[[chunk x, chunk y, [record, ...]], ...]`` in chunk order (copies; the codec stores it as it is)."""
        return [[coord.x, coord.y, copy.deepcopy(items)] for coord, items in sorted(self.records.items(), key=lambda kv: (kv[0].x, kv[0].y)) if items]

    def load(self, data) -> None:
        """Take an ``export`` back (validated by ``validate`` first). The records keep their chunk-relative offsets."""
        self.records = {ChunkCoord(int(x), int(y)): copy.deepcopy(items) for x, y, items in (data or ())}

    @staticmethod
    def validate(data) -> None:
        """Refuse a malformed section; changes nothing. A record is what ``stash`` writes: uid, type, columns (index -> value), offset from the chunk corner, the tick it
        left, its geometry or None, and the inventory-seeding keys."""
        def number(value) -> bool:
            return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

        if not isinstance(data, list):
            raise ValueError(INVALID_SECTION)
        seen = set()
        columns = cfg.MAP_TENSOR_COLS
        for entry in data:
            if not (isinstance(entry, list) and len(entry) == 3 and isinstance(entry[0], int) and isinstance(entry[1], int) and isinstance(entry[2], list) and entry[2]):
                raise ValueError(INVALID_SECTION)
            for record in entry[2]:
                if not (isinstance(record, dict) and set(record) == RECORD_KEYS and isinstance(record["uid"], str) and record["uid"] and record["uid"] not in seen):
                    raise ValueError(INVALID_SECTION)
                seen.add(record["uid"])
                if not (number(record["type"]) and min(cfg.STRUCTURE_TYPES) <= record["type"] <= max(cfg.STRUCTURE_TYPES)):
                    raise ValueError(INVALID_SECTION)
                cols = record["cols"]
                if not (isinstance(cols, dict) and all(isinstance(k, int) and 0 <= k < columns and number(v) for k, v in cols.items())):
                    raise ValueError(INVALID_SECTION)
                offset = record["offset"]
                if not (isinstance(offset, list) and len(offset) == 2 and all(number(v) for v in offset) and isinstance(record["tick"], int) and record["tick"] >= 0):
                    raise ValueError(INVALID_SECTION)
                geo = record["geo"]
                if geo is not None and not (isinstance(geo, dict) and set(geo) == {"shape", "r", "points"} and isinstance(geo["shape"], str) and number(geo["r"])
                                            and isinstance(geo["points"], list) and all(isinstance(p, list) and len(p) == 2 and all(number(v) for v in p) for p in geo["points"])):
                    raise ValueError(INVALID_SECTION)
                if not (isinstance(record["seeded"], list) and all(isinstance(k, str) for k in record["seeded"])):
                    raise ValueError(INVALID_SECTION)
