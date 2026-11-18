from __future__ import annotations

"""Helpers for building decision-facing memory retrieval bundles."""

from typing import Any


def build_memory_query_from_case(case: dict[str, Any]) -> str:
    resident = case.get("resident", {})
    profile = resident.get("profile", {})
    personality = resident.get("personality", {})
    snapshot = resident.get("snapshot", {})
    status = resident.get("status", {})
    goals = list(resident.get("goals", []))
    primary_goal = goals[0] if goals else {}
    parts = [
        str(profile.get("name", case.get("human_id", "resident"))),
        str(personality.get("archetype", profile.get("personality", {}).get("archetype", "balanced_survivor"))),
        f"intent {status.get('current_intent', 'observe')}",
        f"reason {status.get('last_reason', '')}",
        f"threat {round(float(snapshot.get('threat', 0.0)), 2)}",
        f"hunger {round(float(snapshot.get('hunger', 0.0)), 2)}",
        f"thirst {round(float(snapshot.get('thirst', 0.0)), 2)}",
        f"mood {round(float(snapshot.get('mood', 0.0)), 2)}",
    ]
    if primary_goal:
        goal_target = f" target {primary_goal.get('target_id')}" if primary_goal.get("target_id") else ""
        parts.append(f"goal {primary_goal.get('kind', '')}{goal_target}")
    if case.get("distress") is not None:
        parts.append(f"distress {round(float(case['distress']), 2)}")
    nearby = case.get("nearby", {})
    if nearby:
        for key in ("food", "water", "predator", "hazard"):
            value = nearby.get(key)
            if value:
                parts.append(f"{key} {value}")
    return " ; ".join(part for part in parts if part and part != "reason ")


def build_human_memory_bundle(
    memory_rag,
    resident_store,
    human_id: str,
    *,
    query: str | None = None,
    case: dict[str, Any] | None = None,
    top_k_per_query: int = 6,
    traversal_depth: int = 2,
) -> dict[str, Any]:
    resident = resident_store.get(human_id)
    derived_query = query
    if not derived_query and case is not None:
        derived_query = build_memory_query_from_case(case)
    if not derived_query:
        resident_name = str(resident.get("profile", {}).get("name", human_id)) if resident else human_id
        derived_query = f"{resident_name} relationships threats resources recent decisions"
    rag_bundle = memory_rag.retrieve_bundle(
        derived_query,
        resident_id=human_id,
        top_k_per_query=top_k_per_query,
        traversal_depth=traversal_depth,
    )
    return {
        "human_id": human_id,
        "resident": resident,
        "query": derived_query,
        "memory_graph": rag_bundle,
    }


__all__ = [
    "build_human_memory_bundle",
    "build_memory_query_from_case",
]
