from __future__ import annotations

"""High-level helpers for creating and shaping talk cases."""

from typing import Any

from .bark_templates import choose_fallback_bark
from .effects import build_talk_effect_bundle, build_tts_request, should_enqueue_tts
from .routing import build_talk_ticket, derive_followup_tickets
from .schema import (
    HEARD_LOCAL_ONLY,
    HEARD_NEARBY,
    MODE_AMBIENT_NPC_TALK,
    MODE_AMBIENT_TALK,
    MODE_DIRECT_TALK,
    build_pressure_deltas,
    build_talk_event,
    build_talk_result,
)


def create_direct_talk_event(
    event_id: str,
    *,
    tick: int,
    speaker_id: str,
    listener_id: str,
    utterance: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_talk_event(
        event_id,
        MODE_DIRECT_TALK,
        tick=tick,
        speaker_id=speaker_id,
        listener_id=listener_id,
        utterance=utterance,
        metadata=metadata,
    )


def create_ambient_talk_event(
    event_id: str,
    *,
    tick: int,
    speaker_id: str,
    utterance: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return build_talk_event(
        event_id,
        MODE_AMBIENT_TALK,
        tick=tick,
        speaker_id=speaker_id,
        utterance=utterance,
        metadata=metadata,
    )


def create_npc_chatter_frame(
    speaker_id: str,
    listener_id: str,
    *,
    speech_act: str,
    topic: str = "",
    tone: str = "",
    urgency: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "mode": MODE_AMBIENT_NPC_TALK,
        "speaker_id": str(speaker_id),
        "listener_id": str(listener_id),
        "speech_act": str(speech_act or ""),
        "topic": str(topic or ""),
        "tone": str(tone or ""),
        "urgency": str(urgency or ""),
        "metadata": dict(metadata or {}),
    }


def create_fallback_bark_result(
    semantic_frame: dict[str, Any],
    *,
    seed_hint: int = 0,
) -> dict[str, Any]:
    semantic_frame = dict(semantic_frame or {})
    speech_act = str(semantic_frame.get("speech_act", ""))
    return build_talk_result(
        mode=MODE_AMBIENT_NPC_TALK,
        speaker_id=semantic_frame.get("speaker_id"),
        listener_id=semantic_frame.get("listener_id"),
        speech_text=choose_fallback_bark(speech_act, seed_hint=seed_hint),
        speech_act=speech_act,
        topic=str(semantic_frame.get("topic", "")),
        tone=str(semantic_frame.get("tone", "")),
        physical_intent="",
        witness_policy=HEARD_LOCAL_ONLY,
        relationship_delta="neutral",
        pressure_deltas=build_pressure_deltas(),
        memory_salience=0.15,
        metadata=dict(semantic_frame.get("metadata", {})),
    )


def package_talk_runtime_output(
    result: dict[str, Any],
    *,
    tick: int,
    speaker_id: str,
    distance_to_player: float,
    voice_profile: str = "",
) -> dict[str, Any]:
    result = dict(result or {})
    effect_bundle = build_talk_effect_bundle(result, speaker_id=speaker_id)
    followups = derive_followup_tickets(result, tick=tick)
    tts_payload = None
    if should_enqueue_tts(result, distance_to_player=distance_to_player):
        tts_payload = build_tts_request(
            result,
            speaker_id=speaker_id,
            distance_to_player=distance_to_player,
            voice_profile=voice_profile,
            expires_tick=int(tick) + 120,
        )
    return {
        "effect_bundle": effect_bundle,
        "followup_tickets": followups,
        "tts_payload": tts_payload,
    }


def talk_ticket_for_event(event: dict[str, Any], *, tick: int, direct_click: bool = False, listener_count: int = 0) -> dict[str, Any]:
    return build_talk_ticket(event, tick=tick, direct_click=direct_click, listener_count=listener_count)


def default_threat_response(
    *,
    target_id: str,
    speaker_id: str | None = None,
) -> dict[str, Any]:
    return build_talk_result(
        mode=MODE_DIRECT_TALK,
        target_id=str(target_id),
        speaker_id=speaker_id,
        speech_text="Stay away from me!",
        speech_act="threat_response",
        tone="fearful_angry",
        physical_intent="flee",
        danger_upgrade=True,
        reasoning_followup=True,
        witness_policy=HEARD_NEARBY,
        relationship_delta="hostile",
        pressure_deltas=build_pressure_deltas(fear=0.72, hostility=0.44),
        memory_salience=0.89,
    )
