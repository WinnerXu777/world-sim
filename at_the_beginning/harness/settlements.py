"""at_the_beginning/harness/settlements.py
======================================
R6.4 Bounded Settlement Registry and Coordinate Lattice Foundation.

Design reference: ``1010_settlement_gap.md`` (2026-10-10).
Status: Pure engine service foundation. Explicit instance creation only;
no import side effects, no tensor width/column changes, no game save integration,
no inventory item mutations or engine hook defaults.

Coordinate math:
- Fixed-point lattice with Q = 256 subunits per unit.
- Chunk size = 256 units = 65,536 subunits.
- Exact anchor schema: ``{"chunk": [cx, cy], "sub": [sx, sy]}``.
- Chunk components cx, cy in [-2^40, 2^40] (matching chunk_routes.MAX_ABS_COORD).
- Sub components sx, sy in [0, 65535].
- Negative coordinate normalization uses floor division / divmod.
- Live local conversion: ``((cx - origin_cx) * 65536 + sx) / 256.0`` (integer-first).
- Claim distance and overlap use exact integer squared distance against claim_radius_q.
"""
from __future__ import annotations

import copy
import math
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

# Attempt configuration import with clean fallback
try:
    import genesis_config as cfg
except ImportError:  # pragma: no cover - package import fallback
    try:
        from at_the_beginning import genesis_config as cfg
    except ImportError:
        cfg = None

# Max humans global member cap from genesis_config if available
MAX_HUMANS_DEFAULT: int = int(getattr(cfg, "MAX_HUMANS", 100))
STRUCTURE_TYPES_DEFAULT: Set[int] = set(getattr(cfg, "STRUCTURE_TYPES", range(20, 40)))
S_BUILD_PROGRESS_COL: int = int(getattr(cfg, "S_BUILD_PROGRESS", 9))

# Envelope & schema version
SCHEMA_VERSION: int = 1

# Coordinate Lattice Constants
Q: int = 256                                  # Subunits per unit
CHUNK_UNITS: int = 256                        # Units per chunk
CHUNK_SUBUNITS: int = CHUNK_UNITS * Q         # 65,536 subunits per chunk
MAX_ABS_COORD: int = 2**40                    # Maximum absolute chunk coordinate
MIN_CHUNK_COORD: int = -MAX_ABS_COORD
MAX_CHUNK_COORD: int = MAX_ABS_COORD
MIN_SUB_COORD: int = 0
MAX_SUB_COORD: int = CHUNK_SUBUNITS - 1       # 65,535

# Default Claim Radius
DEFAULT_CLAIM_RADIUS_Q: int = 51200           # 200 units * 256 subunits/unit
MIN_CLAIM_RADIUS_Q: int = 1
MAX_CLAIM_RADIUS_Q: int = 131072              # 512 units * 256 subunits/unit

# Tick bounds
MAX_TICK: int = 2**63 - 1

# ID Counter bounds
MIN_ID_COUNTER: int = 1
MAX_ID_COUNTER: int = 100000000               # 10^8: valid allocated suffixes are 1..99999999

# Registry Caps Defaults (Proposed R6.4 data choices)
DEFAULT_MAX_SETTLEMENTS: int = 32
DEFAULT_MAX_PROJECTS: int = 64
DEFAULT_MAX_BUILDING_LINKS: int = 1024
DEFAULT_MAX_MEMBERS_PER_SETTLEMENT: int = 128
DEFAULT_MAX_BUILDINGS_PER_SETTLEMENT: int = 128

# Valid Statuses and Roles
SETTLEMENT_STATUSES: Tuple[str, ...] = ("active", "dissolved")
SETTLEMENT_ROLES: Tuple[str, ...] = ("builder", "keeper", "watch")

PROJECT_STATUSES: Tuple[str, ...] = ("planned", "funded", "building", "complete", "cancelled", "destroyed")
OPEN_PROJECT_STATUSES: Tuple[str, ...] = ("planned", "funded", "building")
TERMINAL_PROJECT_STATUSES: Tuple[str, ...] = ("complete", "cancelled", "destroyed")

# Default recipe for personal shelter (systems/construction/catalog.py)
DEFAULT_PERSONAL_SHELTER_RECIPE: Dict[str, int] = {
    "wood_bundle": 6,
    "fiber_bundle": 3,
    "plank_bundle": 2,
}

ENVELOPE_KEYS: Set[str] = {"schema_version", "next_id", "next_project_id", "records", "projects"}
SETTLEMENT_RECORD_KEYS: Set[str] = {
    "uid",
    "name",
    "anchor",
    "claim_radius_q",
    "members",
    "buildings",
    "roles",
    "founded_tick",
    "last_review_tick",
    "status",
}
PROJECT_RECORD_KEYS: Set[str] = {
    "id",
    "settlement_id",
    "builder_id",
    "building_kind",
    "anchor",
    "structure_uid",
    "status",
    "created_tick",
    "last_work_tick",
    "recipe",
    "paid",
}
ANCHOR_KEYS: Set[str] = {"chunk", "sub"}


# =============================================================================
# Exceptions
# =============================================================================

class SettlementError(Exception):
    """Base exception for all settlement registry errors."""


class SettlementValidationError(SettlementError):
    """Raised when envelope, record, field, or invariant validation fails."""


class SettlementCapError(SettlementValidationError):
    """Raised when a settlement, project, member, building, or ID counter cap is exceeded."""


class SettlementReferenceError(SettlementValidationError):
    """Raised when human or structure reference resolution fails against authoritative source."""


class SettlementConflictError(SettlementValidationError):
    """Raised when duplicate IDs, overlapping claims, or dual-membership conflicts occur."""


# =============================================================================
# Strict Type and Value Validation Helpers
# =============================================================================

def validate_strict_int(val: Any, name: str, min_val: Optional[int] = None, max_val: Optional[int] = None) -> int:
    """Validate that val is a strict Python int (rejecting bool, float, str, etc.)."""
    if type(val) is not int:
        raise SettlementValidationError(f"{name} must be a strict int, got {type(val).__name__}: {val!r}")
    if min_val is not None and val < min_val:
        raise SettlementValidationError(f"{name} must be >= {min_val}, got {val}")
    if max_val is not None and val > max_val:
        raise SettlementValidationError(f"{name} must be <= {max_val}, got {val}")
    return val


def validate_finite_number(val: Any, name: str) -> float:
    """Validate that val is a finite real number (rejecting bool, NaN, and +/-Inf)."""
    if not isinstance(val, (int, float)) or isinstance(val, bool):
        raise SettlementValidationError(f"{name} must be a number, got {type(val).__name__}: {val!r}")
    num = float(val)
    if math.isnan(num) or math.isinf(num):
        raise SettlementValidationError(f"{name} must be finite, got {val!r}")
    return num


def require_exact_keys(d: Any, expected: Set[str], context: str) -> None:
    """Ensure d is a dict containing exactly expected keys, with no extra or missing keys."""
    if not isinstance(d, dict):
        raise SettlementValidationError(f"{context} must be a dict, got {type(d).__name__}")
    actual = set(d.keys())
    if actual != expected:
        missing = expected - actual
        extra = actual - expected
        raise SettlementValidationError(f"{context} key mismatch: missing={sorted(missing)}, extra={sorted(extra)}")


def validate_string(val: Any, name: str, min_len: int = 1, max_len: int = 128, allow_control: bool = False) -> str:
    """Validate a string with length bounds and optional control-character rejection."""
    if not isinstance(val, str):
        raise SettlementValidationError(f"{name} must be a str, got {type(val).__name__}: {val!r}")
    if len(val) < min_len:
        raise SettlementValidationError(f"{name} must have length >= {min_len}, got {len(val)}")
    if len(val) > max_len:
        raise SettlementValidationError(f"{name} must have length <= {max_len}, got {len(val)}")
    if not allow_control:
        for ch in val:
            if ord(ch) < 32 or unicodedata.category(ch) == "Cc":
                raise SettlementValidationError(f"{name} contains prohibited control character: {ch!r}")
    return val


# =============================================================================
# Coordinate and Anchor Functions
# =============================================================================

def make_anchor(chunk_x: int, chunk_y: int, sub_x: int, sub_y: int) -> Dict[str, List[int]]:
    """Construct an exact anchor dictionary from integer chunk and sub components."""
    cx = validate_strict_int(chunk_x, "chunk_x", MIN_CHUNK_COORD, MAX_CHUNK_COORD)
    cy = validate_strict_int(chunk_y, "chunk_y", MIN_CHUNK_COORD, MAX_CHUNK_COORD)
    sx = validate_strict_int(sub_x, "sub_x", MIN_SUB_COORD, MAX_SUB_COORD)
    sy = validate_strict_int(sub_y, "sub_y", MIN_SUB_COORD, MAX_SUB_COORD)
    return {"chunk": [cx, cy], "sub": [sx, sy]}


def validate_anchor(anchor: Any, name: str = "anchor") -> Dict[str, List[int]]:
    """Strictly validate an anchor dictionary against the exact {chunk:[cx,cy], sub:[sx,sy]} schema."""
    require_exact_keys(anchor, ANCHOR_KEYS, name)
    chunk = anchor["chunk"]
    sub = anchor["sub"]
    if not isinstance(chunk, (list, tuple)) or len(chunk) != 2:
        raise SettlementValidationError(f"{name}.chunk must be a 2-element sequence [cx, cy]")
    if not isinstance(sub, (list, tuple)) or len(sub) != 2:
        raise SettlementValidationError(f"{name}.sub must be a 2-element sequence [sx, sy]")
    cx = validate_strict_int(chunk[0], f"{name}.chunk[0]", MIN_CHUNK_COORD, MAX_CHUNK_COORD)
    cy = validate_strict_int(chunk[1], f"{name}.chunk[1]", MIN_CHUNK_COORD, MAX_CHUNK_COORD)
    sx = validate_strict_int(sub[0], f"{name}.sub[0]", MIN_SUB_COORD, MAX_SUB_COORD)
    sy = validate_strict_int(sub[1], f"{name}.sub[1]", MIN_SUB_COORD, MAX_SUB_COORD)
    return {"chunk": [cx, cy], "sub": [sx, sy]}


def normalize_subunits_to_anchor(total_sub_x: int, total_sub_y: int) -> Dict[str, List[int]]:
    """Convert total integer subunits into normalized (chunk, sub) coordinates via floor division (divmod).

    Negative coordinates naturally map to floor chunk and non-negative remainder sub in [0, 65535].
    """
    tx = validate_strict_int(total_sub_x, "total_sub_x")
    ty = validate_strict_int(total_sub_y, "total_sub_y")
    cx, sx = divmod(tx, CHUNK_SUBUNITS)
    cy, sy = divmod(ty, CHUNK_SUBUNITS)
    if cx < MIN_CHUNK_COORD or cx > MAX_CHUNK_COORD or cy < MIN_CHUNK_COORD or cy > MAX_CHUNK_COORD:
        raise SettlementValidationError(f"Normalized chunk coordinates ({cx}, {cy}) exceed +/-2^40 bounds")
    return {"chunk": [cx, cy], "sub": [sx, sy]}


def quantize_unit_to_anchor(world_x: float | int, world_y: float | int) -> Dict[str, List[int]]:
    """Snap world unit coordinates to the Q256 anchor lattice.

    Ties are snapped half-up: int(math.floor(val * Q + 0.5)).
    Negative values are normalized via floor division.
    """
    wx = validate_finite_number(world_x, "world_x")
    wy = validate_finite_number(world_y, "world_y")
    total_sub_x = int(math.floor(wx * Q + 0.5))
    total_sub_y = int(math.floor(wy * Q + 0.5))
    return normalize_subunits_to_anchor(total_sub_x, total_sub_y)


def quantize_chunk_local_to_anchor(chunk_x: int, chunk_y: int, local_x: float | int, local_y: float | int) -> Dict[str, List[int]]:
    """Snap chunk-relative local units to the Q256 anchor lattice."""
    cx = validate_strict_int(chunk_x, "chunk_x", MIN_CHUNK_COORD, MAX_CHUNK_COORD)
    cy = validate_strict_int(chunk_y, "chunk_y", MIN_CHUNK_COORD, MAX_CHUNK_COORD)
    lx = validate_finite_number(local_x, "local_x")
    ly = validate_finite_number(local_y, "local_y")
    sub_x = int(math.floor(lx * Q + 0.5))
    sub_y = int(math.floor(ly * Q + 0.5))
    total_sub_x = cx * CHUNK_SUBUNITS + sub_x
    total_sub_y = cy * CHUNK_SUBUNITS + sub_y
    return normalize_subunits_to_anchor(total_sub_x, total_sub_y)


def anchor_to_total_subunits(anchor: Dict[str, Any]) -> Tuple[int, int]:
    """Convert an anchor to total integer subunits from world coordinate origin."""
    a = validate_anchor(anchor)
    cx, cy = a["chunk"]
    sx, sy = a["sub"]
    return cx * CHUNK_SUBUNITS + sx, cy * CHUNK_SUBUNITS + sy


def anchor_to_local(anchor: Dict[str, Any], origin_cx: int, origin_cy: int) -> Tuple[float, float]:
    """Convert anchor to live local coordinate relative to origin_cx, origin_cy.

    Integer subtraction occurs first to preserve origin invariance and avoid
    large-magnitude floating point accumulation:
    local_x = ((cx - origin_cx) * 65536 + sx) / 256.0
    """
    a = validate_anchor(anchor)
    ocx = validate_strict_int(origin_cx, "origin_cx", MIN_CHUNK_COORD, MAX_CHUNK_COORD)
    ocy = validate_strict_int(origin_cy, "origin_cy", MIN_CHUNK_COORD, MAX_CHUNK_COORD)
    cx, cy = a["chunk"]
    sx, sy = a["sub"]
    local_x = ((cx - ocx) * CHUNK_SUBUNITS + sx) / float(Q)
    local_y = ((cy - ocy) * CHUNK_SUBUNITS + sy) / float(Q)
    return local_x, local_y


def anchor_diff_q(anchor_a: Dict[str, Any], anchor_b: Dict[str, Any]) -> Tuple[int, int]:
    """Return integer differences (dx_q, dy_q) in subunits between two anchors."""
    a = validate_anchor(anchor_a, "anchor_a")
    b = validate_anchor(anchor_b, "anchor_b")
    dx_q = (a["chunk"][0] - b["chunk"][0]) * CHUNK_SUBUNITS + (a["sub"][0] - b["sub"][0])
    dy_q = (a["chunk"][1] - b["chunk"][1]) * CHUNK_SUBUNITS + (a["sub"][1] - b["sub"][1])
    return dx_q, dy_q


def anchor_distance_sq_q(anchor_a: Dict[str, Any], anchor_b: Dict[str, Any]) -> int:
    """Return exact integer squared distance in subunits squared between two anchors."""
    dx_q, dy_q = anchor_diff_q(anchor_a, anchor_b)
    return dx_q * dx_q + dy_q * dy_q


def is_point_in_claim(point_anchor: Dict[str, Any], claim_anchor: Dict[str, Any], claim_radius_q: int) -> bool:
    """Check if point_anchor lies within claim_radius_q of claim_anchor."""
    r = validate_strict_int(claim_radius_q, "claim_radius_q", MIN_CLAIM_RADIUS_Q, MAX_CLAIM_RADIUS_Q)
    dist_sq_q = anchor_distance_sq_q(point_anchor, claim_anchor)
    return dist_sq_q <= r * r


def claims_overlap(
    anchor_a: Dict[str, Any],
    radius_a_q: int,
    anchor_b: Dict[str, Any],
    radius_b_q: int,
    inclusive: bool = True,
) -> bool:
    """Check if two circular claims overlap using exact integer squared distance."""
    ra = validate_strict_int(radius_a_q, "radius_a_q", MIN_CLAIM_RADIUS_Q, MAX_CLAIM_RADIUS_Q)
    rb = validate_strict_int(radius_b_q, "radius_b_q", MIN_CLAIM_RADIUS_Q, MAX_CLAIM_RADIUS_Q)
    dist_sq_q = anchor_distance_sq_q(anchor_a, anchor_b)
    sum_r = ra + rb
    threshold = sum_r * sum_r
    return dist_sq_q <= threshold if inclusive else dist_sq_q < threshold


# =============================================================================
# Configuration
# =============================================================================

@dataclass(frozen=True)
class SettlementConfig:
    max_settlements: int = DEFAULT_MAX_SETTLEMENTS
    max_projects: int = DEFAULT_MAX_PROJECTS
    max_building_links: int = DEFAULT_MAX_BUILDING_LINKS
    max_members_global: int = MAX_HUMANS_DEFAULT
    max_members_per_settlement: int = DEFAULT_MAX_MEMBERS_PER_SETTLEMENT
    max_buildings_per_settlement: int = DEFAULT_MAX_BUILDINGS_PER_SETTLEMENT
    default_claim_radius_q: int = DEFAULT_CLAIM_RADIUS_Q

    def __post_init__(self) -> None:
        validate_strict_int(self.max_settlements, "max_settlements", 1, 1000)
        validate_strict_int(self.max_projects, "max_projects", 1, 1000)
        validate_strict_int(self.max_building_links, "max_building_links", 1, 10000)
        validate_strict_int(self.max_members_global, "max_members_global", 1, MAX_HUMANS_DEFAULT)
        validate_strict_int(self.max_members_per_settlement, "max_members_per_settlement", 1, 1000)
        validate_strict_int(self.max_buildings_per_settlement, "max_buildings_per_settlement", 1, 1000)
        validate_strict_int(self.default_claim_radius_q, "default_claim_radius_q", MIN_CLAIM_RADIUS_Q, MAX_CLAIM_RADIUS_Q)


# =============================================================================
# SettlementRegistry Service
# =============================================================================

class SettlementRegistry:
    """Pure engine service managing settlement records, coordinates, and projects.

    - Explicit instance creation only (no global singleton, no import side effects).
    - Inaccessible to external in-place corruption: all queries return defensive copies.
    - Strict monotonic IDs (s_XXXXXXXX, sp_XXXXXXXX); ID counters never decremented or reused.
    - Global building ownership and global living member exclusivity enforced.
    - Empty-building active founding state allowed (0 buildings while first project is planned;
      dissolved settlements must be empty).
    - Atomic restoration: validation staged completely before state replacement; on any
      failure, the prior state is left completely untouched.
    """

    def __init__(self, config: Optional[SettlementConfig] = None) -> None:
        self._config: SettlementConfig = config or SettlementConfig()
        self._schema_version: int = SCHEMA_VERSION
        self._next_id: int = MIN_ID_COUNTER
        self._next_project_id: int = MIN_ID_COUNTER
        self._records: Dict[str, Dict[str, Any]] = {}
        self._projects: Dict[str, Dict[str, Any]] = {}

    @property
    def config(self) -> SettlementConfig:
        return self._config

    @property
    def schema_version(self) -> int:
        return self._schema_version

    @property
    def next_id(self) -> int:
        return self._next_id

    @property
    def next_project_id(self) -> int:
        return self._next_project_id

    # -------------------------------------------------------------------------
    # ID Allocation (Monotonic, Non-reusable)
    # -------------------------------------------------------------------------

    def _allocate_settlement_id(self) -> str:
        if self._next_id >= MAX_ID_COUNTER:
            raise SettlementCapError("Settlement ID counter exhausted (limit 100,000,000)")
        s_id = f"s_{self._next_id:08d}"
        self._next_id += 1
        return s_id

    def _allocate_project_id(self) -> str:
        if self._next_project_id >= MAX_ID_COUNTER:
            raise SettlementCapError("Project ID counter exhausted (limit 100,000,000)")
        sp_id = f"sp_{self._next_project_id:08d}"
        self._next_project_id += 1
        return sp_id

    # -------------------------------------------------------------------------
    # Defensive Queries
    # -------------------------------------------------------------------------

    def get_settlement(self, uid: str) -> Dict[str, Any]:
        """Return a defensive deep copy of a settlement record."""
        if uid not in self._records:
            raise KeyError(f"Settlement not found: {uid!r}")
        return copy.deepcopy(self._records[uid])

    def has_settlement(self, uid: str) -> bool:
        return uid in self._records

    def list_settlements(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return defensive copies of all settlements, optionally filtered by status."""
        return [
            copy.deepcopy(rec)
            for rec in self._records.values()
            if status is None or rec["status"] == status
        ]

    def get_project(self, project_id: str) -> Dict[str, Any]:
        """Return a defensive deep copy of a project record."""
        if project_id not in self._projects:
            raise KeyError(f"Project not found: {project_id!r}")
        return copy.deepcopy(self._projects[project_id])

    def has_project(self, project_id: str) -> bool:
        return project_id in self._projects

    def list_projects(
        self,
        settlement_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return defensive copies of projects, optionally filtered by settlement or status."""
        return [
            copy.deepcopy(proj)
            for proj in self._projects.values()
            if (settlement_id is None or proj["settlement_id"] == settlement_id)
            and (status is None or proj["status"] == status)
        ]

    def get_open_project(self, settlement_id: str) -> Optional[Dict[str, Any]]:
        """Return defensive copy of the open project for the settlement, or None."""
        for proj in self._projects.values():
            if proj["settlement_id"] == settlement_id and proj["status"] in OPEN_PROJECT_STATUSES:
                return copy.deepcopy(proj)
        return None

    def find_settlement_by_member(self, human_uid: str) -> Optional[str]:
        """Find the active settlement ID that currently contains human_uid as a member."""
        for s_id, rec in self._records.items():
            if rec["status"] == "active" and human_uid in rec["members"]:
                return s_id
        return None

    def find_settlement_by_building(self, structure_uid: str) -> Optional[str]:
        """Find the settlement ID that owns structure_uid."""
        for s_id, rec in self._records.items():
            if structure_uid in rec["buildings"]:
                return s_id
        return None

    # -------------------------------------------------------------------------
    # Settlement Lifecycle Mutators
    # -------------------------------------------------------------------------

    def create_settlement(
        self,
        name: str,
        anchor: Dict[str, Any],
        claim_radius_q: Optional[int] = None,
        members: Sequence[str] = (),
        buildings: Sequence[str] = (),
        roles: Optional[Dict[str, str]] = None,
        current_tick: int = 0,
        human_resolver: Optional[Callable[[str], Any]] = None,
        structure_resolver: Optional[Callable[[str], Any]] = None,
    ) -> str:
        """Create and register a new active settlement.

        - Empty building list is permitted (active founding state).
        - Living members validated against authoritative adapter callback.
        - Structures validated against authoritative adapter callback (active or dormant).
        - Member and building exclusivity across the entire registry enforced.
        """
        # Global settlement cap check
        if len(self._records) >= self._config.max_settlements:
            raise SettlementCapError(
                f"Settlement cap reached ({len(self._records)}/{self._config.max_settlements})"
            )

        name = validate_string(name, "settlement name", min_len=1, max_len=80, allow_control=False)
        validated_anchor = validate_anchor(anchor)
        radius_q = self._config.default_claim_radius_q if claim_radius_q is None else claim_radius_q
        radius_q = validate_strict_int(radius_q, "claim_radius_q", MIN_CLAIM_RADIUS_Q, MAX_CLAIM_RADIUS_Q)
        tick = validate_strict_int(current_tick, "current_tick", 0, MAX_TICK)

        # Normalize and validate members
        for m in members:
            validate_string(m, "member UID", min_len=1, max_len=128, allow_control=False)
        member_list = sorted(set(members))
        if not member_list:
            raise SettlementValidationError("Active settlement must have at least 1 founding member")
        if len(member_list) > self._config.max_members_per_settlement:
            raise SettlementCapError(
                f"Member count {len(member_list)} exceeds per-settlement cap {self._config.max_members_per_settlement}"
            )

        # Check global member limit and exclusivity
        existing_active_members: Set[str] = set()
        for rec in self._records.values():
            if rec["status"] == "active":
                existing_active_members.update(rec["members"])

        conflicts = set(member_list) & existing_active_members
        if conflicts:
            raise SettlementConflictError(f"Members already belong to another active settlement: {sorted(conflicts)}")

        effective_max_members = min(self._config.max_members_global, MAX_HUMANS_DEFAULT)
        if len(existing_active_members) + len(member_list) > effective_max_members:
            raise SettlementCapError(
                f"Total members would exceed global cap {effective_max_members}"
            )

        # Authoritative resident validation
        for m in member_list:
            if human_resolver is not None:
                info = human_resolver(m)
                if not info:
                    raise SettlementReferenceError(f"Resident UID {m!r} could not be resolved")
                if isinstance(info, dict):
                    if "alive" in info and type(info["alive"]) is not bool:
                        raise SettlementValidationError(f"Resident {m!r} 'alive' metadata must be a strict bool")
                    if not info.get("alive", True):
                        raise SettlementReferenceError(f"Resident {m!r} is deceased; cannot be an active member")

        # Normalize and validate buildings (0 allowed on founding)
        for b in buildings:
            validate_string(b, "building UID", min_len=1, max_len=128, allow_control=False)
        building_list = sorted(set(buildings))
        if len(building_list) > self._config.max_buildings_per_settlement:
            raise SettlementCapError(
                f"Building count {len(building_list)} exceeds per-settlement cap {self._config.max_buildings_per_settlement}"
            )

        # Global building link cap and uniqueness check
        existing_buildings: Set[str] = set()
        for rec in self._records.values():
            existing_buildings.update(rec["buildings"])

        building_conflicts = set(building_list) & existing_buildings
        if building_conflicts:
            raise SettlementConflictError(
                f"Buildings already associated with a settlement: {sorted(building_conflicts)}"
            )

        if len(existing_buildings) + len(building_list) > self._config.max_building_links:
            raise SettlementCapError(
                f"Total building links would exceed global cap {self._config.max_building_links}"
            )

        # Authoritative structure validation
        for b in building_list:
            if structure_resolver is not None:
                s_info = structure_resolver(b)
                if not s_info:
                    raise SettlementReferenceError(f"Structure UID {b!r} could not be resolved")
                if not isinstance(s_info, dict):
                    raise SettlementValidationError(f"Structure {b!r} resolver info must be a dict")
                self._validate_structure_info(b, s_info)

        # Validate roles
        roles_dict: Dict[str, str] = {}
        if roles:
            if not isinstance(roles, dict):
                raise SettlementValidationError("roles must be a dictionary")
            for m_uid, role_name in roles.items():
                if m_uid not in member_list:
                    raise SettlementValidationError(f"Role assigned to non-member {m_uid!r}")
                if role_name not in SETTLEMENT_ROLES:
                    raise SettlementValidationError(f"Invalid role {role_name!r}; must be in {SETTLEMENT_ROLES}")
                roles_dict[m_uid] = str(role_name)

        s_uid = self._allocate_settlement_id()
        record: Dict[str, Any] = {
            "uid": s_uid,
            "name": name,
            "anchor": validated_anchor,
            "claim_radius_q": radius_q,
            "members": member_list,
            "buildings": building_list,
            "roles": roles_dict,
            "founded_tick": tick,
            "last_review_tick": tick,
            "status": "active",
        }
        self._records[s_uid] = record
        return s_uid

    def dissolve_settlement(self, settlement_id: str, current_tick: int = 0) -> None:
        """Dissolve an active settlement.

        Clears members, buildings, and roles to empty collections.
        Cancels any open project. Counters are preserved monotonically.
        """
        if settlement_id not in self._records:
            raise KeyError(f"Settlement not found: {settlement_id!r}")
        rec = self._records[settlement_id]
        if rec["status"] == "dissolved":
            return  # Already dissolved

        tick = validate_strict_int(current_tick, "current_tick", rec["last_review_tick"], MAX_TICK)

        # Pre-validate all open projects can accept tick before mutating
        for proj in self._projects.values():
            if proj["settlement_id"] == settlement_id and proj["status"] in OPEN_PROJECT_STATUSES:
                validate_strict_int(tick, "current_tick", proj["last_work_tick"], MAX_TICK)

        # Cancel any open project
        for proj in self._projects.values():
            if proj["settlement_id"] == settlement_id and proj["status"] in OPEN_PROJECT_STATUSES:
                self.cancel_project(proj["id"], current_tick=tick)

        rec["status"] = "dissolved"
        rec["members"] = []
        rec["buildings"] = []
        rec["roles"] = {}
        rec["last_review_tick"] = tick

    def add_member(
        self,
        settlement_id: str,
        human_uid: str,
        role: Optional[str] = None,
        current_tick: int = 0,
        human_resolver: Optional[Callable[[str], Any]] = None,
    ) -> None:
        """Add a living member to an active settlement."""
        if settlement_id not in self._records:
            raise KeyError(f"Settlement not found: {settlement_id!r}")
        rec = self._records[settlement_id]
        if rec["status"] != "active":
            raise SettlementValidationError("Cannot add members to a non-active settlement")

        validate_string(human_uid, "human UID", min_len=1, max_len=128, allow_control=False)
        tick = validate_strict_int(current_tick, "current_tick", rec["last_review_tick"], MAX_TICK)

        if role is not None:
            if role not in SETTLEMENT_ROLES:
                raise SettlementValidationError(f"Invalid role {role!r}; must be in {SETTLEMENT_ROLES}")

        if human_uid in rec["members"]:
            return  # Idempotent

        # Cap checks
        if len(rec["members"]) >= self._config.max_members_per_settlement:
            raise SettlementCapError(
                f"Settlement member cap reached ({self._config.max_members_per_settlement})"
            )

        existing = self.find_settlement_by_member(human_uid)
        if existing is not None:
            raise SettlementConflictError(f"Resident {human_uid!r} already belongs to settlement {existing}")

        # Total member cap check against real engine bound and config
        total_active_members = sum(len(r["members"]) for r in self._records.values() if r["status"] == "active")
        effective_max_members = min(self._config.max_members_global, MAX_HUMANS_DEFAULT)
        if total_active_members + 1 > effective_max_members:
            raise SettlementCapError(f"Global member cap exceeded ({effective_max_members})")

        if human_resolver is not None:
            info = human_resolver(human_uid)
            if not info:
                raise SettlementReferenceError(f"Resident UID {human_uid!r} could not be resolved")
            if isinstance(info, dict):
                if "alive" in info and type(info["alive"]) is not bool:
                    raise SettlementValidationError(f"Resident {human_uid!r} 'alive' metadata must be a strict bool")
                if not info.get("alive", True):
                    raise SettlementReferenceError(f"Deceased resident {human_uid!r} cannot become an active member")

        # Staged mutation: apply only after all validation succeeds
        new_members = sorted(set(rec["members"]) | {human_uid})
        new_roles = dict(rec["roles"])
        if role is not None:
            new_roles[human_uid] = role
        rec["members"] = new_members
        rec["roles"] = new_roles
        rec["last_review_tick"] = tick

    def remove_member(self, settlement_id: str, human_uid: str, current_tick: int = 0) -> None:
        """Remove a member from an active settlement."""
        if settlement_id not in self._records:
            raise KeyError(f"Settlement not found: {settlement_id!r}")
        rec = self._records[settlement_id]
        if rec["status"] != "active":
            raise SettlementValidationError("Cannot remove members from a non-active settlement")

        validate_string(human_uid, "human UID", min_len=1, max_len=128, allow_control=False)
        tick = validate_strict_int(current_tick, "current_tick", rec["last_review_tick"], MAX_TICK)

        if human_uid not in rec["members"]:
            return

        if len(rec["members"]) <= 1:
            raise SettlementValidationError(
                "Cannot remove the last member of an active settlement; dissolve the settlement instead"
            )

        new_members = [m for m in rec["members"] if m != human_uid]
        new_roles = {m: r for m, r in rec["roles"].items() if m != human_uid}
        rec["members"] = new_members
        rec["roles"] = new_roles
        rec["last_review_tick"] = tick

    def set_role(
        self,
        settlement_id: str,
        human_uid: str,
        role: Optional[str],
        current_tick: int = 0,
    ) -> None:
        """Assign or clear a role for a settlement member."""
        if settlement_id not in self._records:
            raise KeyError(f"Settlement not found: {settlement_id!r}")
        rec = self._records[settlement_id]
        if rec["status"] != "active":
            raise SettlementValidationError("Cannot modify roles in a non-active settlement")

        validate_string(human_uid, "human UID", min_len=1, max_len=128, allow_control=False)
        tick = validate_strict_int(current_tick, "current_tick", rec["last_review_tick"], MAX_TICK)

        if role is not None and role not in SETTLEMENT_ROLES:
            raise SettlementValidationError(f"Invalid role {role!r}; must be in {SETTLEMENT_ROLES}")

        if human_uid not in rec["members"]:
            raise SettlementValidationError(f"Resident {human_uid!r} is not a member of {settlement_id}")

        new_roles = dict(rec["roles"])
        if role is None:
            new_roles.pop(human_uid, None)
        else:
            new_roles[human_uid] = role
        rec["roles"] = new_roles
        rec["last_review_tick"] = tick

    def add_building(
        self,
        settlement_id: str,
        structure_uid: str,
        structure_resolver: Optional[Callable[[str], Any]] = None,
        current_tick: int = 0,
    ) -> None:
        """Link an existing structure to a settlement."""
        if settlement_id not in self._records:
            raise KeyError(f"Settlement not found: {settlement_id!r}")
        rec = self._records[settlement_id]
        if rec["status"] != "active":
            raise SettlementValidationError("Cannot add buildings to a non-active settlement")

        validate_string(structure_uid, "structure UID", min_len=1, max_len=128, allow_control=False)
        tick = validate_strict_int(current_tick, "current_tick", rec["last_review_tick"], MAX_TICK)

        if structure_uid in rec["buildings"]:
            return  # Idempotent

        if len(rec["buildings"]) >= self._config.max_buildings_per_settlement:
            raise SettlementCapError(
                f"Settlement building cap reached ({self._config.max_buildings_per_settlement})"
            )

        existing = self.find_settlement_by_building(structure_uid)
        if existing is not None:
            raise SettlementConflictError(f"Structure {structure_uid!r} already belongs to settlement {existing}")

        total_buildings = sum(len(r["buildings"]) for r in self._records.values())
        if total_buildings + 1 > self._config.max_building_links:
            raise SettlementCapError(f"Global building links cap reached ({self._config.max_building_links})")

        if structure_resolver is not None:
            info = structure_resolver(structure_uid)
            if not info:
                raise SettlementReferenceError(f"Structure UID {structure_uid!r} could not be resolved")
            if not isinstance(info, dict):
                raise SettlementValidationError(f"Structure {structure_uid!r} resolver info must be a dict")
            self._validate_structure_info(structure_uid, info)

        new_buildings = sorted(set(rec["buildings"]) | {structure_uid})
        rec["buildings"] = new_buildings
        rec["last_review_tick"] = tick

    def remove_building(self, settlement_id: str, structure_uid: str, current_tick: int = 0) -> None:
        """Unlink a structure from a settlement."""
        if settlement_id not in self._records:
            raise KeyError(f"Settlement not found: {settlement_id!r}")
        rec = self._records[settlement_id]

        validate_string(structure_uid, "structure UID", min_len=1, max_len=128, allow_control=False)
        tick = validate_strict_int(current_tick, "current_tick", rec["last_review_tick"], MAX_TICK)

        if structure_uid not in rec["buildings"]:
            return

        rec["buildings"] = [b for b in rec["buildings"] if b != structure_uid]
        rec["last_review_tick"] = tick

    # -------------------------------------------------------------------------
    # Project Mutators
    # -------------------------------------------------------------------------

    def create_project(
        self,
        settlement_id: str,
        builder_id: str,
        building_kind: str = "personal_shelter",
        anchor: Optional[Dict[str, Any]] = None,
        recipe: Optional[Dict[str, int]] = None,
        current_tick: int = 0,
        human_resolver: Optional[Callable[[str], Any]] = None,
    ) -> str:
        """Create a planned construction project for an active settlement.

        - At most one open project (planned, funded, building) per settlement.
        - Builder must be a living resident and active member of the settlement.
        - Anchor must be inside the settlement claim.
        - Initial status is 'planned' with structure_uid=None and paid=0.
        """
        if len(self._projects) >= self._config.max_projects:
            raise SettlementCapError(
                f"Project cap reached ({len(self._projects)}/{self._config.max_projects})"
            )

        if settlement_id not in self._records:
            raise KeyError(f"Settlement not found: {settlement_id!r}")
        settlement = self._records[settlement_id]
        if settlement["status"] != "active":
            raise SettlementValidationError("Cannot open a project in a dissolved settlement")

        # Invariant: At most one open project per settlement
        if self.get_open_project(settlement_id) is not None:
            raise SettlementConflictError(f"Settlement {settlement_id} already has an open project")

        validate_string(builder_id, "builder UID", min_len=1, max_len=128, allow_control=False)
        if builder_id not in settlement["members"]:
            raise SettlementValidationError(f"Builder {builder_id!r} is not a member of {settlement_id}")

        if human_resolver is not None:
            info = human_resolver(builder_id)
            if not info:
                raise SettlementReferenceError(f"Builder UID {builder_id!r} could not be resolved")
            if isinstance(info, dict):
                if "alive" in info and type(info["alive"]) is not bool:
                    raise SettlementValidationError(f"Builder {builder_id!r} 'alive' metadata must be a strict bool")
                if not info.get("alive", True):
                    raise SettlementReferenceError(f"Builder {builder_id!r} is deceased; cannot plan new work")

        validate_string(building_kind, "building kind", min_len=1, max_len=64)
        proj_anchor = settlement["anchor"] if anchor is None else validate_anchor(anchor, "project anchor")

        # Anchor must lie within settlement claim
        if not is_point_in_claim(proj_anchor, settlement["anchor"], settlement["claim_radius_q"]):
            raise SettlementValidationError("Project anchor lies outside settlement claim radius")

        tick = validate_strict_int(current_tick, "current_tick", settlement["founded_tick"], MAX_TICK)

        # Recipe validation
        if recipe is None:
            if building_kind == "personal_shelter":
                recipe_dict = copy.deepcopy(DEFAULT_PERSONAL_SHELTER_RECIPE)
            else:
                raise SettlementValidationError(f"Explicit recipe required for kind {building_kind!r}")
        else:
            recipe_dict = self._validate_recipe(recipe)

        paid_dict = {item: 0 for item in recipe_dict}
        proj_id = self._allocate_project_id()

        project_record: Dict[str, Any] = {
            "id": proj_id,
            "settlement_id": settlement_id,
            "builder_id": builder_id,
            "building_kind": building_kind,
            "anchor": proj_anchor,
            "structure_uid": None,
            "status": "planned",
            "created_tick": tick,
            "last_work_tick": tick,
            "recipe": recipe_dict,
            "paid": paid_dict,
        }
        self._projects[proj_id] = project_record
        return proj_id

    def fund_project(
        self,
        project_id: str,
        structure_uid: str,
        paid: Optional[Dict[str, int]] = None,
        current_tick: int = 0,
        structure_resolver: Optional[Callable[[str], Any]] = None,
    ) -> None:
        """Fund a planned project and link its designated runtime structure.

        - Transition from 'planned' -> 'funded'.
        - Requires paid == recipe and resolving structure_uid.
        """
        if project_id not in self._projects:
            raise KeyError(f"Project not found: {project_id!r}")
        proj = self._projects[project_id]
        if proj["status"] != "planned":
            raise SettlementValidationError(
                f"Cannot fund project in status {proj['status']!r}; must be 'planned'"
            )

        validate_string(structure_uid, "structure UID", min_len=1, max_len=128, allow_control=False)

        # Structure uniqueness: must not be linked to another settlement or active project
        other_settlement = self.find_settlement_by_building(structure_uid)
        if other_settlement is not None and other_settlement != proj["settlement_id"]:
            raise SettlementConflictError(
                f"Structure {structure_uid!r} belongs to different settlement {other_settlement}"
            )

        for other_p in self._projects.values():
            if other_p["id"] != project_id and other_p["structure_uid"] == structure_uid:
                if other_p["status"] in ("funded", "building", "complete"):
                    raise SettlementConflictError(
                        f"Structure {structure_uid!r} already used by project {other_p['id']}"
                    )

        if structure_resolver is not None:
            info = structure_resolver(structure_uid)
            if not info:
                raise SettlementReferenceError(f"Structure UID {structure_uid!r} could not be resolved")
            if not isinstance(info, dict):
                raise SettlementValidationError(f"Structure {structure_uid!r} resolver info must be a dict")
            self._validate_structure_info(structure_uid, info)
            # Live/funded structure progress must be below 100
            progress = info.get("progress")
            if progress is not None:
                prog = validate_strict_int(progress, f"Structure {structure_uid!r} progress")
                if prog >= 100:
                    raise SettlementValidationError("Newly funded structure cannot already have progress=100")

        tick = validate_strict_int(current_tick, "current_tick", proj["last_work_tick"], MAX_TICK)

        if paid is None:
            paid_dict = copy.deepcopy(proj["recipe"])
        else:
            paid_dict = self._validate_paid(paid, proj["recipe"])

        if paid_dict != proj["recipe"]:
            raise SettlementValidationError("Funding requires full payment (paid == recipe)")

        proj["structure_uid"] = structure_uid
        proj["paid"] = paid_dict
        proj["status"] = "funded"
        proj["last_work_tick"] = tick

    def advance_project_work(
        self,
        project_id: str,
        current_tick: int = 0,
        structure_resolver: Optional[Callable[[str], Any]] = None,
    ) -> None:
        """Advance work on a funded or building project. Transitions to 'building'."""
        if project_id not in self._projects:
            raise KeyError(f"Project not found: {project_id!r}")
        proj = self._projects[project_id]
        if proj["status"] not in ("funded", "building"):
            raise SettlementValidationError(
                f"Cannot advance project in status {proj['status']!r}; must be 'funded' or 'building'"
            )

        tick = validate_strict_int(current_tick, "current_tick", proj["last_work_tick"], MAX_TICK)

        if structure_resolver is not None and proj["structure_uid"] is not None:
            info = structure_resolver(proj["structure_uid"])
            if not info:
                raise SettlementReferenceError(f"Structure UID {proj['structure_uid']!r} unresolved")
            if not isinstance(info, dict):
                raise SettlementValidationError(f"Structure {proj['structure_uid']!r} resolver info must be a dict")
            self._validate_structure_info(proj["structure_uid"], info)
            progress = info.get("progress")
            if progress is not None:
                prog = validate_strict_int(progress, f"Structure {proj['structure_uid']!r} progress")
                if prog >= 100:
                    raise SettlementValidationError("In-progress project structure cannot have progress >= 100")

        proj["status"] = "building"
        proj["last_work_tick"] = tick

    def complete_project(
        self,
        project_id: str,
        current_tick: int = 0,
        structure_resolver: Optional[Callable[[str], Any]] = None,
    ) -> None:
        """Complete a building project.

        Requires progress=100 from authoritative structure adapter.
        Links the structure UID to the owning settlement's buildings list.
        """
        if project_id not in self._projects:
            raise KeyError(f"Project not found: {project_id!r}")
        proj = self._projects[project_id]
        if proj["status"] not in ("building", "funded"):
            raise SettlementValidationError(
                f"Cannot complete project in status {proj['status']!r}; must be 'building' or 'funded'"
            )

        structure_uid = proj["structure_uid"]
        if structure_uid is None:
            raise SettlementValidationError("Cannot complete project with null structure_uid")

        tick = validate_strict_int(current_tick, "current_tick", proj["last_work_tick"], MAX_TICK)

        if structure_resolver is not None:
            info = structure_resolver(structure_uid)
            if not info:
                raise SettlementReferenceError(f"Structure {structure_uid!r} could not be resolved")
            if not isinstance(info, dict):
                raise SettlementValidationError(f"Structure {structure_uid!r} resolver info must be a dict")
            self._validate_structure_info(structure_uid, info)
            if "progress" not in info or info["progress"] is None:
                raise SettlementValidationError("Completion requires structure progress=100")
            prog = validate_strict_int(info["progress"], f"Structure {structure_uid!r} progress")
            if prog != 100:
                raise SettlementValidationError(
                    f"Completion requires structure progress=100, got {prog!r}"
                )

        settlement = self._records[proj["settlement_id"]]
        if structure_uid not in settlement["buildings"]:
            if len(settlement["buildings"]) >= self._config.max_buildings_per_settlement:
                raise SettlementCapError(
                    f"Settlement building cap reached ({self._config.max_buildings_per_settlement})"
                )
            total_buildings = sum(len(r["buildings"]) for r in self._records.values())
            if total_buildings + 1 > self._config.max_building_links:
                raise SettlementCapError(f"Global building links cap reached ({self._config.max_building_links})")
            existing = self.find_settlement_by_building(structure_uid)
            if existing is not None and existing != proj["settlement_id"]:
                raise SettlementConflictError(f"Structure {structure_uid!r} already belongs to settlement {existing}")

        proj["status"] = "complete"
        proj["last_work_tick"] = tick

        # Link structure to settlement
        if structure_uid not in settlement["buildings"]:
            settlement["buildings"] = sorted(set(settlement["buildings"]) | {structure_uid})
            settlement["last_review_tick"] = tick

    def cancel_project(self, project_id: str, current_tick: int = 0) -> None:
        """Cancel an open project.

        - If planned: cancelled before placement (null UID, zero payment).
        - If funded/building: cancelled after funding (retains structure link and paid == recipe).
          Invested materials remain consumed; no automatic refunds.
        """
        if project_id not in self._projects:
            raise KeyError(f"Project not found: {project_id!r}")
        proj = self._projects[project_id]
        if proj["status"] not in OPEN_PROJECT_STATUSES:
            raise SettlementValidationError(
                f"Cannot cancel project in terminal status {proj['status']!r}"
            )

        tick = validate_strict_int(current_tick, "current_tick", proj["last_work_tick"], MAX_TICK)
        proj["status"] = "cancelled"
        proj["last_work_tick"] = tick

    def destroy_project(self, project_id: str, current_tick: int = 0) -> Dict[str, Any]:
        """Destroy a placed structure associated with a project.

        Transition to 'destroyed': nullifies structure_uid, retains paid == recipe,
        removes the building link from the owning settlement, and emits an audit record.
        """
        if project_id not in self._projects:
            raise KeyError(f"Project not found: {project_id!r}")
        proj = self._projects[project_id]

        if proj["structure_uid"] is None:
            raise SettlementValidationError("Cannot destroy project with no placed structure")

        old_uid = proj["structure_uid"]
        tick = validate_strict_int(current_tick, "current_tick", proj["last_work_tick"], MAX_TICK)

        # Remove building link from settlement if present
        settlement = self._records.get(proj["settlement_id"])
        if settlement is not None and old_uid in settlement["buildings"]:
            settlement["buildings"] = [b for b in settlement["buildings"] if b != old_uid]
            settlement["last_review_tick"] = tick

        proj["structure_uid"] = None
        proj["status"] = "destroyed"
        proj["last_work_tick"] = tick

        audit_entry: Dict[str, Any] = {
            "audit": "project_destroyed",
            "project_id": project_id,
            "settlement_id": proj["settlement_id"],
            "destroyed_structure_uid": old_uid,
            "invested_materials_lost": copy.deepcopy(proj["paid"]),
            "tick": tick,
        }
        return audit_entry

    # -------------------------------------------------------------------------
    # State Snapshot Export and Atomic Staged Restore
    # -------------------------------------------------------------------------

    def export_state(self) -> Dict[str, Any]:
        """Export generic serializable state envelope. Returns defensive deep copies."""
        return {
            "schema_version": self._schema_version,
            "next_id": self._next_id,
            "next_project_id": self._next_project_id,
            "records": copy.deepcopy(self._records),
            "projects": copy.deepcopy(self._projects),
        }

    def validate_state(
        self,
        payload: Any,
        human_resolver: Optional[Callable[[str], Any]] = None,
        structure_resolver: Optional[Callable[[str], Any]] = None,
        current_tick: Optional[int] = None,
    ) -> None:
        """Validate a state envelope and all inner records, caps, and cross-field invariants.

        Raises SettlementValidationError, SettlementCapError, SettlementReferenceError,
        or SettlementConflictError on any validation violation.
        Does not mutate any registry state.
        """
        require_exact_keys(payload, ENVELOPE_KEYS, "State envelope")

        schema_ver = validate_strict_int(payload["schema_version"], "schema_version")
        if schema_ver != SCHEMA_VERSION:
            raise SettlementValidationError(f"Unsupported schema_version {schema_ver}, expected {SCHEMA_VERSION}")

        next_id = validate_strict_int(payload["next_id"], "next_id", MIN_ID_COUNTER, MAX_ID_COUNTER)
        next_proj_id = validate_strict_int(payload["next_project_id"], "next_project_id", MIN_ID_COUNTER, MAX_ID_COUNTER)

        records = payload["records"]
        projects = payload["projects"]
        if not isinstance(records, dict):
            raise SettlementValidationError("records must be a dict")
        if not isinstance(projects, dict):
            raise SettlementValidationError("projects must be a dict")

        if len(records) > self._config.max_settlements:
            raise SettlementCapError(f"Settlements count {len(records)} exceeds cap {self._config.max_settlements}")
        if len(projects) > self._config.max_projects:
            raise SettlementCapError(f"Projects count {len(projects)} exceeds cap {self._config.max_projects}")

        # Validate each settlement record
        seen_settlement_ids: Set[str] = set()
        active_members_global: Set[str] = set()
        all_linked_buildings: Set[str] = set()

        for s_uid, rec in records.items():
            if not isinstance(s_uid, str):
                raise SettlementValidationError(f"Settlement key must be a string, got {type(s_uid).__name__}")
            self._validate_settlement_record(
                s_uid,
                rec,
                next_id,
                current_tick,
                human_resolver,
                structure_resolver,
            )
            seen_settlement_ids.add(s_uid)

            # Global member exclusivity & global cap
            if rec["status"] == "active":
                for m in rec["members"]:
                    if m in active_members_global:
                        raise SettlementConflictError(f"Member {m!r} belongs to multiple active settlements")
                    active_members_global.add(m)

            # Global building ownership uniqueness
            for b in rec["buildings"]:
                if b in all_linked_buildings:
                    raise SettlementConflictError(f"Building {b!r} linked to multiple settlements")
                all_linked_buildings.add(b)

        effective_max_members = min(self._config.max_members_global, MAX_HUMANS_DEFAULT)
        if len(active_members_global) > effective_max_members:
            raise SettlementCapError(
                f"Global active member count {len(active_members_global)} exceeds cap {effective_max_members}"
            )

        if len(all_linked_buildings) > self._config.max_building_links:
            raise SettlementCapError(
                f"Global building link count {len(all_linked_buildings)} exceeds cap {self._config.max_building_links}"
            )

        # Validate each project record
        open_projects_by_settlement: Dict[str, str] = {}
        project_structures: Set[str] = set()

        for p_id, proj in projects.items():
            if not isinstance(p_id, str):
                raise SettlementValidationError(f"Project key must be a string, got {type(p_id).__name__}")
            self._validate_project_record(
                p_id,
                proj,
                next_proj_id,
                records,
                current_tick,
                human_resolver,
                structure_resolver,
            )

            # At most one open project per settlement
            s_id = proj["settlement_id"]
            if proj["status"] in OPEN_PROJECT_STATUSES:
                if s_id in open_projects_by_settlement:
                    raise SettlementConflictError(
                        f"Settlement {s_id} has multiple open projects: {open_projects_by_settlement[s_id]} and {p_id}"
                    )
                open_projects_by_settlement[s_id] = p_id

            # Project structure uniqueness
            s_uid = proj["structure_uid"]
            if s_uid is not None:
                if s_uid in project_structures:
                    raise SettlementConflictError(f"Structure UID {s_uid!r} linked to multiple projects")
                project_structures.add(s_uid)

                # Cannot belong to another settlement's buildings
                for other_s_id, other_rec in records.items():
                    if other_s_id != s_id and s_uid in other_rec["buildings"]:
                        raise SettlementConflictError(
                            f"Project structure {s_uid!r} belongs to different settlement {other_s_id}"
                        )

    def restore_state(
        self,
        payload: Any,
        human_resolver: Optional[Callable[[str], Any]] = None,
        structure_resolver: Optional[Callable[[str], Any]] = None,
        current_tick: Optional[int] = None,
    ) -> None:
        """Atomically restore registry state from a validated snapshot payload.

        Staged validation runs completely first on an isolated defensive copy.
        If any check fails, an exception is raised and the prior internal state
        remains completely untouched.
        Internal metadata and records are assigned only from the staged copy,
        ensuring external aliases to payload cannot mutate internal registry state.
        """
        require_exact_keys(payload, ENVELOPE_KEYS, "State envelope")
        staged_payload = copy.deepcopy(payload)

        # Validate staged data first
        self.validate_state(
            staged_payload,
            human_resolver=human_resolver,
            structure_resolver=structure_resolver,
            current_tick=current_tick,
        )

        # Atomic commit from isolated staged copy
        self._schema_version = staged_payload["schema_version"]
        self._next_id = staged_payload["next_id"]
        self._next_project_id = staged_payload["next_project_id"]
        self._records = staged_payload["records"]
        self._projects = staged_payload["projects"]

    # -------------------------------------------------------------------------
    # Internal Validation Helpers
    # -------------------------------------------------------------------------

    def _validate_settlement_record(
        self,
        key_uid: str,
        rec: Any,
        next_id: int,
        current_tick: Optional[int],
        human_resolver: Optional[Callable[[str], Any]],
        structure_resolver: Optional[Callable[[str], Any]],
    ) -> None:
        require_exact_keys(rec, SETTLEMENT_RECORD_KEYS, f"Settlement {key_uid!r}")

        uid = rec["uid"]
        if uid != key_uid:
            raise SettlementValidationError(f"Settlement key {key_uid!r} != record uid {uid!r}")
        if not (isinstance(uid, str) and uid.startswith("s_") and len(uid) == 10 and uid[2:].isdigit()):
            raise SettlementValidationError(f"Invalid settlement UID format: {uid!r}; must be s_ plus 8 digits")

        suffix = int(uid[2:])
        if suffix < 1 or suffix >= next_id:
            raise SettlementValidationError(
                f"Settlement UID suffix {suffix} must be in [1, next_id - 1] (next_id={next_id})"
            )

        validate_string(rec["name"], "name", min_len=1, max_len=80, allow_control=False)
        validate_anchor(rec["anchor"], f"Settlement {uid} anchor")
        validate_strict_int(rec["claim_radius_q"], "claim_radius_q", MIN_CLAIM_RADIUS_Q, MAX_CLAIM_RADIUS_Q)

        status = rec["status"]
        if status not in SETTLEMENT_STATUSES:
            raise SettlementValidationError(f"Invalid settlement status {status!r}; must be in {SETTLEMENT_STATUSES}")

        members = rec["members"]
        buildings = rec["buildings"]
        roles = rec["roles"]

        if not isinstance(members, list):
            raise SettlementValidationError("members must be a list")
        if not isinstance(buildings, list):
            raise SettlementValidationError("buildings must be a list")
        if not isinstance(roles, dict):
            raise SettlementValidationError("roles must be a dict")

        # Sorted unique check
        if members != sorted(set(members)):
            raise SettlementValidationError(f"Settlement {uid} members must be sorted and unique")
        if buildings != sorted(set(buildings)):
            raise SettlementValidationError(f"Settlement {uid} buildings must be sorted and unique")

        # Status-specific members/buildings/roles constraints
        if status == "active":
            if len(members) < 1:
                raise SettlementValidationError(f"Active settlement {uid} must have at least 1 member")
            if len(members) > self._config.max_members_per_settlement:
                raise SettlementCapError(
                    f"Settlement {uid} member count {len(members)} exceeds cap {self._config.max_members_per_settlement}"
                )
            if len(buildings) > self._config.max_buildings_per_settlement:
                raise SettlementCapError(
                    f"Settlement {uid} building count {len(buildings)} exceeds cap {self._config.max_buildings_per_settlement}"
                )

            # Roles validation
            for r_uid, r_name in roles.items():
                if r_uid not in members:
                    raise SettlementValidationError(f"Role assigned to non-member {r_uid!r} in {uid}")
                if r_name not in SETTLEMENT_ROLES:
                    raise SettlementValidationError(f"Invalid role {r_name!r} in {uid}; must be in {SETTLEMENT_ROLES}")
        else:  # dissolved
            if len(members) != 0:
                raise SettlementValidationError(f"Dissolved settlement {uid} must have empty members")
            if len(buildings) != 0:
                raise SettlementValidationError(f"Dissolved settlement {uid} must have empty buildings")
            if len(roles) != 0:
                raise SettlementValidationError(f"Dissolved settlement {uid} must have empty roles")

        # Member string checks and authoritative resolution
        for m in members:
            validate_string(m, "member UID", min_len=1, max_len=128, allow_control=False)
            if human_resolver is not None:
                info = human_resolver(m)
                if not info:
                    raise SettlementReferenceError(f"Resident {m!r} in {uid} unresolved")
                if isinstance(info, dict):
                    if "alive" in info and type(info["alive"]) is not bool:
                        raise SettlementValidationError(f"Resident {m!r} 'alive' metadata must be a strict bool")
                    if not info.get("alive", True):
                        raise SettlementReferenceError(f"Resident {m!r} in {uid} is deceased")

        # Building string checks and authoritative resolution
        for b in buildings:
            validate_string(b, "building UID", min_len=1, max_len=128, allow_control=False)
            if structure_resolver is not None:
                s_info = structure_resolver(b)
                if not s_info:
                    raise SettlementReferenceError(f"Structure {b!r} in {uid} unresolved")
                if not isinstance(s_info, dict):
                    raise SettlementValidationError(f"Structure {b!r} resolver info must be a dict")
                self._validate_structure_info(b, s_info)

        # Ticks
        founded = validate_strict_int(rec["founded_tick"], "founded_tick", 0, MAX_TICK)
        max_review = MAX_TICK if current_tick is None else current_tick
        review = validate_strict_int(rec["last_review_tick"], "last_review_tick", founded, max_review)

    def _validate_project_record(
        self,
        key_id: str,
        proj: Any,
        next_proj_id: int,
        records: Dict[str, Any],
        current_tick: Optional[int],
        human_resolver: Optional[Callable[[str], Any]],
        structure_resolver: Optional[Callable[[str], Any]],
    ) -> None:
        require_exact_keys(proj, PROJECT_RECORD_KEYS, f"Project {key_id!r}")

        p_id = proj["id"]
        if p_id != key_id:
            raise SettlementValidationError(f"Project key {key_id!r} != record id {p_id!r}")
        if not (isinstance(p_id, str) and p_id.startswith("sp_") and len(p_id) == 11 and p_id[3:].isdigit()):
            raise SettlementValidationError(f"Invalid project ID format: {p_id!r}; must be sp_ plus 8 digits")

        suffix = int(p_id[3:])
        if suffix < 1 or suffix >= next_proj_id:
            raise SettlementValidationError(
                f"Project ID suffix {suffix} must be in [1, next_project_id - 1] (next_project_id={next_proj_id})"
            )

        s_id = proj["settlement_id"]
        if s_id not in records:
            raise SettlementValidationError(f"Project {p_id} references nonexistent settlement {s_id!r}")
        settlement = records[s_id]

        builder_id = validate_string(proj["builder_id"], "builder_id", min_len=1, max_len=128, allow_control=False)
        validate_string(proj["building_kind"], "building_kind", min_len=1, max_len=64)
        proj_anchor = validate_anchor(proj["anchor"], f"Project {p_id} anchor")

        if not is_point_in_claim(proj_anchor, settlement["anchor"], settlement["claim_radius_q"]):
            raise SettlementValidationError(f"Project {p_id} anchor lies outside settlement claim")

        status = proj["status"]
        if status not in PROJECT_STATUSES:
            raise SettlementValidationError(f"Invalid project status {status!r}; must be in {PROJECT_STATUSES}")

        # Ticks
        created = validate_strict_int(proj["created_tick"], "created_tick", settlement["founded_tick"], MAX_TICK)
        max_work = MAX_TICK if current_tick is None else current_tick
        work_tick = validate_strict_int(proj["last_work_tick"], "last_work_tick", created, max_work)

        # Recipe & paid
        recipe = self._validate_recipe(proj["recipe"])
        paid = self._validate_paid(proj["paid"], recipe)

        # Structure UID & cross-field payment constraints
        struct_uid = proj["structure_uid"]
        if struct_uid is not None:
            validate_string(struct_uid, "structure_uid", min_len=1, max_len=128, allow_control=False)

        if status == "planned":
            if struct_uid is not None:
                raise SettlementValidationError(f"Planned project {p_id} must have structure_uid=None")
            if any(qty != 0 for qty in paid.values()):
                raise SettlementValidationError(f"Planned project {p_id} must have all paid quantities zero")
        elif status in ("funded", "building", "complete"):
            if struct_uid is None:
                raise SettlementValidationError(f"Project {p_id} in status {status!r} must have resolving structure_uid")
            if paid != recipe:
                raise SettlementValidationError(f"Project {p_id} in status {status!r} must have paid == recipe")
        elif status == "cancelled":
            if struct_uid is None:
                # Cancelled before placement
                if any(qty != 0 for qty in paid.values()):
                    raise SettlementValidationError(
                        f"Project {p_id} cancelled before placement must have all paid quantities zero"
                    )
            else:
                # Cancelled after funding
                if paid != recipe:
                    raise SettlementValidationError(
                        f"Project {p_id} cancelled after funding must have paid == recipe"
                    )
        elif status == "destroyed":
            if struct_uid is not None:
                raise SettlementValidationError(f"Destroyed project {p_id} must have structure_uid=None")
            if paid != recipe:
                raise SettlementValidationError(f"Destroyed project {p_id} must have paid == recipe")

        # Authoritative resolvers
        if human_resolver is not None:
            info = human_resolver(builder_id)
            if not info:
                raise SettlementReferenceError(f"Builder {builder_id!r} in project {p_id} unresolved")
            # For open projects, builder must be living
            if status in OPEN_PROJECT_STATUSES and isinstance(info, dict):
                if "alive" in info and type(info["alive"]) is not bool:
                    raise SettlementValidationError(f"Builder {builder_id!r} 'alive' metadata must be a strict bool")
                if not info.get("alive", True):
                    raise SettlementReferenceError(f"Builder {builder_id!r} in open project {p_id} is deceased")

        if structure_resolver is not None and struct_uid is not None:
            s_info = structure_resolver(struct_uid)
            if not s_info:
                raise SettlementReferenceError(f"Structure {struct_uid!r} in project {p_id} unresolved")
            if not isinstance(s_info, dict):
                raise SettlementValidationError(f"Structure {struct_uid!r} resolver info must be a dict")
            self._validate_structure_info(struct_uid, s_info)
            progress = s_info.get("progress")
            if progress is not None:
                p_num = validate_strict_int(progress, f"Structure {struct_uid!r} progress")
                if status == "complete" and p_num != 100:
                    raise SettlementValidationError(f"Complete project {p_id} requires progress=100, got {p_num}")
                if status in ("funded", "building") and p_num >= 100:
                    raise SettlementValidationError(
                        f"Live work project {p_id} requires progress < 100, got {p_num}"
                    )
            elif status == "complete":
                raise SettlementValidationError(f"Complete project {p_id} requires progress=100")

    def _validate_recipe(self, recipe: Any) -> Dict[str, int]:
        if not isinstance(recipe, dict):
            raise SettlementValidationError("recipe must be a dictionary")
        if not recipe:
            raise SettlementValidationError("recipe dictionary cannot be empty")
        validated: Dict[str, int] = {}
        for item, qty in recipe.items():
            validate_string(item, "recipe item key", min_len=1, max_len=64)
            val = validate_strict_int(qty, f"recipe[{item!r}]", min_val=1)
            validated[item] = val
        return validated

    def _validate_paid(self, paid: Any, recipe: Dict[str, int]) -> Dict[str, int]:
        if not isinstance(paid, dict):
            raise SettlementValidationError("paid must be a dictionary")
        if set(paid.keys()) != set(recipe.keys()):
            raise SettlementValidationError(
                f"paid keys {sorted(paid.keys())} do not match recipe keys {sorted(recipe.keys())}"
            )
        validated: Dict[str, int] = {}
        for item, qty in paid.items():
            val = validate_strict_int(qty, f"paid[{item!r}]", min_val=0, max_val=recipe[item])
            validated[item] = val
        return validated

    def _validate_structure_info(self, uid: str, info: Dict[str, Any]) -> None:
        """Validate structure metadata returned by caller's authoritative resolver.

        Contract:
        - info must be a dict.
        - Generated chunk features (c*.*:*) are excluded.
        - Explicit authoritative 'space' metadata required: strict int == 0 (overworld).
          Missing space or default space is NOT silently accepted.
        - Explicit authoritative 'type' metadata required: strict int in STRUCTURE_TYPES.
          Missing type is NOT silently accepted.
        - Strict types enforced: bool is rejected (bool is not int).
        - If 'progress' metadata is present, it must be strict int in [0, 100].
        """
        if not isinstance(info, dict):
            raise SettlementValidationError(f"Structure {uid!r} resolver info must be a dict, got {type(info).__name__}")

        # Generated chunk features are excluded (must be runtime structures e.g. e_...)
        if uid.startswith("c") and ":" in uid:
            raise SettlementValidationError(f"Generated chunk feature {uid!r} cannot be linked to settlement")

        # Explicit space metadata required; default space as overworld is NOT silently accepted
        if "space" not in info:
            raise SettlementValidationError(f"Structure {uid!r} missing explicit authoritative 'space' metadata")
        space = validate_strict_int(info["space"], f"Structure {uid!r} space")
        if space != 0:
            raise SettlementValidationError(f"Structure {uid!r} space is {space!r}; overworld (0) required")

        # Explicit type metadata required; missing type is NOT silently accepted
        if "type" not in info:
            raise SettlementValidationError(f"Structure {uid!r} missing explicit authoritative 'type' metadata")
        s_type = validate_strict_int(info["type"], f"Structure {uid!r} type")
        if s_type not in STRUCTURE_TYPES_DEFAULT:
            raise SettlementValidationError(
                f"Structure {uid!r} type {s_type!r} is not in STRUCTURE_TYPES"
            )

        if "progress" in info and info["progress"] is not None:
            validate_strict_int(info["progress"], f"Structure {uid!r} progress", 0, 100)


__all__ = [
    "ANCHOR_KEYS",
    "CHUNK_SUBUNITS",
    "CHUNK_UNITS",
    "DEFAULT_CLAIM_RADIUS_Q",
    "DEFAULT_MAX_BUILDING_LINKS",
    "DEFAULT_MAX_BUILDINGS_PER_SETTLEMENT",
    "DEFAULT_MAX_MEMBERS_PER_SETTLEMENT",
    "DEFAULT_MAX_PROJECTS",
    "DEFAULT_MAX_SETTLEMENTS",
    "DEFAULT_PERSONAL_SHELTER_RECIPE",
    "ENVELOPE_KEYS",
    "MAX_ABS_COORD",
    "MAX_CLAIM_RADIUS_Q",
    "MAX_ID_COUNTER",
    "MAX_SUB_COORD",
    "MAX_TICK",
    "MIN_CHUNK_COORD",
    "MIN_CLAIM_RADIUS_Q",
    "MIN_ID_COUNTER",
    "MIN_SUB_COORD",
    "OPEN_PROJECT_STATUSES",
    "PROJECT_RECORD_KEYS",
    "PROJECT_STATUSES",
    "Q",
    "SCHEMA_VERSION",
    "SETTLEMENT_RECORD_KEYS",
    "SETTLEMENT_ROLES",
    "SETTLEMENT_STATUSES",
    "SettlementCapError",
    "SettlementConfig",
    "SettlementConflictError",
    "SettlementError",
    "SettlementReferenceError",
    "SettlementRegistry",
    "SettlementValidationError",
    "TERMINAL_PROJECT_STATUSES",
    "anchor_diff_q",
    "anchor_distance_sq_q",
    "anchor_to_local",
    "anchor_to_total_subunits",
    "claims_overlap",
    "is_point_in_claim",
    "make_anchor",
    "normalize_subunits_to_anchor",
    "quantize_chunk_local_to_anchor",
    "quantize_unit_to_anchor",
    "require_exact_keys",
    "validate_anchor",
    "validate_finite_number",
    "validate_strict_int",
    "validate_string",
]
