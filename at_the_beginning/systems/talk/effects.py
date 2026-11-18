from __future__ import annotations

"""Pure helpers for converting talk outputs into runtime-side effects."""

from typing import Any

from .schema import AMBIENT_NPC_VOICE, AMBIENT_TALK_VOICE, DIRECT_TALK_VOICE, build_tts_payload


def merge_pressure_deltas(base: dict[str, float] | None, extra: dict[str, float] | None) -> dict[str, float]:
    merged: dict[str, float] = {}
    for source in [dict(base or {}), dict(extra or {})]:
        for key, value in source.items():
            merged[str(key)] = round(float(merged.get(str(key), 0.0)) + float(value), 3)
    return {key: value for key, value in merged.items() if abs(value) > 1e-6}


def derive_tts_priority(result: dict[str, Any]) -> str:
    result = dict(result or {})
    mode = str(result.get("mode", "")).strip().lower()
    if mode == "direct_talk":
        return DIRECT_TALK_VOICE
    if mode == "ambient_talk":
        return AMBIENT_TALK_VOICE
    return AMBIENT_NPC_VOICE


def should_enqueue_tts(
    result: dict[str, Any],
    *,
    distance_to_player: float,
    direct_talk_max_distance: float = 16.0,
    ambient_talk_max_distance: float = 18.0,
    ambient_npc_max_distance: float = 12.0,
) -> bool:
    priority = derive_tts_priority(result)
    distance = max(0.0, float(distance_to_player))
    if priority == DIRECT_TALK_VOICE:
        return distance <= float(direct_talk_max_distance)
    if priority == AMBIENT_TALK_VOICE:
        return distance <= float(ambient_talk_max_distance)
    return distance <= float(ambient_npc_max_distance)


def build_tts_request(
    result: dict[str, Any],
    *,
    speaker_id: str,
    distance_to_player: float,
    voice_profile: str = "",
    expires_tick: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = dict(result or {})
    return build_tts_payload(
        speaker_id=speaker_id,
        speech_text=str(result.get("speech_text", "")),
        tts_priority=derive_tts_priority(result),
        distance_to_player=float(distance_to_player),
        memory_salience=float(result.get("memory_salience", 0.0)),
        voice_profile=voice_profile,
        expires_tick=expires_tick,
        metadata=metadata,
    )


def build_talk_effect_bundle(
    result: dict[str, Any],
    *,
    speaker_id: str | None = None,
    target_id: str | None = None,
) -> dict[str, Any]:
    result = dict(result or {})
    return {
        "speaker_id": speaker_id or result.get("speaker_id"),
        "target_id": target_id or result.get("target_id") or result.get("listener_id") or result.get("primary_listener_id"),
        "speech_text": str(result.get("speech_text", "")),
        "speech_act": str(result.get("speech_act", "")),
        "tone": str(result.get("tone", "")),
        "physical_intent": str(result.get("physical_intent", "")),
        "pressure_deltas": dict(result.get("pressure_deltas", {})),
        "relationship_delta": str(result.get("relationship_delta", "")),
        "danger_upgrade": bool(result.get("danger_upgrade")),
        "reasoning_followup": bool(result.get("reasoning_followup")),
        "memory_salience": float(result.get("memory_salience", 0.0)),
    }
