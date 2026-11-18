"""Tasks as data: the store behind the ``Task`` effect (create / assign / cancel / complete), for durative actions.

A durative action ("eat", "craft", "walk to the well") does not finish inside one tick. It creates a task record that says who does
what, for how long and with which arguments; later ticks progress and finally ``complete`` or ``cancel`` it. The record is plain
data (a dict of JSON-friendly values), so it can be listed in a manifest, saved, replayed and compared in tests.

``DictTaskStore`` is the synthetic implementation (unit tests, tiny worlds). The duck-typed interface is:

    get(task_id) -> dict | None (a copy)      has(task_id) -> bool        new_id() -> str
    put(record) -> None                        update(task_id, **fields)   open_for(owner) -> list of records, oldest first
    all() -> list of records                   cancel_owned_by(owner, tick, reason) -> list of task ids

Status values: ``pending`` (no owner yet), ``assigned`` (has an owner), and the terminal ``done``, ``cancelled``.
The Engine adapter does NOT yet bridge this store to the legacy ``resident["tasks"]`` queue (the actions package keeps using
its RecordOps for that); see ``1008_scheduler_design.md``.
"""
from __future__ import annotations

import copy
from typing import Optional

PENDING, ASSIGNED, DONE, CANCELLED = "pending", "assigned", "done", "cancelled"
TERMINAL = (DONE, CANCELLED)


class DictTaskStore:
    def __init__(self):
        self._tasks: dict = {}
        self._order: list = []
        self._next = 1

    def has(self, task_id) -> bool:
        return task_id in self._tasks

    def get(self, task_id) -> Optional[dict]:
        record = self._tasks.get(task_id)
        return copy.deepcopy(record) if record is not None else None

    def new_id(self) -> str:
        while True:
            candidate = f"t_{self._next:06d}"
            self._next += 1
            if candidate not in self._tasks:
                return candidate

    def put(self, record: dict) -> None:
        task_id = record["id"]
        if task_id in self._tasks:
            raise KeyError(f"task {task_id!r} already exists")
        self._tasks[task_id] = copy.deepcopy(record)
        self._order.append(task_id)

    def update(self, task_id, **fields) -> None:
        self._tasks[task_id].update(copy.deepcopy(fields))

    def open_for(self, owner) -> list:
        return [copy.deepcopy(self._tasks[i]) for i in self._order
                if self._tasks[i]["owner"] == owner and self._tasks[i]["status"] not in TERMINAL]

    def all(self) -> list:
        return [copy.deepcopy(self._tasks[i]) for i in self._order]

    def cancel_owned_by(self, owner, tick: int, reason: str) -> list:
        """Cancel every open task whose owner is ``owner`` (used when the owner leaves the world). Returns the cancelled ids."""
        cancelled = []
        for task_id in self._order:
            record = self._tasks[task_id]
            if record["owner"] == owner and record["status"] not in TERMINAL:
                record.update(status=CANCELLED, reason=reason, closed_tick=int(tick))
                cancelled.append(task_id)
        return cancelled
