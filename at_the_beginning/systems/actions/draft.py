"""What an Action returns: pure data, nothing applied. The runner applies ``effects`` + ``event`` atomically through the harness, then runs ``ops``."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from harness import effects as fx


class ActionRefused(Exception):
    """Raised inside an Action function for a refusal with a stable reason code (the legality predicate normally catches these first)."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason, self.detail = reason, detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


@dataclass(frozen=True)
class RecordOp:
    """A change to resident records or a legacy system that is not a tensor/item effect (task queue, schedule routine, relationship, order).

    Kinds (executed by ``recordops``): ``queue_task``, ``set_routine``, ``site_trip``, ``relationship``, ``commission_request``, ``request_response``, ``trade_offer``, ``trade_close``, ``memory_note``.
    """
    kind: str
    args: dict = field(default_factory=dict)


@dataclass
class ActionDraft:
    effects: list = field(default_factory=list)          # harness Effects (Delta, Set, Transfer, ...)
    event: Optional[fx.Emit] = None
    ops: list = field(default_factory=list)              # RecordOps, run after a successful apply, in order
    preview: dict = field(default_factory=dict)
    consumes: tuple = ()                                 # ((item, qty), ...) this action destroys: the only src=None-free Transfers allowed
    produces: tuple = ()                                 # ((item, qty), ...) this action creates


def queue_task(task_kind: str, **kwargs) -> RecordOp:
    """``systems.tasks.ops.queue_resident_task`` arguments (priority, summary, target_kind, target_id, target_place, required_item, requested_quantity, metadata)."""
    return RecordOp("queue_task", {"task_kind": task_kind, **kwargs})


def set_routine(kind: str, reason: str = "action") -> RecordOp:
    """The schedule-routine route: the roster driver walks a roster resident to the anchor that routine kind maps to."""
    return RecordOp("set_routine", {"kind": kind, "reason": reason})


def site_trip(kind: str, reason: str = "action") -> RecordOp:
    """Start the resident's food or water trip now (``kind``: ``food`` / ``water``): the same walk-stand-reset the needs loop starts at the threshold."""
    return RecordOp("site_trip", {"kind": kind, "reason": reason})


def roster_driven(ctx, why: str) -> None:
    """Refuse a verb whose executor is a task that needs the resident's own movement or a worksite: a roster resident is walked by the
    anchor driver and task movement is suppressed for it, so the queued task would stay active forever and block the queue
    (measured: 1008_actions.md section 10.5). The affordance mask still lists the verb; D-008 decides whether that changes."""
    if ctx.is_roster:
        raise ActionRefused("roster_driven", why)
