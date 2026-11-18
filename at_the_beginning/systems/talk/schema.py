from __future__ import annotations

"""Structured record builders for local spoken dialogue."""

from typing import Any


TALK_SCHEMA_VERSION = 1

MODE_DIRECT_TALK = "direct_talk"
MODE_AMBIENT_TALK = "ambient_talk"
MODE_AMBIENT_NPC_TALK = "ambient_npc_talk"

DIRECT_TALK_VOICE = "direct_talk_voice"
AMBIENT_TALK_VOICE = "ambient_talk_voice"
AMBIENT_NPC_VOICE = "ambient_npc_voice"

HEARD_NONE = "none"
HEARD_NEARBY = "nearby_hear"
HEARD_CROWD = "crowd_hears"
HEARD_LOCAL_ONLY = "audible_local_only"

DEFAULT_DIRECT_HEARING_RADIUS = 14.0
DEFAULT_AMBIENT_HEARING_RADIUS = 24.0
DEFAULT_NPC_CHAT_HEARING_RADIUS = 18.0

SHORT_REPLY_MAX_WORDS = 20
NPC_BARK_MAX_WORDS = 12


def clamp_unit(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 3)


def build_pressure_deltas(
    *,
    fear: float = 0.0,
    hostility: float = 0.0,
    trust: float = 0.0,
    loyalty: float = 0.0,
    courage: float = 0.0,
) -> dict[str, float]:
    deltas = {
        "fear": round(float(fear), 3),
        "hostility": round(float(hostility), 3),
        "trust": round(float(trust), 3),
        "loyalty": round(float(loyalty), 3),
        "courage": round(float(courage), 3),
    }
    return {key: value for key, value in deltas.items() if abs(value) > 1e-6}


def build_talk_event(
    event_id: str,
    mode: str,
    *,
    tick: int,
    speaker_id: str,
    utterance: str,
    listener_id: str | None = None,
    speech_act_hint: str = "",
    tone_hint: str = "",
    source: str = "human_mode",
    audible_radius: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": TALK_SCHEMA_VERSION,
        "event_id": str(event_id),
        "mode": str(mode),
        "source": str(source),
        "speaker_id": str(speaker_id),
        "listener_id": listener_id,
        "utterance": str(utterance or "").strip(),
        "speech_act_hint": str(speech_act_hint or ""),
        "tone_hint": str(tone_hint or ""),
        "tick": int(tick),
        "audible_radius": None if audible_radius is None else round(float(audible_radius), 3),
        "metadata": dict(metadata or {}),
    }


def build_talk_session(
    session_id: str,
    mode: str,
    *,
    tick: int,
    speaker_id: str,
    listener_ids: list[str] | None = None,
    active: bool = True,
    expires_tick: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": TALK_SCHEMA_VERSION,
        "session_id": str(session_id),
        "mode": str(mode),
        "speaker_id": str(speaker_id),
        "listener_ids": [str(listener_id) for listener_id in list(listener_ids or []) if str(listener_id)],
        "active": bool(active),
        "created_tick": int(tick),
        "last_turn_tick": int(tick),
        "expires_tick": None if expires_tick is None else int(expires_tick),
        "turns": [],
        "metadata": dict(metadata or {}),
    }


def build_talk_turn(
    *,
    tick: int,
    speaker_id: str,
    text: str,
    mode: str,
    speech_act: str = "",
    tone: str = "",
    physical_intent: str = "",
    tts_priority: str = "",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "tick": int(tick),
        "speaker_id": str(speaker_id),
        "text": str(text or "").strip(),
        "mode": str(mode),
        "speech_act": str(speech_act or ""),
        "tone": str(tone or ""),
        "physical_intent": str(physical_intent or ""),
        "tts_priority": str(tts_priority or ""),
        "metadata": dict(metadata or {}),
    }


def build_talk_result(
    *,
    mode: str,
    speaker_id: str | None = None,
    listener_id: str | None = None,
    primary_listener_id: str | None = None,
    target_id: str | None = None,
    speech_text: str = "",
    speech_act: str = "",
    topic: str = "",
    tone: str = "",
    physical_intent: str = "",
    danger_upgrade: bool = False,
    reasoning_followup: bool = False,
    witness_policy: str = HEARD_NONE,
    relationship_delta: str = "",
    pressure_deltas: dict[str, float] | None = None,
    memory_salience: float = 0.0,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": TALK_SCHEMA_VERSION,
        "mode": str(mode),
        "speaker_id": speaker_id,
        "listener_id": listener_id,
        "primary_listener_id": primary_listener_id,
        "target_id": target_id,
        "speech_text": str(speech_text or "").strip(),
        "speech_act": str(speech_act or ""),
        "topic": str(topic or ""),
        "tone": str(tone or ""),
        "physical_intent": str(physical_intent or ""),
        "danger_upgrade": bool(danger_upgrade),
        "reasoning_followup": bool(reasoning_followup),
        "witness_policy": str(witness_policy or HEARD_NONE),
        "relationship_delta": str(relationship_delta or ""),
        "pressure_deltas": dict(pressure_deltas or {}),
        "memory_salience": clamp_unit(memory_salience),
        "metadata": dict(metadata or {}),
    }


def build_tts_payload(
    *,
    speaker_id: str,
    speech_text: str,
    tts_priority: str,
    distance_to_player: float,
    memory_salience: float,
    voice_profile: str = "",
    expires_tick: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": TALK_SCHEMA_VERSION,
        "speaker_id": str(speaker_id),
        "speech_text": str(speech_text or "").strip(),
        "tts_priority": str(tts_priority or ""),
        "distance_to_player": round(max(0.0, float(distance_to_player)), 3),
        "memory_salience": clamp_unit(memory_salience),
        "voice_profile": str(voice_profile or ""),
        "expires_tick": None if expires_tick is None else int(expires_tick),
        "metadata": dict(metadata or {}),
    }
