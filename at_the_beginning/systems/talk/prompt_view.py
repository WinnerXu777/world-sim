from __future__ import annotations

"""Prompt shaping helpers for tiny-model talk modes."""

from typing import Any


def summarize_personality(personality: dict[str, Any] | None) -> str:
    personality = dict(personality or {})
    archetype = str(personality.get("archetype", "")).strip()
    traits = dict(personality.get("traits", {}))
    if not traits:
        return archetype or "unknown"
    ranked = sorted(traits.items(), key=lambda item: abs(float(item[1])), reverse=True)[:3]
    trait_summary = ", ".join("%s=%0.2f" % (str(name), float(value)) for name, value in ranked)
    return "%s (%s)" % (archetype, trait_summary) if archetype else trait_summary


def summarize_relationship(relationship: dict[str, Any] | None) -> str:
    relationship = dict(relationship or {})
    if not relationship:
        return "unknown"
    tags = relationship.get("tags", [])
    if tags:
        return ", ".join(str(tag) for tag in list(tags)[:3])
    return str(relationship.get("status", "unknown"))


def summarize_memories(memories: list[dict[str, Any]] | None, *, limit: int = 3) -> list[str]:
    summary: list[str] = []
    for memory in list(memories or [])[: max(0, int(limit))]:
        if not isinstance(memory, dict):
            continue
        kind = str(memory.get("kind", memory.get("event_type", "memory")))
        note = str(memory.get("summary", memory.get("note", ""))).strip()
        summary.append("%s: %s" % (kind, note) if note else kind)
    return summary


def build_talk_prompt_case(
    event: dict[str, Any],
    *,
    speaker_summary: dict[str, Any] | None = None,
    listener_summary: dict[str, Any] | None = None,
    relationship_summary: dict[str, Any] | None = None,
    recent_memories: list[dict[str, Any]] | None = None,
    local_context: dict[str, Any] | None = None,
    allowed_physical_intents: list[str] | None = None,
) -> dict[str, Any]:
    event = dict(event or {})
    return {
        "mode": str(event.get("mode", "")),
        "utterance": str(event.get("utterance", "")),
        "speech_act_hint": str(event.get("speech_act_hint", "")),
        "tone_hint": str(event.get("tone_hint", "")),
        "speaker": dict(speaker_summary or {}),
        "listener": dict(listener_summary or {}),
        "personality_summary": summarize_personality((listener_summary or {}).get("personality")),
        "relationship_summary": summarize_relationship(relationship_summary),
        "recent_memories": summarize_memories(recent_memories),
        "local_context": dict(local_context or {}),
        "allowed_physical_intents": [str(intent) for intent in list(allowed_physical_intents or []) if str(intent)],
    }


def build_npc_bark_prompt_case(
    semantic_frame: dict[str, Any],
    *,
    speaker_summary: dict[str, Any] | None = None,
    listener_summary: dict[str, Any] | None = None,
    local_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    semantic_frame = dict(semantic_frame or {})
    return {
        "mode": "ambient_npc_talk",
        "speaker_id": semantic_frame.get("speaker_id"),
        "listener_id": semantic_frame.get("listener_id"),
        "speech_act": str(semantic_frame.get("speech_act", "")),
        "topic": str(semantic_frame.get("topic", "")),
        "tone": str(semantic_frame.get("tone", "")),
        "urgency": str(semantic_frame.get("urgency", "")),
        "speaker_personality_summary": summarize_personality((speaker_summary or {}).get("personality")),
        "listener_relationship_summary": summarize_relationship((listener_summary or {}).get("relationship")),
        "local_context": dict(local_context or {}),
    }
