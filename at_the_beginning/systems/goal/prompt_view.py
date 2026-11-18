from __future__ import annotations

"""Prompt-facing goal summaries."""


def build_goal_prompt_payload(resident: dict, *, limit: int = 3) -> list[dict]:
    goals = sorted(
        list(resident.get("goals", [])),
        key=lambda goal: float(goal.get("priority", 0.0)),
        reverse=True,
    )[: max(limit, 0)]
    payload = []
    for goal in goals:
        payload.append(
            {
                "id": str(goal.get("id", "")),
                "kind": str(goal.get("kind", "")),
                "priority": round(float(goal.get("priority", 0.0)), 3),
                "target_id": goal.get("target_id"),
                "horizon": str(goal.get("horizon", "")),
                "plan_hint": str(goal.get("plan_hint", "")),
            }
        )
    return payload


def summarize_goals(resident: dict, *, limit: int = 2) -> str:
    payload = build_goal_prompt_payload(resident, limit=limit)
    if not payload:
        return "no active goals"
    parts = []
    for goal in payload:
        target = f"->{goal['target_id']}" if goal.get("target_id") else ""
        parts.append(f"{goal['kind']}{target} ({goal['priority']:.2f})")
    return "; ".join(parts)
