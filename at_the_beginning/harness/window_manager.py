"""1008 WS-D P5 (c): the streaming window. ``WindowManager`` keeps the chunks around the residents integrated in the engine.

One step hook (``engine_hooks.window_hook``) calls ``WindowManager.tick`` once per engine tick:

1. plan (``rings.plan_stream``) when a resident changed chunk or every ``PLAN_EVERY_TICKS`` ticks, and hand the plan to the ``ChunkService``;
2. ``service.pump()`` once (the only call that can block; inline generation only with ``workers=0``, as in tests);
3. integrate at most ONE chunk whose bytes are ready (nearest first), else unload at most ONE (farthest first).

Integrating a chunk writes its feature entities as rows (``SlotAllocator``, ids ``c<cx>_<cy>:<kind><n>`` from the chunk document, row type and
columns from ``systems.map.resources.spec_for`` so a generated berry patch and an authored one are the same row), registers their
``map_geo`` circles, and keeps the chunk's wall boxes in a per-chunk list. Unloading stores what changed against the generated state (the chunk
delta, decision Q1: columns that differ, or ``removed``), releases the rows through ``release_slots`` and drops the boxes. The wall boxes of all integrated chunks plus
the void boxes (one thin box along every integrated edge whose neighbour is not integrated, so nothing can walk into a chunk that does not exist yet) are
published to the movement contract as ``engine._window_contract`` (``systems/movement/spatial._compose`` appends them; the revision is cached and
changes only with the integrated set).

Positions are window-local floats: ``local = (chunk - frame.origin) * 256 + chunk_local``. When the residents drift more than ``REBASE_AT`` chunks
from the origin the window re-bases (``rebase``, between ticks, at the start of ``tick``): the origin moves to the residents' chunk and every
space-0 position the engine holds shifts by the same whole number of chunks (tensor rows, map_geo shapes and tile owners, chunk and void boxes,
the registered primary map, uid-keyed resident memory, pending nature event, camera window, previous-position cache), then the model plane shifts
its own (``systems.actions.rebase.rebase_model_plane``). Animals are step (c2)
(spawn entries are materialised near residents); rows the game creates at run time (built structures, regrown forests) are plain legacy rows and are
not owned by a chunk. Nothing here runs unless ``EDEN_WINDOW=1`` (``engine_hooks.install``).
"""
from __future__ import annotations

import collections
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Optional

try:
    import genesis_config as cfg
    import map_geo
    from systems.map import resources as map_resources
    from systems.worldgen import PinnedSet, starter_village_area
    from systems.worldgen.rings import Actor, ChunkCoord, RingConfig, plan_stream
    from systems.worldgen.service import ChunkService
    from world_map.resources import check_resource
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg
    from at_the_beginning import map_geo
    from at_the_beginning.systems.map import resources as map_resources
    from at_the_beginning.systems.worldgen import PinnedSet, starter_village_area
    from at_the_beginning.systems.worldgen.rings import Actor, ChunkCoord, RingConfig, plan_stream
    from at_the_beginning.systems.worldgen.service import ChunkService
    from at_the_beginning.world_map.resources import check_resource
from .frame import SpaceFrame
from .creature_store import CreatureStore
from . import temperature
from .structure_store import StructureStore
from .window import REBASE_AT, WINDOW_FRAME, WINDOW_ROW_BUDGET, SlotAllocator, release_slots

try:
    import torch
    from systems.movement.map_contract import MAP_CONTRACTS
except ImportError:  # pragma: no cover - package import fallback
    import torch
    from at_the_beginning.systems.movement.map_contract import MAP_CONTRACTS

LOG_TAIL = 64
PLAN_EVERY_TICKS = 4
VOID_THICKNESS = 2.0
WALL_HEIGHT = 2.4
SEED_ENV = "EDEN_WORLD_SEED"
WORKERS_ENV = "EDEN_CHUNK_WORKERS"
DEFAULT_SEED = 1008
SKIP_DELTA_COLUMNS = (cfg.M_GEN, cfg.M_SPACE, cfg.CX, cfg.CY)   # never part of a chunk delta (positions are window-local and chunk entities are static)


@dataclass
class ChunkState:
    """What the engine holds for one integrated chunk."""
    coord: ChunkCoord
    sha256: str
    slots: list
    uids: list
    boxes: list                                       # wall boxes in window-local coordinates
    baseline: list = field(default_factory=list)      # generated row values per slot (list of lists), to compute the delta on unload


def default_service(seed: Optional[int] = None, workers: Optional[int] = None) -> ChunkService:
    seed = int(os.environ.get(SEED_ENV, DEFAULT_SEED)) if seed is None else int(seed)
    workers = int(os.environ.get(WORKERS_ENV, "2")) if workers is None else int(workers)
    return ChunkService(seed, pinned=PinnedSet([starter_village_area()]), workers=workers)


class WindowManager:
    def __init__(self, engine, service: ChunkService, *, ring: RingConfig = RingConfig(), budget: int = WINDOW_ROW_BUDGET,
                 plan_every: int = PLAN_EVERY_TICKS):
        self.engine = engine
        self.service = service
        self.ring = ring
        self.plan_every = int(plan_every)
        self.world_epoch = engine.world_epoch
        self.frame = SpaceFrame(float(ring.chunk_units), origin=(0, 0))
        self.allocator = SlotAllocator(engine, budget)
        self.structures = StructureStore(self)       # EDEN_STRUCTURE_STORE: built structures of chunks that are not integrated
        self.creatures = CreatureStore(self)         # EDEN_CREATURES: animals of the spawn plan, stored per chunk while the chunk is away
        self.chunks: dict = {}                        # ChunkCoord -> ChunkState, insertion order = integration order
        self.deltas: dict = {}                        # ChunkCoord -> {uid: {"removed": True} | {"cols": {col: value}}}
        self.log: list = []                           # (tick, "integrate" | "unload" | "rebase", cx, cy): what a replay feeds instead of the service
        self.epoch = 0                                # incremented by every re-base: a client that cached window-local positions must refetch
        self.counters = collections.Counter()
        self.counters["void_hits"] = 0
        self.counters["void_hits_player"] = 0
        self.counters["void_hits_resident"] = 0
        self.counters["wall_hits"] = 0
        self.counters["wall_hits_player"] = 0
        self.counters["wall_hits_resident"] = 0
        self.pump_ms: collections.deque = collections.deque(maxlen=4096)
        self.step_ms: collections.deque = collections.deque(maxlen=4096)
        self._plan = None
        self._plan_key = None
        self._contract_cache = None
        engine._window = self
        self._set_primary_shift(0.0, 0.0)             # a new world starts with its primary map where it was registered
        self._publish()

    # ------------------------------------------------------------------ residents
    def actors(self) -> list:
        """Space-0 humans as absolute positions (units); the rings are built around them."""
        h = self.engine.state.h_tensor
        live = (h[:, cfg.TYPE] == cfg.AGENT_TYPE_HUMAN) & (h[:, cfg.H_SPACE] == 0)
        size = float(self.ring.chunk_units)
        ox, oy = self.frame.origin
        return [Actor(ox * size + x, oy * size + y) for x, y in h[live][:, [cfg.X, cfg.Y]].tolist()]

    def controlled_slots(self) -> list:
        """Slots of the humans a player is attached to: controlled right now (a session), or the avatar a controller incarnated (it stays the
        player's body when the session lapses after a few idle seconds, so the window does not snap back to the village under a parked avatar)."""
        h = self.engine.state.h_tensor
        slots = []
        sessions = getattr(getattr(self.engine, "player_control", None), "sessions_by_controller", None) or {}
        for session in sessions.values():
            slot = session.get("slot") if hasattr(session, "get") and session.get("target_kind") == "human" else None
            if isinstance(slot, int) and 0 <= slot < h.shape[0]:
                slots.append(slot)
        avatars = getattr(self.engine, "_incarnated_human_by_controller", None) or {}
        uids = self.engine._human_uid_by_slot
        for record in avatars.values():
            uid = str((record or {}).get("human_id", "")).strip() if hasattr(record, "get") else ""
            if uid and uid in uids:
                slots.append(uids.index(uid))
        return sorted(set(slots))

    def controlled_actors(self) -> list:
        """Space-0 humans a player is attached to (``controlled_slots``) as absolute positions. Empty with no player."""
        h = self.engine.state.h_tensor
        size = float(self.ring.chunk_units)
        ox, oy = self.frame.origin
        found = []
        for slot in self.controlled_slots():
            row = h[slot]
            if float(row[cfg.TYPE]) != float(cfg.AGENT_TYPE_HUMAN) or float(row[cfg.H_SPACE]) != 0.0:
                continue
            found.append(Actor(ox * size + float(row[cfg.X]), oy * size + float(row[cfg.Y])))
        return found

    # ------------------------------------------------------------------ the tick
    def tick(self) -> None:
        started = time.perf_counter()
        self.rebase_if_due()
        actors = self.actors()
        if actors:
            key = tuple(sorted({(c.x, c.y) for c in (self._chunk_of(a) for a in actors)}))
            if self._plan is None or key != self._plan_key or self.engine.tick % self.plan_every == 0:
                self._plan = plan_stream(actors, loaded=self.chunks.keys(), cfg=self.ring)
                self._plan_key = key
                self.service.apply_plan(self._plan)
        pumped = time.perf_counter()
        self.service.pump()
        self.pump_ms.append((time.perf_counter() - pumped) * 1e3)
        if self._plan is not None:
            self._advance(self._plan)
        self.creatures.tick()                          # EDEN_CREATURES: stash wanderers, populate chunks that were never populated (a no-op with the flag off)
        self.step_ms.append((time.perf_counter() - started) * 1e3)

    def _chunk_of(self, actor) -> ChunkCoord:
        size = float(self.ring.chunk_units)
        return ChunkCoord(int(actor.x // size), int(actor.y // size))

    def _advance(self, plan) -> None:
        for coord in plan.integrate:
            if coord in self.chunks:
                continue
            chunk = self.service.peek(coord)
            if chunk is None:
                continue
            if not self._in_frame(coord):
                self.counters["out_of_frame"] += 1
                continue
            if self.allocator.headroom() < self._row_estimate(chunk) + self.structures.estimate(coord):
                self.counters["deferred_budget"] += 1
                return
            self.integrate(coord, chunk)
            return
        for coord in list(self.chunks):
            if not self._in_frame(coord):                  # a re-base followed a player away: what lies outside the frame now cannot be kept
                self.unload(coord)
                self.counters["unloaded_out_of_frame"] += 1
                return
        for coord in plan.unload:
            if coord in self.chunks:
                self.unload(coord)
                return

    def _in_frame(self, coord) -> bool:
        """True when the chunk's local square lies inside the fixed tile frame (map_geo would clip anything outside it)."""
        grid_w, grid_h, (col0, row0) = WINDOW_FRAME
        tile = float(map_geo.TILE_SIZE)
        x0, y0 = self._local_origin(coord)
        size = float(self.ring.chunk_units)
        return col0 * tile <= x0 and x0 + size <= (col0 + grid_w) * tile and row0 * tile <= y0 and y0 + size <= (row0 + grid_h) * tile

    @staticmethod
    def _row_estimate(chunk) -> int:
        return sum(1 for e in chunk.entities if e.get("interactive"))

    # ------------------------------------------------------------------ integrate / unload
    def _local_origin(self, coord) -> tuple:
        size = float(self.ring.chunk_units)
        return (coord.x - self.frame.origin[0]) * size, (coord.y - self.frame.origin[1]) * size

    def _entity_rows(self, chunk) -> list:
        """(entity dict, spec) for every entity of the chunk that becomes a row, in document order."""
        rows = []
        for entity in chunk.entities:
            if not entity.get("interactive"):
                continue
            problems = []
            decl = check_resource(entity, entity.get("kind", ""), True, entity.get("id", "?"), lambda path, msg: problems.append((path, msg)))
            spec = map_resources.spec_for({"kind": entity.get("kind", ""), "resource": decl or {}})
            if spec is None or problems:
                self.counters["entities_skipped"] += 1
                continue
            rows.append((entity, spec))
        return rows

    def integrate(self, coord, chunk) -> None:
        started = time.perf_counter()
        bx, by = self._local_origin(coord)
        delta = self.deltas.get(coord, {})
        kept = [(e, s) for e, s in self._entity_rows(chunk) if not delta.get(e["id"], {}).get("removed")]
        uids = [e["id"] for e, _ in kept]
        columns: dict = {}
        for index, (_, spec) in enumerate(kept):
            for col, value in {**spec["col_vals"], cfg.M_HP: 100.0, cfg.SCALE: float(spec["scale"])}.items():
                columns.setdefault(int(col), [0.0] * len(kept))[index] = float(value)
        slots = self.allocator.allocate(uids, [spec["m_type"] for _, spec in kept], [bx + e["position"][0] for e, _ in kept],
                                        [by + e["position"][1] for e, _ in kept], columns) if kept else []
        m = self.engine.state.m_tensor
        baseline = []
        for slot, uid, (entity, spec) in zip(slots, uids, kept):
            baseline.append(m[slot].tolist())                                       # generated state, before the stored delta is applied
            for col, value in delta.get(uid, {}).get("cols", {}).items():
                m[slot, int(col)] = float(value)
            map_geo.register_entity(slot, "circle", float(m[slot, cfg.CX]), float(m[slot, cfg.CY]), float(spec["scale"]), device=self.engine.state.device)
        boxes = [{"id": w["id"], "min": [bx + w["min"][0], by + w["min"][1]], "max": [bx + w["max"][0], by + w["max"][1]],
                  "height": float(w.get("height", WALL_HEIGHT))} for w in chunk.walls]
        self.chunks[coord] = ChunkState(coord, chunk.sha256, slots, uids, boxes, baseline)
        self.structures.restore(coord)                                              # built structures after the generated rows
        self.creatures.on_integrate(coord, chunk)                                   # EDEN_CREATURES: stored creatures come back, the spawn plan fills the rest
        self.log.append((self.engine.tick, "integrate", coord.x, coord.y))
        self.counters["integrated"] += 1
        self.counters["integrate_ms_x1000"] += int((time.perf_counter() - started) * 1e6)
        self._publish()

    def unload(self, coord) -> None:
        state = self.chunks.pop(coord)
        m = self.engine.state.m_tensor
        stored = {}
        for slot, uid, base in zip(state.slots, state.uids, state.baseline):
            row = m[slot].tolist()
            if self.engine._entity_uid_by_slot[slot] != uid or row[cfg.M_TYPE] <= 0.0:
                stored[uid] = {"removed": True}
                continue
            changed = {col: row[col] for col in range(len(row)) if col not in SKIP_DELTA_COLUMNS and row[col] != base[col]}
            if changed:
                stored[uid] = {"cols": changed}
        if stored:
            self.deltas[coord] = stored
        else:
            self.deltas.pop(coord, None)
        self.structures.stash(coord, state.uids)
        self.creatures.on_unload(coord)                                             # EDEN_CREATURES: creatures standing in the chunk are stored with it
        self.allocator.release([s for s, u in zip(state.slots, state.uids) if self.engine._entity_uid_by_slot[s] == u])
        self.log.append((self.engine.tick, "unload", coord.x, coord.y))
        self.counters["unloaded"] += 1
        self._publish()

    # ------------------------------------------------------------------ re-base
    def rebase_if_due(self):
        """Re-base to the chunk of the controlled human (a player walking away must carry the window with them; the residents they leave
        behind stay where they are, unsimulated beyond the frame until the window returns) when it is more than ``REBASE_AT`` chunks from the
        origin; with no controlled human, to the residents' mean position by the same rule. The result of ``rebase`` or None."""
        actors = self.controlled_actors() or self.actors()
        if not actors:
            return None
        size = float(self.ring.chunk_units)
        centre = (int((sum(a.x for a in actors) / len(actors)) // size), int((sum(a.y for a in actors) / len(actors)) // size))
        if max(abs(centre[0] - self.frame.origin[0]), abs(centre[1] - self.frame.origin[1])) <= REBASE_AT:
            return None
        return self.rebase(centre)

    def rebase(self, new_origin) -> dict:
        """Move the window origin to chunk ``new_origin`` and shift every space-0 position by the same whole number of chunks. Run on the tick
        thread between ticks. Returns the shift and what moved ({} when the origin does not change)."""
        new_origin = (int(new_origin[0]), int(new_origin[1]))
        if new_origin == self.frame.origin:
            return {}
        engine = self.engine
        dx, dy = self.frame.rebase_shift(new_origin)
        h, m = engine.state.h_tensor, engine.state.m_tensor
        h_rows = torch.nonzero((h[:, cfg.TYPE] > 0) & (h[:, cfg.H_SPACE] == 0)).flatten()
        m_rows = torch.nonzero((m[:, cfg.M_TYPE] > 0) & (m[:, cfg.M_SPACE] == 0)).flatten()
        h_slots, m_slots = h_rows.tolist(), m_rows.tolist()
        h[h_rows, cfg.X] += dx
        h[h_rows, cfg.Y] += dy
        m[m_rows, cfg.CX] += dx
        m[m_rows, cfg.CY] += dy
        moved = {"humans": len(h_slots), "entities": len(m_slots)}
        moved["geometry"] = map_geo.shift_entities(m_slots, dx, dy, device=engine.state.device)
        for state in self.chunks.values():
            for box in state.boxes:
                box["min"] = [box["min"][0] + dx, box["min"][1] + dy]
                box["max"] = [box["max"][0] + dx, box["max"][1] + dy]
        moved["prev_positions"] = self._shift_prev_positions(h_slots, m_slots, dx, dy)
        moved["map_contract"] = self._shift_primary_contract(dx, dy)
        moved["resident_memory"] = self._shift_resident_memory(dx, dy)
        warmed = temperature.shift_sources(engine, dx, dy)                                    # EDEN_TEMPERATURE: lit fires are absolute positions
        if warmed:
            moved["warmth_sources"] = warmed                                                  # absent when there are none: the flag-off result is unchanged
        moved["view_window"] = self._shift_keys(getattr(engine, "_view_window_state", None), dx, dy)
        pending = (getattr(engine, "_nature_state", None) or {}).get("pending_event")
        moved["pending_event"] = self._shift_keys(pending, dx, dy, ("center_x", "center_y"))
        self.frame.rebase(new_origin)
        self.epoch += 1
        engine._window_epoch = self.epoch
        engine._force_map_refresh = True
        engine._force_frame_refresh = True
        self._plan = None                                  # the plan is in absolute chunks, but keep one rule: replan after a re-base
        self._publish()
        self.log.append((engine.tick, "rebase", new_origin[0], new_origin[1]))
        self.counters["rebased"] += 1
        try:
            from systems.actions.rebase import rebase_model_plane
        except ImportError:                                # the model plane has not landed yet: nothing of its to shift
            rebase_model_plane = None
        result = {"shift": [dx, dy], "origin": list(new_origin), "epoch": self.epoch, "moved": moved}
        if rebase_model_plane is not None:
            result["model_plane"] = rebase_model_plane(engine, dx, dy)
        return result

    def _shift_prev_positions(self, h_slots, m_slots, dx, dy) -> int:
        previous = self.engine._actor_prev_positions
        uids = [self.engine._human_uid_by_slot[s] for s in h_slots] + [self.engine._entity_uid_by_slot[s] for s in m_slots]
        count = 0
        for uid in uids:
            if uid in previous:
                x, y = previous[uid]
                previous[uid] = (x + dx, y + dy)
                count += 1
        return count

    def _shift_primary_contract(self, dx, dy) -> int:
        """The registered overworld map (the primary one, not the placed interiors): bounds, boxes, anchors, entities and origin."""
        entry = MAP_CONTRACTS.get(getattr(self.engine, "_map_name", None))
        if entry is None or entry.get("world") is not None:
            return 0
        b = entry["bounds"]
        entry["bounds"] = [b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy]
        for box in entry["boxes"]:
            box["min"] = [box["min"][0] + dx, box["min"][1] + dy]
            box["max"] = [box["max"][0] + dx, box["max"][1] + dy]
        for item in (*entry["anchors"], *entry["entities"]):
            item["position"] = [item["position"][0] + dx, item["position"][1] + dy]
        shift = entry.get("window_shift", [0.0, 0.0])      # where the map is now relative to its registration (origin and info keep the registration)
        entry["window_shift"] = [shift[0] + dx, shift[1] + dy]
        return len(entry["boxes"]) + len(entry["anchors"]) + len(entry["entities"])

    def _shift_resident_memory(self, dx, dy) -> int:
        """Remembered resources carry the source's absolute position (``abs``): their window-local x, y follow the origin."""
        store = getattr(self.engine, "resident_store", None)
        cache = getattr(store, "_cache", None) or {}
        count = 0
        for human_id, resident in cache.items():
            touched = False
            for entries in (resident.get("memory") or {}).values():
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if isinstance(entry, dict) and "abs" in entry and "x" in entry and "y" in entry:
                        entry["x"], entry["y"] = round(float(entry["x"]) + dx, 2), round(float(entry["y"]) + dy, 2)
                        count += 1
                        touched = True
            if touched:
                store._mark_dirty(human_id)
                store._mark_memory_dirty(human_id)
        return count

    @staticmethod
    def _shift_keys(target, dx, dy, keys=("center_x", "center_y")) -> int:
        if not isinstance(target, dict) or keys[0] not in target or keys[1] not in target:
            return 0
        target[keys[0]], target[keys[1]] = float(target[keys[0]]) + dx, float(target[keys[1]]) + dy
        return 1

    # ------------------------------------------------------------------ save
    def snapshot(self) -> dict:
        """Plain data for world format 3: origin, epoch, the integrated chunks (rows, ids, boxes, generated row values), the chunk deltas, the
        rows this window owns and the tail of the integration log; with structures in the dormant store, a ``structures`` key too (world format 4).
        Everything else (tensors, geometry, ids) is saved by the world itself."""
        state = {
            "origin": list(self.frame.origin), "epoch": self.epoch,
            "chunks": [{"coord": [c.x, c.y], "sha256": s.sha256, "slots": list(s.slots), "uids": list(s.uids),
                        "boxes": [{"id": b["id"], "min": list(b["min"]), "max": list(b["max"]), "height": b["height"]} for b in s.boxes],
                        "baseline": [list(row) for row in s.baseline]} for c, s in self.chunks.items()],
            "deltas": [[[c.x, c.y], {uid: ({"removed": True} if d.get("removed") else {"cols": dict(d["cols"])}) for uid, d in entry.items()}]
                       for c, entry in self.deltas.items()],
            "owned": sorted(self.allocator.owned),
            "log": [list(item) for item in self.log[-LOG_TAIL:]],
        }
        since = getattr(self.engine, "_dormant_since", None)
        if since:                                     # EDEN_WINDOW_DORMANCY: only when something is dormant, so every other save is unchanged
            state["dormant_since"] = {str(uid): int(tick) for uid, tick in since.items()}
        if self.structures.count():                   # EDEN_STRUCTURE_STORE: only when something is stored away, so every other save stays format 3
            state["structures"] = self.structures.export()
        return state

    def load(self, state: dict) -> None:
        """Take a ``snapshot`` back (the world's tensors, ids and geometry are already restored). The primary map moves to the saved origin."""
        self.frame.origin = (int(state["origin"][0]), int(state["origin"][1]))
        self.epoch = int(state["epoch"])
        self.engine._window_epoch = self.epoch
        self.engine._dormant_since = {str(uid): int(tick) for uid, tick in state.get("dormant_since", {}).items()}
        self.chunks = {}
        for item in state["chunks"]:
            coord = ChunkCoord(int(item["coord"][0]), int(item["coord"][1]))
            self.chunks[coord] = ChunkState(coord, item["sha256"], [int(s) for s in item["slots"]], list(item["uids"]),
                                            [dict(b) for b in item["boxes"]], [list(row) for row in item["baseline"]])
        self.deltas = {ChunkCoord(int(c[0]), int(c[1])): entry for c, entry in state["deltas"]}
        self.allocator.owned = {int(s) for s in state["owned"]}
        self.structures.load(state.get("structures", []))
        self.creatures.after_load()                   # EDEN_CREATURES: nothing of the creature store is saved (decision c3: regenerated from the plan)
        self.log = [tuple(item) for item in state["log"]]
        size = float(self.ring.chunk_units)
        self._set_primary_shift(-self.frame.origin[0] * size, -self.frame.origin[1] * size)
        self._plan = None
        self._publish()

    def _set_primary_shift(self, total_dx, total_dy) -> None:
        """Bring the registered primary map to ``total`` away from its registration (a restore into a process whose map is at another shift)."""
        entry = MAP_CONTRACTS.get(getattr(self.engine, "_map_name", None))
        if entry is None or entry.get("world") is not None:
            return
        shift = entry.get("window_shift", [0.0, 0.0])
        dx, dy = total_dx - shift[0], total_dy - shift[1]
        if dx or dy:
            self._shift_primary_contract(dx, dy)

    # ------------------------------------------------------------------ contract
    def void_boxes(self) -> list:
        size = float(self.ring.chunk_units)
        t = VOID_THICKNESS
        boxes = []
        for coord in sorted(self.chunks, key=lambda c: (c.x, c.y)):
            x0, y0 = self._local_origin(coord)
            x1, y1 = x0 + size, y0 + size
            for name, dx, dy, lo, hi in (("w", -1, 0, [x0 - t, y0], [x0, y1]), ("e", 1, 0, [x1, y0], [x1 + t, y1]),
                                         ("n", 0, -1, [x0, y0 - t], [x1, y0]), ("s", 0, 1, [x0, y1], [x1, y1 + t])):
                if ChunkCoord(coord.x + dx, coord.y + dy) not in self.chunks:
                    boxes.append({"id": f"void:{coord.x}:{coord.y}:{name}", "min": lo, "max": hi, "height": WALL_HEIGHT})
        return boxes

    def _publish(self) -> None:
        """Rebuild the box list and revision the movement contract appends (only when the integrated set changed)."""
        size = float(self.ring.chunk_units)
        boxes = [box for coord in sorted(self.chunks, key=lambda c: (c.x, c.y)) for box in self.chunks[coord].boxes] + self.void_boxes()
        bounds = None
        if self.chunks:
            lows = [self._local_origin(c) for c in self.chunks]
            bounds = [min(x for x, _ in lows), min(y for _, y in lows), max(x for x, _ in lows) + size, max(y for _, y in lows) + size]
        digest = hashlib.sha256(json.dumps([self.frame.origin, sorted((c.x, c.y, s.sha256) for c, s in self.chunks.items())]).encode()).hexdigest()[:16]
        self.engine._window_contract = {"boxes": boxes, "bounds": bounds, "revision": digest}

    # ------------------------------------------------------------------ collision telemetry
    def record_void_hit(self, *, is_player: bool = False, count: int = 1) -> None:
        """Authoritative void-barrier collision event (attempted movement blocked or slid by a void box)."""
        self.counters["void_hits"] += count
        if is_player:
            self.counters["void_hits_player"] += count
        else:
            self.counters["void_hits_resident"] += count

    def record_wall_hit(self, *, is_player: bool = False, count: int = 1) -> None:
        """Authoritative authored or chunk wall collision event."""
        self.counters["wall_hits"] += count
        if is_player:
            self.counters["wall_hits_player"] += count
        else:
            self.counters["wall_hits_resident"] += count

    def reset_void_counters(self) -> None:
        """Reset void barrier and wall collision counters (e.g. for a measured test window)."""
        for key in ("void_hits", "void_hits_player", "void_hits_resident", "wall_hits", "wall_hits_player", "wall_hits_resident"):
            self.counters[key] = 0

    def reset_counters(self) -> None:
        """Reset collision counters."""
        self.reset_void_counters()

    @property
    def void_hits(self) -> int:
        return int(self.counters["void_hits"])

    @property
    def void_hits_player(self) -> int:
        return int(self.counters["void_hits_player"])

    @property
    def void_hits_resident(self) -> int:
        return int(self.counters["void_hits_resident"])

    @property
    def wall_hits(self) -> int:
        return int(self.counters["wall_hits"])

    @property
    def wall_hits_player(self) -> int:
        return int(self.counters["wall_hits_player"])

    @property
    def wall_hits_resident(self) -> int:
        return int(self.counters["wall_hits_resident"])

    # ------------------------------------------------------------------ report
    def stats(self) -> dict:
        def summary(values):
            values = sorted(values)
            if not values:
                return {"n": 0}
            return {"n": len(values), "mean": round(sum(values) / len(values), 4), "p95": round(values[int(0.95 * (len(values) - 1))], 4),
                    "max": round(values[-1], 4)}
        return {"integrated": len(self.chunks), "rows": len(self.allocator.owned), "deltas": len(self.deltas), "counters": dict(self.counters),
                "creatures": dict(self.creatures.counters), "pump_ms": summary(self.pump_ms), "tick_ms": summary(self.step_ms), "service": self.service.stats()}

    def close(self) -> None:
        self.service.close()


# -- process-wide service and accessor -------------------------------------------------------------------------------------
_SERVICE: Optional[ChunkService] = None


def shared_service() -> ChunkService:
    """The one ChunkService of the process (the routes get it through ``service_factory=shared_service``)."""
    global _SERVICE
    if _SERVICE is None:
        _SERVICE = default_service()
    return _SERVICE


def close_service() -> None:
    global _SERVICE
    if _SERVICE is not None:
        _SERVICE.close()
        _SERVICE = None


def world_seed_of(engine) -> int:
    """The seed of the world this engine streams: its manager's service, else the process-wide default (``EDEN_WORLD_SEED``)."""
    current = getattr(engine, "_window", None)
    if current is not None:
        return int(current.service.world_seed)
    return int(os.environ.get(SEED_ENV, DEFAULT_SEED))


def restore_manager(engine, state: dict) -> WindowManager:
    """A manager for ``engine`` holding the saved window state (world format 3 restore); the caller sets ``world_epoch`` afterwards through
    world's new ``world_epoch`` must already be set (a manager is rebuilt when it differs)."""
    current = getattr(engine, "_window", None)
    service = current.service if current is not None else shared_service()
    manager = WindowManager(engine, service)
    manager.load(state)
    return manager


def manager_for(engine) -> WindowManager:
    """The engine's window manager, built on first use and rebuilt for a new world (``engine.world_epoch`` changes)."""
    current = getattr(engine, "_window", None)
    if current is None or current.world_epoch != engine.world_epoch:
        current = WindowManager(engine, shared_service())
    return current
