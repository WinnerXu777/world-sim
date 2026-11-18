from __future__ import annotations

"""Prompt-facing plan summaries and catalog payloads."""

from .catalog import PLAN_KIND_DEFS, PLAN_OP_DEFS


def build_plan_prompt_payload(resident: dict, *, limit: int = 2) -> list[dict]:
    plans = sorted(
        list(resident.get("plans", [])),
        key=lambda plan: float(plan.get("priority", 0.0)),
        reverse=True,
    )[: max(limit, 0)]
    payload = []
    for plan in plans:
        payload.append(
            {
                "id": str(plan.get("id", "")),
                "goal_id": plan.get("goal_id"),
                "plan_kind": str(plan.get("plan_kind", "")),
                "priority": round(float(plan.get("priority", 0.0)), 3),
                "status": str(plan.get("status", "")),
                "summary": str(plan.get("summary", "")),
                "step_count": len(list(plan.get("steps", []))),
            }
        )
    return payload


def summarize_plans(resident: dict, *, limit: int = 2) -> str:
    payload = build_plan_prompt_payload(resident, limit=limit)
    if not payload:
        return "no active plans"
    parts = []
    for plan in payload:
        parts.append(f"{plan['plan_kind']} ({plan['priority']:.2f}, {plan['step_count']} steps)")
    return "; ".join(parts)


def build_plan_catalog_payload() -> dict[str, list[dict[str, object]]]:
    return {
        "plan_kinds": [
            {
                "kind": kind,
                "label": str(defn.get("label", kind)),
                "horizon": str(defn.get("horizon", "")),
            }
            for kind, defn in sorted(PLAN_KIND_DEFS.items())
        ],
        "plan_ops": [
            {
                "op": op,
                "label": str(defn.get("label", op)),
                "requires": list(defn.get("requires", [])),
            }
            for op, defn in sorted(PLAN_OP_DEFS.items())
        ],
    }
