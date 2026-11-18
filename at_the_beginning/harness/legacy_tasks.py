"""Step 1 of the Task-store bridge: a READ-ONLY view of the legacy resident task queues in the harness task shape.

``LegacyTaskView(engine)`` reads ``resident["tasks"]`` (queued / active), ``task_state["paused_tasks"]`` and
``task_state["last_completed_task"]`` of every live human through ``engine.resident_store.get`` and presents them with the same
duck-typed interface as ``DictTaskStore`` (``get / has / all / open_for``). It never writes: ``new_id / put / update`` raise
``ReadOnlyTaskStore`` and ``cancel_owned_by`` returns ``[]`` (a despawn through the harness must not fail; the legacy death path
owns the resident's queue). Nothing here calls ``queue_revision`` bumps, dirty marks or any ``systems.tasks.ops`` function.

Mapping (legacy -> harness record): ``id`` is ``metadata["harness_id"]`` when present, else the legacy id (``task_000001``, from a
process-global counter, so never used for ordering or hashing); ``kind`` = ``task_kind``; ``owner`` = the resident id,
``owner_table`` = ``humans``; ``status``: queued / active / paused -> ``assigned``; ``last_completed_task`` -> ``done`` when its
legacy status is ``completed``, else ``cancelled`` (only the latest closed task per resident is kept by the legacy queue, so closed
history is not available); ``args`` = ``metadata["harness_args"]``; ``duration`` = ``metadata["duration"]``; the original legacy
record is under ``legacy``. ``all()`` is ordered by slot, then queue position, then paused tasks, then the closed one.
See ``1008_s3_s5_taskbridge_design.md`` section 3.
"""
from __future__ import annotations

import copy
from typing import Optional

from . import tasks as tasks_mod


class ReadOnlyTaskStore(RuntimeError):
    """A write was attempted on the read-only legacy task view (bridge step 1)."""


def _record(owner, task: dict, *, closed: bool = False) -> dict:
    meta = task.get("metadata") if isinstance(task.get("metadata"), dict) else {}
    legacy_status = str(task.get("status", ""))
    if closed:
        status = tasks_mod.DONE if legacy_status == "completed" else tasks_mod.CANCELLED
    else:
        status = tasks_mod.ASSIGNED
    return {"id": str(meta.get("harness_id") or task.get("id", "")), "kind": str(task.get("task_kind", "")), "owner": owner,
            "owner_table": "humans", "status": status, "args": copy.deepcopy(meta.get("harness_args") or {}),
            "priority": float(task.get("priority", 0.0)), "duration": meta.get("duration"),
            "expires_tick": task.get("expires_tick"), "created_tick": int(task.get("created_tick", 0)),
            "closed_tick": int(task.get("last_update_tick", 0)) if closed else None,
            "reason": str(meta.get("completion_reason", "")) if closed else "",
            "legacy": copy.deepcopy(task), "legacy_status": legacy_status}


class LegacyTaskView:
    def __init__(self, engine):
        self.engine = engine

    # reads --------------------------------------------------------------------------------------------------------
    def _residents(self):
        store = self.engine.resident_store
        for human_id in self.engine._human_uid_by_slot:
            if not human_id:
                continue
            resident = store.get(human_id)
            if isinstance(resident, dict):
                yield human_id, resident

    def all(self) -> list:
        out: list = []
        for human_id, resident in self._residents():
            out.extend(_record(human_id, t) for t in resident.get("tasks", ()) if isinstance(t, dict))
            state = resident.get("task_state") if isinstance(resident.get("task_state"), dict) else {}
            out.extend(_record(human_id, t) for t in state.get("paused_tasks", ()) if isinstance(t, dict))
            closed = state.get("last_completed_task")
            if isinstance(closed, dict) and closed:
                out.append(_record(human_id, closed, closed=True))
        return out

    def get(self, task_id) -> Optional[dict]:
        for record in self.all():
            if record["id"] == task_id or record["legacy"].get("id") == task_id:
                return record
        return None

    def has(self, task_id) -> bool:
        return self.get(task_id) is not None

    def open_for(self, owner) -> list:
        return [r for r in self.all() if r["owner"] == owner and r["status"] not in tasks_mod.TERMINAL]

    # writes: refused ----------------------------------------------------------------------------------------------
    def new_id(self):
        raise ReadOnlyTaskStore("the legacy task view is read-only (bridge step 1)")

    def put(self, record):
        raise ReadOnlyTaskStore("the legacy task view is read-only (bridge step 1)")

    def update(self, task_id, **fields):
        raise ReadOnlyTaskStore("the legacy task view is read-only (bridge step 1)")

    def cancel_owned_by(self, owner, tick: int, reason: str) -> list:
        return []                                    # the legacy death path owns the resident's queue; nothing is written here
