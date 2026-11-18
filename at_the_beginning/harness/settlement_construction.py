"""at_the_beginning/harness/settlement_construction.py
===================================================
R6.4 Bounded Settlement Construction Service: Deterministic Site Selection,
Material-Funded Project Commitment, and Exact Labor Progress.

Design reference: ``design_docs/designs/settlement_gap.md`` (2026-10-10).
Architectural status:
- Pure engine service layer; caller-driven execution only.
- No automatic tick hooks, global allocator registrations, or default action verb flips.
- DR-22 authoritative save compatibility remains OPEN; no unsaved authoritative state is wired
  into automatic gameplay or silently dropped.
- Operates on real isolated Engine / World tensors / inventory / SettlementRegistry.
- Strict material conservation: personal_shelter recipe is exactly 6 wood_bundle,
  3 fiber_bundle, 2 plank_bundle; no virtual H_CARRYING credit or free item creation.
- Exact transaction boundary: all validation and reversible mementos staged before mutations;
  full rollback of tensor rows, entity counters, UID mappings, geometry, inventories,
  and registry state on any exception.
- Progress uses existing S_BUILD_PROGRESS (col 9); no new tensor column or width expansion.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

import torch

# Configuration import with clean fallback
try:
    import genesis_config as cfg
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg

try:
    import map_geo
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import map_geo

try:
    from harness import settlements
    from harness.settlements import (
        CHUNK_SUBUNITS,
        CHUNK_UNITS,
        DEFAULT_CLAIM_RADIUS_Q,
        MAX_ABS_COORD,
        MAX_CHUNK_COORD,
        MAX_CLAIM_RADIUS_Q,
        MAX_ID_COUNTER,
        MAX_TICK,
        MIN_CHUNK_COORD,
        MIN_CLAIM_RADIUS_Q,
        MIN_ID_COUNTER,
        Q,
        SCHEMA_VERSION,
        SETTLEMENT_ROLES,
        SettlementCapError,
        SettlementConfig,
        SettlementConflictError,
        SettlementError,
        SettlementReferenceError,
        SettlementRegistry,
        SettlementValidationError,
        anchor_diff_q,
        anchor_distance_sq_q,
        anchor_to_local,
        anchor_to_total_subunits,
        claims_overlap,
        is_point_in_claim,
        make_anchor,
        normalize_subunits_to_anchor,
        quantize_chunk_local_to_anchor,
        quantize_unit_to_anchor,
        validate_anchor,
        validate_finite_number,
        validate_strict_int,
        validate_string,
    )
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness import settlements
    from at_the_beginning.harness.settlements import (
        CHUNK_SUBUNITS,
        CHUNK_UNITS,
        DEFAULT_CLAIM_RADIUS_Q,
        MAX_ABS_COORD,
        MAX_CHUNK_COORD,
        MAX_CLAIM_RADIUS_Q,
        MAX_ID_COUNTER,
        MAX_TICK,
        MIN_CHUNK_COORD,
        MIN_CLAIM_RADIUS_Q,
        MIN_ID_COUNTER,
        Q,
        SCHEMA_VERSION,
        SETTLEMENT_ROLES,
        SettlementCapError,
        SettlementConfig,
        SettlementConflictError,
        SettlementError,
        SettlementReferenceError,
        SettlementRegistry,
        SettlementValidationError,
        anchor_diff_q,
        anchor_distance_sq_q,
        anchor_to_local,
        anchor_to_total_subunits,
        claims_overlap,
        is_point_in_claim,
        make_anchor,
        normalize_subunits_to_anchor,
        quantize_chunk_local_to_anchor,
        quantize_unit_to_anchor,
        validate_anchor,
        validate_finite_number,
        validate_strict_int,
        validate_string,
    )

try:
    from systems.construction.building import designate_construction_site
    from systems.construction.catalog import BUILDING_BLUEPRINT_DEFS
    from systems.construction.sites import BUILD_BLOCKED_TYPES, HABITABLE, structure_blueprint
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.construction.building import designate_construction_site
    from at_the_beginning.systems.construction.catalog import BUILDING_BLUEPRINT_DEFS
    from at_the_beginning.systems.construction.sites import BUILD_BLOCKED_TYPES, HABITABLE, structure_blueprint

try:
    from systems.inventory.ops import add_item, remove_item
    from systems.inventory.queries import total_quantity
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.inventory.ops import add_item, remove_item
    from at_the_beginning.systems.inventory.queries import total_quantity

try:
    import instincts_and_tools as iat
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import instincts_and_tools as iat

try:
    from systems.movement.map_contract import MAP_CONTRACTS, get_map_contract
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.movement.map_contract import MAP_CONTRACTS, get_map_contract

try:
    from systems.worldgen.rings import ChunkCoord
except ImportError:  # pragma: no cover - package import fallback
    try:
        from at_the_beginning.systems.worldgen.rings import ChunkCoord
    except ImportError:
        from collections import namedtuple
        ChunkCoord = namedtuple("ChunkCoord", ["x", "y"])


# =============================================================================
# Constants and Typed Defaults
# =============================================================================

# Catalog requirements for personal_shelter (systems/construction/catalog.py)
RECIPE_PERSONAL_SHELTER: Dict[str, int] = {
    "wood_bundle": 6,
    "fiber_bundle": 3,
    "plank_bundle": 2,
}

# Blueprint properties for personal_shelter (M_HOUSE = 20)
SHELTER_STRUCTURE_TYPE: int = int(getattr(cfg, "M_HOUSE", 20))
SHELTER_SCALE: float = 22.0
SHELTER_DURABILITY: float = 140.0
SHELTER_CAP: float = 4.0

# Site planning search constants
MAX_CANDIDATES: int = 64
DEFAULT_LATTICE_STEP_UNITS: float = 24.0

# Worker and reach defaults from genesis_config
BUILD_RADIUS: float = float(getattr(cfg, "BUILD_RADIUS", 70.0))
BUILD_MIN_STAMINA: float = float(getattr(cfg, "BUILD_MIN_STAMINA", 8.0))
BUILD_STAMINA_COST: float = float(getattr(cfg, "BUILD_STAMINA_COST", 6.0))
BUILD_PROGRESS_PER_HUMAN: float = float(getattr(cfg, "BUILD_PROGRESS_PER_HUMAN", 8.0))
BUILD_SITE_HP_FRACTION: float = float(getattr(cfg, "BUILD_SITE_HP_FRACTION", 0.15))

# Blocked and habitable terrain definitions
BLOCKED_TERRAIN_TYPES: Set[int] = set(BUILD_BLOCKED_TYPES)
HABITABLE_TERRAIN_TYPES: Set[int] = set(HABITABLE) | {int(getattr(cfg, "M_BARREN", 19))}
STRUCTURE_TYPE_SET: Set[int] = set(getattr(cfg, "STRUCTURE_TYPES", range(20, 40)))
MAP_OBJECT_TYPE: int = int(getattr(cfg, "M_MAP_OBJECT", 17))
STORAGE_CASE_TYPE: int = int(getattr(cfg, "M_STORAGE_CASE", 21))


# =============================================================================
# Exceptions
# =============================================================================

class SettlementConstructionError(SettlementError):
    """Base exception for settlement construction operations."""


class SettlementSiteSelectionError(SettlementConstructionError):
    """Raised when deterministic site selection fails to find a viable candidate."""


class SettlementPreflightError(SettlementConstructionError):
    """Raised when preflight guards fail (inventory, reach, capacity, dead builder, etc.)."""


class SettlementStalePlanError(SettlementPreflightError):
    """Raised when committing a plan with stale revision, epoch, or builder status."""


class SettlementTransactionError(SettlementConstructionError):
    """Raised when a mutation fails and the transaction is rolled back."""


class SettlementDormancyError(SettlementConstructionError):
    """Raised when construction work is attempted on dormant or unloaded chunks."""


# =============================================================================
# Data Structures
# =============================================================================

@dataclass
class SitePlan:
    """Deterministic snapshot of an approved building site candidate."""
    token: str
    settlement_id: str
    builder_id: str
    building_kind: str
    anchor: Dict[str, List[int]]
    local_x: float
    local_y: float
    origin_chunk: List[int]
    engine_tick: int
    window_epoch: int
    world_revision: int
    footprint_radius: float
    recipe: Dict[str, int]
    candidates_evaluated: int = 0

    def recompute_local(self, current_origin_cx: int, current_origin_cy: int) -> Tuple[float, float]:
        """Recompute live local floating coordinates after an origin rebase from saved integer anchor.

        Maintains exact integer origin invariance without re-quantizing or floating drift.
        """
        ocx = validate_strict_int(current_origin_cx, "current_origin_cx", MIN_CHUNK_COORD, MAX_CHUNK_COORD)
        ocy = validate_strict_int(current_origin_cy, "current_origin_cy", MIN_CHUNK_COORD, MAX_CHUNK_COORD)
        lx, ly = anchor_to_local(self.anchor, ocx, ocy)
        self.local_x = lx
        self.local_y = ly
        self.origin_chunk = [ocx, ocy]
        return lx, ly


@dataclass(frozen=True)
class ConstructionTransactionResult:
    """Auditable result of a successfully committed construction funding transaction."""
    ok: bool
    project_id: str
    structure_uid: str
    slot: int
    anchor: Dict[str, List[int]]
    local_pos: Tuple[float, float]
    paid: Dict[str, int]
    tick: int


@dataclass(frozen=True)
class ConstructionProgressResult:
    """Auditable result of caller-controlled construction labor progression."""
    ok: bool
    project_id: str
    structure_uid: str
    slot: int
    progress: float
    durability: float
    hp: float
    completed: bool
    tick: int


# =============================================================================
# Authoritative Resolvers
# =============================================================================

def make_engine_structure_resolver(engine: Any) -> Callable[[str], Optional[Dict[str, Any]]]:
    """Build an authoritative structure resolver querying live m_tensor and dormant StructureStore."""
    def resolver(structure_uid: str) -> Optional[Dict[str, Any]]:
        validate_string(structure_uid, "structure_uid", min_len=1, max_len=128)
        uids = getattr(engine, "_entity_uid_by_slot", [])
        if structure_uid in uids:
            slot = uids.index(structure_uid)
            m = engine.state.m_tensor
            m_type = int(m[slot, cfg.M_TYPE])
            space = int(m[slot, cfg.M_SPACE]) if hasattr(cfg, "M_SPACE") else 0
            # The registry accepts integer progress. Fractional work below 100
            # must stay below 100 when presented through the resolver.
            progress = math.floor(float(m[slot, cfg.S_BUILD_PROGRESS]))
            return {
                "uid": structure_uid,
                "type": m_type,
                "space": space,
                "progress": progress,
                "slot": slot,
                "dormant": False,
            }

        # Check dormant structures in WindowManager's StructureStore
        window = getattr(engine, "_window", None)
        if window is not None and hasattr(window, "structures"):
            records_map = getattr(window.structures, "records", {})
            for coord, records in records_map.items():
                for rec in records:
                    if rec.get("uid") == structure_uid:
                        m_type = int(rec["type"])
                        cols = rec.get("cols", {})
                        progress = math.floor(float(cols.get(cfg.S_BUILD_PROGRESS, 0.0)))
                        return {
                            "uid": structure_uid,
                            "type": m_type,
                            "space": 0,
                            "progress": progress,
                            "dormant": True,
                        }
        return None
    return resolver


def make_engine_human_resolver(engine: Any) -> Callable[[str], Optional[Dict[str, Any]]]:
    """Build an authoritative resident resolver querying resident_store and live h_tensor."""
    def resolver(human_uid: str) -> Optional[Dict[str, Any]]:
        validate_string(human_uid, "human_uid", min_len=1, max_len=128)
        resident_store = getattr(engine, "resident_store", None)
        if resident_store is None:
            return None
        resident = resident_store.get(human_uid)
        if resident is None:
            return None

        alive = True
        status = resident.get("status", {})
        if status.get("alive") is False or status.get("deceased") or status.get("dead"):
            alive = False

        h_uids = getattr(engine, "_human_uid_by_slot", [])
        if human_uid in h_uids:
            slot = h_uids.index(human_uid)
            if float(engine.state.h_tensor[slot, cfg.HP]) <= 0.0:
                alive = False

        return {
            "uid": human_uid,
            "alive": bool(alive),
            "name": str(resident.get("profile", {}).get("name", human_uid)),
        }
    return resolver


# =============================================================================
# Candidate Lattice Generation
# =============================================================================

def generate_lattice_candidates(
    center_anchor: Dict[str, Any],
    step_units: float = DEFAULT_LATTICE_STEP_UNITS,
    max_candidates: int = MAX_CANDIDATES,
) -> List[Dict[str, List[int]]]:
    """Generate deterministic lattice candidates ordered by integer squared distance then coordinate order.

    - Fixed-point subunit arithmetic with Q=256 subunits/unit.
    - Symmetric integer offset lattice in subunits.
    - Exact ordering: (anchor_distance_sq_q, cx, cy, sx, sy).
    - Hard-capped at max_candidates (default 64).
    """
    valid_anchor = validate_anchor(center_anchor, "center_anchor")
    step_q = int(round(validate_finite_number(step_units, "step_units") * Q))
    if step_q <= 0:
        step_q = int(DEFAULT_LATTICE_STEP_UNITS * Q)

    cap = validate_strict_int(max_candidates, "max_candidates", 1, 256)

    center_total_sx, center_total_sy = anchor_to_total_subunits(valid_anchor)

    # 9x9 lattice grid gives 81 candidate offsets, sufficient for capping at 64
    candidates_with_keys = []
    for di in range(-4, 5):
        for dj in range(-4, 5):
            cand_sx = center_total_sx + di * step_q
            cand_sy = center_total_sy + dj * step_q
            cand_anchor = normalize_subunits_to_anchor(cand_sx, cand_sy)
            dist_sq_q = anchor_distance_sq_q(cand_anchor, valid_anchor)
            cx, cy = cand_anchor["chunk"]
            sx, sy = cand_anchor["sub"]
            key = (dist_sq_q, cx, cy, sx, sy)
            candidates_with_keys.append((key, cand_anchor))

    # Sort strictly by integer squared distance, tie-broken by cx, cy, sx, sy
    candidates_with_keys.sort(key=lambda item: item[0])

    # Deduplicate while preserving order and take at most cap
    result: List[Dict[str, List[int]]] = []
    seen: Set[Tuple[int, int, int, int]] = set()
    for _, cand in candidates_with_keys:
        tup = (cand["chunk"][0], cand["chunk"][1], cand["sub"][0], cand["sub"][1])
        if tup not in seen:
            seen.add(tup)
            result.append(cand)
            if len(result) >= cap:
                break

    return result


# =============================================================================
# Spatial & Candidate Viability Checker
# =============================================================================

def is_site_candidate_viable(
    candidate_anchor: Dict[str, Any],
    engine: Any,
    registry: SettlementRegistry,
    settlement_id: str,
    footprint_radius: float = SHELTER_SCALE,
    allowed_claim_overlap: bool = False,
) -> Tuple[bool, str]:
    """Validate a site candidate against claim, chunk integration, terrain, and obstacles.

    Returns:
        (is_viable, reason_if_not_viable)
    """
    cand = validate_anchor(candidate_anchor, "candidate_anchor")
    settlement = registry.get_settlement(settlement_id)
    if settlement["status"] != "active":
        return False, "settlement_not_active"

    # Report a foreign claim even when the candidate is also outside its own claim.
    if not allowed_claim_overlap:
        for other_rec in registry.list_settlements(status="active"):
            other_id = other_rec["uid"]
            if other_id == settlement_id:
                continue
            if is_point_in_claim(cand, other_rec["anchor"], other_rec["claim_radius_q"]):
                return False, f"inside_foreign_claim:{other_id}"

    # 2. Local integrated-ready chunk
    cand_cx, cand_cy = cand["chunk"]
    window = getattr(engine, "_window", None)
    if window is not None and hasattr(window, "chunks"):
        if ChunkCoord(cand_cx, cand_cy) not in window.chunks:
            return False, f"chunk_not_integrated:{cand_cx}:{cand_cy}"
        origin_cx, origin_cy = int(window.frame.origin[0]), int(window.frame.origin[1])
    else:
        origin_cx, origin_cy = 0, 0

    local_x, local_y = anchor_to_local(cand, origin_cx, origin_cy)

    # 2b. Map bounds check for legacy frame
    if window is None:
        map_w = float(getattr(cfg, "MAP_WIDTH", 1200.0))
        map_h = float(getattr(cfg, "MAP_HEIGHT", 900.0))
        if local_x < footprint_radius or local_x > map_w - footprint_radius or \
           local_y < footprint_radius or local_y > map_h - footprint_radius:
            return False, "outside_world_bounds"

    # 3. Habitable terrain check
    m_tensor = engine.state.m_tensor

    # Direct tile query at candidate center
    center_eid = map_geo.entity_at(local_x, local_y)
    if center_eid != -1:
        et = int(m_tensor[center_eid, cfg.M_TYPE])
        if et in BLOCKED_TERRAIN_TYPES:
            return False, f"blocked_terrain_type:{et}"
        if et in STRUCTURE_TYPE_SET:
            return False, f"occupied_by_structure:{center_eid}"
        if et in (MAP_OBJECT_TYPE, STORAGE_CASE_TYPE):
            return False, f"authored_obstacle_at_center:{center_eid}"

    # Radius query around candidate footprint
    nearby_eids = map_geo.entities_in_radius(local_x, local_y, footprint_radius, m_tensor)
    for eid in nearby_eids:
        et = int(m_tensor[eid, cfg.M_TYPE])
        if et in BLOCKED_TERRAIN_TYPES:
            return False, f"blocked_terrain_nearby:{et}"
        if et in STRUCTURE_TYPE_SET:
            return False, f"structure_overlap:{eid}"
        if et in (MAP_OBJECT_TYPE, STORAGE_CASE_TYPE):
            return False, f"authored_obstacle_nearby:{eid}"

    # 4. Active structure footprints in m_tensor
    uids = getattr(engine, "_entity_uid_by_slot", [])
    for slot, uid in enumerate(uids):
        if not uid:
            continue
        st = int(m_tensor[slot, cfg.M_TYPE])
        if st in STRUCTURE_TYPE_SET:
            sx = float(m_tensor[slot, cfg.CX])
            sy = float(m_tensor[slot, cfg.CY])
            sr = float(m_tensor[slot, cfg.SCALE])
            if math.hypot(local_x - sx, local_y - sy) < (footprint_radius + sr):
                return False, f"active_structure_overlap:{uid}"

    # 5. Dormant structure footprints in StructureStore
    if window is not None and hasattr(window, "structures"):
        for coord, rec_list in window.structures.records.items():
            bx = (coord.x - origin_cx) * CHUNK_UNITS
            by = (coord.y - origin_cy) * CHUNK_UNITS
            for rec in rec_list:
                offset = rec["offset"]
                dormant_x = bx + float(offset[0])
                dormant_y = by + float(offset[1])
                geo = rec.get("geo")
                dormant_r = float(geo["r"]) if geo and "r" in geo else SHELTER_SCALE
                if math.hypot(local_x - dormant_x, local_y - dormant_y) < (footprint_radius + dormant_r):
                    return False, f"dormant_structure_overlap:{rec.get('uid')}"

    # 6. Authored movement contract protection: wall boxes, portals, and authored entities
    contract = get_map_contract(getattr(engine, "_map_name", ""))
    if contract is not None:
        # Authored wall boxes
        for box in contract.get("boxes", ()):
            bmin = box.get("min", [0.0, 0.0])
            bmax = box.get("max", [0.0, 0.0])
            closest_x = max(float(bmin[0]), min(local_x, float(bmax[0])))
            closest_y = max(float(bmin[1]), min(local_y, float(bmax[1])))
            if math.hypot(local_x - closest_x, local_y - closest_y) < footprint_radius:
                return False, f"authored_wall_box_overlap:{box.get('id')}"

        # Authored portals
        for portal in contract.get("portals", ()):
            ppos = portal.get("position", [0.0, 0.0])
            pr = float(portal.get("radius", 4.0))
            if math.hypot(local_x - float(ppos[0]), local_y - float(ppos[1])) < (footprint_radius + pr):
                return False, f"authored_portal_overlap:{portal.get('id')}"

        # Authored interactive entities (doors, forges, anvils, etc.)
        for ent in contract.get("entities", ()):
            epos = ent.get("position", [0.0, 0.0])
            er = float(ent.get("interact_radius", 4.0))
            if math.hypot(local_x - float(epos[0]), local_y - float(epos[1])) < (footprint_radius + er):
                return False, f"authored_entity_overlap:{ent.get('id')}"

    if not is_point_in_claim(cand, settlement["anchor"], settlement["claim_radius_q"]):
        return False, "outside_settlement_claim"

    return True, "viable"


# =============================================================================
# Deterministic Site Planning Service API
# =============================================================================

def plan_settlement_site(
    engine: Any,
    registry: SettlementRegistry,
    settlement_id: str,
    builder_id: str,
    building_kind: str = "personal_shelter",
    *,
    target_anchor: Optional[Dict[str, Any]] = None,
    max_candidates: int = MAX_CANDIDATES,
    step_units: float = DEFAULT_LATTICE_STEP_UNITS,
    max_reach: float = BUILD_RADIUS,
) -> SitePlan:
    """Plan a deterministic, bounded building site for a settlement construction project.

    - Validates settlement active status, builder residency and living state.
    - Strictly restricts building_kind to 'personal_shelter' with exact recipe.
    - Generates up to max_candidates (default 64) lattice candidate anchors.
    - Validates claim ownership, integrated chunks, habitable terrain, active/dormant structures,
      and protected authored obstacles/walls/portals/forges.
    - Evaluates candidates in strict (dist_sq_q, cx, cy, sx, sy) order.
    - Returns a self-contained SitePlan holding integer absolute anchor and live local coords.
    """
    settlement = registry.get_settlement(settlement_id)
    if settlement["status"] != "active":
        raise SettlementSiteSelectionError(f"Settlement {settlement_id} is not active")

    validate_string(builder_id, "builder_id", min_len=1, max_len=128)
    if builder_id not in settlement["members"]:
        raise SettlementSiteSelectionError(f"Builder {builder_id} is not a member of {settlement_id}")

    # Authoritative human validation
    human_resolver = make_engine_human_resolver(engine)
    h_info = human_resolver(builder_id)
    h_uids = engine._human_uid_by_slot
    if not h_info or not h_info["alive"] or builder_id not in h_uids:
        raise SettlementSiteSelectionError(f"Builder {builder_id} is deceased or not live in world tensors")
    builder = engine.state.h_tensor[h_uids.index(builder_id)]
    if int(builder[cfg.H_SPACE]) != 0:
        raise SettlementSiteSelectionError(f"Builder {builder_id} is outside the overworld")
    bx, by = float(builder[cfg.X]), float(builder[cfg.Y])

    # Catalog kind and recipe check
    if building_kind != "personal_shelter":
        raise SettlementSiteSelectionError(
            f"Unsupported building kind {building_kind!r}; only 'personal_shelter' is supported in this slice"
        )
    recipe = copy.deepcopy(RECIPE_PERSONAL_SHELTER)

    # Check builder inventory has required materials
    builder_inv = engine._human_inventory_record(builder_id)
    for item, req_qty in recipe.items():
        have_qty = total_quantity(builder_inv, item)
        if have_qty < req_qty:
            raise SettlementPreflightError(
                f"Builder {builder_id} lacks required materials: need {req_qty} {item}, have {have_qty}"
            )

    # Check registry project cap and settlement open project status
    if registry.get_open_project(settlement_id) is not None:
        raise SettlementConflictError(f"Settlement {settlement_id} already has an open project")
    if (
        len(registry.list_projects()) >= registry.config.max_projects
        or registry.next_project_id >= MAX_ID_COUNTER
    ):
        raise SettlementCapError("Settlement registry project cap reached")

    # Determine window origin and epoch
    window = getattr(engine, "_window", None)
    if window is not None:
        origin_cx = int(window.frame.origin[0])
        origin_cy = int(window.frame.origin[1])
        window_epoch = int(window.epoch)
    else:
        origin_cx = 0
        origin_cy = 0
        window_epoch = 0

    engine_tick = int(getattr(engine, "tick", 0))
    world_revision = int(getattr(engine, "_map_state_version", 0))

    # Resolve center anchor
    if target_anchor is not None:
        center_anchor = validate_anchor(target_anchor, "target_anchor")
    else:
        # An implicit target can fall back to the settlement anchor.
        center_anchor = quantize_chunk_local_to_anchor(origin_cx, origin_cy, bx, by)
        if not is_point_in_claim(center_anchor, settlement["anchor"], settlement["claim_radius_q"]):
            center_anchor = settlement["anchor"]

    # Generate lattice candidates
    candidates = generate_lattice_candidates(center_anchor, step_units=step_units, max_candidates=max_candidates)

    footprint_r = SHELTER_SCALE

    evaluated_count = 0
    for cand in candidates:
        evaluated_count += 1
        viable, reason = is_site_candidate_viable(
            cand,
            engine,
            registry,
            settlement_id,
            footprint_radius=footprint_r,
        )
        if not viable:
            continue

        lx, ly = anchor_to_local(cand, origin_cx, origin_cy)

        # Reach check
        if math.hypot(lx - bx, ly - by) > max_reach:
            continue

        # Found the first viable candidate in deterministic order!
        cx, cy = cand["chunk"]
        sx, sy = cand["sub"]
        token = f"sp_plan_{settlement_id}_{builder_id}_{engine_tick}_{cx}_{cy}_{sx}_{sy}"
        return SitePlan(
            token=token,
            settlement_id=settlement_id,
            builder_id=builder_id,
            building_kind=building_kind,
            anchor=cand,
            local_x=lx,
            local_y=ly,
            origin_chunk=[origin_cx, origin_cy],
            engine_tick=engine_tick,
            window_epoch=window_epoch,
            world_revision=world_revision,
            footprint_radius=footprint_r,
            recipe=recipe,
            candidates_evaluated=evaluated_count,
        )

    raise SettlementSiteSelectionError(
        f"No viable building site found among {len(candidates)} lattice candidates (evaluated {evaluated_count})"
    )


# =============================================================================
# Material-Funded Project Commitment Transaction Service
# =============================================================================

def commit_settlement_project(
    engine: Any,
    registry: SettlementRegistry,
    plan: SitePlan,
    *,
    fault_hook_after_consume: Optional[Callable[[], None]] = None,
    fault_hook_after_create: Optional[Callable[[int], None]] = None,
    fault_hook_after_geo: Optional[Callable[[int], None]] = None,
    fault_hook_after_registry: Optional[Callable[[str, str], None]] = None,
) -> ConstructionTransactionResult:
    """Commit a site plan into an actual funded construction project on real engine state.

    Transaction stages:
    0. Full preflight and plan revalidation:
       - Window epoch freshness check.
       - Builder alive, active member, living state.
       - Reach check.
       - Whole-batch item balance check.
       - Entity and registry capacity checks.
       - Immediate site footprint viability revalidation.
    1. Capture reversible mementos for all touched engine components.
    2. Atomic mutations:
       a. Consume discrete catalog items from builder personal inventory.
       b. Allocate entity slot and designate unfinished structure via designate_construction_site.
       c. Allocate runtime e_* UID and register geometry in map_geo.
       d. Record open project and fund state in SettlementRegistry.
       e. Emit audit event.
    3. Rollback on ANY exception after first mutation:
       - Complete restoration of inventory items.
       - Restoration of the original tensor row.
       - Restoration of entity counts and next UID counters.
       - Restoration of map_geo geometry, tile ownership, and geo_version.
       - Atomic restoration of SettlementRegistry state.
       - Event ledger cleanup.
    """
    if not isinstance(plan, SitePlan):
        raise TypeError(f"plan must be a SitePlan, got {type(plan).__name__}")

    settlement = registry.get_settlement(plan.settlement_id)
    if settlement["status"] != "active":
        raise SettlementPreflightError(f"Settlement {plan.settlement_id} is not active")
    if plan.building_kind != "personal_shelter" or plan.recipe != RECIPE_PERSONAL_SHELTER:
        raise SettlementPreflightError("Site plan must use the personal shelter catalog recipe")
    if plan.footprint_radius != SHELTER_SCALE:
        raise SettlementPreflightError("Site plan must use the personal shelter footprint")

    # 0. Revalidation of plan freshness and revisions
    window = getattr(engine, "_window", None)
    current_epoch = int(window.epoch) if window is not None else 0
    if plan.window_epoch != current_epoch:
        raise SettlementStalePlanError(
            f"Stale plan window epoch: plan had {plan.window_epoch}, current window epoch is {current_epoch}"
        )
    if plan.world_revision != int(getattr(engine, "_map_state_version", 0)):
        raise SettlementStalePlanError("Stale plan world revision")

    current_tick = int(getattr(engine, "tick", 0))
    if plan.engine_tick > current_tick:
        raise SettlementStalePlanError(
            f"Plan engine tick {plan.engine_tick} is in future relative to engine {current_tick}"
        )

    # Builder living and membership revalidation
    human_resolver = make_engine_human_resolver(engine)
    h_info = human_resolver(plan.builder_id)
    if not h_info or not h_info["alive"]:
        raise SettlementPreflightError(f"Builder {plan.builder_id} is deceased or missing")
    if plan.builder_id not in settlement["members"]:
        raise SettlementPreflightError(f"Builder {plan.builder_id} is no longer a settlement member")

    h_uids = getattr(engine, "_human_uid_by_slot", [])
    if plan.builder_id not in h_uids:
        raise SettlementPreflightError(f"Builder {plan.builder_id} is not live in world tensors")
    builder = engine.state.h_tensor[h_uids.index(plan.builder_id)]
    if int(builder[cfg.H_SPACE]) != 0:
        raise SettlementPreflightError(f"Builder {plan.builder_id} is outside the overworld")

    # Reach revalidation
    origin_cx, origin_cy = window.frame.origin if window is not None else (0, 0)
    lx, ly = anchor_to_local(plan.anchor, origin_cx, origin_cy)
    bx, by = float(builder[cfg.X]), float(builder[cfg.Y])
    if math.hypot(lx - bx, ly - by) > BUILD_RADIUS:
        raise SettlementPreflightError(
            f"Builder {plan.builder_id} at ({bx:.1f}, {by:.1f}) is out of reach of site ({lx:.1f}, {ly:.1f})"
        )

    # Capacity revalidation
    m_tensor = engine.state.m_tensor
    max_entities = min(cfg.MAX_ENTITIES, len(m_tensor), len(engine._entity_uid_by_slot))
    if int(engine._entity_count_ref[0]) >= max_entities:
        raise SettlementCapError("Engine entity capacity reached")
    free_slots = torch.where(m_tensor[:max_entities, cfg.M_TYPE] == 0)[0]
    if not len(free_slots):
        raise SettlementCapError("Engine has no free entity row")
    reserved_slot = int(free_slots[0])
    if engine._entity_uid_by_slot[reserved_slot] is not None or reserved_slot in map_geo.MAP_GEO:
        raise SettlementPreflightError(f"Free entity row {reserved_slot} still has a UID or geometry")

    open_project = registry.get_open_project(plan.settlement_id)
    if open_project is None:
        if (
            len(registry.list_projects()) >= registry.config.max_projects
            or registry.next_project_id >= MAX_ID_COUNTER
        ):
            raise SettlementCapError("Registry project cap reached")
    elif (
        open_project["status"] != "planned"
        or open_project["builder_id"] != plan.builder_id
        or open_project["building_kind"] != plan.building_kind
        or open_project["anchor"] != plan.anchor
        or open_project["recipe"] != plan.recipe
    ):
        raise SettlementConflictError(f"Settlement {plan.settlement_id} already has a different open project")

    # Inventory materials balance revalidation
    builder_inv = engine._human_inventory_record(plan.builder_id)
    for item, req_qty in plan.recipe.items():
        have_qty = total_quantity(builder_inv, item)
        if have_qty < req_qty:
            raise SettlementPreflightError(
                f"Insufficient material {item!r}: required {req_qty}, available {have_qty}"
            )

    # Immediate site viability revalidation
    viable, reason = is_site_candidate_viable(
        plan.anchor,
        engine,
        registry,
        plan.settlement_id,
        footprint_radius=plan.footprint_radius,
    )
    if not viable:
        raise SettlementPreflightError(f"Site is no longer viable: {reason}")

    # 1. Capture reversible mementos
    inv_memento = copy.deepcopy(builder_inv)
    registry_memento = registry.export_state()
    pre_entity_count = int(engine._entity_count_ref[0])
    pre_next_entity_uid = int(engine._next_entity_uid)
    pre_row = m_tensor[reserved_slot].clone()
    pre_geo_version = int(map_geo.geo_version)
    pre_events_len = len(engine._pending_events)
    pre_event_seq = getattr(engine, "_event_seq", None)
    pre_tiles = None

    def create_site_row(*args, **kwargs):
        # Designation configures the row. The transaction registers geometry later.
        kwargs["register_geo"] = False
        return iat.instinct_create_object(*args, **kwargs)

    # 2. Atomic mutation execution with complete rollback on exception
    try:
        # 2a. Consume materials from builder personal inventory
        for item, qty in sorted(plan.recipe.items()):
            res = remove_item(builder_inv, item_kind=item, quantity=qty)
            if res.get("remaining", 0) > 0:
                raise RuntimeError(f"Failed to consume required quantity of {item}")

        if fault_hook_after_consume is not None:
            fault_hook_after_consume()

        # 2b. Designate construction site entity in m_tensor
        allocated_slot = designate_construction_site(
            engine.state.m_tensor,
            engine._entity_count_ref,
            structure_type=SHELTER_STRUCTURE_TYPE,
            center_x=lx,
            center_y=ly,
            scale=plan.footprint_radius,
            durability=SHELTER_DURABILITY,
            shelter_cap=SHELTER_CAP,
            build_progress=0.0,
            create_object_fn=create_site_row,
            device=engine.state.device,
        )
        if allocated_slot != reserved_slot:
            raise RuntimeError("Failed to allocate the reserved entity row")

        # 2c. Allocate runtime e_* UID
        created_structure_uid = engine._make_entity_id()
        engine._entity_uid_by_slot[allocated_slot] = created_structure_uid

        if fault_hook_after_create is not None:
            fault_hook_after_create(allocated_slot)

        # 2d. Register geometry in map_geo
        pre_tiles = map_geo.TILE_TO_ENTITY.copy()
        map_geo.register_entity(
            allocated_slot,
            "circle",
            lx,
            ly,
            plan.footprint_radius,
            device=engine.state.device,
        )

        if fault_hook_after_geo is not None:
            fault_hook_after_geo(allocated_slot)

        # 2e. Update SettlementRegistry
        if open_project is not None:
            proj_id = open_project["id"]
        else:
            proj_id = registry.create_project(
                plan.settlement_id,
                builder_id=plan.builder_id,
                building_kind=plan.building_kind,
                anchor=plan.anchor,
                recipe=copy.deepcopy(plan.recipe),
                current_tick=current_tick,
                human_resolver=human_resolver,
            )

        struct_resolver = make_engine_structure_resolver(engine)
        registry.fund_project(
            proj_id,
            structure_uid=created_structure_uid,
            paid=copy.deepcopy(plan.recipe),
            current_tick=current_tick,
            structure_resolver=struct_resolver,
        )

        if fault_hook_after_registry is not None:
            fault_hook_after_registry(proj_id, created_structure_uid)

        # 2f. Queue audit event
        engine._queue_event(
            "settlement_shelter_funded",
            created_structure_uid,
            allocated_slot,
            project_id=proj_id,
            settlement_id=plan.settlement_id,
        )

        return ConstructionTransactionResult(
            ok=True,
            project_id=proj_id,
            structure_uid=created_structure_uid,
            slot=allocated_slot,
            anchor=copy.deepcopy(plan.anchor),
            local_pos=(lx, ly),
            paid=copy.deepcopy(plan.recipe),
            tick=current_tick,
        )

    except Exception as exc:
        # =====================================================================
        # COMPLETE PRECISION ROLLBACK
        # =====================================================================
        # 1. Restore registry
        registry.restore_state(registry_memento)

        # 2. Restore map_geo geometry
        if pre_tiles is not None:
            map_geo.MAP_GEO.pop(reserved_slot, None)
            map_geo.TILE_TO_ENTITY.clear()
            map_geo.TILE_TO_ENTITY.update(pre_tiles)
            map_geo.geo_version = pre_geo_version

        # 3. Restore entity slot and counters
        m_tensor[reserved_slot] = pre_row
        engine._entity_uid_by_slot[reserved_slot] = None
        engine._entity_count_ref[0] = pre_entity_count
        engine._next_entity_uid = pre_next_entity_uid

        # 4. Restore builder inventory
        builder_inv.clear()
        builder_inv.update(inv_memento)

        # 5. Restore event ledger
        del engine._pending_events[pre_events_len:]
        if pre_event_seq is not None:
            engine._event_seq = pre_event_seq

        raise SettlementTransactionError(f"Transaction failed and rolled back cleanly: {exc}") from exc


# =============================================================================
# Caller-Controlled Construction Progress Service API
# =============================================================================

def advance_settlement_construction(
    engine: Any,
    registry: SettlementRegistry,
    project_id: str,
    worker_id: str,
    *,
    progress_step: Optional[float] = None,
    fault_hook_before_complete: Optional[Callable[[], None]] = None,
) -> ConstructionProgressResult:
    """Advance construction labor on an active funded settlement project.

    - Preflight guards: project in ('funded', 'building'), living worker member,
      active chunk (not dormant), worker reach and stamina.
    - Consumes worker stamina; updates S_BUILD_PROGRESS (col 9) and structure M_HP.
    - Transitions registry status from 'funded' -> 'building', and 'building' -> 'complete'
      exactly once when progress reaches 100.
    - Links completed structure UID into settlement buildings list.
    - Enforces complete rollback on injected fault before completion.
    """
    proj = registry.get_project(project_id)
    if proj["status"] not in ("funded", "building"):
        raise SettlementPreflightError(
            f"Cannot advance construction on project in status {proj['status']!r}; must be 'funded' or 'building'"
        )
    if proj["paid"] != proj["recipe"]:
        raise SettlementPreflightError(f"Project {project_id} has not been fully paid")

    settlement = registry.get_settlement(proj["settlement_id"])
    if settlement["status"] != "active":
        raise SettlementPreflightError(f"Owning settlement {proj['settlement_id']} is not active")

    validate_string(worker_id, "worker_id", min_len=1, max_len=128)
    if worker_id not in settlement["members"]:
        raise SettlementPreflightError(f"Worker {worker_id} is not a member of {proj['settlement_id']}")

    # Worker living state
    human_resolver = make_engine_human_resolver(engine)
    h_info = human_resolver(worker_id)
    if not h_info or not h_info.get("alive"):
        raise SettlementPreflightError(f"Worker {worker_id} is deceased or missing")

    h_uids = getattr(engine, "_human_uid_by_slot", [])
    if worker_id not in h_uids:
        raise SettlementPreflightError(f"Worker {worker_id} is not live in world tensors")
    w_slot = h_uids.index(worker_id)
    if int(engine.state.h_tensor[w_slot, cfg.H_SPACE]) != 0:
        raise SettlementPreflightError(f"Worker {worker_id} is outside the overworld")

    # Worker stamina check
    stamina = float(engine.state.h_tensor[w_slot, cfg.H_STAMINA])
    if stamina < BUILD_MIN_STAMINA:
        raise SettlementPreflightError(f"Worker {worker_id} lacks minimum stamina ({stamina:.1f} < {BUILD_MIN_STAMINA})")

    # Structure living state in m_tensor
    structure_uid = proj["structure_uid"]
    if structure_uid is None:
        raise SettlementPreflightError(f"Project {project_id} has null structure_uid")

    e_uids = getattr(engine, "_entity_uid_by_slot", [])
    if structure_uid not in e_uids:
        # Check dormancy
        window = getattr(engine, "_window", None)
        if window is not None and hasattr(window, "structures"):
            for coord, rec_list in window.structures.records.items():
                for rec in rec_list:
                    if rec.get("uid") == structure_uid:
                        raise SettlementDormancyError(
                            f"Structure {structure_uid} is dormant; construction progress is frozen"
                        )
        raise SettlementPreflightError(f"Structure {structure_uid} is not present in live engine tensors")
    s_slot = e_uids.index(structure_uid)

    # Dormancy check: ensure chunks are integrated
    window = getattr(engine, "_window", None)
    if window is not None and hasattr(window, "chunks"):
        struct_anchor = proj["anchor"]
        s_cx, s_cy = struct_anchor["chunk"]
        if ChunkCoord(s_cx, s_cy) not in window.chunks:
            raise SettlementDormancyError(
                f"Project structure chunk ({s_cx}, {s_cy}) is dormant; construction is frozen"
            )

    # Reach check
    sx = float(engine.state.m_tensor[s_slot, cfg.CX])
    sy = float(engine.state.m_tensor[s_slot, cfg.CY])
    wx = float(engine.state.h_tensor[w_slot, cfg.X])
    wy = float(engine.state.h_tensor[w_slot, cfg.Y])
    if math.hypot(sx - wx, sy - wy) > BUILD_RADIUS:
        raise SettlementPreflightError(f"Worker {worker_id} is out of reach of structure {structure_uid}")

    current_tick = int(getattr(engine, "tick", 0))
    step = BUILD_PROGRESS_PER_HUMAN if progress_step is None else validate_finite_number(progress_step, "progress_step")
    if step <= 0.0:
        raise SettlementPreflightError("Construction progress step must be positive")

    # Capture mementos for rollback
    pre_stamina = float(engine.state.h_tensor[w_slot, cfg.H_STAMINA])
    pre_progress = float(engine.state.m_tensor[s_slot, cfg.S_BUILD_PROGRESS])
    pre_hp = float(engine.state.m_tensor[s_slot, cfg.M_HP])
    registry_memento = registry.export_state()
    pre_events_len = len(engine._pending_events)
    pre_event_seq = getattr(engine, "_event_seq", None)

    try:
        # Deduct stamina
        engine.state.h_tensor[w_slot, cfg.H_STAMINA] = max(0.0, pre_stamina - BUILD_STAMINA_COST)

        # Calculate progress gain
        skill = float(engine.state.h_tensor[w_slot, cfg.H_SKILL])
        skill_factor = 1.0 + skill / 100.0
        gain = step * skill_factor
        row = engine.state.m_tensor[s_slot]
        row[cfg.S_BUILD_PROGRESS] = min(100.0, pre_progress + gain)
        new_progress = float(row[cfg.S_BUILD_PROGRESS])

        # Update tensor progress and HP
        durability = float(engine.state.m_tensor[s_slot, cfg.S_DURABILITY])
        new_hp = max(1.0, durability * (new_progress / 100.0))
        row[cfg.M_HP] = new_hp

        # Update registry status
        struct_resolver = make_engine_structure_resolver(engine)
        completed = new_progress >= 100.0
        if not completed:
            registry.advance_project_work(
                project_id,
                current_tick=current_tick,
                structure_resolver=struct_resolver,
            )

        else:
            if fault_hook_before_complete is not None:
                fault_hook_before_complete()

            registry.complete_project(
                project_id,
                current_tick=current_tick,
                structure_resolver=struct_resolver,
            )
            engine._queue_event(
                "settlement_shelter_completed",
                structure_uid,
                s_slot,
                project_id=project_id,
                settlement_id=proj["settlement_id"],
            )

        return ConstructionProgressResult(
            ok=True,
            project_id=project_id,
            structure_uid=structure_uid,
            slot=s_slot,
            progress=new_progress,
            durability=durability,
            hp=new_hp,
            completed=completed,
            tick=current_tick,
        )

    except Exception as exc:
        # Rollback advance mutations
        engine.state.h_tensor[w_slot, cfg.H_STAMINA] = pre_stamina
        engine.state.m_tensor[s_slot, cfg.S_BUILD_PROGRESS] = pre_progress
        engine.state.m_tensor[s_slot, cfg.M_HP] = pre_hp
        registry.restore_state(registry_memento)
        del engine._pending_events[pre_events_len:]
        if pre_event_seq is not None:
            engine._event_seq = pre_event_seq
        raise SettlementTransactionError(f"Construction progress failed and rolled back: {exc}") from exc


__all__ = [
    "BLOCKED_TERRAIN_TYPES",
    "BUILD_MIN_STAMINA",
    "BUILD_PROGRESS_PER_HUMAN",
    "BUILD_RADIUS",
    "BUILD_SITE_HP_FRACTION",
    "BUILD_STAMINA_COST",
    "ConstructionProgressResult",
    "ConstructionTransactionResult",
    "DEFAULT_LATTICE_STEP_UNITS",
    "HABITABLE_TERRAIN_TYPES",
    "MAX_CANDIDATES",
    "RECIPE_PERSONAL_SHELTER",
    "SHELTER_CAP",
    "SHELTER_DURABILITY",
    "SHELTER_SCALE",
    "SHELTER_STRUCTURE_TYPE",
    "SettlementConstructionError",
    "SettlementDormancyError",
    "SettlementPreflightError",
    "SettlementSiteSelectionError",
    "SettlementStalePlanError",
    "SettlementTransactionError",
    "SitePlan",
    "advance_settlement_construction",
    "commit_settlement_project",
    "generate_lattice_candidates",
    "is_site_candidate_viable",
    "make_engine_human_resolver",
    "make_engine_structure_resolver",
    "plan_settlement_site",
]
