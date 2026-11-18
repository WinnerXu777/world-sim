from __future__ import annotations

"""Compile validated plans into approved runtime-friendly structures."""

from typing import Any

from .validator import validate_plan


def compile_plan(plan: dict[str, Any]) -> dict[str, Any]:
    errors = validate_plan(plan)
    if errors:
        return {
            "ok": False,
            "errors": errors,
            "compiled_steps": [],
        }

    compiled_steps: list[dict[str, Any]] = []
    for index, raw_step in enumerate(list(plan.get("steps", []))):
        step = dict(raw_step)
        compiled_steps.append(
            {
                "index": index,
                "op": str(step.get("op", "")),
                "target_id": step.get("target_id"),
                "place_hint": str(step.get("place_hint", "")),
                "threshold": step.get("threshold"),
                "target_tick": step.get("target_tick"),
                "count": step.get("count"),
                "metadata": dict(step.get("metadata", {})),
            }
        )

    return {
        "ok": True,
        "errors": [],
        "plan_kind": str(plan.get("plan_kind", "")),
        "goal_id": plan.get("goal_id"),
        "compiled_steps": compiled_steps,
    }


def compile_plan_bundle(plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [compile_plan(plan) for plan in list(plans)]
