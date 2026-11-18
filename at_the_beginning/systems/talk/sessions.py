from __future__ import annotations

"""Conversation/session helpers for local spoken dialogue."""

from typing import Any

from .schema import build_talk_session, build_talk_turn


def build_talk_state() -> dict[str, Any]:
    return {
        "sessions": {},
        "next_session_index": 1,
    }


def ensure_talk_state(state: dict[str, Any] | None) -> dict[str, Any]:
    base = build_talk_state()
    if not isinstance(state, dict):
        return base
    base["sessions"] = dict(state.get("sessions", {}))
    base["next_session_index"] = max(1, int(state.get("next_session_index", 1)))
    return base


def next_session_id(state: dict[str, Any]) -> str:
    state["next_session_index"] = max(1, int(state.get("next_session_index", 1)))
    session_id = "talk_%05d" % int(state["next_session_index"])
    state["next_session_index"] = int(state["next_session_index"]) + 1
    return session_id


def start_session(
    state: dict[str, Any],
    mode: str,
    *,
    tick: int,
    speaker_id: str,
    listener_ids: list[str] | None = None,
    ttl_ticks: int = 120,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session = build_talk_session(
        next_session_id(state),
        mode,
        tick=tick,
        speaker_id=speaker_id,
        listener_ids=listener_ids,
        expires_tick=int(tick) + max(1, int(ttl_ticks)),
        metadata=metadata,
    )
    state.setdefault("sessions", {})[session["session_id"]] = session
    return session


def record_turn(
    state: dict[str, Any],
    session_id: str,
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
) -> dict[str, Any] | None:
    session = dict(state.get("sessions", {}).get(str(session_id), {}))
    if not session:
        return None
    turn = build_talk_turn(
        tick=tick,
        speaker_id=speaker_id,
        text=text,
        mode=mode,
        speech_act=speech_act,
        tone=tone,
        physical_intent=physical_intent,
        tts_priority=tts_priority,
        metadata=metadata,
    )
    turns = list(session.get("turns", []))
    turns.append(turn)
    session["turns"] = turns[-6:]
    session["last_turn_tick"] = int(tick)
    state.setdefault("sessions", {})[str(session_id)] = session
    return turn


def expire_sessions(state: dict[str, Any], *, tick: int) -> list[str]:
    removed: list[str] = []
    sessions = dict(state.get("sessions", {}))
    for session_id, session in list(sessions.items()):
        expires_tick = session.get("expires_tick")
        if expires_tick is not None and int(expires_tick) <= int(tick):
            removed.append(str(session_id))
            sessions.pop(session_id, None)
    state["sessions"] = sessions
    return removed


def recent_session_turns(state: dict[str, Any], session_id: str) -> list[dict[str, Any]]:
    session = dict(state.get("sessions", {}).get(str(session_id), {}))
    return [dict(turn) for turn in list(session.get("turns", []))]
