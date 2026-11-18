"""1008 Phase 2 (``1008_creatures_gap.md`` section 6): creatures in the streaming window. Flag ``EDEN_CREATURES=1`` (default off, needs ``EDEN_WINDOW=1``).

Three jobs, all keyed by chunk and all closed-form (nothing replays ticks):

* **populate** (``on_integrate`` / ``tick``): a chunk that has not been populated, or whose creatures have been away for ``RESPAWN_DAYS``, gets the creatures of its spawn plan
  (``systems.creatures.spawn.plan``, a pure function of the chunk document) that are neither alive nor stored, up to the creature row quota;
* **stash** (``on_unload``, ``sweep``): every creature standing in a chunk that leaves the window, or standing outside all integrated chunks (a wanderer), moves out of the tensors
  into a record of the chunk it stands in (position as an offset from the chunk corner, so a re-base needs nothing). The rows are released;
* **restore** (``on_integrate``): the records of the chunk come back with a closed-form catch-up (age advances, hunger and thirst rise but stay under the starvation threshold, a
  creature past its life expectancy does not come back).

Creature rows are NOT rows of the window budget: they are taken out of ``allocator.owned`` and counted against their own quota (``EDEN_CREATURE_ROWS``, default 96).

Saving (decision c3, option a): the records, the populated ledger and the kill ledger are not saved. Creatures standing in the integrated chunks are ordinary rows and the world saves
them with the tensors; after a load the integrated chunks are populated again from the plan, skipping the uids that are alive (so nothing doubles), and a creature that was killed
and has no row any more comes back. Wounds, kills and wandering of stored creatures are lost on save/continue. No new refusal text, no new world format.

Species whose table row says ``brain: table`` need the behaviour kernel (``systems.creatures.kernel_ready``): until it exists only the legacy-brain species are spawned.
"""
from __future__ import annotations

import os

import torch

try:
    import genesis_config as cfg
    from . import calendar as _calendar
    from . import dormancy as _dormancy
    from .numerics import window_enabled
    from systems import creatures as _creatures
    from systems.creatures import spawn as _spawn, table as _table
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg
    from at_the_beginning.harness import calendar as _calendar
    from at_the_beginning.harness import dormancy as _dormancy
    from at_the_beginning.harness.numerics import window_enabled
    from at_the_beginning.systems import creatures as _creatures
    from at_the_beginning.systems.creatures import spawn as _spawn, table as _table

ROWS_ENV = "EDEN_CREATURE_ROWS"
DEFAULT_ROWS = 96
RESPAWN_DAYS = 2                # a populated chunk refills killed creatures after this many game days without a visit
SWEEP_EVERY = 20                # ticks between the wanderer sweeps
MAX_RECORDS = 512               # stored creatures kept; the oldest go first (a record for a chunk nobody returns to is not worth keeping)
CHUNK_UNITS = 256.0
SKIP_COLUMNS = (cfg.CX, cfg.CY, cfg.M_GEN, cfg.M_SPACE, cfg.M_TYPE)
HUNGER_CAP, THIRST_CAP = 60.0, 60.0          # well under the damage thresholds (90 and 90): a creature is never killed by being stored


def enabled() -> bool:
    return _creatures.enabled() and window_enabled()


def row_quota() -> int:
    try:
        return max(0, int(os.environ.get(ROWS_ENV, DEFAULT_ROWS)))
    except ValueError:
        return DEFAULT_ROWS


class CreatureStore:
    def __init__(self, manager):
        self.manager = manager
        self.records: dict = {}              # ChunkCoord -> [record]
        self.index: dict = {}                # uid -> ChunkCoord of its record
        self.populated: dict = {}            # ChunkCoord -> tick of the last populate
        self.counters = {"populated": 0, "stashed": 0, "restored": 0, "died_away": 0, "skipped_quota": 0, "skipped_rows": 0, "dropped_records": 0, "skipped_kernel": 0}
        self._ids = None

    # -- queries ---------------------------------------------------------------------------------------------------------
    def type_ids(self) -> torch.Tensor:
        if self._ids is None:
            self._ids = torch.tensor(sorted(r["id"] for r in _table.CREATURES.values()), dtype=torch.float32)
        return self._ids

    def live_mask(self) -> torch.Tensor:
        m = self.manager.engine.state.m_tensor
        return torch.isin(m[:cfg.MAX_ENTITIES, cfg.M_TYPE], self.type_ids().to(m.device)) & (m[:cfg.MAX_ENTITIES, cfg.M_SPACE] == 0)

    def live_count(self) -> int:
        return int(self.live_mask().sum())

    def count(self) -> int:
        return sum(len(v) for v in self.records.values())

    def estimate(self, coord) -> int:
        return len(self.records.get(coord, ())) if enabled() else 0

    def _live_uids(self) -> set:
        uids = self.manager.engine._entity_uid_by_slot
        return {uids[s] for s in self.live_mask().nonzero(as_tuple=False).flatten().tolist() if uids[s]}

    # -- integrate -------------------------------------------------------------------------------------------------------
    def on_integrate(self, coord, chunk) -> int:
        """Records of ``coord`` come back, then the plan fills what is missing. Returns how many rows were added."""
        if not enabled():
            return 0
        added = self.restore(coord)
        added += self.populate(coord, chunk)
        return added

    def restore(self, coord) -> int:
        records = self.records.pop(coord, None)
        if not records:
            return 0
        for record in records:
            self.index.pop(record["uid"], None)
        engine = self.manager.engine
        now = int(engine.tick)
        taken = self._live_uids()
        keep, back = [], []
        for record in records:
            if record["uid"] in taken:
                continue                                                   # the same creature is alive elsewhere: the record is stale
            cols = self._catch_up(record, now)
            if cols is None:
                self.counters["died_away"] += 1
                continue
            back.append((record, cols))
        room = self.manager.allocator.headroom()                          # a stored creature returns whenever there is a row; the quota only limits new ones
        for record, cols in back[room:]:
            keep.append(record)                                            # no row for it now: it stays stored
        back = back[:room]
        if keep:
            self.records.setdefault(coord, []).extend(keep)
            for record in keep:
                self.index[record["uid"]] = coord
            self.counters["skipped_rows"] += len(keep)
        return self._allocate(coord, [(r["uid"], r["type"], r["offset"][0], r["offset"][1], cols) for r, cols in back], restored=True)

    def _catch_up(self, record, now):
        cols = {int(c): float(v) for c, v in record["cols"].items()}
        elapsed = max(0, now - int(record["tick"]))
        cols[cfg.A_AGE] = cols.get(cfg.A_AGE, 0.0) + elapsed * _calendar.age_step()
        if cols[cfg.A_AGE] > cols.get(cfg.A_LIFE_EXP, 1e9):
            return None
        need = _calendar.rate_scale("needs")
        cols[cfg.A_HUNGER] = min(HUNGER_CAP, max(cols.get(cfg.A_HUNGER, 0.0), cols.get(cfg.A_HUNGER, 0.0) + cfg.ANIMAL_HUNGER_TICK_RATE * need * elapsed))
        cols[cfg.A_THIRST] = min(THIRST_CAP, max(cols.get(cfg.A_THIRST, 0.0), cols.get(cfg.A_THIRST, 0.0) + cfg.ANIMAL_THIRST_TICK_RATE * need * elapsed))
        cols[cfg.A_COOLDOWN] = max(0.0, cols.get(cfg.A_COOLDOWN, 0.0) - elapsed * _calendar.cooldown_decay_rate())
        return cols

    def populate(self, coord, chunk) -> int:
        engine = self.manager.engine
        now = int(engine.tick)
        last = self.populated.get(coord)
        if last is not None and now - last < RESPAWN_DAYS * int(_calendar.active().day_ticks):
            return 0
        self.populated[coord] = now
        present = self._live_uids() | set(self.index)
        wanted = []
        for rec in _spawn.plan(chunk.document):
            if rec["uid"] in present:
                continue
            if _table.CREATURES[rec["species"]]["brain"] == "table" and not _creatures.kernel_ready():
                self.counters["skipped_kernel"] += 1
                continue
            wanted.append(rec)
        room = min(self.manager.allocator.headroom(), max(0, row_quota() - self.live_count()))
        if len(wanted) > room:
            self.counters["skipped_quota"] += len(wanted) - room
            wanted = wanted[:room]
        rows = []
        for rec in wanted:
            row = _table.CREATURES[rec["species"]]
            cols = {cfg.M_HP: rec["hp"], cfg.SCALE: max(row["footprint"]) / 2.0, cfg.A_AGE: rec["age"], cfg.A_LIFE_EXP: rec["life_exp"], cfg.A_SEX: rec["sex"],
                    cfg.A_COOLDOWN: 0.0, cfg.A_HUNGER: 10.0, cfg.A_AGGRESSION: float(row["aggro"]), cfg.A_THIRST: 0.0,
                    _table.C_VARIANT: rec["variant"], _table.C_GROUP: rec["group"]}
            rows.append((rec["uid"], rec["id"], rec["x"], rec["y"], cols))
        added = self._allocate(coord, rows, restored=False)
        self.counters["populated"] += added
        return added

    def _allocate(self, coord, rows, *, restored) -> int:
        if not rows:
            return 0
        bx, by = self.manager._local_origin(coord)
        columns: dict = {}
        for index, (_, _, _, _, cols) in enumerate(rows):
            for col, value in cols.items():
                columns.setdefault(int(col), [0.0] * len(rows))[index] = float(value)
        slots = self.manager.allocator.allocate([r[0] for r in rows], [r[1] for r in rows], [bx + r[2] for r in rows], [by + r[3] for r in rows], columns)
        self.manager.allocator.owned.difference_update(slots)           # a creature is not one of the window's chunk rows
        if restored:
            self.counters["restored"] += len(slots)
        return len(slots)

    # -- unload / sweep --------------------------------------------------------------------------------------------------
    def on_unload(self, coord) -> int:
        """Stash the creatures standing in ``coord`` (called before its rows are released)."""
        if not enabled():
            return 0
        m = self.manager.engine.state.m_tensor
        bx, by = self.manager._local_origin(coord)
        inside = (self.live_mask() & (m[:cfg.MAX_ENTITIES, cfg.CX] >= bx) & (m[:cfg.MAX_ENTITIES, cfg.CX] < bx + CHUNK_UNITS)
                  & (m[:cfg.MAX_ENTITIES, cfg.CY] >= by) & (m[:cfg.MAX_ENTITIES, cfg.CY] < by + CHUNK_UNITS))
        return self._stash(inside.nonzero(as_tuple=False).flatten().tolist())

    def tick(self) -> None:
        """Once per window tick: every ``SWEEP_EVERY`` ticks stash wanderers; populate one integrated chunk that was never populated (after a load)."""
        if not enabled():
            return
        engine = self.manager.engine
        if int(engine.tick) % SWEEP_EVERY == 0:
            self.sweep()
        for coord in self.manager.chunks:
            if coord not in self.populated:
                chunk = self.manager.service.peek(coord)
                if chunk is not None:
                    self.restore(coord)
                    self.populate(coord, chunk)
                    break

    def sweep(self) -> int:
        """Creatures standing outside every integrated chunk go into the record of the chunk they stand in."""
        m = self.manager.engine.state.m_tensor
        outside = _dormancy._outside(self.manager, m, self.live_mask_full(), cfg.CX, cfg.CY)
        return self._stash(outside.nonzero(as_tuple=False).flatten().tolist())

    def live_mask_full(self) -> torch.Tensor:
        m = self.manager.engine.state.m_tensor
        full = torch.zeros(m.shape[0], dtype=torch.bool, device=m.device)
        full[:cfg.MAX_ENTITIES] = self.live_mask()
        return full

    def _stash(self, slots) -> int:
        if not slots:
            return 0
        engine = self.manager.engine
        m = engine.state.m_tensor
        ox, oy = self.manager.frame.origin
        stashed = 0
        for slot in slots:
            uid = engine._entity_uid_by_slot[slot]
            row = m[slot].tolist()
            if not uid or row[cfg.M_TYPE] <= 0.0:
                continue
            cell_x, cell_y = int(row[cfg.CX] // CHUNK_UNITS), int(row[cfg.CY] // CHUNK_UNITS)
            coord = _make_coord(cell_x + ox, cell_y + oy)
            record = {"uid": str(uid), "type": row[cfg.M_TYPE], "cols": {i: v for i, v in enumerate(row) if i not in SKIP_COLUMNS},
                      "offset": [row[cfg.CX] - cell_x * CHUNK_UNITS, row[cfg.CY] - cell_y * CHUNK_UNITS], "tick": int(engine.tick)}
            self.records.setdefault(coord, []).append(record)
            self.index[record["uid"]] = coord
            stashed += 1
        self.manager.allocator.release(slots)
        self.counters["stashed"] += stashed
        self._trim()
        return stashed

    def _trim(self) -> None:
        excess = self.count() - MAX_RECORDS
        if excess <= 0:
            return
        oldest = sorted(((r["tick"], coord, r["uid"]) for coord, items in self.records.items() for r in items))[:excess]
        for _, coord, uid in oldest:
            self.records[coord] = [r for r in self.records[coord] if r["uid"] != uid]
            if not self.records[coord]:
                del self.records[coord]
            self.index.pop(uid, None)
        self.counters["dropped_records"] += excess

    # -- load ------------------------------------------------------------------------------------------------------------
    def after_load(self) -> None:
        """A world was loaded: nothing of the store was saved; the integrated chunks are populated again lazily (``tick``)."""
        self.records.clear()
        self.index.clear()
        self.populated.clear()


def _make_coord(x, y):
    try:
        from systems.worldgen.rings import ChunkCoord
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.systems.worldgen.rings import ChunkCoord
    return ChunkCoord(int(x), int(y))
