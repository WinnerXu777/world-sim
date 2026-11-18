from __future__ import annotations

"""Execution-facing helpers for resident plans.

This module intentionally stays conservative for now. It provides a stable
place for future runtime plan execution without yet mutating the simulation.
"""

from typing import Any

from .compiler import compile_plan


def tick_resident_plans(resident: dict[str, Any], tick: int) -> dict[str, Any]:
    plans = list(resident.get("plans", []))
    active = next((plan for plan in plans if str(plan.get("status", "queued")) in {"active", "queued"}), None)
    if active is None:
        return {"active_plan": None, "advanced": False}
    active["last_update_tick"] = int(tick)
    if str(active.get("status", "queued")) == "queued":
        active["status"] = "active"
    return {"active_plan": active, "advanced": False}


def compile_active_plan(resident: dict[str, Any]) -> dict[str, Any]:
    active = next(
        (plan for plan in resident.get("plans", []) if str(plan.get("status", "queued")) in {"active", "queued"}),
        None,
    )
    if active is None:
        return {"ok": False, "errors": ["no_active_plan"], "compiled_steps": []}
    return compile_plan(active)


def execute_compiled_plan_step(
    engine: Any,
    resident: dict[str, Any],
    compiled_step: dict[str, Any],
) -> dict[str, Any]:
    _ = engine, resident
    return {
        "ok": False,
        "executed": False,
        "reason": f"plan_op_not_wired:{compiled_step.get('op', '')}",
    }
