from __future__ import annotations

"""Validation helpers for reasoning-lane plans."""

from typing import Any

from .catalog import PLAN_KIND_DEFS, PLAN_OP_DEFS


def validate_plan_step(step: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    op = str(step.get("op", "")).strip()
    if not op:
        return ["missing_step_op"]
    op_def = PLAN_OP_DEFS.get(op)
    if op_def is None:
        return [f"unknown_step_op:{op}"]
    for field_name in list(op_def.get("requires", [])):
        value = step.get(field_name)
        if value is None or value == "" or value == []:
            errors.append(f"missing_step_field:{op}:{field_name}")
    return errors


def validate_plan(plan: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    plan_kind = str(plan.get("plan_kind", "")).strip()
    if not plan_kind:
        errors.append("missing_plan_kind")
    elif plan_kind not in PLAN_KIND_DEFS:
        errors.append(f"unknown_plan_kind:{plan_kind}")

    steps = list(plan.get("steps", []))
    if not steps:
        errors.append("missing_plan_steps")
    for step in steps:
        errors.extend(validate_plan_step(dict(step)))
    return errors


def plan_is_valid(plan: dict[str, Any]) -> bool:
    return not validate_plan(plan)
