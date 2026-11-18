"""1010 Auxiliary Resident Hot-State Storage Foundation (R6.13, Harness Plane).

Provides an explicitly instantiated bounded storage table and validated schema
for auxiliary resident hot-state.

Key Invariants:
- Human column 31 in h_tensor remains untouched and unallocated.
- Statically bounded capacity up to cfg.MAX_HUMANS and ceiling of MAX_AUX_COLS (16).
- float32 storage tensor with exact int64 generation counters to prevent IEEE 754
  aliasing beyond 2^24.
- Internal tensors (_tensor, _slot_gen) are private implementation storage; public
  properties return defensive clones and metadata is read-only.
- Note: Python private attributes are an implementation encapsulation boundary,
  not an operating system or security sandbox boundary.
- Explicit lifecycle and identity binding (bind, recycle, clear, freeze, wake) safe
  against stale reads and writes.
- Public clear_slot() and apply_mutations() strictly reject dormant frozen rows.
- Internal lifecycle reset (used during bind and recycle) resets storage unconditionally
  without being blocked by inactive or frozen checks, preventing partial commits.
- Detects int64 generation exhaustion (MAX_INT64 = 9223372036854775807) rather than overflow.
- Strict rejection of bool for integers, tokens, and floats (no bool 0/1 token alias).
- Validates actual float32 conversion and rounded value vs declared bounds for defaults,
  mutations, and rebuilds; rejects out-of-bounds candidates without silent clamping.
- Subnormal float32 underflow-to-zero is governed by standard IEEE 754 float32 semantics
  and is not rejected as an error.
- Rejection of AUTHORITATIVE specs pending supported persistence (DR22 is OPEN);
  foundation accepts DERIVED_CACHE specs only.
- Dormant frozen rows reject mutation until wake; wake cache rebuild is atomic with
  unchanged state on failed rebuild.
- No table, singleton, or tensor storage allocation occurs at module import time;
  storage allocation is strictly explicit and caller-instantiated.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
import math
from typing import Any, Callable, Optional, Sequence, Union

import torch

try:
    import genesis_config as cfg
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg

# Infrastructure ceiling for auxiliary columns as proposed in R6.13
MAX_AUX_COLS: int = 16

# Maximum positive signed 64-bit integer
MAX_INT64: int = int(torch.iinfo(torch.int64).max)  # 9223372036854775807

# IEEE 754 single-precision float32 limits
FLOAT32_MIN: float = float(torch.finfo(torch.float32).min)
FLOAT32_MAX: float = float(torch.finfo(torch.float32).max)


class AuxStateError(Exception):
    """Base exception for auxiliary hot-state storage errors."""


class DuplicateFieldError(AuxStateError, ValueError):
    """Raised when duplicate field names or columns are defined in schema."""


class InvalidSchemaError(AuxStateError, ValueError):
    """Raised when schema parameters or dimensions are invalid."""


class UnsupportedOwnershipError(AuxStateError, ValueError):
    """Raised when unsupported ownership semantics (e.g. AUTHORITATIVE pending DR22) are passed."""


class InvalidNumericValueError(AuxStateError, ValueError):
    """Raised when a numeric value is non-finite, out of float32 bounds, or invalid type."""


class InvalidSlotError(AuxStateError, IndexError):
    """Raised when an entity slot index is out of bounds or inactive."""


class StaleIdentityError(AuxStateError, ValueError):
    """Raised when slot UID does not match expected live UID token."""


class StaleGenerationError(AuxStateError, ValueError):
    """Raised when slot generation does not match expected generation token."""


class FrozenRowMutationError(AuxStateError, RuntimeError):
    """Raised when attempting to mutate or publicly clear a dormant frozen slot."""


class GenerationExhaustionError(AuxStateError, OverflowError):
    """Raised when int64 generation token reaches MAX_INT64 exhaustion."""


class AuxWakeRebuildError(AuxStateError, RuntimeError):
    """Raised when wake cache rebuild fails for a derived field."""


def _is_strict_int(val: Any) -> bool:
    """Return True if val is strictly an int and not a bool."""
    return isinstance(val, int) and not isinstance(val, bool)


def _to_finite_float32(val: Any, name: str = "value") -> float:
    """Validate that val is a finite numeric value representable as float32.

    Strictly rejects bool, non-numeric types, NaN, +/-Inf, and overflow beyond float32 limits.
    Returns the converted float32 value as a Python float.
    Note: IEEE 754 float32 underflow-to-zero is not treated as an error.
    """
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise InvalidNumericValueError(
            f"{name} must be a numeric int or float (rejecting bool), got {val!r}"
        )
    try:
        f_val = float(val)
    except (ValueError, TypeError, OverflowError) as exc:
        raise InvalidNumericValueError(f"{name} cannot be converted to float: {val!r}") from exc
    if not math.isfinite(f_val):
        raise InvalidNumericValueError(
            f"{name} must be finite (rejecting NaN/Inf), got {f_val!r}"
        )
    if f_val < FLOAT32_MIN or f_val > FLOAT32_MAX:
        raise InvalidNumericValueError(
            f"{name} exceeds float32 range [{FLOAT32_MIN}, {FLOAT32_MAX}], got {f_val!r}"
        )
    try:
        f32 = float(torch.tensor(f_val, dtype=torch.float32).item())
        if not math.isfinite(f32):
            raise InvalidNumericValueError(f"{name} converted to non-finite float32: {f32!r}")
        return f32
    except Exception as exc:
        raise InvalidNumericValueError(f"{name} failed float32 conversion: {val!r}") from exc


def _is_finite_float32(val: Any) -> bool:
    """Return True if val is a numeric value representable as finite float32."""
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        return False
    try:
        f_val = float(val)
    except (ValueError, TypeError, OverflowError):
        return False
    if not math.isfinite(f_val):
        return False
    if f_val < FLOAT32_MIN or f_val > FLOAT32_MAX:
        return False
    try:
        t = torch.tensor(f_val, dtype=torch.float32)
        return bool(torch.isfinite(t).item())
    except Exception:
        return False


def _validate_float32_value(val: Any, name: str = "value") -> float:
    """Validate and return float32 value or raise InvalidNumericValueError."""
    return _to_finite_float32(val, name)


def _validate_in_bounds(val: Any, min_val: float, max_val: float, name: str = "value") -> float:
    """Validate value and its float32 representation against declared bounds [min_val, max_val].

    Both the raw Python float and the converted/rounded float32 value must lie within [min_val, max_val].
    Rejects values whose conversion/rounding crosses declared boundaries.
    Returns the validated float32 value as float.
    """
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise InvalidNumericValueError(f"{name} must be numeric (not bool), got {val!r}")
    f_val = float(val)
    if not math.isfinite(f_val):
        raise InvalidNumericValueError(f"{name} must be finite, got {f_val!r}")
    if f_val < min_val or f_val > max_val:
        raise InvalidNumericValueError(
            f"{name} ({f_val}) is outside declared bounds [{min_val}, {max_val}]"
        )
    f32_val = _to_finite_float32(f_val, name)
    if f32_val < min_val or f32_val > max_val:
        raise InvalidNumericValueError(
            f"{name} float32 rounded value ({f32_val}) stores outside declared bounds [{min_val}, {max_val}]"
        )
    return f32_val


def _validate_engine_authority(engine: Any, slot: int, expected_uid: Optional[str] = None) -> None:
    """Validate caller-supplied engine against slot authority without silent skipping."""
    if engine is None:
        return
    if not hasattr(engine, "_human_uid_by_slot"):
        raise ValueError(
            f"Caller supplied malformed engine lacking '_human_uid_by_slot': {engine!r}"
        )
    uid_list = getattr(engine, "_human_uid_by_slot")
    if not isinstance(uid_list, (list, tuple)):
        raise ValueError(
            f"Caller supplied engine with non-sequence '_human_uid_by_slot': {type(uid_list).__name__}"
        )
    if slot < 0 or slot >= len(uid_list):
        raise InvalidSlotError(
            f"Slot {slot} out of range for engine._human_uid_by_slot (length {len(uid_list)})"
        )
    engine_uid = uid_list[slot]
    if expected_uid is not None and engine_uid != expected_uid:
        raise StaleIdentityError(
            f"Slot {slot} engine UID mismatch: expected {expected_uid!r}, got {engine_uid!r}"
        )


class FieldOwnership(Enum):
    """Ownership category determining persistence and lifecycle semantics."""
    AUTHORITATIVE = auto()  # Ground truth; must be saved; dropping causes data loss (DR22 OPEN)
    DERIVED_CACHE = auto()  # Recomputable; can rebuild on boot/wake; safe to drop


@dataclass(frozen=True)
class AuxFieldSpec:
    """Configurable schema definition for an auxiliary tensor column."""
    name: str
    column: int
    min_value: float
    max_value: float
    default_value: float
    ownership: FieldOwnership
    rebuild_fn: Optional[Callable[[Any, int], float]] = None

    def __post_init__(self) -> None:
        if isinstance(self.name, bool) or not isinstance(self.name, str) or not self.name.strip():
            raise InvalidSchemaError(f"Field name must be a non-empty string, got {self.name!r}")
        if not _is_strict_int(self.column) or self.column < 0:
            raise InvalidSchemaError(f"Field '{self.name}' column must be non-negative strict int, got {self.column!r}")
        if not isinstance(self.ownership, FieldOwnership):
            raise InvalidSchemaError(f"Field '{self.name}' ownership must be a FieldOwnership enum, got {self.ownership!r}")

        # Foundation requirement: reject AUTHORITATIVE pending supported persistence (DR22)
        if self.ownership == FieldOwnership.AUTHORITATIVE:
            raise UnsupportedOwnershipError(
                f"Field '{self.name}': Authoritative auxiliary field specs are rejected pending supported persistence "
                "(DR22 remains OPEN); this foundation accepts DERIVED_CACHE specs only."
            )
        if self.ownership != FieldOwnership.DERIVED_CACHE:
            raise InvalidSchemaError(
                f"Field '{self.name}' ownership must be FieldOwnership.DERIVED_CACHE, got {self.ownership!r}"
            )

        # Validate float32 numeric bounds and defaults
        min_f32 = _to_finite_float32(self.min_value, f"Field '{self.name}' min_value")
        max_f32 = _to_finite_float32(self.max_value, f"Field '{self.name}' max_value")

        if float(self.min_value) > float(self.max_value) or min_f32 > max_f32:
            raise InvalidNumericValueError(
                f"Field '{self.name}' min_value ({self.min_value}) cannot exceed max_value ({self.max_value})"
            )

        # Validate default_value against declared bounds and float32 rounding
        _validate_in_bounds(
            self.default_value,
            float(self.min_value),
            float(self.max_value),
            f"Field '{self.name}' default_value",
        )
        def_f32 = _to_finite_float32(self.default_value, f"Field '{self.name}' default_value")
        if def_f32 < min_f32 or def_f32 > max_f32:
            raise InvalidNumericValueError(
                f"Field '{self.name}' default_value rounded float32 ({def_f32}) outside bounds [{min_f32}, {max_f32}]"
            )

        if not callable(self.rebuild_fn):
            raise InvalidSchemaError(
                f"Field '{self.name}': DERIVED_CACHE field must provide a callable rebuild_fn"
            )


@dataclass(frozen=True)
class AuxSchema:
    """Explicit, bounded schema registry for auxiliary hot-state."""
    cols: int
    fields: tuple[AuxFieldSpec, ...]

    def __init__(self, cols: int, fields: Sequence[AuxFieldSpec]) -> None:
        if not _is_strict_int(cols):
            raise InvalidSchemaError(f"Schema cols must be strict int, got {cols!r}")
        if cols <= 0 or cols > MAX_AUX_COLS:
            raise InvalidSchemaError(
                f"Schema cols ({cols}) must be in range [1, {MAX_AUX_COLS}] (infrastructure ceiling)"
            )

        field_tuple = tuple(fields)
        seen_names: set[str] = set()
        seen_cols: set[int] = set()

        for f in field_tuple:
            if not isinstance(f, AuxFieldSpec):
                raise InvalidSchemaError(f"Item {f!r} is not an AuxFieldSpec")
            if f.name in seen_names:
                raise DuplicateFieldError(f"Duplicate field name '{f.name}' in AuxSchema")
            if f.column >= cols:
                raise InvalidSchemaError(
                    f"Field '{f.name}' column index {f.column} exceeds schema column count {cols}"
                )
            if f.column in seen_cols:
                raise DuplicateFieldError(f"Duplicate column index {f.column} in AuxSchema")
            seen_names.add(f.name)
            seen_cols.add(f.column)

        object.__setattr__(self, "cols", cols)
        object.__setattr__(self, "fields", field_tuple)

    def get_field(self, column: int) -> AuxFieldSpec:
        if not _is_strict_int(column):
            raise KeyError(f"Column index must be strict int, got {column!r}")
        for f in self.fields:
            if f.column == column:
                return f
        raise KeyError(f"Unknown auxiliary column: {column}")

    def get_field_by_name(self, name: str) -> AuxFieldSpec:
        if isinstance(name, bool) or not isinstance(name, str):
            raise KeyError(f"Field name must be str, got {name!r}")
        for f in self.fields:
            if f.name == name:
                return f
        raise KeyError(f"Unknown auxiliary field name: {name}")

    def has_column(self, column: int) -> bool:
        if not _is_strict_int(column):
            return False
        return any(f.column == column for f in self.fields)

    def has_name(self, name: str) -> bool:
        if isinstance(name, bool) or not isinstance(name, str):
            return False
        return any(f.name == name for f in self.fields)


@dataclass(frozen=True)
class AuxMutationDraft:
    """Immutable staged mutation draft."""
    slot: int
    column: int
    value: float
    expected_uid: str
    expected_gen: int

    def __post_init__(self) -> None:
        if not _is_strict_int(self.slot) or self.slot < 0:
            raise InvalidSchemaError(f"Draft slot must be non-negative strict int, got {self.slot!r}")
        if not _is_strict_int(self.column) or self.column < 0:
            raise InvalidSchemaError(f"Draft column must be non-negative strict int, got {self.column!r}")
        if isinstance(self.expected_uid, bool) or not isinstance(self.expected_uid, str) or not self.expected_uid.strip():
            raise InvalidSchemaError(f"Draft expected_uid must be non-empty string, got {self.expected_uid!r}")
        if not _is_strict_int(self.expected_gen) or self.expected_gen < 0:
            raise InvalidSchemaError(f"Draft expected_gen must be non-negative strict int, got {self.expected_gen!r}")
        f32 = _to_finite_float32(self.value, "Draft value")
        object.__setattr__(self, "value", f32)


class AuxStateTable:
    """Statically bounded auxiliary storage container.

    Maintains float32 tensor storage, exact int64 generation tracking, and UID
    metadata bounded to capacity <= cfg.MAX_HUMANS.

    Internal storage tensors are private implementation details. Public properties
    return defensive clones, and metadata attributes are read-only to prevent
    unvalidated in-place mutation or schema bypass.
    """

    def __init__(
        self,
        schema: AuxSchema,
        capacity: int = cfg.MAX_HUMANS,
        device: Optional[torch.device] = None,
        dtype: torch.dtype = torch.float32,
    ) -> None:
        if not isinstance(schema, AuxSchema):
            raise TypeError(f"schema must be an AuxSchema, got {type(schema).__name__}")
        if not _is_strict_int(capacity):
            raise TypeError(f"capacity must be strict int, got {capacity!r}")
        if capacity <= 0 or capacity > cfg.MAX_HUMANS:
            raise ValueError(
                f"AuxStateTable capacity ({capacity}) must be in range [1, {cfg.MAX_HUMANS}] (MAX_HUMANS)"
            )
        if dtype != torch.float32:
            raise ValueError(f"AuxStateTable storage requires torch.float32, got {dtype}")

        dev = device if device is not None else torch.device("cpu")

        self._schema: AuxSchema = schema
        self._capacity: int = capacity
        self._device: torch.device = dev
        self._dtype: torch.dtype = dtype

        # Core private tensor allocation
        self._tensor: torch.Tensor = torch.zeros((capacity, schema.cols), dtype=dtype, device=dev)
        self._slot_gen: torch.Tensor = torch.zeros(capacity, dtype=torch.int64, device=dev)

        # Slot metadata bounded strictly to capacity
        self._uids: list[Optional[str]] = [None] * capacity
        self._active: list[bool] = [False] * capacity
        self._frozen: list[bool] = [False] * capacity

        # Defaults initialized to schema defaults
        for field in schema.fields:
            self._tensor[:, field.column] = field.default_value

    def _validate_slot_index(self, slot: int) -> None:
        if not _is_strict_int(slot):
            raise InvalidSlotError(f"Slot must be strict int, got {slot!r}")
        if slot < 0 or slot >= self._capacity:
            raise InvalidSlotError(f"Slot {slot} out of range [0, {self._capacity})")

    # --- Read-Only Metadata & Storage Properties ---

    @property
    def schema(self) -> AuxSchema:
        return self._schema

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def device(self) -> torch.device:
        return self._device

    @property
    def dtype(self) -> torch.dtype:
        return self._dtype

    @property
    def tensor(self) -> torch.Tensor:
        """Defensive clone of storage tensor. Normal public access cannot mutate internal state."""
        return self._tensor.clone()

    @property
    def slot_gen(self) -> torch.Tensor:
        """Defensive clone of slot generation tensor. Normal public access cannot mutate internal state."""
        return self._slot_gen.clone()

    # --- Defensive Snapshot APIs ---

    def get_tensor_copy(self) -> torch.Tensor:
        """Return defensive clone of storage tensor to prevent external mutation."""
        return self._tensor.clone()

    def get_row_copy(self, slot: int) -> torch.Tensor:
        """Return defensive clone of single row."""
        self._validate_slot_index(slot)
        return self._tensor[slot].clone()

    def get_slot_gen_copy(self) -> torch.Tensor:
        """Return defensive clone of slot generation tensor."""
        return self._slot_gen.clone()

    def get_field_snapshot(self, slot: int, column: int) -> float:
        """Defensive scalar snapshot of single cell without identity validation."""
        self._validate_slot_index(slot)
        if isinstance(column, bool) or not _is_strict_int(column) or not self._schema.has_column(column):
            raise KeyError(f"Unknown auxiliary column: {column}")
        return float(self._tensor[slot, column].item())

    # --- Query APIs ---

    def is_active(self, slot: int) -> bool:
        self._validate_slot_index(slot)
        return self._active[slot]

    def is_frozen(self, slot: int) -> bool:
        self._validate_slot_index(slot)
        return self._frozen[slot]

    def get_uid(self, slot: int) -> Optional[str]:
        self._validate_slot_index(slot)
        return self._uids[slot]

    def get_gen(self, slot: int) -> int:
        self._validate_slot_index(slot)
        return int(self._slot_gen[slot].item())

    # --- Test Fixture Support (Clearly Private) ---

    def _set_slot_gen_for_test(self, slot: int, gen: int) -> None:
        """Private fixture setup helper for testing generation boundary conditions.

        Not part of public API contracts. Python private attributes are an implementation
        detail, not a security boundary.
        """
        self._validate_slot_index(slot)
        if not _is_strict_int(gen) or gen < 0:
            raise ValueError(f"gen must be non-negative strict int, got {gen!r}")
        self._slot_gen[slot] = gen

    # --- Lifecycle APIs ---

    def _reset_slot_storage_internal(self, slot: int) -> None:
        """Internal storage reset to schema defaults.

        Unlike public clear_slot(), this internal lifecycle operation explicitly resets
        storage during bind and recycle transitions without rejecting frozen or inactive
        states, avoiding partial commitment during identity transitions.
        """
        for field in self._schema.fields:
            self._tensor[slot, field.column] = field.default_value

    def bind_slot(self, slot: int, uid: str) -> int:
        """Bind slot to a live UID.

        If the slot was previously active or held a UID, bumps exact int64 generation
        (verifying exhaustion first) to invalidate prior tokens. Resets storage internally
        to schema defaults.
        """
        self._validate_slot_index(slot)
        if isinstance(uid, bool) or not isinstance(uid, str) or not uid.strip():
            raise ValueError(f"UID must be non-empty string, got {uid!r}")

        # If slot was already active or bound, invalidate prior identity
        if self._active[slot] or self._uids[slot] is not None:
            cur_gen = int(self._slot_gen[slot].item())
            if cur_gen >= MAX_INT64:
                raise GenerationExhaustionError(
                    f"Slot {slot} generation counter reached MAX_INT64 exhaustion"
                )
            self._slot_gen[slot] += 1

        self._uids[slot] = uid
        self._active[slot] = True
        self._frozen[slot] = False

        # Reset row storage internally to schema defaults
        self._reset_slot_storage_internal(slot)
        return int(self._slot_gen[slot].item())

    def recycle_slot(self, slot: int) -> int:
        """Recycle slot on human death/eviction.

        Bumps exact int64 generation (checking for exhaustion first), clears live UID,
        marks inactive, and resets storage row internally to defaults.
        Can explicitly reset frozen storage internally as part of lifecycle retirement.
        """
        self._validate_slot_index(slot)
        cur_gen = int(self._slot_gen[slot].item())
        if cur_gen >= MAX_INT64:
            raise GenerationExhaustionError(
                f"Slot {slot} generation counter reached MAX_INT64 exhaustion"
            )
        self._slot_gen[slot] += 1

        self._uids[slot] = None
        self._active[slot] = False
        self._frozen[slot] = False

        # Internal reset is safe regardless of prior frozen/inactive status
        self._reset_slot_storage_internal(slot)
        return int(self._slot_gen[slot].item())

    def clear_slot(self, slot: int) -> None:
        """Public API: reset an active, non-frozen slot to schema defaults.

        Strictly rejects inactive slots and dormant frozen slots.
        """
        self._validate_slot_index(slot)
        if not self._active[slot]:
            raise InvalidSlotError(f"Cannot clear inactive slot {slot}")
        if self._frozen[slot]:
            raise FrozenRowMutationError(f"Cannot clear dormant frozen slot {slot}")
        self._reset_slot_storage_internal(slot)

    def freeze_slot(self, slot: int) -> None:
        """Mark active slot as frozen (dormant). Frozen rows reject mutations."""
        self._validate_slot_index(slot)
        if not self._active[slot]:
            raise InvalidSlotError(f"Cannot freeze inactive slot {slot}")
        self._frozen[slot] = True

    def wake_slot(self, slot: int, engine: Any = None) -> None:
        """Wake dormant slot and recompute all derived fields atomically.

        Stages converted rebuild values before committing. If any rebuild_fn fails,
        returns non-finite, or returns a value outside declared bounds (including
        float32 rounding crossing boundary), internal row storage remains wholly
        unchanged, slot remains frozen, and AuxWakeRebuildError is raised.
        """
        self._validate_slot_index(slot)
        if not self._active[slot]:
            raise InvalidSlotError(f"Cannot wake inactive slot {slot}")
        if not self._frozen[slot]:
            return  # Not frozen, nothing to rebuild

        backup_values = self._tensor[slot].clone()
        staged_rebuild: list[tuple[int, float]] = []

        try:
            for field in self._schema.fields:
                if field.rebuild_fn is None:
                    staged_rebuild.append((field.column, field.default_value))
                    continue

                rebuilt = field.rebuild_fn(engine, slot)
                # Strict float32 bounds and rounding validation
                f_val = _validate_in_bounds(
                    rebuilt,
                    field.min_value,
                    field.max_value,
                    f"Rebuild for field '{field.name}'",
                )
                staged_rebuild.append((field.column, f_val))
        except Exception as exc:
            # Atomic failure guarantee: values and status remain wholly unchanged
            self._tensor[slot].copy_(backup_values)
            self._frozen[slot] = True
            raise AuxWakeRebuildError(
                f"Wake cache rebuild failed for slot {slot}: {exc}"
            ) from exc

        # All rebuilds succeeded: atomic commit
        for col, val in staged_rebuild:
            self._tensor[slot, col] = val
        self._frozen[slot] = False

    # --- Read & Mutation APIs ---

    def get_field(
        self,
        slot: int,
        column: int,
        expected_uid: Optional[str] = None,
        expected_gen: Optional[int] = None,
        engine: Any = None,
    ) -> float:
        """Read field with exact live UID and generation token validation.

        Strictly rejects bool aliases for expected_gen (no bool 0/1 token alias)
        and expected_uid. If engine is supplied, validates engine authority without
        silent skipping.
        """
        self._validate_slot_index(slot)
        if isinstance(column, bool) or not _is_strict_int(column) or not self._schema.has_column(column):
            raise KeyError(f"Unknown auxiliary column: {column}")

        if not self._active[slot]:
            raise InvalidSlotError(f"Slot {slot} is inactive")

        if expected_uid is not None:
            if isinstance(expected_uid, bool) or not isinstance(expected_uid, str) or not expected_uid.strip():
                raise TypeError(f"expected_uid must be non-empty str (rejecting bool), got {expected_uid!r}")
            actual_uid = self._uids[slot]
            if actual_uid != expected_uid:
                raise StaleIdentityError(
                    f"Slot {slot} UID mismatch: expected {expected_uid}, got {actual_uid}"
                )
            _validate_engine_authority(engine, slot, expected_uid)
        elif engine is not None:
            # Engine supplied without expected_uid: validate against table's live UID
            _validate_engine_authority(engine, slot, self._uids[slot])

        if expected_gen is not None:
            if not _is_strict_int(expected_gen) or expected_gen < 0:
                raise TypeError(
                    f"expected_gen must be non-negative strict int (rejecting bool), got {expected_gen!r}"
                )
            actual_gen = int(self._slot_gen[slot].item())
            if actual_gen != expected_gen:
                raise StaleGenerationError(
                    f"Slot {slot} generation mismatch: expected {expected_gen}, got {actual_gen}"
                )

        return float(self._tensor[slot, column].item())

    def plan_mutation(
        self,
        slot: int,
        column: int,
        candidate_value: float,
        expected_uid: str,
        expected_gen: int,
        engine: Any = None,
    ) -> Optional[AuxMutationDraft]:
        """Validate candidate mutation against active status, freeze state, bounds, and tokens.

        Rejects out-of-bound candidates and values whose float32 rounding crosses declared
        boundaries (returns None). Does NOT silently clamp.
        """
        if not _is_strict_int(slot) or slot < 0 or slot >= self._capacity:
            return None
        if not self._active[slot]:
            return None
        if self._frozen[slot]:
            return None  # Frozen dormant rows reject mutation
        if isinstance(expected_uid, bool) or not isinstance(expected_uid, str) or not expected_uid.strip():
            return None
        if self._uids[slot] != expected_uid:
            return None
        if not _is_strict_int(expected_gen) or expected_gen < 0:
            return None
        if int(self._slot_gen[slot].item()) != expected_gen:
            return None
        if isinstance(column, bool) or not _is_strict_int(column) or not self._schema.has_column(column):
            return None

        # Engine authority check
        if engine is not None:
            try:
                _validate_engine_authority(engine, slot, expected_uid)
            except Exception:
                return None

        spec = self._schema.get_field(column)
        try:
            # Reject out-of-bounds candidates; no silent clamping!
            f32_val = _validate_in_bounds(
                candidate_value,
                spec.min_value,
                spec.max_value,
                f"Candidate for '{spec.name}'",
            )
        except Exception:
            return None

        return AuxMutationDraft(
            slot=slot,
            column=column,
            value=f32_val,
            expected_uid=expected_uid,
            expected_gen=expected_gen,
        )

    def apply_mutations(
        self,
        drafts: Sequence[AuxMutationDraft],
        engine: Any = None,
    ) -> int:
        """Atomic batch commit: revalidates entire batch and stages converted values before commit.

        Rejects duplicate targets, stale tokens, frozen rows, non-representable values,
        out-of-bound values, or schema mismatches. On any validation failure, leaves internal
        storage wholly unchanged and returns 0.
        """
        if not drafts:
            return 0

        # Phase 1: Batch target deduplication and draft structure check
        seen_targets: set[tuple[int, int]] = set()
        for d in drafts:
            if not isinstance(d, AuxMutationDraft):
                return 0
            target = (d.slot, d.column)
            if target in seen_targets:
                return 0  # Duplicate target in single batch rejected
            seen_targets.add(target)

        # Phase 2: Complete revalidation against live state, staging converted values
        staged_commits: list[tuple[int, int, float]] = []
        for d in drafts:
            if not _is_strict_int(d.slot) or d.slot < 0 or d.slot >= self._capacity:
                return 0
            if not self._active[d.slot]:
                return 0
            if self._frozen[d.slot]:
                return 0  # Frozen rows reject mutation
            if isinstance(d.expected_uid, bool) or not isinstance(d.expected_uid, str) or not d.expected_uid.strip():
                return 0
            if self._uids[d.slot] != d.expected_uid:
                return 0
            if not _is_strict_int(d.expected_gen) or d.expected_gen < 0:
                return 0
            if int(self._slot_gen[d.slot].item()) != d.expected_gen:
                return 0
            if isinstance(d.column, bool) or not _is_strict_int(d.column) or not self._schema.has_column(d.column):
                return 0

            # Engine authority check
            if engine is not None:
                try:
                    _validate_engine_authority(engine, d.slot, d.expected_uid)
                except Exception:
                    return 0

            spec = self._schema.get_field(d.column)
            try:
                f32_val = _validate_in_bounds(
                    d.value,
                    spec.min_value,
                    spec.max_value,
                    f"Draft value for '{spec.name}'",
                )
            except Exception:
                return 0

            staged_commits.append((d.slot, d.column, f32_val))

        # Phase 3: All validations passed -> atomic commit
        for slot, col, val in staged_commits:
            self._tensor[slot, col] = val
        return len(drafts)


# --- Functional APIs (Conforming with 1010_aux_state_gap.md) ---

def allocate_aux_state(
    schema: AuxSchema,
    capacity: int = cfg.MAX_HUMANS,
    device: Optional[torch.device] = None,
    dtype: torch.dtype = torch.float32,
) -> AuxStateTable:
    """Allocate a bounded auxiliary storage table."""
    return AuxStateTable(schema=schema, capacity=capacity, device=device, dtype=dtype)


def bind_aux_state(engine: Any, table: AuxStateTable) -> None:
    """Attach auxiliary table to engine, verifying capacity and primary device alignment."""
    if not isinstance(table, AuxStateTable):
        raise TypeError(f"table must be an AuxStateTable, got {type(table).__name__}")
    if table.capacity != cfg.MAX_HUMANS:
        raise ValueError(f"Aux table capacity {table.capacity} != MAX_HUMANS {cfg.MAX_HUMANS}")
    if hasattr(engine, "state") and hasattr(engine.state, "h_tensor"):
        if table.device != engine.state.h_tensor.device:
            raise ValueError(
                f"Aux table device ({table.device}) mismatch with primary h_tensor ({engine.state.h_tensor.device})"
            )
        engine.state.h_aux = table
    elif hasattr(engine, "h_aux"):
        engine.h_aux = table
    elif hasattr(engine, "state"):
        engine.state.h_aux = table


def bind_aux_slot(table: AuxStateTable, slot: int, uid: str) -> int:
    """Bind a human UID to an auxiliary table slot and return current generation token."""
    return table.bind_slot(slot=slot, uid=uid)


def recycle_aux_slot(table: AuxStateTable, slot: int) -> int:
    """Recycle an auxiliary slot on human eviction and return bumped generation token."""
    return table.recycle_slot(slot=slot)


def clear_aux_slot(table: AuxStateTable, slot: int) -> None:
    """Reset an auxiliary slot row to schema defaults. Rejects frozen and inactive slots."""
    table.clear_slot(slot=slot)


def freeze_aux_slot(table: AuxStateTable, slot: int) -> None:
    """Mark an auxiliary slot as dormant/frozen."""
    table.freeze_slot(slot=slot)


def wake_aux_slot(table: AuxStateTable, slot: int, engine: Any = None) -> None:
    """Wake a dormant slot and recompute derived cache fields atomically."""
    table.wake_slot(slot=slot, engine=engine)


def get_aux_field(
    arg1: Any,
    arg2: Any,
    slot_or_col: Any = None,
    column: Optional[int] = None,
    expected_uid: Optional[str] = None,
    expected_gen: Optional[int] = None,
) -> float:
    """Read auxiliary field with flexible caller signature.

    Supports both:
      get_aux_field(engine, table, slot, column, expected_uid=..., expected_gen=...)
      get_aux_field(table, slot, column, expected_uid=..., expected_gen=...)
    """
    if isinstance(arg1, AuxStateTable):
        table = arg1
        engine = None
        slot = arg2
        col = slot_or_col
    elif isinstance(arg2, AuxStateTable):
        engine = arg1
        table = arg2
        slot = slot_or_col
        col = column
    else:
        raise TypeError("Neither first nor second argument is an AuxStateTable")

    return table.get_field(
        slot=slot,
        column=col,
        expected_uid=expected_uid,
        expected_gen=expected_gen,
        engine=engine,
    )


def plan_aux_mutation(
    arg1: Any,
    arg2: Any,
    slot: Any = None,
    column: Any = None,
    candidate_value: Any = None,
    expected_uid: Any = None,
    expected_gen: Any = None,
) -> Optional[AuxMutationDraft]:
    """Plan auxiliary mutation with flexible caller signature.

    Supports both:
      plan_aux_mutation(engine, table, slot, column, candidate_value, expected_uid, expected_gen)
      plan_aux_mutation(table, slot, column, candidate_value, expected_uid, expected_gen)
    """
    if isinstance(arg1, AuxStateTable):
        table = arg1
        engine = None
        s = arg2
        c = slot
        val = column
        uid = candidate_value
        gen = expected_uid
    elif isinstance(arg2, AuxStateTable):
        engine = arg1
        table = arg2
        s = slot
        c = column
        val = candidate_value
        uid = expected_uid
        gen = expected_gen
    else:
        return None

    return table.plan_mutation(
        slot=s,
        column=c,
        candidate_value=val,
        expected_uid=uid,
        expected_gen=gen,
        engine=engine,
    )


def apply_aux_mutations(
    arg1: Any,
    arg2: Any = None,
    drafts: Optional[Sequence[AuxMutationDraft]] = None,
) -> int:
    """Atomic apply with flexible caller signature.

    Supports both:
      apply_aux_mutations(engine, table, drafts)
      apply_aux_mutations(table, drafts)
    """
    if isinstance(arg1, AuxStateTable):
        table = arg1
        engine = None
        d = arg2
    elif isinstance(arg2, AuxStateTable):
        engine = arg1
        table = arg2
        d = drafts
    else:
        return 0

    return table.apply_mutations(drafts=d, engine=engine)
