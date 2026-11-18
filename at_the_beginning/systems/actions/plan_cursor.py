"""Per-step scheduling of a Tier 3 plan: ``PlanCursors`` runs one step at a time and starts the next step only when the previous one is done.

``run_plan`` (plan_ops.py) sends every step through the runner in one go, which is right for instant steps but wrong when a step queues a legacy
task (rest, go to work, follow ...): the next step is judged before the task has done anything and can fail legality. A cursor instead:

* runs step ``i`` through ``ActionRunner.run`` (schema, grounding, legality, rate/risk, audit - exactly like any call);
* if the step queued a task (``task_id`` in the record-op result) it waits until that task has left the resident's queue, then reads how it
  ended (``task_state.last_completed_task``): ``completed`` -> next step, anything else -> abort ``task_<outcome>``;
* a ``set_routine`` step (roster residents) has no task to watch: it waits ``routine_wait_ticks`` (placeholder) and goes on;
* instant steps chain in the same ``advance`` (at most ``max_instant`` per call, so a long plan cannot hold a tick);
* aborts, with a stable reason, on: a step the runner refuses (``step_<i>:<code>``), a task that does not end within ``timeout_ticks``
  (``timeout``), a task that ends badly (``task_<outcome>``), a changed epoch (``stale_epoch``: world reset or model switch toggled),
  a new plan for the same resident (``superseded``), or ``cancel``.

Pure bookkeeping on top of the runner; it never touches the engine. Event dicts are returned from ``advance`` for the caller to log/count.
"""
from __future__ import annotations

from typing import Optional


class PlanCursors:
    def __init__(self, runner, *, timeout_ticks: int = 400, routine_wait_ticks: int = 60, max_instant: int = 8):
        self.runner = runner
        self.timeout_ticks, self.routine_wait_ticks, self.max_instant = int(timeout_ticks), int(routine_wait_ticks), int(max_instant)
        self.cursors: dict = {}
        self.events: list = []

    # -- api -----------------------------------------------------------------------------------------------------------------------
    def start(self, actor: str, steps, *, confidence: Optional[float], tick: int, epoch: str, plan_id: str = "") -> dict:
        events = []
        if actor in self.cursors:
            events.append(self._end(actor, "aborted", "superseded", tick))
        self.cursors[actor] = {"actor": actor, "steps": [dict(s) for s in steps], "confidence": confidence, "epoch": str(epoch), "index": 0,
                               "completed": 0, "wait": None, "started": int(tick), "plan_id": plan_id}
        return {"actor": actor, "status": "started", "reason": "", "steps": len(steps), "tick": int(tick), "superseded": bool(events)}

    def cancel(self, actor: str, reason: str = "cancelled", tick: int = 0) -> Optional[dict]:
        return self._end(actor, "aborted", reason, tick) if actor in self.cursors else None

    def active(self) -> list:
        return sorted(self.cursors)

    def advance(self, tick: int, epoch: str) -> list:
        """Move every cursor as far as it can go this tick; returns the events (``done`` / ``aborted``) of the cursors that ended."""
        out = []
        for actor in list(self.cursors):
            event = self._advance_one(self.cursors[actor], int(tick), str(epoch))
            if event is not None:
                out.append(event)
        del self.events[:-200]
        return out

    # -- internals -----------------------------------------------------------------------------------------------------------------
    def _advance_one(self, c: dict, tick: int, epoch: str) -> Optional[dict]:
        actor = c["actor"]
        if epoch != c["epoch"]:
            return self._end(actor, "aborted", "stale_epoch", tick)
        for _ in range(self.max_instant + 1):
            wait = c["wait"]
            if wait is not None:
                if wait["kind"] == "routine":
                    if tick < wait["until"]:
                        return None
                else:
                    status = self.task_status(actor, wait["id"])
                    if status == "running":
                        return self._end(actor, "aborted", "timeout", tick) if tick - wait["since"] > self.timeout_ticks else None
                    if status not in ("completed", "gone"):         # gone = left the queue without a record we can read: the next step is judged by the runner anyway
                        return self._end(actor, "aborted", f"task_{status}", tick)
                c["wait"] = None
            if c["index"] >= len(c["steps"]):
                return self._end(actor, "done", "", tick)
            step = c["steps"][c["index"]]
            result = self.runner.run(actor, step.get("op", ""), step.get("args"), proposer="tier3", confidence=c["confidence"])
            if not result.ok:
                return self._end(actor, "aborted", f"step_{c['index']}:{result.code}", tick)
            c["index"] += 1
            c["completed"] += 1
            c["wait"] = self._wait_for(result, tick)
            if c["wait"] is not None:
                return None                       # judge the wait on the next advance (a task needs at least one engine tick)
        return None                               # max_instant reached: continue next tick

    def _wait_for(self, result, tick: int) -> Optional[dict]:
        task_id = ""
        routine = False
        for op in result.ops:
            if op.get("kind") == "queue_task" and op.get("ok") and op.get("task_id"):
                task_id = str(op["task_id"])                       # the last queued task is the one that ends the step
            elif op.get("kind") == "set_routine" and op.get("ok"):
                routine = True
        if task_id:
            return {"kind": "task", "id": task_id, "since": tick}
        if routine:
            return {"kind": "routine", "until": tick + self.routine_wait_ticks}
        return None

    def task_status(self, actor: str, task_id: str) -> str:
        """``running`` (still queued / active / paused), ``completed`` or the other outcome the task ended with, ``gone`` (left the queue unseen)."""
        record = self.runner.services.record(actor) or {}
        if any(str(t.get("id", "")) == task_id for t in record.get("tasks", []) or []):
            return "running"
        last = (record.get("task_state") or {}).get("last_completed_task") or {}
        if str(last.get("id", "")) == task_id:
            return str(last.get("status") or "completed")
        return "gone"

    def _end(self, actor: str, status: str, reason: str, tick: int) -> dict:
        c = self.cursors.pop(actor)
        event = {"actor": actor, "status": status, "reason": reason, "tick": int(tick), "steps": len(c["steps"]), "completed": c["completed"],
                 "failed_at": c["index"] if status == "aborted" and reason.startswith("step_") else None}
        self.events.append(event)
        return event

    def status(self) -> dict:
        return {"active": {a: {"index": c["index"], "of": len(c["steps"]), "waiting": c["wait"]} for a, c in self.cursors.items()},
                "recent": self.events[-5:]}
