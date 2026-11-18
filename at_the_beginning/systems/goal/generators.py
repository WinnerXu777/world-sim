from __future__ import annotations

"""Goal generation from personality, memory, relationships, and pressures."""

from .lifecycle import clear_goal_review, ensure_goal_state, mark_goal_review_needed, prune_goals, primary_goal, upsert_goal


def _primary_target_from_events(resident: dict) -> str | None:
    for entry in reversed(list(resident.get("memory", {}).get("recent_events", []))):
        if str(entry.get("kind", "")) in {"attacked", "killed_by", "attack"} and entry.get("other_human_id"):
            return str(entry["other_human_id"])
    return None


def _relationship_targets(resident: dict, desired_tags: set[str]) -> list[str]:
    targets = []
    for other_id, relation in resident.get("relationships", {}).items():
        if any(str(tag) in desired_tags for tag in relation.get("tags", [])):
            targets.append(str(other_id))
    return targets


def initialize_starter_goals(resident: dict, tick: int) -> list[dict]:
    ensure_goal_state(resident, tick)
    if resident.get("goals"):
        return resident["goals"]

    traits = resident.get("personality", {}).get("traits", {})
    candidates = []

    if float(traits.get("greed", 0.0)) >= 0.62:
        candidates.append({"kind": "accumulate_wealth", "priority": float(traits["greed"]), "origin": "seed"})
    if float(traits.get("protectiveness", 0.0)) + float(traits.get("loyalty", 0.0)) >= 1.25:
        candidates.append({"kind": "protect_kin", "priority": 0.55 + float(traits["protectiveness"]) * 0.35, "origin": "seed"})
    if float(traits.get("curiosity", 0.0)) >= 0.64:
        candidates.append({"kind": "explore_region", "priority": 0.45 + float(traits["curiosity"]) * 0.4, "origin": "seed"})
    if float(traits.get("ambition", 0.0)) + float(traits.get("pride", 0.0)) >= 1.18:
        candidates.append({"kind": "gain_status", "priority": 0.48 + float(traits["ambition"]) * 0.36, "origin": "seed"})
    if float(traits.get("discipline", 0.0)) + float(traits.get("resourcefulness", 0.0)) >= 1.18:
        candidates.append({"kind": "hoard_food", "priority": 0.44 + float(traits["discipline"]) * 0.28, "origin": "seed"})
    if float(traits.get("caution", 0.0)) + float(traits.get("fearfulness", 0.0)) >= 1.2:
        candidates.append({"kind": "guard_home", "priority": 0.44 + float(traits["caution"]) * 0.3, "origin": "seed"})
    if float(traits.get("sociability", 0.0)) >= 0.72 and float(traits.get("ambition", 0.0)) >= 0.58:
        candidates.append({"kind": "seek_mate", "priority": 0.42 + float(traits["sociability"]) * 0.26, "origin": "seed"})

    if not candidates:
        fallback_kind = "explore_region" if float(traits.get("curiosity", 0.5)) >= float(traits.get("caution", 0.5)) else "guard_home"
        candidates.append({"kind": fallback_kind, "priority": 0.5, "origin": "seed"})

    for goal in sorted(candidates, key=lambda item: float(item["priority"]), reverse=True)[:2]:
        upsert_goal(resident, goal, tick)
    clear_goal_review(resident, tick, "seed")
    return resident.get("goals", [])


def apply_event_goal_updates(
    resident: dict,
    tick: int,
    event_kind: str,
    event_payload: dict | None = None,
) -> list[dict]:
    ensure_goal_state(resident, tick)
    event = dict(event_payload or {})
    traits = resident.get("personality", {}).get("traits", {})
    pressures = resident.get("pressures", {})
    updated = []

    if event_kind in {"attacked", "killed_by"}:
        target_id = str(event.get("other_human_id") or event.get("target_id") or "")
        if target_id:
            retaliation_bias = (
                float(traits.get("vengefulness", 0.5))
                + float(traits.get("aggression", 0.5))
                + float(traits.get("pride", 0.5))
            ) / 3.0
            avoidance_bias = (
                float(traits.get("caution", 0.5))
                + float(traits.get("fearfulness", 0.5))
                + float(pressures.get("fear_pressure", 0.0))
            ) / 3.0
            if retaliation_bias + 0.08 >= avoidance_bias:
                updated.append(
                    upsert_goal(
                        resident,
                        {
                            "kind": "retaliate",
                            "target_id": target_id,
                            "priority": max(0.55, float(pressures.get("vengeance_pressure", retaliation_bias))),
                            "origin": "event",
                            "plan_hint": "recover_then_counterattack",
                        },
                        tick,
                    )
                )
            else:
                updated.append(
                    upsert_goal(
                        resident,
                        {
                            "kind": "avoid_target",
                            "target_id": target_id,
                            "priority": max(0.55, float(pressures.get("fear_pressure", avoidance_bias))),
                            "origin": "event",
                            "plan_hint": "avoid_until_safe",
                        },
                        tick,
                    )
                )
            if float(traits.get("loyalty", 0.5)) + float(traits.get("sociability", 0.5)) >= 1.18:
                updated.append(
                    upsert_goal(
                        resident,
                        {
                            "kind": "recruit_allies",
                            "target_id": target_id,
                            "priority": 0.46 + float(pressures.get("loyalty_pressure", 0.0)) * 0.35,
                            "origin": "event",
                            "plan_hint": "seek nearby support",
                        },
                        tick,
                    )
                )
            mark_goal_review_needed(resident, tick, "attack_event")

    elif event_kind in {"child_birth", "born_to_parent"}:
        target_id = str(event.get("other_human_id") or event.get("target_id") or "")
        updated.append(
            upsert_goal(
                resident,
                {
                    "kind": "protect_kin",
                    "target_id": target_id or None,
                    "priority": 0.62 + float(traits.get("protectiveness", 0.5)) * 0.28,
                    "origin": "event",
                    "plan_hint": "keep kin safe",
                },
                tick,
            )
        )
        mark_goal_review_needed(resident, tick, "kin_event")

    elif event_kind in {"witnessed_death", "death"}:
        updated.append(
            upsert_goal(
                resident,
                {
                    "kind": "guard_home",
                    "priority": 0.42 + float(pressures.get("security_pressure", 0.0)) * 0.38,
                    "origin": "event",
                    "plan_hint": "stay near safety after loss",
                },
                tick,
            )
        )
        mark_goal_review_needed(resident, tick, "death_event")

    prune_goals(resident, tick)
    return updated


def run_periodic_goal_review(resident: dict, tick: int, reason: str = "periodic") -> list[dict]:
    ensure_goal_state(resident, tick)
    pressures = dict(resident.get("pressures", {}))
    traits = dict(resident.get("personality", {}).get("traits", {}))
    relationships = resident.get("relationships", {})

    candidates = []
    attacker_id = str(pressures.get("latest_attacker_id") or _primary_target_from_events(resident) or "")
    kin_targets = _relationship_targets(resident, {"parent", "child", "family", "mate"})

    if attacker_id and float(pressures.get("vengeance_pressure", 0.0)) >= 0.45:
        candidates.append(
            {
                "kind": "retaliate",
                "target_id": attacker_id,
                "priority": float(pressures["vengeance_pressure"]),
                "origin": reason,
                "plan_hint": "watch for a safer retaliation window",
            }
        )
    if attacker_id and float(pressures.get("fear_pressure", 0.0)) >= 0.48:
        candidates.append(
            {
                "kind": "avoid_target",
                "target_id": attacker_id,
                "priority": max(float(pressures["fear_pressure"]), 0.42),
                "origin": reason,
                "plan_hint": "keep distance until conditions improve",
            }
        )
    if kin_targets and float(pressures.get("loyalty_pressure", 0.0)) >= 0.45:
        candidates.append(
            {
                "kind": "protect_kin",
                "target_id": kin_targets[0],
                "priority": max(float(pressures["loyalty_pressure"]), 0.46),
                "origin": reason,
                "plan_hint": "prioritize family safety",
            }
        )
    if float(pressures.get("greed_pressure", 0.0)) >= 0.52:
        candidates.append({"kind": "accumulate_wealth", "priority": float(pressures["greed_pressure"]), "origin": reason})
    if float(pressures.get("greed_pressure", 0.0)) >= 0.66 and float(traits.get("deceitfulness", 0.0)) >= 0.55:
        candidates.append(
            {
                "kind": "steal_when_safe",
                "priority": max(0.45, float(pressures["greed_pressure"]) * 0.9),
                "origin": reason,
                "plan_hint": "look for low-risk theft windows",
            }
        )
    if float(pressures.get("status_pressure", 0.0)) >= 0.54:
        candidates.append({"kind": "gain_status", "priority": float(pressures["status_pressure"]), "origin": reason})
    if float(pressures.get("security_pressure", 0.0)) >= 0.55:
        candidates.append(
            {
                "kind": "guard_home",
                "priority": float(pressures["security_pressure"]),
                "origin": reason,
                "plan_hint": "stay closer to safety",
            }
        )
    if float(pressures.get("curiosity_pressure", 0.0)) >= 0.55:
        candidates.append({"kind": "explore_region", "priority": float(pressures["curiosity_pressure"]), "origin": reason})
    if float(pressures.get("resource_pressure", 0.0)) >= 0.58:
        candidates.append(
            {
                "kind": "hoard_food",
                "priority": float(pressures["resource_pressure"]),
                "origin": reason,
                "plan_hint": "build a reserve before scarcity gets worse",
            }
        )
    if attacker_id and float(pressures.get("loyalty_pressure", 0.0)) >= 0.55:
        candidates.append(
            {
                "kind": "recruit_allies",
                "target_id": attacker_id,
                "priority": max(0.4, float(pressures["loyalty_pressure"]) * 0.85),
                "origin": reason,
                "plan_hint": "seek help before acting",
            }
        )
    if "mate" not in {str(tag) for relation in relationships.values() for tag in relation.get("tags", [])} and (
        float(traits.get("sociability", 0.0)) >= 0.66 and float(traits.get("curiosity", 0.0)) >= 0.46
    ):
        candidates.append(
            {
                "kind": "seek_mate",
                "priority": 0.32 + float(traits["sociability"]) * 0.28 + float(traits["curiosity"]) * 0.14,
                "origin": reason,
            }
        )

    if not candidates:
        current = primary_goal(resident)
        if current is not None:
            candidates.append(
                {
                    "kind": str(current.get("kind", "explore_region")),
                    "target_id": current.get("target_id"),
                    "priority": max(0.3, float(current.get("priority", 0.4)) * 0.92),
                    "origin": reason,
                    "plan_hint": str(current.get("plan_hint", "")),
                }
            )
        else:
            candidates.append({"kind": "explore_region", "priority": 0.35, "origin": reason})

    for goal in resident.get("goals", []):
        if goal.get("kind") not in {candidate["kind"] for candidate in candidates}:
            goal["priority"] = round(float(goal.get("priority", 0.0)) * 0.92, 3)

    chosen = sorted(candidates, key=lambda item: float(item.get("priority", 0.0)), reverse=True)[:3]
    updated = [upsert_goal(resident, goal, tick) for goal in chosen]
    prune_goals(resident, tick)
    clear_goal_review(resident, tick, reason)
    return updated
