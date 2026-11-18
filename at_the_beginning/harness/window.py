"""1008 WS-D P5 (a): entity-row lifecycle for the streaming window: ``SlotAllocator`` and ``release_slots``.

A window world holds at most ``WINDOW_ROW_BUDGET`` chunk-resident rows of the engine's ``m_tensor`` at a time. Chunks load (rows are claimed
and written) and unload (rows are released) while the engine runs, so a row index is no longer a stable identity: the *uid* is
(``engine._entity_uid_by_slot``), and ``M_GEN`` counts how often a slot was released, so a (slot, generation) pair taken before a release never
matches the row that reuses the slot.

``release_slots`` is the one place that frees an entity row on purpose. It leaves nothing of the old entity behind in any index the
legacy engine keeps by slot or uid: the tensor row (zeroed except for the bumped ``M_GEN``), the geometry (``map_geo`` shape and tile owners),
the uid, the previous-frame masks and actor caches, the harness spatial index, the seeded-container markers and, for an animal, the
``animal_despawned`` event the next frame would otherwise emit from the mask difference. Container *contents* (``inventory_state``) are not
touched: they belong to the chunk delta of the caller (decision Q1).

Pure of EDEN_WINDOW: nothing in the legacy engine calls this module; the window manager (P5 c) does. See ``1008_spaces_p4_p5_gap.md`` 5.
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence

import torch

try:
    import genesis_config as cfg
    import map_geo
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg
    from at_the_beginning import map_geo

WINDOW_FRAME = (352, 352, (-160, -160))   # tiles: grid_w, grid_h, origin tile; covers window-local [-1280, 1536) at 8 units per tile
REBASE_AT = 2                    # chunks of drift before the window origin moves (design 4.4)
WINDOW_ROW_BUDGET = 800          # entity rows the window may hold at once (of cfg.MAX_ENTITIES)

# Interior pocket pool (design 5.4): two strips outside the window-local range in x, |coordinate| < 2048 so float32 stays within 1.2e-4.
# A pocket is a 256 x 256 unit square (32 x 32 tiles). A re-base never moves a pocket: only rows with M_SPACE == 0 shift.
POCKET_UNITS = 256.0
POCKETS_PER_STRIP = 16
POCKET_ORIGINS = tuple([(1792.0, -2048.0 + POCKET_UNITS * i) for i in range(POCKETS_PER_STRIP)]
                       + [(-2048.0, -2048.0 + POCKET_UNITS * i) for i in range(POCKETS_PER_STRIP)])
POCKET_STEP = 1                  # authored interiors take consecutive pockets (decision c3 R5: under EDEN_WINDOW the space masks, not
                                 # map_contract.ISOLATION_DISTANCE, keep interiors apart; the leak tests are the guard)


def authored_pocket(index: int) -> int:
    """The pocket of the ``index``-th secondary map of the authored world (0 = first interior)."""
    pocket = POCKET_STEP * int(index)
    if pocket >= len(POCKET_ORIGINS):
        raise ValueError(f"the authored world has more interiors than pockets ({len(POCKET_ORIGINS) // POCKET_STEP})")
    return pocket


def _frame_of(engine):
    """The window frame: the manager's when a window runs, else the harness world's (tests, flag off), else None."""
    manager = getattr(engine, "_window", None)
    if manager is not None:
        return manager.frame
    return getattr(getattr(getattr(engine, "harness", None), "world", None), "frame", None)


def absolute_position(engine, x: float, y: float):
    """The absolute position of a window-local point as a JSON-safe dict ``{"chunk": [cx, cy], "x", "y"}`` (what resident memory stores
    next to a remembered place), or None when the engine has no harness frame. Survives a re-base, local ``x``, ``y`` do not."""
    frame = _frame_of(engine)
    if frame is None:
        return None
    pos = frame.to_absolute(float(x), float(y))
    return {"chunk": [pos.chunk_x, pos.chunk_y], "x": pos.x, "y": pos.y}


def local_position(engine, stored: dict):
    """The window-local ``(x, y)`` of a position stored by ``absolute_position`` under the frame as it is now."""
    from .frame import AbsPos
    frame = _frame_of(engine)
    return frame.to_local(AbsPos(int(stored["chunk"][0]), int(stored["chunk"][1]), float(stored["x"]), float(stored["y"])))


class SlotExhausted(RuntimeError):
    """No free entity rows, or the window row budget would be exceeded. Nothing was changed."""


def _live_engine_state(engine):
    return engine.state.m_tensor, engine._entity_uid_by_slot, engine._entity_count_ref


def generation_of(engine, slot: int) -> int:
    """How many times ``slot`` has been released through ``release_slots`` (a counter in ``M_GEN``)."""
    return int(engine.state.m_tensor[int(slot), cfg.M_GEN])


def release_slots(engine, slots: Iterable[int]) -> list:
    """Free entity rows completely. Returns the uids that were released, in slot order. Slots that are already free are skipped.

    Order matters and is fixed: collect the facts that need the row (uid, animal or not), drop geometry and every uid-keyed record, queue the
    despawn event, then zero the row keeping ``M_GEN + 1`` and lower the live-entity count."""
    m, uids, count_ref = _live_engine_state(engine)
    released = []
    for slot in sorted({int(s) for s in slots}):
        if not (0 <= slot < cfg.MAX_ENTITIES) or float(m[slot, cfg.M_TYPE]) <= 0.0:
            continue
        uid = uids[slot]
        was_animal = int(m[slot, cfg.M_TYPE]) in cfg.ANIMAL_TYPES
        generation = float(m[slot, cfg.M_GEN]) + 1.0
        map_geo.unregister_entity(slot)
        if uid is not None:
            _forget_uid(engine, str(uid))
            if was_animal and bool(engine._prev_a_mask[slot]):          # the client was told about it; one that never appeared needs no despawn
                engine._pending_despawns.append(uid)
                engine._queue_event("animal_despawned", uid, slot)
        uids[slot] = None
        engine._prev_entity_mask[slot] = False
        engine._prev_a_mask[slot] = False
        m[slot] = 0.0
        m[slot, cfg.M_GEN] = generation
        count_ref[0] -= 1
        released.append(uid)
    if released:
        engine._force_map_refresh = True
    return released


def _forget_uid(engine, uid: str) -> None:
    """Remove ``uid`` from every uid-keyed cache the engine and the harness keep for entities (not inventories, not residents)."""
    engine._inventory_seeded_containers.discard(uid)
    engine._inventory_seeded_containers.discard(f"stock:{uid}")
    engine._actor_prev_positions.pop(uid, None)
    facing = getattr(engine, "_actor_prev_facing_yaw", None)
    if isinstance(facing, dict):
        facing.pop(uid, None)
    runtime = getattr(engine, "harness", None)
    world = getattr(runtime, "world", None)
    index = getattr(world, "index", None)
    if index is not None and uid in index:
        index.remove(uid)


class SlotAllocator:
    """Claims entity rows for the window, lowest free row first (the order ``entity_born`` uses), under a row budget.

    ``allocate`` writes the claimed rows (type, position and any extra columns; everything else zero, ``M_GEN`` kept), assigns the uids,
    raises the live-entity count and returns the slots. It either claims every requested row or raises ``SlotExhausted`` having changed
    nothing. ``release`` frees through ``release_slots`` and forgets the rows. ``owned`` is the set of rows this allocator claimed and has not
    released: the window's share of the entity tensor."""

    def __init__(self, engine, budget: int = WINDOW_ROW_BUDGET):
        self.engine = engine
        self.budget = int(budget)
        self.owned: set = set()

    def free_rows(self) -> int:
        return int((self.engine.state.m_tensor[:cfg.MAX_ENTITIES, cfg.M_TYPE] == 0).sum())

    def headroom(self) -> int:
        """Rows that can still be claimed now: the smaller of the free rows and the budget left."""
        return max(0, min(self.free_rows(), self.budget - len(self.owned)))

    def allocate(self, uids: Sequence[str], m_types: Sequence[float], x: Sequence[float], y: Sequence[float],
                 columns: Optional[dict] = None) -> list:
        n = len(uids)
        if not (len(m_types) == len(x) == len(y) == n):
            raise ValueError("allocate: uids, m_types, x and y must have one entry per row")
        if len(set(uids)) != n:
            raise ValueError("allocate: duplicate uids in one request")
        engine = self.engine
        taken = {u for u in engine._entity_uid_by_slot if u is not None}
        clash = sorted(set(uids) & taken)
        if clash:
            raise ValueError(f"allocate: uid already in use: {clash[0]!r}")
        if n == 0:
            return []
        m = engine.state.m_tensor
        if n > self.headroom():
            raise SlotExhausted(f"{n} rows requested, {self.free_rows()} free rows, {self.budget - len(self.owned)} budget left")
        if any(float(t) <= 0.0 for t in m_types):
            raise ValueError("allocate: M_TYPE must be positive (type 0 means a free row)")
        for col, values in (columns or {}).items():            # every refusal comes before the first write
            if int(col) in (cfg.M_TYPE, cfg.M_GEN, cfg.CX, cfg.CY):
                raise ValueError(f"allocate: column {col} is owned by the allocator")
            if len(values) != n:
                raise ValueError(f"allocate: column {col} needs one value per row")
        free = torch.where(m[:cfg.MAX_ENTITIES, cfg.M_TYPE] == 0)[0][:n]
        slots = free.tolist()
        generation = m[free, cfg.M_GEN].clone()
        m[free] = 0.0
        m[free, cfg.M_GEN] = generation
        m[free, cfg.CX] = torch.tensor(list(x), dtype=m.dtype, device=m.device)
        m[free, cfg.CY] = torch.tensor(list(y), dtype=m.dtype, device=m.device)
        m[free, cfg.M_TYPE] = torch.tensor([float(t) for t in m_types], dtype=m.dtype, device=m.device)
        for col, values in (columns or {}).items():
            m[free, int(col)] = torch.tensor([float(v) for v in values], dtype=m.dtype, device=m.device)
        for slot, uid in zip(slots, uids):
            engine._entity_uid_by_slot[slot] = str(uid)
        engine._entity_count_ref[0] += n
        self.owned.update(slots)
        engine._force_map_refresh = True
        return slots

    def release(self, slots: Iterable[int]) -> list:
        slots = [int(s) for s in slots]
        released = release_slots(self.engine, slots)
        self.owned.difference_update(slots)
        return released
