from __future__ import annotations

from typing import Any

import torch

try:
    import genesis_config as cfg
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg

from .common import clamp, dist, live_human_mask, move_away
from .tiny_runtime import TINY_MODE_AMBIENT_NPC_TALK, TINY_MODE_TALK_REPLY

try:
    from systems.talk import (
        HEARD_CROWD,
        HEARD_LOCAL_ONLY,
        HEARD_NEARBY,
        MODE_AMBIENT_NPC_TALK,
        MODE_AMBIENT_TALK,
        MODE_DIRECT_TALK,
        build_pressure_deltas,
        build_npc_bark_prompt_case,
        build_talk_prompt_case,
        create_ambient_talk_event,
        create_fallback_bark_result,
        create_npc_chatter_frame,
        create_direct_talk_event,
        default_threat_response,
        ensure_talk_state,
        expire_sessions,
        package_talk_runtime_output,
        record_turn,
        start_session,
        talk_ticket_for_event,
    )
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.talk import (
        HEARD_CROWD,
        HEARD_LOCAL_ONLY,
        HEARD_NEARBY,
        MODE_AMBIENT_NPC_TALK,
        MODE_AMBIENT_TALK,
        MODE_DIRECT_TALK,
        build_pressure_deltas,
        build_npc_bark_prompt_case,
        build_talk_prompt_case,
        create_ambient_talk_event,
        create_fallback_bark_result,
        create_npc_chatter_frame,
        create_direct_talk_event,
        default_threat_response,
        ensure_talk_state,
        expire_sessions,
        package_talk_runtime_output,
        record_turn,
        start_session,
        talk_ticket_for_event,
    )


DIRECT_HEARING_RADIUS = 14.0
AMBIENT_HEARING_RADIUS = 24.0
NPC_CHAT_RADIUS = 16.0
NPC_CHAT_COOLDOWN_TICKS = max(1, int(round(cfg.TICK_RATE_HZ * 4.0)))
MAX_FEED_LINES = 24
MAX_TTS_REQUESTS = 24


class TalkAgentRuntime:
    """Player-centered spoken dialogue runtime for human mode."""

    def __init__(self, resident_store: Any):
        self.resident_store = resident_store
        self.state = ensure_talk_state(None)
        self.history: list[dict[str, Any]] = []
        self.recent_lines: list[dict[str, Any]] = []
        self.recent_tts_requests: list[dict[str, Any]] = []
        self._pending_direct: list[dict[str, Any]] = []
        self._pending_ambient: list[dict[str, Any]] = []
        self._pending_npc: list[dict[str, Any]] = []
        self._next_event_index = 1
        self._last_npc_chat_tick = -10**9

    def reset(self) -> None:
        self.state = ensure_talk_state(None)
        self.history.clear()
        self.recent_lines.clear()
        self.recent_tts_requests.clear()
        self._pending_direct.clear()
        self._pending_ambient.clear()
        self._pending_npc.clear()
        self._next_event_index = 1
        self._last_npc_chat_tick = -10**9

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "direct_pending": len(self._pending_direct),
            "ambient_pending": len(self._pending_ambient),
            "npc_pending": len(self._pending_npc),
            "recent_lines": self.recent_lines[-8:],
            "recent_tts_requests": self.recent_tts_requests[-6:],
            "history": self.history[-10:],
        }

    def recent_feed_for_controller(self, controller_id: str = "local_player", *, limit: int = 8) -> list[dict[str, Any]]:
        controller_id = str(controller_id or "local_player")
        return [
            dict(line)
            for line in self.recent_lines
            if str(line.get("controller_id", "")) == controller_id
        ][-max(0, int(limit)) :]

    def _next_event_id(self) -> str:
        event_id = "talk_event_%05d" % int(self._next_event_index)
        self._next_event_index += 1
        return event_id

    def _controller_human_session(self, engine: Any, controller_id: str = "local_player") -> dict[str, Any] | None:
        for session in engine.player_control.status_snapshot().get("sessions", []):
            if str(session.get("controller_id", "")) != str(controller_id):
                continue
            if str(session.get("target_kind", "")) != "human":
                continue
            return dict(session)
        return None

    def _human_slot_for_id(self, engine: Any, human_id: str | None) -> int:
        wanted = str(human_id or "").strip()
        if not wanted:
            return -1
        for slot, uid in enumerate(engine._human_uid_by_slot):
            if uid == wanted:
                return slot
        return -1

    def _human_name(self, engine: Any, human_id: str | None, *, you_if_local: bool = False, controller_id: str = "local_player") -> str:
        human_id = str(human_id or "").strip()
        if not human_id:
            return "Unknown"
        session = self._controller_human_session(engine, controller_id)
        if you_if_local and session is not None and str(session.get("target_id", "")) == human_id:
            return "You"
        resident = self.resident_store.get(human_id)
        if resident is not None:
            return str(resident.get("profile", {}).get("name", human_id))
        return human_id

    def _player_anchor(self, engine: Any, controller_id: str = "local_player") -> tuple[str, int, float, float] | None:
        session = self._controller_human_session(engine, controller_id)
        if session is None:
            return None
        slot = self._human_slot_for_id(engine, str(session.get("target_id", "")))
        if slot == -1:
            return None
        h_tensor = engine.state.h_tensor
        return (
            str(session.get("target_id", "")),
            slot,
            float(h_tensor[slot, cfg.X]),
            float(h_tensor[slot, cfg.Y]),
        )

    def _resolve_listener_for_ambient(self, engine: Any, speaker_slot: int, speaker_id: str, *, controller_id: str = "local_player") -> tuple[str | None, int]:
        anchor = self._player_anchor(engine, controller_id)
        if anchor is None:
            return None, -1
        _, _, player_x, player_y = anchor
        best_id: str | None = None
        best_slot = -1
        best_score = float("inf")
        for slot in torch.where(live_human_mask(engine.state.h_tensor))[0].tolist():
            candidate_id = engine._human_uid_by_slot[slot]
            if candidate_id is None or candidate_id == speaker_id or slot == speaker_slot:
                continue
            candidate_x = float(engine.state.h_tensor[slot, cfg.X])
            candidate_y = float(engine.state.h_tensor[slot, cfg.Y])
            hear_distance = dist(player_x, player_y, candidate_x, candidate_y)
            if hear_distance > AMBIENT_HEARING_RADIUS:
                continue
            score = dist(float(engine.state.h_tensor[speaker_slot, cfg.X]), float(engine.state.h_tensor[speaker_slot, cfg.Y]), candidate_x, candidate_y)
            if score < best_score:
                best_score = score
                best_id = candidate_id
                best_slot = slot
        return best_id, best_slot

    def _queue_control_events(self, engine: Any) -> None:
        for control_event in engine.player_control.drain_talk_events(engine):
            session = dict(control_event.get("session", {}))
            event = dict(control_event.get("event", {}))
            controller_id = str(control_event.get("controller_id", "local_player"))
            speaker_id = str(session.get("target_id", ""))
            if not speaker_id:
                continue
            text = str(event.get("text", "")).strip()
            if not text:
                continue
            talk_mode = str(event.get("talk_mode", "")).strip().lower()
            target_kind = str(event.get("target_kind", "")).strip().lower()
            target_id = str(event.get("target_id", "")).strip()
            if talk_mode == MODE_DIRECT_TALK and target_kind == "human" and target_id:
                talk_event = create_direct_talk_event(
                    self._next_event_id(),
                    tick=engine.tick,
                    speaker_id=speaker_id,
                    listener_id=target_id,
                    utterance=text,
                    metadata={"controller_id": controller_id},
                )
            else:
                talk_event = create_ambient_talk_event(
                    self._next_event_id(),
                    tick=engine.tick,
                    speaker_id=speaker_id,
                    utterance=text,
                    metadata={"controller_id": controller_id},
                )
            ticket = talk_ticket_for_event(
                talk_event,
                tick=engine.tick,
                direct_click=(talk_event["mode"] == MODE_DIRECT_TALK),
                listener_count=1 if talk_event["mode"] == MODE_DIRECT_TALK else 0,
            )
            envelope = {
                "controller_id": controller_id,
                "session": session,
                "event": talk_event,
                "ticket": ticket,
            }
            if ticket["mode"] == MODE_DIRECT_TALK:
                self._pending_direct.append(envelope)
            else:
                self._pending_ambient.append(envelope)

    def _maybe_queue_npc_chatter(self, engine: Any, *, controller_id: str = "local_player") -> None:
        if str(engine._view_window_state.get("camera_mode", "")).strip().lower() != "human":
            return
        if (int(engine.tick) - int(self._last_npc_chat_tick)) < int(NPC_CHAT_COOLDOWN_TICKS):
            return
        anchor = self._player_anchor(engine, controller_id)
        if anchor is None:
            return
        player_id, _, player_x, player_y = anchor
        h_tensor = engine.state.h_tensor
        live_slots = torch.where(live_human_mask(h_tensor))[0].tolist()
        speaker_slot = -1
        listener_slot = -1
        best_pair_score = float("inf")
        for slot in live_slots:
            speaker_id = engine._human_uid_by_slot[slot]
            if speaker_id is None or speaker_id == player_id:
                continue
            sx = float(h_tensor[slot, cfg.X])
            sy = float(h_tensor[slot, cfg.Y])
            if dist(player_x, player_y, sx, sy) > NPC_CHAT_RADIUS:
                continue
            for other_slot in live_slots:
                if other_slot == slot:
                    continue
                listener_id = engine._human_uid_by_slot[other_slot]
                if listener_id is None or listener_id == player_id:
                    continue
                ox = float(h_tensor[other_slot, cfg.X])
                oy = float(h_tensor[other_slot, cfg.Y])
                if dist(player_x, player_y, ox, oy) > NPC_CHAT_RADIUS:
                    continue
                pair_score = dist(sx, sy, ox, oy)
                if pair_score < best_pair_score:
                    best_pair_score = pair_score
                    speaker_slot = slot
                    listener_slot = other_slot
        if speaker_slot == -1 or listener_slot == -1:
            return

        speaker_id = str(engine._human_uid_by_slot[speaker_slot])
        listener_id = str(engine._human_uid_by_slot[listener_slot])
        speech_act = self._npc_speech_act(engine, speaker_slot, listener_slot)
        frame = create_npc_chatter_frame(
            speaker_id,
            listener_id,
            speech_act=speech_act,
            topic="danger" if speech_act in {"warn", "alarm", "fear"} else "daily_life",
            tone="tense" if speech_act in {"warn", "alarm", "fear", "conflict"} else "plain",
            urgency="high" if speech_act in {"warn", "alarm"} else "low",
            metadata={"controller_id": controller_id},
        )
        self._pending_npc.append(
            {
                "controller_id": controller_id,
                "frame": frame,
                "ticket": {"queue": "ambient_npc_talk", "priority": 0.24, "queued_tick": int(engine.tick)},
            }
        )
        self._last_npc_chat_tick = int(engine.tick)

    def _npc_speech_act(self, engine: Any, speaker_slot: int, listener_slot: int) -> str:
        h_tensor = engine.state.h_tensor
        speaker_threat = float(h_tensor[speaker_slot, cfg.THREAT])
        listener_threat = float(h_tensor[listener_slot, cfg.THREAT])
        speaker_mood = float(h_tensor[speaker_slot, cfg.MOOD])
        listener_mood = float(h_tensor[listener_slot, cfg.MOOD])
        if max(speaker_threat, listener_threat) >= 35.0:
            return "warn"
        if min(speaker_mood, listener_mood) <= 30.0:
            return "comfort"
        if (speaker_slot + listener_slot + int(engine.tick)) % 7 == 0:
            return "work"
        if (speaker_slot + listener_slot + int(engine.tick)) % 5 == 0:
            return "gossip"
        return "greet"

    def _resident_summary(self, human_id: str | None) -> dict[str, Any]:
        resident = self.resident_store.get(str(human_id or "").strip())
        if resident is None:
            return {}
        return {
            "human_id": str(human_id or ""),
            "name": str(resident.get("profile", {}).get("name", human_id or "")),
            "personality": dict(resident.get("personality") or {}),
            "occupation": dict(resident.get("occupation") or {}),
            "schedule_state": dict(resident.get("schedule_state") or {}),
            "status": dict(resident.get("status") or {}),
        }

    def _relationship_summary(self, listener_id: str | None, speaker_id: str | None) -> dict[str, Any]:
        listener = self.resident_store.get(str(listener_id or "").strip())
        if listener is None:
            return {}
        return dict((listener.get("relationships") or {}).get(str(speaker_id or "").strip()) or {})

    def _build_tiny_direct_case(self, engine: Any, envelope: dict[str, Any]) -> dict[str, Any]:
        event = dict(envelope.get("event", {}))
        speaker_id = str(event.get("speaker_id", "")).strip()
        listener_id = str(event.get("listener_id", "")).strip()
        return {
            "resident_model_mode": TINY_MODE_TALK_REPLY,
            "talk_mode": MODE_DIRECT_TALK,
            "event_id": str(event.get("event_id", "")),
            "speaker_id": speaker_id,
            "listener_id": listener_id,
            "controller_id": str(envelope.get("controller_id", "local_player")),
            "prompt_case": build_talk_prompt_case(
                event,
                speaker_summary=self._resident_summary(speaker_id),
                listener_summary=self._resident_summary(listener_id),
                relationship_summary=self._relationship_summary(listener_id, speaker_id),
                recent_memories=[],
                local_context={
                    "tick": int(engine.tick),
                    "distance_to_player": round(self._distance_to_player(engine, listener_id), 3),
                    "camera_mode": str(engine._view_window_state.get("camera_mode", "")),
                },
                allowed_physical_intents=[
                    "flee",
                    "back_away",
                    "scan_and_prepare",
                    "counterattack",
                    "call_help",
                    "stay_alert",
                ],
            ),
        }

    def _build_tiny_ambient_case(self, engine: Any, envelope: dict[str, Any]) -> dict[str, Any]:
        event = dict(envelope.get("event", {}))
        speaker_id = str(event.get("speaker_id", "")).strip()
        speaker_slot = self._human_slot_for_id(engine, speaker_id)
        listener_id = ""
        if speaker_slot != -1:
            listener_id, _ = self._resolve_listener_for_ambient(
                engine,
                speaker_slot,
                speaker_id,
                controller_id=str(envelope.get("controller_id", "local_player")),
            )
        return {
            "resident_model_mode": TINY_MODE_TALK_REPLY,
            "talk_mode": MODE_AMBIENT_TALK,
            "event_id": str(event.get("event_id", "")),
            "speaker_id": speaker_id,
            "listener_id": str(listener_id or ""),
            "controller_id": str(envelope.get("controller_id", "local_player")),
            "prompt_case": build_talk_prompt_case(
                event,
                speaker_summary=self._resident_summary(speaker_id),
                listener_summary=self._resident_summary(listener_id),
                relationship_summary=self._relationship_summary(listener_id, speaker_id),
                recent_memories=[],
                local_context={
                    "tick": int(engine.tick),
                    "distance_to_player": round(self._distance_to_player(engine, speaker_id), 3),
                    "camera_mode": str(engine._view_window_state.get("camera_mode", "")),
                },
                allowed_physical_intents=[
                    "scan_and_prepare",
                    "stay_alert",
                    "call_help",
                    "back_away",
                ],
            ),
        }

    def _build_tiny_npc_case(self, engine: Any, envelope: dict[str, Any]) -> dict[str, Any]:
        frame = dict(envelope.get("frame", {}))
        speaker_id = str(frame.get("speaker_id", "")).strip()
        listener_id = str(frame.get("listener_id", "")).strip()
        return {
            "resident_model_mode": TINY_MODE_AMBIENT_NPC_TALK,
            "talk_mode": MODE_AMBIENT_NPC_TALK,
            "speaker_id": speaker_id,
            "listener_id": listener_id,
            "controller_id": str(envelope.get("controller_id", "local_player")),
            "prompt_case": build_npc_bark_prompt_case(
                frame,
                speaker_summary=self._resident_summary(speaker_id),
                listener_summary=self._resident_summary(listener_id),
                local_context={
                    "tick": int(engine.tick),
                    "distance_to_player": round(self._distance_to_player(engine, speaker_id), 3),
                    "camera_mode": str(engine._view_window_state.get("camera_mode", "")),
                },
            ),
        }

    @staticmethod
    def _wrap_tiny_talk_packet(result: dict[str, Any] | None, *, mode: str) -> dict[str, Any]:
        packet = dict(result or {})
        packet.setdefault("resident_model_mode", str(mode))
        packet["source"] = str(packet.get("source") or "tiny_model_mock")
        packet["mock"] = bool(packet.get("mock", False) or "mock" in str(packet["source"]).lower())
        return packet

    def _run_tiny_talk_batch(
        self,
        engine: Any,
        *,
        mode: str,
        cases: list[dict[str, Any]],
        fallback_packets: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        tiny_runtime = getattr(engine, "tiny_model_runtime", None)
        if tiny_runtime is None:
            return [self._wrap_tiny_talk_packet(packet, mode=mode) for packet in fallback_packets]
        results = tiny_runtime.run_mode_batch(
            mode=mode,
            cases=cases,
            engine=engine,
            fallback_packets=fallback_packets,
        )
        return [dict(result.get("packet") or {}) for result in results]

    def _generate_direct_result(self, engine: Any, envelope: dict[str, Any]) -> dict[str, Any] | None:
        event = dict(envelope.get("event", {}))
        listener_id = str(event.get("listener_id", "")).strip()
        speaker_id = str(event.get("speaker_id", "")).strip()
        if not listener_id:
            return None
        from systems.commission.engine import commission_open_between
        if commission_open_between(engine, speaker_id, listener_id):
            return None  # decision D9: the commission dialogue answers; keyword rules stay quiet
        resident = self.resident_store.get(listener_id)
        utterance = str(event.get("utterance", "")).strip()
        lower = utterance.lower()
        caution = float((((resident or {}).get("personality", {}) or {}).get("traits", {}) or {}).get("caution", 0.5))
        aggression = float((((resident or {}).get("personality", {}) or {}).get("traits", {}) or {}).get("aggression", 0.5))
        if any(word in lower for word in ["kill", "murder", "hurt", "destroy", "attack you", "i'll get you", "die"]):
            result = default_threat_response(target_id=listener_id, speaker_id=speaker_id)
            result["speaker_id"] = listener_id
            result["listener_id"] = speaker_id
            result.setdefault("metadata", {})["source_speaker_id"] = speaker_id
            if aggression > 0.72 and caution < 0.42:
                result["speech_text"] = "Try it and you'll bleed first."
                result["physical_intent"] = "counterattack"
            return result
        if any(word in lower for word in ["sorry", "apolog", "forgive"]):
            return {
                "mode": MODE_DIRECT_TALK,
                "target_id": listener_id,
                "speaker_id": listener_id,
                "listener_id": speaker_id,
                "speech_text": "Then leave me alone.",
                "speech_act": "apology_response",
                "tone": "guarded",
                "physical_intent": "back_away",
                "danger_upgrade": False,
                "reasoning_followup": False,
                "witness_policy": "none",
                "relationship_delta": "guarded",
                "pressure_deltas": build_pressure_deltas(fear=-0.08, trust=0.05),
                "memory_salience": 0.41,
                "metadata": {"source_speaker_id": speaker_id},
            }
        if any(word in lower for word in ["help", "wolf", "wolves", "tiger", "run", "danger"]):
            return {
                "mode": MODE_DIRECT_TALK,
                "target_id": listener_id,
                "speaker_id": listener_id,
                "listener_id": speaker_id,
                "speech_text": "Where? Show me.",
                "speech_act": "alarm_response",
                "tone": "alert",
                "physical_intent": "scan_and_prepare",
                "danger_upgrade": False,
                "reasoning_followup": True,
                "witness_policy": HEARD_NEARBY,
                "relationship_delta": "supportive",
                "pressure_deltas": build_pressure_deltas(fear=0.18, loyalty=0.08),
                "memory_salience": 0.64,
                "metadata": {"source_speaker_id": speaker_id},
            }
        if any(word in lower for word in ["money", "coin", "coins", "pay", "trade", "buy", "sell"]):
            return {
                "mode": MODE_DIRECT_TALK,
                "target_id": listener_id,
                "speaker_id": listener_id,
                "listener_id": speaker_id,
                "speech_text": "What are you offering?",
                "speech_act": "trade_response",
                "tone": "guarded",
                "physical_intent": "",
                "danger_upgrade": False,
                "reasoning_followup": False,
                "witness_policy": "none",
                "relationship_delta": "neutral",
                "pressure_deltas": build_pressure_deltas(),
                "memory_salience": 0.22,
                "metadata": {"source_speaker_id": speaker_id},
            }
        return {
            "mode": MODE_DIRECT_TALK,
            "target_id": listener_id,
            "speaker_id": listener_id,
            "listener_id": speaker_id,
            "speech_text": "I'm listening.",
            "speech_act": "reply",
            "tone": "neutral",
            "physical_intent": "",
            "danger_upgrade": False,
            "reasoning_followup": False,
            "witness_policy": "none",
            "relationship_delta": "neutral",
            "pressure_deltas": build_pressure_deltas(),
            "memory_salience": 0.18,
            "metadata": {"source_speaker_id": speaker_id},
        }

    def _generate_ambient_result(self, engine: Any, envelope: dict[str, Any]) -> dict[str, Any] | None:
        event = dict(envelope.get("event", {}))
        speaker_id = str(event.get("speaker_id", "")).strip()
        speaker_slot = self._human_slot_for_id(engine, speaker_id)
        if speaker_slot == -1:
            return None
        listener_id, _ = self._resolve_listener_for_ambient(engine, speaker_slot, speaker_id, controller_id=str(envelope.get("controller_id", "local_player")))
        if not listener_id:
            return None
        utterance = str(event.get("utterance", "")).strip()
        lower = utterance.lower()
        if any(word in lower for word in ["help", "wolf", "wolves", "tiger", "run", "danger"]):
            return {
                "mode": MODE_AMBIENT_TALK,
                "speaker_id": listener_id,
                "listener_id": speaker_id,
                "primary_listener_id": listener_id,
                "speech_text": "Where are they?",
                "speech_act": "alarm_response",
                "topic": "danger",
                "tone": "alert",
                "physical_intent": "scan_and_prepare",
                "danger_upgrade": False,
                "reasoning_followup": True,
                "witness_policy": HEARD_CROWD,
                "relationship_delta": "neutral",
                "pressure_deltas": build_pressure_deltas(fear=0.21, loyalty=0.09),
                "memory_salience": 0.63,
                "metadata": {"source_speaker_id": speaker_id},
            }
        if any(word in lower for word in ["kill", "hurt", "attack", "die"]):
            return {
                "mode": MODE_AMBIENT_TALK,
                "speaker_id": listener_id,
                "listener_id": speaker_id,
                "primary_listener_id": listener_id,
                "speech_text": "Back away from us!",
                "speech_act": "alarm_response",
                "topic": "threat",
                "tone": "fearful_angry",
                "physical_intent": "stay_alert",
                "danger_upgrade": True,
                "reasoning_followup": True,
                "witness_policy": HEARD_CROWD,
                "relationship_delta": "hostile",
                "pressure_deltas": build_pressure_deltas(fear=0.36, hostility=0.22),
                "memory_salience": 0.78,
                "metadata": {"source_speaker_id": speaker_id},
            }
        return {
            "mode": MODE_AMBIENT_TALK,
            "speaker_id": listener_id,
            "listener_id": speaker_id,
            "primary_listener_id": listener_id,
            "speech_text": "We heard you.",
            "speech_act": "ambient_reply",
            "topic": "crowd",
            "tone": "neutral",
            "physical_intent": "",
            "danger_upgrade": False,
            "reasoning_followup": False,
            "witness_policy": HEARD_CROWD,
            "relationship_delta": "neutral",
            "pressure_deltas": build_pressure_deltas(),
            "memory_salience": 0.16,
            "metadata": {"source_speaker_id": speaker_id},
        }

    def _distance_to_player(self, engine: Any, human_id: str | None, *, controller_id: str = "local_player") -> float:
        anchor = self._player_anchor(engine, controller_id)
        if anchor is None:
            return 9999.0
        _, _, player_x, player_y = anchor
        slot = self._human_slot_for_id(engine, human_id)
        if slot == -1:
            return 9999.0
        return dist(player_x, player_y, float(engine.state.h_tensor[slot, cfg.X]), float(engine.state.h_tensor[slot, cfg.Y]))

    def _apply_listener_reaction(self, engine: Any, listener_id: str, speaker_id: str | None, physical_intent: str, *, danger_upgrade: bool = False) -> None:
        slot = self._human_slot_for_id(engine, listener_id)
        if slot == -1:
            return
        h_tensor = engine.state.h_tensor
        speaker_slot = self._human_slot_for_id(engine, speaker_id)
        if physical_intent in {"flee", "back_away"} and speaker_slot != -1:
            move_away(
                h_tensor,
                slot,
                float(h_tensor[speaker_slot, cfg.X]),
                float(h_tensor[speaker_slot, cfg.Y]),
                cfg.MOVE_STEP * (2.4 if physical_intent == "flee" else 1.2),
            )
            h_tensor[slot, cfg.THREAT] = clamp(float(h_tensor[slot, cfg.THREAT]) + (20.0 if physical_intent == "flee" else 8.0), 0.0, 100.0)
        elif physical_intent in {"scan_and_prepare", "stay_alert", "call_help", "counterattack"}:
            h_tensor[slot, cfg.THREAT] = clamp(float(h_tensor[slot, cfg.THREAT]) + 16.0, 0.0, 100.0)
        if danger_upgrade or physical_intent in {"scan_and_prepare", "stay_alert", "call_help", "counterattack"}:
            h_tensor[slot, cfg.ESCALATION_FLAG] = 1.0

    def _apply_relationship_delta(self, listener_id: str, speaker_id: str | None, *, delta: str, tick: int) -> None:
        speaker_id = str(speaker_id or "").strip()
        if not speaker_id:
            return
        if delta == "hostile":
            self.resident_store.update_relationship(listener_id, speaker_id, "rival", closeness_delta=-0.12, tick=tick)
        elif delta == "supportive":
            self.resident_store.update_relationship(listener_id, speaker_id, "friend", closeness_delta=0.06, tick=tick)
        elif delta == "guarded":
            self.resident_store.update_relationship(listener_id, speaker_id, "neighbor", closeness_delta=-0.03, tick=tick)

    def _record_runtime_line(
        self,
        engine: Any,
        result: dict[str, Any],
        *,
        controller_id: str,
    ) -> None:
        speaker_id = str(result.get("speaker_id", "") or "")
        listener_id = str(result.get("listener_id", "") or result.get("primary_listener_id", "") or result.get("target_id", "") or "")
        distance = self._distance_to_player(engine, speaker_id or listener_id, controller_id=controller_id)
        line = {
            "tick": int(engine.tick),
            "controller_id": controller_id,
            "mode": str(result.get("mode", "")),
            "speaker_id": speaker_id,
            "speaker_name": self._human_name(engine, speaker_id, you_if_local=True, controller_id=controller_id),
            "listener_id": listener_id or None,
            "listener_name": self._human_name(engine, listener_id, controller_id=controller_id) if listener_id else None,
            "text": str(result.get("speech_text", "")),
            "speech_act": str(result.get("speech_act", "")),
            "tone": str(result.get("tone", "")),
            "distance_to_player": round(distance, 2),
        }
        self.recent_lines.append(line)
        self.recent_lines = self.recent_lines[-MAX_FEED_LINES:]

    def _record_tts_request(self, payload: dict[str, Any] | None) -> None:
        if payload is None:
            return
        self.recent_tts_requests.append(dict(payload))
        self.recent_tts_requests = self.recent_tts_requests[-MAX_TTS_REQUESTS:]

    def _record_history(self, kind: str, payload: dict[str, Any]) -> None:
        entry = {"kind": str(kind)}
        entry.update(dict(payload))
        self.history.append(entry)
        self.history = self.history[-30:]

    def _apply_result(self, engine: Any, result: dict[str, Any], *, controller_id: str) -> None:
        target_id = str(result.get("target_id", "") or result.get("primary_listener_id", "") or result.get("listener_id", "") or "")
        speaker_id = str(result.get("speaker_id", "") or "")
        source_speaker_id = str(dict(result.get("metadata", {})).get("source_speaker_id", result.get("listener_id", "")) or "")
        if target_id:
            self.resident_store.record_event(
                target_id,
                engine.tick,
                "heard_talk",
                note=str(result.get("speech_text", "")),
                other_human_id=source_speaker_id or None,
            )
            self._apply_relationship_delta(target_id, source_speaker_id, delta=str(result.get("relationship_delta", "")), tick=engine.tick)
            self._apply_listener_reaction(
                engine,
                target_id,
                source_speaker_id,
                str(result.get("physical_intent", "")),
                danger_upgrade=bool(result.get("danger_upgrade", False)),
            )
            target_resident = self.resident_store.get(target_id)
            if isinstance(target_resident, dict):
                task_state = target_resident.setdefault("task_state", {})
                physical_intent = str(result.get("physical_intent", ""))
                if source_speaker_id and (bool(result.get("danger_upgrade", False)) or physical_intent in {"counterattack", "scan_and_prepare"}):
                    task_state["pending_combat_signal"] = {
                        "kind": "attack_target",
                        "target_kind": "human",
                        "target_id": source_speaker_id,
                        "target_name": self._human_name(engine, source_speaker_id, controller_id=controller_id) or source_speaker_id,
                        "reason": "talk_threat",
                        "priority": 0.93,
                        "summary": "retaliate against threat",
                    }
                elif physical_intent == "call_help":
                    task_state["pending_social_signal"] = {
                        "kind": "call_for_help",
                        "priority": 0.72,
                        "summary": "call for help",
                        "speaker_id": source_speaker_id,
                    }
                elif source_speaker_id and physical_intent in {"back_away", "stay_alert"}:
                    task_state["pending_social_signal"] = {
                        "kind": "talk_to_target",
                        "target_human_id": source_speaker_id,
                        "target_name": self._human_name(engine, source_speaker_id, controller_id=controller_id) or source_speaker_id,
                        "priority": 0.44,
                        "summary": "respond nearby",
                    }
        bundle = package_talk_runtime_output(
            result,
            tick=engine.tick,
            speaker_id=speaker_id,
            distance_to_player=self._distance_to_player(engine, speaker_id or target_id, controller_id=controller_id),
        )
        if isinstance(bundle.get("tts_payload"), dict):
            bundle["tts_payload"].setdefault("metadata", {})
            bundle["tts_payload"]["metadata"]["controller_id"] = controller_id
        self._record_runtime_line(engine, result, controller_id=controller_id)
        self._record_tts_request(bundle.get("tts_payload"))
        self._record_history("line", {"tick": engine.tick, "controller_id": controller_id, "line": result.get("speech_text", "")})
        engine._force_frame_refresh = True

    def _open_session_for_result(self, result: dict[str, Any], *, tick: int) -> None:
        speaker_id = str(result.get("speaker_id", "") or "")
        listener_id = str(result.get("listener_id", "") or result.get("primary_listener_id", "") or result.get("target_id", "") or "")
        if not speaker_id:
            return
        session = start_session(
            self.state,
            str(result.get("mode", "")),
            tick=tick,
            speaker_id=speaker_id,
            listener_ids=[listener_id] if listener_id else [],
            ttl_ticks=120,
        )
        record_turn(
            self.state,
            session["session_id"],
            tick=tick,
            speaker_id=speaker_id,
            text=str(result.get("speech_text", "")),
            mode=str(result.get("mode", "")),
            speech_act=str(result.get("speech_act", "")),
            tone=str(result.get("tone", "")),
            physical_intent=str(result.get("physical_intent", "")),
            tts_priority="",
        )

    def _process_direct_queue(self, engine: Any) -> dict[str, Any] | None:
        if not self._pending_direct:
            return None
        envelope = self._pending_direct.pop(0)
        fallback_result = self._generate_direct_result(engine, envelope)
        if fallback_result is None:
            return None
        result = None
        tiny_packets = self._run_tiny_talk_batch(
            engine,
            mode=TINY_MODE_TALK_REPLY,
            cases=[self._build_tiny_direct_case(engine, envelope)],
            fallback_packets=[self._wrap_tiny_talk_packet(fallback_result, mode=TINY_MODE_TALK_REPLY)],
        )
        if tiny_packets:
            result = dict(tiny_packets[0])
        if result is None:
            return None
        self._open_session_for_result(result, tick=engine.tick)
        controller_id = str(envelope.get("controller_id", "local_player"))
        self._apply_result(engine, result, controller_id=controller_id)
        return {
            "kind": "direct",
            "tick": int(engine.tick),
            "controller_id": controller_id,
            "result": dict(result),
        }

    def _process_ambient_queue(self, engine: Any) -> dict[str, Any] | None:
        if not self._pending_ambient:
            return None
        envelope = self._pending_ambient.pop(0)
        fallback_result = self._generate_ambient_result(engine, envelope)
        if fallback_result is None:
            return None
        result = None
        tiny_packets = self._run_tiny_talk_batch(
            engine,
            mode=TINY_MODE_TALK_REPLY,
            cases=[self._build_tiny_ambient_case(engine, envelope)],
            fallback_packets=[self._wrap_tiny_talk_packet(fallback_result, mode=TINY_MODE_TALK_REPLY)],
        )
        if tiny_packets:
            result = dict(tiny_packets[0])
        if result is None:
            return None
        self._open_session_for_result(result, tick=engine.tick)
        controller_id = str(envelope.get("controller_id", "local_player"))
        self._apply_result(engine, result, controller_id=controller_id)
        return {
            "kind": "ambient",
            "tick": int(engine.tick),
            "controller_id": controller_id,
            "result": dict(result),
        }

    def _process_npc_queue(self, engine: Any) -> dict[str, Any] | None:
        if not self._pending_npc:
            return None
        envelope = self._pending_npc.pop(0)
        frame = dict(envelope.get("frame", {}))
        result = None
        tiny_packets = self._run_tiny_talk_batch(
            engine,
            mode=TINY_MODE_AMBIENT_NPC_TALK,
            cases=[self._build_tiny_npc_case(engine, envelope)],
            fallback_packets=[
                self._wrap_tiny_talk_packet(
                    create_fallback_bark_result(frame, seed_hint=int(engine.tick)),
                    mode=TINY_MODE_AMBIENT_NPC_TALK,
                )
            ],
        )
        if tiny_packets:
            result = dict(tiny_packets[0])
        if result is None:
            return None
        self._open_session_for_result(result, tick=engine.tick)
        controller_id = str(envelope.get("controller_id", "local_player"))
        self._apply_result(engine, result, controller_id=controller_id)
        return {
            "kind": "npc",
            "tick": int(engine.tick),
            "controller_id": controller_id,
            "result": dict(result),
        }

    def process_tick(self, engine: Any) -> list[dict[str, Any]]:
        expire_sessions(self.state, tick=int(engine.tick))
        self._queue_control_events(engine)
        self._maybe_queue_npc_chatter(engine)
        processed: list[dict[str, Any]] = []
        direct_result = self._process_direct_queue(engine)
        if direct_result is not None:
            processed.append(direct_result)
        if not processed:
            ambient_result = self._process_ambient_queue(engine)
            if ambient_result is not None:
                processed.append(ambient_result)
        if not processed:
            npc_result = self._process_npc_queue(engine)
            if npc_result is not None:
                processed.append(npc_result)
        return processed
