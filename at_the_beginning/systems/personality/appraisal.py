from __future__ import annotations

"""Deterministic appraisal and pressure updates derived from resident state."""

from typing import Any

from .assign import get_personality_traits
from .traits import clamp_trait


def _count_recent_events(memory: dict[str, Any], *kinds: str) -> int:
    event_kinds = {str(kind) for kind in kinds}
    return sum(1 for entry in memory.get("recent_events", []) if str(entry.get("kind", "")) in event_kinds)


def _latest_event_target(memory: dict[str, Any], *kinds: str) -> str | None:
    event_kinds = {str(kind) for kind in kinds}
    for entry in reversed(list(memory.get("recent_events", []))):
        if str(entry.get("kind", "")) in event_kinds and entry.get("other_human_id"):
            return str(entry["other_human_id"])
    return None


def _relationship_tag_count(relationships: dict[str, Any], tags: set[str]) -> int:
    count = 0
    for relation in relationships.values():
        if any(str(tag) in tags for tag in relation.get("tags", [])):
            count += 1
    return count


def compute_pressures(resident: dict[str, Any], tick: int | None = None) -> dict[str, float]:
    del tick
    snapshot = resident.get("snapshot", {})
    memory = resident.get("memory", {})
    relationships = resident.get("relationships", {})
    traits = get_personality_traits(resident.get("personality"))

    hp = max(0.0, min(100.0, float(snapshot.get("hp", 100.0))))
    hunger = max(0.0, min(100.0, float(snapshot.get("hunger", 0.0)))) / 100.0
    thirst = max(0.0, min(100.0, float(snapshot.get("thirst", 0.0)))) / 100.0
    threat = max(0.0, min(100.0, float(snapshot.get("threat", 0.0)))) / 100.0
    mood = max(0.0, min(100.0, float(snapshot.get("mood", 50.0))))
    stamina = max(0.0, min(100.0, float(snapshot.get("stamina", 100.0))))
    critical_health = clamp_trait(float(snapshot.get("critical_health", 1.0 if hp <= 15.0 else 0.0)))

    low_hp = clamp_trait((100.0 - hp) / 100.0)
    low_mood = clamp_trait((100.0 - mood) / 100.0)
    low_stamina = clamp_trait((100.0 - stamina) / 100.0)

    recent_attack = clamp_trait(_count_recent_events(memory, "attacked", "killed_by") / 3.0)
    recent_hunt = clamp_trait(_count_recent_events(memory, "hunt_attack", "hunt_kill") / 3.0)
    witnessed_death = clamp_trait(_count_recent_events(memory, "witnessed_death", "death") / 3.0)
    scarcity = 1.0 - clamp_trait(
        (len(memory.get("known_food_sources", [])) + len(memory.get("known_water_sources", []))) / 6.0
    )
    kin_count = clamp_trait(
        _relationship_tag_count(relationships, {"parent", "child", "family", "mate"}) / 4.0
    )
    rival_count = clamp_trait(_relationship_tag_count(relationships, {"rival"}) / 3.0)
    friend_count = clamp_trait(_relationship_tag_count(relationships, {"friend", "tribe_mate", "mate"}) / 4.0)

    fear_pressure = clamp_trait(
        0.32 * threat
        + 0.2 * low_hp
        + 0.15 * low_stamina
        + 0.12 * float(traits["fearfulness"])
        + 0.11 * recent_attack
        + 0.1 * witnessed_death
    )
    vengeance_pressure = clamp_trait(
        0.34 * recent_attack
        + 0.22 * float(traits["vengefulness"])
        + 0.14 * float(traits["aggression"])
        + 0.12 * float(traits["pride"])
        + 0.08 * rival_count
        - 0.1 * float(traits["mercy"])
    )
    greed_pressure = clamp_trait(
        0.45 * float(traits["greed"])
        + 0.18 * float(traits["ambition"])
        + 0.14 * scarcity
        + 0.12 * low_mood
        + 0.11 * float(traits["resourcefulness"])
    )
    loyalty_pressure = clamp_trait(
        0.34 * float(traits["loyalty"])
        + 0.24 * float(traits["protectiveness"])
        + 0.12 * float(traits["sociability"])
        + 0.16 * kin_count
        + 0.08 * friend_count
    )
    security_pressure = clamp_trait(
        0.3 * float(traits["caution"])
        + 0.2 * float(traits["fearfulness"])
        + 0.2 * threat
        + 0.18 * low_hp
        + 0.12 * low_stamina
    )
    status_pressure = clamp_trait(
        0.36 * float(traits["ambition"])
        + 0.26 * float(traits["pride"])
        + 0.12 * float(traits["sociability"])
        + 0.1 * float(traits["aggression"])
        + 0.08 * friend_count
        + 0.08 * rival_count
    )
    curiosity_pressure = clamp_trait(
        0.46 * float(traits["curiosity"])
        + 0.16 * float(traits["resourcefulness"])
        + 0.14 * (1.0 - security_pressure)
        + 0.12 * clamp_trait(mood / 100.0)
        + 0.12 * (1.0 - scarcity)
    )
    resource_pressure = clamp_trait(
        0.32 * max(hunger, thirst)
        + 0.2 * scarcity
        + 0.16 * float(traits["resourcefulness"])
        + 0.16 * float(traits["discipline"])
        + 0.08 * recent_hunt
        + 0.08 * low_hp
    )

    pressures: dict[str, float] = {
        "fear_pressure": fear_pressure,
        "vengeance_pressure": vengeance_pressure,
        "greed_pressure": greed_pressure,
        "loyalty_pressure": loyalty_pressure,
        "security_pressure": security_pressure,
        "status_pressure": status_pressure,
        "curiosity_pressure": curiosity_pressure,
        "resource_pressure": resource_pressure,
    }
    latest_attacker = _latest_event_target(memory, "attacked", "killed_by")
    if latest_attacker:
        pressures["latest_attacker_id"] = latest_attacker
    return pressures
