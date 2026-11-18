from __future__ import annotations

"""Master task dispatcher for family-based task execution."""

from .contracts import TaskExecutionContext
from .families import combat, construction, occupation, social, strategic, survival


TASK_FAMILY_MODULES = (
    occupation,
    construction,
    survival,
    social,
    combat,
    strategic,
)


def dispatch_family(context: TaskExecutionContext):
    task_kind = str(context.task_kind).strip()
    if not task_kind:
        return None
    for family in TASK_FAMILY_MODULES:
        can_handle = getattr(family, "can_handle_task", None)
        if callable(can_handle) and can_handle(task_kind):
            return family
    return None


def execute_active_task_step(context: TaskExecutionContext) -> bool:
    family = dispatch_family(context)
    if family is None:
        return False
    execute = getattr(family, "execute_task_step", None)
    if not callable(execute):
        return False
    return bool(execute(context))


__all__ = [
    "TASK_FAMILY_MODULES",
    "dispatch_family",
    "execute_active_task_step",
]
