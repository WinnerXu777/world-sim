"""Effects as data, and the vectorised EffectApplier.

Systems, actions and powers return typed ``Effect`` objects instead of writing tensors. One ``EffectApplier`` applies them in
batches, enforces column bounds, checks that items are conserved, re-resolves stable ids at apply time (a row that has been
reused or despawned is skipped, never mis-targeted), bumps the world's state revision (the number the stale-result guard
already uses) and returns a report with everything that was applied, skipped, clamped and emitted.

Effect kinds: ``Delta`` (add), ``Set`` (assign), ``Spawn``, ``Despawn``, ``Transfer`` (item moves between owners; the owner
``None`` on one side means creation or destruction, which needs an ``ItemPermit`` or ``allow_item_creation``), ``Task`` (create,
assign, cancel or complete a task record for a durative action; see ``tasks.py``) and ``Emit`` (an event in the ledger).
Adjacent ``Delta``s (and ``Set``s) on the same table and field are applied as one tensor operation; order between different
kinds is preserved.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

import torch

from . import tasks as tasks_mod


# -- effect types ---------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Delta:
    table: str
    ids: tuple
    field: str
    amount: Any            # a number applied to every id, or a sequence with one number per id


@dataclass(frozen=True)
class Set:
    table: str
    ids: tuple
    field: str
    value: Any             # a number for every id, or a sequence with one number per id


@dataclass(frozen=True)
class Spawn:
    table: str
    fields: dict
    id: Optional[str] = None


@dataclass(frozen=True)
class Despawn:
    table: str
    ids: tuple


@dataclass(frozen=True)
class Transfer:
    item: str
    qty: int
    src: Any               # owner id, or None = created from nothing
    dst: Any               # owner id, or None = destroyed (consumed)


@dataclass(frozen=True)
class Emit:
    type: str
    actors: tuple = ()
    place: Optional[tuple] = None
    space: int = 0
    visibility: str = "local"
    radius: float = 80.0
    payload: Optional[dict] = None
    event_id: Optional[str] = None


@dataclass(frozen=True)
class ResourceGuard:
    tick: int
    humans: Any
    human_ids: tuple
    entities: Any
    entity_ids: tuple
    geo_version: int


@dataclass(frozen=True)
class BirthBatch:
    """Live-engine births, prepared without consuming engine IDs or mutating the world."""
    births: tuple  # (mother id, father id, slot, fields)
    tick: int
    next_uid: int
    guard_rows: Any
    guard_ids: tuple


@dataclass(frozen=True)
class ResidentRelations:
    updates: tuple  # (owner, other, kind, closeness or None)


@dataclass(frozen=True)
class CalendarOverride:
    field: str
    value: Optional[str]


@dataclass(frozen=True)
class Task:
    """A task record operation. ``op``: ``create`` | ``assign`` | ``cancel`` | ``complete``.

    ``create`` needs ``kind`` (and optionally ``owner``, ``args``, ``priority`` 0..1, ``duration`` ticks, ``expires_tick``); with no
    ``task_id`` the store allocates one when the effect is applied (so a later effect in the same batch can only name a task it
    created if it gave an explicit ``task_id``). ``assign`` sets the owner of an open task. ``cancel`` / ``complete`` close an open
    task. ``owner_table`` names the table the owner id must be live in."""
    op: str
    task_id: Optional[str] = None
    kind: str = ""
    owner: Optional[str] = None
    owner_table: str = "humans"
    args: Optional[dict] = None
    priority: float = 0.5
    duration: Optional[int] = None
    expires_tick: Optional[int] = None
    reason: str = ""


TASK_OPS = ("create", "assign", "cancel", "complete")
Effect = (Delta, Set, Spawn, Despawn, Transfer, Task, Emit)


def task_create(kind, owner=None, **kw) -> Task:
    return Task("create", kind=kind, owner=owner, **kw)


def task_assign(task_id, owner, owner_table="humans") -> Task:
    return Task("assign", task_id=task_id, owner=owner, owner_table=owner_table)


def task_cancel(task_id, reason="") -> Task:
    return Task("cancel", task_id=task_id, reason=reason)


def task_complete(task_id) -> Task:
    return Task("complete", task_id=task_id)


@dataclass(frozen=True)
class ItemPermit:
    """Declared permission for one apply to destroy (``consume``) or create (``produce``) items.

    Each map is ``item -> most units this apply may move`` (``None`` = any quantity of that item). A ``Transfer`` whose ``dst`` is
    None (consumption) needs the item in ``consume``; one whose ``src`` is None (production) needs it in ``produce``; the sum over
    the apply must stay within the cap. Everything not declared is refused. Transfers between two owners never need a permit.
    The permit is data, so an action's declaration can be listed in the manifest and checked before anything runs.
    """
    consume: dict = field(default_factory=dict)
    produce: dict = field(default_factory=dict)

    def __post_init__(self):
        for label, table in (("consume", self.consume), ("produce", self.produce)):
            for item, cap in dict(table).items():
                if not isinstance(item, str) or not item:
                    raise ValueError(f"ItemPermit.{label}: item names must be non-empty strings, got {item!r}")
                if cap is not None and (not isinstance(cap, int) or isinstance(cap, bool) or cap <= 0):
                    raise ValueError(f"ItemPermit.{label}[{item!r}]: cap must be a positive integer or None, got {cap!r}")

    @classmethod
    def of(cls, consume=(), produce=()) -> "ItemPermit":
        """Build from item names (any quantity) or from ``{item: cap}`` mappings."""
        def norm(value):
            return dict(value) if isinstance(value, dict) else {name: None for name in value}
        return cls(norm(consume), norm(produce))

    def __bool__(self) -> bool:
        return bool(self.consume or self.produce)

    def as_dict(self) -> dict:
        return {"consume": dict(self.consume), "produce": dict(self.produce)}


def delta(table, ids, field_name, amount) -> Delta:
    return Delta(table, _ids(ids), field_name, amount)


def set_(table, ids, field_name, value) -> Set:
    return Set(table, _ids(ids), field_name, value)


def despawn(table, ids) -> Despawn:
    return Despawn(table, _ids(ids))


def _ids(ids) -> tuple:
    return (ids,) if isinstance(ids, (str, int)) else tuple(ids)


# -- report ---------------------------------------------------------------------------------------------------------
@dataclass
class Skip:
    index: int
    kind: str
    reason: str
    detail: str = ""


@dataclass
class ApplyReport:
    applied: dict = field(default_factory=dict)
    skipped: list = field(default_factory=list)
    clamped: int = 0
    spawned: list = field(default_factory=list)
    despawned: list = field(default_factory=list)
    events: list = field(default_factory=list)
    created: dict = field(default_factory=dict)
    destroyed: dict = field(default_factory=dict)
    revision: int = 0
    changed: bool = False
    rolled_back: bool = False
    tasks: list = field(default_factory=list)        # (op, task_id) in application order, including owner_gone cancellations

    @property
    def ok(self) -> bool:
        return not self.skipped

    def count(self, kind: str, n: int = 1) -> None:
        self.applied[kind] = self.applied.get(kind, 0) + n


class ConservationError(RuntimeError):
    """Items appeared or vanished outside declared creation/destruction (a bug in a store or an effect source)."""


# -- applier --------------------------------------------------------------------------------------------------------
class EffectApplier:
    def __init__(self, world, allow_item_creation: bool = False):
        self.world = world
        self.allow_item_creation = allow_item_creation
        self._permit: Optional[ItemPermit] = None

    # public ---------------------------------------------------------------------
    def validate(self, effects: Sequence, items: Optional[ItemPermit] = None) -> list:
        """Problems that would make ``apply`` skip something, found without changing anything (``Skip`` list)."""
        problems: list[Skip] = []
        balances: dict = {}
        previous, self._permit = self._permit, items
        try:
            for index, effect in enumerate(effects):
                self._validate_one(index, effect, problems, balances)
        finally:
            self._permit = previous
        return problems

    def apply(self, effects: Sequence, *, atomic: bool = False, cause: str = "", items: Optional[ItemPermit] = None) -> ApplyReport:
        """Apply ``effects`` in order. With ``atomic`` nothing is applied unless ``validate`` finds no problem.

        ``items`` declares which items this apply may consume or produce (see ``ItemPermit``); without it item creation and
        destruction are refused unless the applier was built with ``allow_item_creation`` (unrestricted, kept for tests)."""
        previous, self._permit = self._permit, items
        try:
            return self._apply(effects, atomic, cause, items)
        finally:
            self._permit = previous

    def _apply(self, effects, atomic, cause, items) -> ApplyReport:
        report = ApplyReport(revision=self.world.revision)
        effects = list(effects)
        if atomic:
            problems = self.validate(effects, items)
            if problems:
                report.skipped = problems
                report.rolled_back = True
                return report
        totals_before = {item: self.world.items.total(item) for item in set(self.world.items.items()) | self._items_in(effects)}
        run: list = []
        run_key = None
        touched: dict = {}
        for index, effect in enumerate(effects):
            key = (type(effect).__name__, getattr(effect, "table", None), getattr(effect, "field", None))
            if run and (key != run_key or not isinstance(effect, (Delta, Set))):
                self._flush(run, report, touched)
                run = []
            if isinstance(effect, (Delta, Set)):
                run.append((index, effect))
                run_key = key
                continue
            self._apply_single(index, effect, report, touched, cause)
            if atomic and isinstance(effect, BirthBatch) and report.skipped:
                report.rolled_back = True
                return report
        if run:
            self._flush(run, report, touched)
        for table_name, slots in touched.items():
            self.world.reindex(table_name, sorted(slots))
        self._check_conservation(totals_before, report)
        report.changed = bool(report.applied)
        if report.changed:
            report.revision = self.world.bump_revision()
        return report

    # validation -----------------------------------------------------------------
    def _validate_one(self, index, effect, problems, balances):
        w = self.world
        if isinstance(effect, (Delta, Set)):
            try:
                table = w.table(effect.table)
                table.col(effect.field)
            except KeyError as exc:
                problems.append(Skip(index, type(effect).__name__, "unknown_table_or_field", str(exc)))
                return
            slots, missing = table.slots_of(effect.ids)
            for eid in missing:
                problems.append(Skip(index, type(effect).__name__, "unknown_id", str(eid)))
            for slot in slots:
                if not table.is_live_slot(slot):
                    problems.append(Skip(index, type(effect).__name__, "not_live", str(table.ids[slot])))
            if isinstance(effect, Set) and table.spec(effect.field).mode == "reject":
                values = _broadcast(effect.value, len(effect.ids))
                spec = table.spec(effect.field)
                for eid, value in zip(effect.ids, values):
                    if not _in_bounds(value, spec):
                        problems.append(Skip(index, "Set", "out_of_bounds", f"{eid}.{effect.field}={value}"))
            for value in _broadcast(effect.amount if isinstance(effect, Delta) else effect.value, len(effect.ids)):
                if not math.isfinite(float(value)):
                    problems.append(Skip(index, type(effect).__name__, "non_finite", str(value)))
        elif isinstance(effect, Spawn):
            try:
                table = w.table(effect.table)
            except KeyError as exc:
                problems.append(Skip(index, "Spawn", "unknown_table", str(exc)))
                return
            if table.free_slot() is None:
                problems.append(Skip(index, "Spawn", "table_full", effect.table))
            if effect.id is not None and effect.id in table.ids:
                problems.append(Skip(index, "Spawn", "duplicate_id", effect.id))
            if float(effect.fields.get(table.type_col, 0)) <= 0:
                problems.append(Skip(index, "Spawn", "missing_type", effect.table))
        elif isinstance(effect, ResourceGuard):
            import map_geo
            humans, entities = w.table("humans"), w.table("entities")
            if (index != 0 or os.environ.get("EDEN_GOD_POWER_PORTS") != "1" or os.environ.get("EDEN_GOD_MIND_PORTS") != "1"
                    or int(w.tick) != effect.tick or map_geo.geo_version != effect.geo_version
                    or tuple(humans.ids) != effect.human_ids or tuple(entities.ids) != effect.entity_ids
                    or not torch.equal(humans.tensor, effect.humans) or not torch.equal(entities.tensor, effect.entities)):
                problems.append(Skip(index, "ResourceGuard", "stale_or_disabled"))
        elif isinstance(effect, BirthBatch):
            engine = getattr(w, "engine", None)
            table = w.table("humans")
            if os.environ.get("EDEN_GOD_POWER_PORTS") != "1" or os.environ.get("EDEN_GOD_MIND_PORTS") != "1":
                problems.append(Skip(index, "BirthBatch", "disabled"))
                return
            if (index != 0 or engine is None or int(w.tick) != effect.tick or engine._next_human_uid != effect.next_uid
                    or tuple(table.ids) != effect.guard_ids or not torch.equal(table.tensor, effect.guard_rows)):
                problems.append(Skip(index, "BirthBatch", "stale_or_unsupported"))
                return
            slots_seen = set()
            for offset, (mother, father, slot, fields) in enumerate(effect.births):
                uid = f"h_{effect.next_uid + offset:06d}"
                store = engine.resident_store
                cache = getattr(store, "_cache", getattr(store, "records", {}))
                path_fn = getattr(store, "_path", None)
                if (uid in table.ids or uid in cache or (callable(path_fn) and path_fn(uid).exists())
                        or slot in slots_seen or not (0 <= slot < table.rows)):
                    problems.append(Skip(index, "BirthBatch", "invalid_allocation", uid))
                    continue
                slots_seen.add(slot)
                if table.ids[slot] is not None or table.is_live_slot(slot) or bool(engine._prev_h_mask[slot]):
                    problems.append(Skip(index, "BirthBatch", "slot_unavailable", str(slot)))
                for parent in (mother, father):
                    parent_slot = table.slot_of(parent)
                    if parent_slot is None or not table.is_live_slot(parent_slot):
                        problems.append(Skip(index, "BirthBatch", "parent_unavailable", str(parent)))
                if any(key not in table.columns or not math.isfinite(float(value)) for key, value in fields.items()):
                    problems.append(Skip(index, "BirthBatch", "invalid_fields", uid))
                if fields.get(table.type_col) != 1:
                    problems.append(Skip(index, "BirthBatch", "invalid_type", uid))
            if len(table.live_slots()) + len(effect.births) > table.rows:
                problems.append(Skip(index, "BirthBatch", "table_full"))
        elif isinstance(effect, Despawn):
            table = w.table(effect.table)
            slots, missing = table.slots_of(effect.ids)
            for eid in missing:
                problems.append(Skip(index, "Despawn", "unknown_id", str(eid)))
        elif isinstance(effect, Transfer):
            self._validate_transfer(index, effect, problems, balances)
        elif isinstance(effect, Task):
            self._validate_task(index, effect, problems, balances)
        elif isinstance(effect, ResidentRelations):
            if not isinstance(effect.updates, (tuple, list)):
                problems.append(Skip(index, "ResidentRelations", "invalid_updates"))
                return
            for update in effect.updates:
                if not isinstance(update, (tuple, list)) or len(update) != 4:
                    problems.append(Skip(index, "ResidentRelations", "invalid_update"))
                    continue
                owner, other, kind, value = update
                if not isinstance(owner, str) or not isinstance(other, str) or owner not in w.residents or other not in w.residents:
                    problems.append(Skip(index, "ResidentRelations", "unknown_resident", str(owner)))
                if not isinstance(kind, str) or not kind:
                    problems.append(Skip(index, "ResidentRelations", "invalid_kind"))
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not -1 <= value <= 1):
                    problems.append(Skip(index, "ResidentRelations", "invalid_value"))
        elif isinstance(effect, CalendarOverride):
            from . import calendar
            if effect.field not in ("season", "time"):
                problems.append(Skip(index, "CalendarOverride", "invalid_field"))
            elif effect.value is not None and effect.value not in (calendar.SEASONS if effect.field == "season" else calendar.BLOCKS):
                problems.append(Skip(index, "CalendarOverride", "invalid_value"))
        elif isinstance(effect, Emit):
            pass
        else:
            problems.append(Skip(index, type(effect).__name__, "unknown_effect_type"))

    def _validate_transfer(self, index, effect, problems, balances):
        store = self.world.items
        if not isinstance(effect.qty, int) or isinstance(effect.qty, bool) or effect.qty <= 0:
            problems.append(Skip(index, "Transfer", "invalid_quantity", str(effect.qty)))
            return
        if effect.src is None and effect.dst is None:
            problems.append(Skip(index, "Transfer", "no_endpoints"))
            return
        if effect.src is None or effect.dst is None:
            if not self._item_permitted(index, effect, problems, balances):
                return
        if effect.src is not None:
            have = balances.setdefault((effect.src, effect.item), store.quantity(effect.src, effect.item))
            if have < effect.qty:
                problems.append(Skip(index, "Transfer", "insufficient", f"{effect.src} has {have} {effect.item}, needs {effect.qty}"))
                return
            balances[(effect.src, effect.item)] = have - effect.qty
        if effect.dst is not None:
            room = store.room(effect.dst, effect.item)
            if room is not None and room < effect.qty:
                problems.append(Skip(index, "Transfer", "no_room", f"{effect.dst} has room for {room}"))
                return
            balances[(effect.dst, effect.item)] = balances.get((effect.dst, effect.item), store.quantity(effect.dst, effect.item)) + effect.qty

    def _task_status(self, task_id, balances):
        """Status of a task as it will be after the earlier effects of this batch (None = no such task)."""
        key = ("\0task", task_id)
        if key in balances:
            return balances[key]
        record = self.world.tasks.get(task_id)
        return None if record is None else record["status"]

    def _owner_problem(self, effect) -> Optional[tuple]:
        try:
            table = self.world.table(effect.owner_table)
        except KeyError:
            return ("unknown_owner", f"no table {effect.owner_table!r}")
        slots, missing = table.slots_of([effect.owner])
        if missing:
            return ("unknown_owner", str(effect.owner))
        if not table.is_live_slot(slots[0]):
            return ("not_live", str(effect.owner))
        return None

    def _validate_task(self, index, effect, problems, balances):
        def bad(reason, detail=""):
            problems.append(Skip(index, "Task", reason, detail))
        if effect.op not in TASK_OPS:
            return bad("invalid_task", f"unknown op {effect.op!r}")
        if effect.op == "create":
            if not isinstance(effect.kind, str) or not effect.kind:
                return bad("invalid_task", "kind must be a non-empty string")
            if not isinstance(effect.priority, (int, float)) or isinstance(effect.priority, bool) or not 0.0 <= effect.priority <= 1.0:
                return bad("invalid_task", f"priority must be in [0, 1], got {effect.priority!r}")
            if effect.duration is not None and (not isinstance(effect.duration, int) or isinstance(effect.duration, bool) or effect.duration <= 0):
                return bad("invalid_task", f"duration must be a positive integer, got {effect.duration!r}")
            if effect.expires_tick is not None and (not isinstance(effect.expires_tick, int) or isinstance(effect.expires_tick, bool)
                                                    or effect.expires_tick <= int(self.world.tick)):
                return bad("invalid_task", f"expires_tick must be an integer after the current tick, got {effect.expires_tick!r}")
            if effect.args is not None and not isinstance(effect.args, dict):
                return bad("invalid_task", "args must be a dict")
            if effect.task_id is not None:
                if not isinstance(effect.task_id, str) or not effect.task_id:
                    return bad("invalid_task", "task_id must be a non-empty string")
                if self._task_status(effect.task_id, balances) is not None:
                    return bad("task_exists", effect.task_id)
            if effect.owner is not None:
                problem = self._owner_problem(effect)
                if problem:
                    return bad(*problem)
            if effect.task_id is not None:
                balances[("\0task", effect.task_id)] = tasks_mod.ASSIGNED if effect.owner is not None else tasks_mod.PENDING
            return
        status = self._task_status(effect.task_id, balances)
        if status is None:
            return bad("unknown_task", str(effect.task_id))
        if status in tasks_mod.TERMINAL:
            return bad("task_closed", f"{effect.task_id} is {status}")
        if effect.op == "assign":
            if effect.owner is None:
                return bad("invalid_task", "assign needs an owner")
            problem = self._owner_problem(effect)
            if problem:
                return bad(*problem)
            balances[("\0task", effect.task_id)] = tasks_mod.ASSIGNED
        else:
            balances[("\0task", effect.task_id)] = tasks_mod.CANCELLED if effect.op == "cancel" else tasks_mod.DONE

    def _task_apply(self, index, effect, report) -> None:
        problems: list = []
        self._validate_task(index, effect, problems, {})
        if problems:
            report.skipped.extend(problems)
            return
        store, tick = self.world.tasks, int(self.world.tick)
        if effect.op == "create":
            task_id = effect.task_id or store.new_id()
            store.put({"id": task_id, "kind": effect.kind, "owner": effect.owner, "owner_table": effect.owner_table,
                       "status": tasks_mod.ASSIGNED if effect.owner is not None else tasks_mod.PENDING,
                       "args": dict(effect.args or {}), "priority": float(effect.priority), "duration": effect.duration,
                       "expires_tick": effect.expires_tick, "created_tick": tick, "closed_tick": None, "reason": ""})
        elif effect.op == "assign":
            task_id = effect.task_id
            store.update(task_id, owner=effect.owner, owner_table=effect.owner_table, status=tasks_mod.ASSIGNED)
        else:
            task_id = effect.task_id
            store.update(task_id, status=tasks_mod.CANCELLED if effect.op == "cancel" else tasks_mod.DONE, reason=effect.reason,
                         closed_tick=tick)
        report.tasks.append((effect.op, task_id))
        report.count("Task")

    def _item_permitted(self, index, effect, problems, balances) -> bool:
        """Creation (src None) / destruction (dst None) of items: allowed by the declared permit, or unrestricted by the flag."""
        if self._permit is None:
            if self.allow_item_creation:
                return True
            problems.append(Skip(index, "Transfer", "creation_not_allowed", effect.item))
            return False
        producing = effect.src is None
        declared = self._permit.produce if producing else self._permit.consume
        label = "produce" if producing else "consume"
        if effect.item not in declared:
            problems.append(Skip(index, "Transfer", f"{label}_not_declared", effect.item))
            return False
        cap = declared[effect.item]
        key = ("\0" + label, effect.item)
        used = balances.get(key, 0)
        if cap is not None and used + effect.qty > cap:
            problems.append(Skip(index, "Transfer", f"{label}_over_cap", f"{effect.item}: {used}+{effect.qty} > {cap}"))
            return False
        balances[key] = used + effect.qty
        return True

    # application ----------------------------------------------------------------
    def _flush(self, run, report, touched):
        """Apply a run of adjacent Delta (or Set) effects on one table and field as one tensor operation."""
        first = run[0][1]
        w = self.world
        try:
            table = w.table(first.table)
            col = table.col(first.field)
        except KeyError as exc:
            for index, effect in run:
                report.skipped.append(Skip(index, type(effect).__name__, "unknown_table_or_field", str(exc)))
            return
        spec = self._effective_spec(table, first.field)
        is_delta = isinstance(first, Delta)
        slots: list = []
        values: list = []
        for index, effect in run:
            ids = effect.ids
            amounts = _broadcast(effect.amount if is_delta else effect.value, len(ids))
            for eid, amount in zip(ids, amounts):
                slot = table.slot_of(eid)
                if slot is None:
                    report.skipped.append(Skip(index, type(effect).__name__, "unknown_id", str(eid)))
                elif not table.is_live_slot(slot):
                    report.skipped.append(Skip(index, type(effect).__name__, "not_live", str(eid)))
                elif not math.isfinite(float(amount)):
                    report.skipped.append(Skip(index, type(effect).__name__, "non_finite", f"{eid}.{first.field}"))
                elif not is_delta and spec.mode == "reject" and not _in_bounds(float(amount), spec):
                    report.skipped.append(Skip(index, "Set", "out_of_bounds", f"{eid}.{first.field}={amount}"))
                else:
                    slots.append(slot)
                    values.append(float(amount))
        if not slots:
            return
        slot_t = torch.tensor(slots, dtype=torch.long)
        val_t = torch.tensor(values, dtype=table.tensor.dtype)
        if is_delta:
            uniq, inverse = torch.unique(slot_t, return_inverse=True)
            summed = torch.zeros(len(uniq), dtype=table.tensor.dtype).index_add_(0, inverse, val_t)
            new = table.tensor[uniq, col] + summed
            target_slots = uniq
        else:  # for repeated ids in one batch the last value wins, as a sequence of Sets would
            last = {}
            for s, v in zip(slots, values):
                last[s] = v
            target_slots = torch.tensor(list(last), dtype=torch.long)
            new = torch.tensor(list(last.values()), dtype=table.tensor.dtype)
        clamped = self._clamp(new, spec)
        report.clamped += int(((clamped != new) & torch.isfinite(new)).sum().item())
        if spec.integer:
            clamped = torch.round(clamped)
        table.tensor[target_slots, col] = clamped
        report.count("Delta" if is_delta else "Set", len(target_slots))
        touched.setdefault(first.table, set()).update(int(s) for s in target_slots.tolist())

    def _effective_spec(self, table, field_name):
        spec = table.spec(field_name)
        bounds = self.world.bounds()
        if table.pos_cols and bounds is not None and field_name in table.pos_cols:
            axis = table.pos_cols.index(field_name)
            lo, hi = bounds[axis], bounds[axis + 2]
            return type(spec)(lo=lo if spec.lo is None else max(lo, spec.lo), hi=hi if spec.hi is None else min(hi, spec.hi),
                              integer=spec.integer, mode="clamp")
        return spec

    @staticmethod
    def _clamp(values: torch.Tensor, spec) -> torch.Tensor:
        if spec.lo is not None:
            values = torch.clamp(values, min=spec.lo)
        if spec.hi is not None:
            values = torch.clamp(values, max=spec.hi)
        return values

    def _apply_single(self, index, effect, report, touched, cause):
        w = self.world
        if isinstance(effect, Spawn):
            self._spawn(index, effect, report, touched)
        elif isinstance(effect, ResourceGuard):
            return
        elif isinstance(effect, BirthBatch):
            engine, table = w.engine, w.table("humans")
            problems = []
            self._validate_one(index, effect, problems, {})
            if problems:
                report.skipped.extend(problems)
                return
            # Resident creation only mutates in-memory store collections; snapshot those collections
            # before allocation so a failed ensure cannot leave a partial batch or consume IDs.
            store = engine.resident_store
            store_state = {key: value.copy() if isinstance(value, (dict, set, list)) else value
                           for key, value in vars(store).items()}
            previous_links = dict(engine._pending_birth_links_by_slot)
            next_uid = engine._next_human_uid
            slots = [birth[2] for birth in effect.births]
            old_rows = {slot: table.tensor[slot].clone() for slot in slots}
            try:
                for mother, father, slot, fields in effect.births:
                    uid = engine._make_human_id()
                    table.tensor[slot] = 0.0
                    for key, value in fields.items():
                        table.tensor[slot, table.col(key)] = value
                    table.ids[slot] = uid
                    store.ensure_resident(uid, slot, table.tensor, int(w.tick))
                    engine._pending_birth_links_by_slot[slot] = {"tick": int(w.tick), "parent_ids": [mother, father]}
            except Exception as exc:
                for slot in slots:
                    table.tensor[slot] = old_rows[slot]
                    table.ids[slot] = None
                engine._next_human_uid = next_uid
                engine._pending_birth_links_by_slot.clear()
                engine._pending_birth_links_by_slot.update(previous_links)
                vars(store).clear()
                vars(store).update(store_state)
                report.skipped.append(Skip(index, "BirthBatch", "birth_failed", type(exc).__name__))
                return
            for offset, (_, _, slot, _) in enumerate(effect.births):
                uid = f"h_{effect.next_uid + offset:06d}"
                report.spawned.append(("humans", uid))
                report.count("BirthBatch")
                touched.setdefault("humans", set()).add(slot)
        elif isinstance(effect, Despawn):
            table = w.table(effect.table)
            for eid in effect.ids:
                slot = table.slot_of(eid)
                if slot is None:
                    report.skipped.append(Skip(index, "Despawn", "unknown_id", str(eid)))
                    continue
                table.tensor[slot] = 0.0
                table.ids[slot] = None
                w.index.remove(eid)
                report.despawned.append((effect.table, eid))
                report.count("Despawn")
                for task_id in w.tasks.cancel_owned_by(eid, int(w.tick), "owner_gone"):
                    report.tasks.append(("cancel", task_id))
                    report.count("Task")
        elif isinstance(effect, Transfer):
            self._transfer(index, effect, report)
        elif isinstance(effect, Task):
            self._task_apply(index, effect, report)
        elif isinstance(effect, ResidentRelations):
            problems = []
            self._validate_one(index, effect, problems, {})
            if problems:
                report.skipped.extend(problems)
                return
            for owner, other, kind, value in effect.updates:
                store = getattr(getattr(w, "engine", None), "resident_store", None)
                if store is not None:
                    old = w.residents[owner].get("relationships", {}).get(other, {})
                    previous = float(old.get("closeness", 0.0))
                    store.update_relationship(owner, other, kind, 0.0 if value is None else value - previous, int(w.tick))
                    continue
                relations = w.residents[owner].setdefault("relationships", {})
                relation = relations.setdefault(other, {"kind": kind, "closeness": 0.0, "tags": [], "tag_meta": {}})
                relation["kind"] = kind
                if value is not None:
                    relation["closeness"] = value
                relation["last_seen_tick"] = int(w.tick)
                tags = relation.setdefault("tags", [])
                if kind not in tags:
                    tags.append(kind)
            report.count("ResidentRelations")
        elif isinstance(effect, CalendarOverride):
            from . import calendar
            problems = []
            self._validate_one(index, effect, problems, {})
            if problems:
                report.skipped.extend(problems)
                return
            calendar.set_override(w, effect.field, effect.value)
            report.count("CalendarOverride")
        elif isinstance(effect, Emit):
            event = w.events.emit(effect.type, actors=effect.actors, place=effect.place, space=effect.space,
                                  visibility=effect.visibility, radius=effect.radius, payload=effect.payload,
                                  event_id=effect.event_id, cause=cause)
            report.events.append(event)
            report.count("Emit")
        else:
            report.skipped.append(Skip(index, type(effect).__name__, "unknown_effect_type"))

    def _spawn(self, index, effect, report, touched):
        w = self.world
        table = w.table(effect.table)
        problems: list = []
        self._validate_one(index, effect, problems, {})
        if problems:
            report.skipped.extend(problems)
            return
        slot = table.free_slot()
        entity_id = effect.id or table.new_id()
        table.tensor[slot] = 0.0
        for name, value in effect.fields.items():
            spec = self._effective_spec(table, name)
            clamped = float(self._clamp(torch.tensor([float(value)]), spec)[0])
            table.tensor[slot, table.col(name)] = round(clamped) if spec.integer else clamped
        table.ids[slot] = entity_id
        report.spawned.append((effect.table, entity_id))
        report.count("Spawn")
        touched.setdefault(effect.table, set()).add(slot)

    def _transfer(self, index, effect, report):
        store = self.world.items
        problems: list = []
        used = {("\0produce", i): n for i, n in report.created.items()}
        used.update({("\0consume", i): n for i, n in report.destroyed.items()})
        self._validate_transfer(index, effect, problems, used)
        if problems:
            report.skipped.extend(problems)
            return
        removed = store.remove(effect.src, effect.item, effect.qty) if effect.src is not None else effect.qty
        if removed != effect.qty:
            if removed and effect.src is not None:
                store.add(effect.src, effect.item, removed)
            report.skipped.append(Skip(index, "Transfer", "insufficient", f"removed {removed} of {effect.qty}"))
            return
        if effect.dst is not None:
            added = store.add(effect.dst, effect.item, effect.qty)
            if added != effect.qty:  # roll back so nothing is lost
                if added:
                    store.remove(effect.dst, effect.item, added)
                if effect.src is not None:
                    store.add(effect.src, effect.item, effect.qty)
                report.skipped.append(Skip(index, "Transfer", "no_room", f"added {added} of {effect.qty}"))
                return
        if effect.src is None:
            report.created[effect.item] = report.created.get(effect.item, 0) + effect.qty
        if effect.dst is None:
            report.destroyed[effect.item] = report.destroyed.get(effect.item, 0) + effect.qty
        report.count("Transfer")

    # conservation ---------------------------------------------------------------
    @staticmethod
    def _items_in(effects) -> set:
        return {e.item for e in effects if isinstance(e, Transfer)}

    def _check_conservation(self, before: dict, report: ApplyReport) -> None:
        store = self.world.items
        for item in set(before) | set(store.items()):
            expected = before.get(item, 0) + report.created.get(item, 0) - report.destroyed.get(item, 0)
            actual = store.total(item)
            if actual != expected:
                raise ConservationError(f"item {item!r}: expected total {expected} after apply, found {actual}")


def _broadcast(value, n: int) -> list:
    if isinstance(value, (list, tuple)) or hasattr(value, "tolist") and getattr(value, "ndim", 0) > 0:
        values = list(value.tolist() if hasattr(value, "tolist") else value)
        if len(values) != n:
            raise ValueError(f"expected {n} values, got {len(values)}")
        return values
    return [value] * n


def _in_bounds(value, spec) -> bool:
    return (spec.lo is None or value >= spec.lo) and (spec.hi is None or value <= spec.hi)
