from __future__ import annotations

import math
import uuid
import time
import copy
import hashlib
import json
from typing import Any

import torch

try:
    import genesis_config as cfg
    from systems.movement.map_contract import outside_placed_maps
    from systems.control import (
        apply_semantic_event_to_command_state,
        empty_command_state,
        merge_control_semantic_state,
        normalize_control_event,
        normalize_target_kind,
    )
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg
    from at_the_beginning.systems.movement.map_contract import outside_placed_maps
    from at_the_beginning.systems.control import (
        apply_semantic_event_to_command_state,
        empty_command_state,
        merge_control_semantic_state,
        normalize_control_event,
        normalize_target_kind,
    )


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _live_human_mask(h_tensor: torch.Tensor) -> torch.Tensor:
    return h_tensor[:, cfg.TYPE] == cfg.AGENT_TYPE_HUMAN


class PlayerControlRuntime:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.input_timeout = 0.75
        self.possession_timeout = 5.0
        self.sessions_by_controller: dict[str, dict[str, Any]] = {}
        self.controller_by_target: dict[tuple[str, str], str] = {}
        self.history: list[dict[str, Any]] = []
        self.last_error: dict[str, Any] | None = None

    @staticmethod
    def _normalize_mode(mode: str | None) -> str:
        normalized = str(mode or "possess").strip().lower()
        if normalized in {"observe", "possess", "assist", "incarnate"}:
            return normalized
        return "possess"

    @staticmethod
    def _has_direct_control(session: dict[str, Any], *, target_kind: str | None = None) -> bool:
        session_target_kind = str(session.get("target_kind", "")).strip().lower()
        if target_kind is not None and session_target_kind != str(target_kind).strip().lower():
            return False
        session_mode = str(session.get("mode", "")).strip().lower()
        if session_mode == "possess":
            return True
        return session_target_kind == "human" and session_mode == "incarnate"

    @staticmethod
    def _normalize_target_kind(target_kind: str | None) -> str:
        return normalize_target_kind(target_kind, fallback="human")

    @staticmethod
    def _target_key(target_kind: str, target_id: str) -> tuple[str, str]:
        return (str(target_kind).strip().lower(), str(target_id).strip())

    def _session_payload(self, session: dict[str, Any]) -> dict[str, Any]:
        command_state = dict(session.get("command_state", {}))
        payload = {
            "protocol_version": 1,
            "world_epoch": session["world_epoch"],
            "possession_epoch": session["possession_epoch"],
            "controller_id": session["controller_id"],
            "target_kind": session["target_kind"],
            "target_id": session["target_id"],
            "target_name": session["target_name"],
            "slot": int(session["slot"]),
            "mode": session["mode"],
            "control_context": session.get("control_context"),
            "view_style": session.get("view_style"),
            "last_input_seq": int(session.get("last_input_seq", -1)),
            "last_applied_input_seq": int(session.get("last_applied_input_seq", -1)),
            "committed_state": copy.deepcopy(session.get("committed_state")),
            "last_seen_tick": int(session.get("last_seen_tick", -1)),
            "last_consumed_command_seq": int(session.get("last_consumed_command_seq", -1)),
            "pending_command_count": len(session.get("pending_inputs", [])),
            "input_age_ms": round(max(0.0, self.clock() - session["last_received_at"]) * 1000, 1),
            "input_timeout_seconds": self.input_timeout,
            "possession_timeout_seconds": self.possession_timeout,
            "move_vector": dict(session.get("move_vector", {"x": 0.0, "y": 0.0})),
            "move_target": command_state.get("move_target"),
            "selected_target_kind": command_state.get("selected_target_kind"),
            "selected_target_id": command_state.get("selected_target_id"),
            "selected_target_name": command_state.get("selected_target_name"),
            "selected_target_tag": command_state.get("selected_target_tag"),
            "selected_world": command_state.get("selected_world"),
            "pending_action": command_state.get("pending_action"),
            "pending_semantic_action": command_state.get("pending_semantic_action"),
            "pending_action_family": command_state.get("pending_action_family"),
            "aim_world": session.get("aim_world"),
            "look_yaw": session.get("look_yaw"),
            "look_pitch": session.get("look_pitch"),
            "intent_state": dict(session.get("intent_state", {})),
            "talk_target_kind": command_state.get("talk_target_kind"),
            "talk_target_id": command_state.get("talk_target_id"),
            "talk_target_name": command_state.get("talk_target_name"),
            "talk_target_tag": command_state.get("talk_target_tag"),
        }
        if session["target_kind"] == "human":
            payload["human_id"] = session["target_id"]
            payload["human_name"] = session["target_name"]
        elif session["target_kind"] == "entity":
            payload["entity_id"] = session["target_id"]
            payload["entity_name"] = session["target_name"]
        return payload

    @staticmethod
    def _empty_command_state() -> dict[str, Any]:
        return empty_command_state()

    @staticmethod
    def _clear_command_state(session: dict[str, Any]) -> None:
        session["command_state"] = PlayerControlRuntime._empty_command_state()

    def _resolve_target_name_from_id(self, engine: Any, target_kind: str, target_id: str | None) -> str | None:
        wanted_id = str(target_id or "").strip()
        if not wanted_id:
            return None
        if target_kind == "entity":
            for slot, entity_uid in enumerate(engine._entity_uid_by_slot):
                if entity_uid == wanted_id and 0 <= slot < engine.state.m_tensor.shape[0]:
                    return engine._type_label(int(engine.state.m_tensor[slot, cfg.M_TYPE]))
            return None
        for slot, human_uid in enumerate(engine._human_uid_by_slot):
            if human_uid != wanted_id:
                continue
            resident = engine.resident_store.get(human_uid)
            return str(resident["profile"]["name"]) if resident else human_uid
        return None

    def _resolve_target_slot_from_id(self, engine: Any, target_kind: str, target_id: str | None) -> int:
        wanted_id = str(target_id or "").strip()
        if not wanted_id:
            return -1
        if target_kind == "entity":
            for slot, entity_uid in enumerate(engine._entity_uid_by_slot):
                if entity_uid == wanted_id:
                    return slot
            return -1
        for slot, human_uid in enumerate(engine._human_uid_by_slot):
            if human_uid == wanted_id:
                return slot
        return -1

    def _normalize_control_event(
        self,
        engine: Any,
        payload: dict[str, Any],
        *,
        session: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return normalize_control_event(
            payload,
            session_target_kind=(session or {}).get("target_kind"),
            session_context=(session or {}).get("control_context"),
            session_view_style=(session or {}).get("view_style"),
            resolve_target_name=lambda target_kind, target_id: self._resolve_target_name_from_id(
                engine,
                target_kind,
                target_id,
            ),
        )

    def _apply_event_to_session(self, session: dict[str, Any], normalized_event: dict[str, Any]) -> None:
        semantic_action = str(normalized_event.get("semantic_action", "")).strip().lower()
        if semantic_action in {"cancel", "clear_selection"}:
            session["move_vector"] = {"x": 0.0, "y": 0.0}
            session["command_state"] = self._empty_command_state()
            return

        session["control_context"] = str(normalized_event.get("context") or session.get("control_context") or "")
        session["view_style"] = str(normalized_event.get("view_style") or session.get("view_style") or "")
        session["command_state"] = apply_semantic_event_to_command_state(
            session.get("command_state", self._empty_command_state()),
            normalized_event,
        )
        if semantic_action == "move":
            session["move_vector"] = {"x": 0.0, "y": 0.0}

    def _resolve_human_target(
        self,
        engine: Any,
        *,
        human_id: str | None = None,
        human_name: str | None = None,
    ) -> dict[str, Any] | None:
        wanted_id = str(human_id or "").strip()
        wanted_name = str(human_name or "").strip().lower()
        h_mask = _live_human_mask(engine.state.h_tensor)
        for slot in torch.where(h_mask)[0].tolist():
            slot_human_id = engine._human_uid_by_slot[slot]
            if slot_human_id is None:
                continue
            resident = engine.resident_store.get(slot_human_id)
            resident_name = str(resident["profile"]["name"]) if resident else slot_human_id
            if wanted_id and slot_human_id != wanted_id:
                continue
            if wanted_name and resident_name.lower() != wanted_name and slot_human_id.lower() != wanted_name:
                continue
            return {
                "target_kind": "human",
                "target_id": slot_human_id,
                "target_name": resident_name,
                "slot": slot,
                "human_id": slot_human_id,
                "human_name": resident_name,
            }
        return None

    def _resolve_entity_target(
        self,
        engine: Any,
        *,
        entity_id: str | None = None,
        entity_name: str | None = None,
    ) -> dict[str, Any] | None:
        wanted_id = str(entity_id or "").strip()
        wanted_name = str(entity_name or "").strip().lower()
        entity_mask = engine.state.m_tensor[:, cfg.M_TYPE] > 0
        for slot in torch.where(entity_mask)[0].tolist():
            slot_entity_id = engine._entity_uid_by_slot[slot]
            if slot_entity_id is None:
                continue
            entity_name_value = engine._type_label(int(engine.state.m_tensor[slot, cfg.M_TYPE]))
            if wanted_id and slot_entity_id != wanted_id:
                continue
            if wanted_name and entity_name_value.lower() != wanted_name and slot_entity_id.lower() != wanted_name:
                continue
            return {
                "target_kind": "entity",
                "target_id": slot_entity_id,
                "target_name": entity_name_value,
                "slot": slot,
                "entity_id": slot_entity_id,
                "entity_name": entity_name_value,
            }
        return None

    def _resolve_target(
        self,
        engine: Any,
        *,
        target_kind: str = "human",
        target_id: str | None = None,
        target_name: str | None = None,
        human_id: str | None = None,
        human_name: str | None = None,
        entity_id: str | None = None,
        entity_name: str | None = None,
    ) -> dict[str, Any] | None:
        normalized_kind = self._normalize_target_kind(target_kind)
        if normalized_kind == "entity":
            return self._resolve_entity_target(
                engine,
                entity_id=entity_id or target_id,
                entity_name=entity_name or target_name,
            )
        return self._resolve_human_target(
            engine,
            human_id=human_id or target_id,
            human_name=human_name or target_name,
        )

    def _record(self, tick: int, kind: str, **payload: Any) -> None:
        entry = {"tick": tick, "kind": kind}
        entry.update(payload)
        self.history.append(entry)
        self.history = self.history[-30:]

    def recent_interactions_for_target(
        self,
        *,
        target_kind: str,
        target_id: str,
        current_tick: int,
        horizon_ticks: int = 160,
    ) -> dict[str, Any] | None:
        normalized_kind = self._normalize_target_kind(target_kind)
        wanted_id = str(target_id or "").strip()
        if not wanted_id:
            return None

        best: dict[str, Any] | None = None
        for entry in reversed(self.history):
            if str(entry.get("kind", "")) != "event":
                continue
            if str(entry.get("click_target_kind", "")).strip().lower() != normalized_kind:
                continue
            if str(entry.get("click_target_id", "")).strip() != wanted_id:
                continue
            age_ticks = max(0, int(current_tick) - int(entry.get("tick", current_tick)))
            if age_ticks > int(horizon_ticks):
                continue
            action = str(entry.get("action", "")).strip().lower()
            semantic_action = str(entry.get("semantic_action", "")).strip().lower()
            signal_action = semantic_action or action
            reaction_base = {
                "attack": 1.0,
                "attack_target": 1.0,
                "interact": 0.18,
                "interact_target": 0.18,
                "select": 0.0,
                "select_target": 0.0,
                "focus_world_point": 0.0,
                "talk": 0.26,
                "talk_command": 0.26,
                "move": 0.0,
                "cancel": 0.0,
            }.get(signal_action, 0.18)
            consequence_base = {
                "attack": 1.0,
                "attack_target": 1.0,
                "interact": 0.62,
                "interact_target": 0.62,
                "select": 0.12,
                "select_target": 0.12,
                "focus_world_point": 0.08,
                "talk": 0.42,
                "talk_command": 0.42,
                "move": 0.0,
                "cancel": 0.0,
            }.get(signal_action, 0.35)
            freshness = max(0.0, 1.0 - (age_ticks / float(max(horizon_ticks, 1))))
            best = {
                "controller_id": entry.get("controller_id"),
                "actor_kind": entry.get("target_kind"),
                "actor_id": entry.get("target_id"),
                "target_kind": normalized_kind,
                "target_id": wanted_id,
                "event": entry.get("event"),
                "action": action,
                "semantic_action": semantic_action,
                "source_tick": int(entry.get("tick", current_tick)),
                "source_seq": entry.get("seq"),
                "source_key": f"{int(entry.get('tick', current_tick))}:{entry.get('controller_id', '')}:{signal_action}:{wanted_id}:{entry.get('seq', '')}",
                "age_ticks": age_ticks,
                "reaction_score": round(reaction_base * freshness, 3),
                "consequence_score": round(consequence_base * freshness, 3),
                "reaction_reason": f"manual_{signal_action}",
                "consequence_reason": f"manual_{signal_action}",
                "freshness": round(freshness, 3),
            }
            break
        return best

    def has_active_sessions(self) -> bool:
        return bool(self.sessions_by_controller)

    def has_active_entity_sessions(self) -> bool:
        return any(
            session.get("mode") == "possess" and session.get("target_kind") == "entity"
            for session in self.sessions_by_controller.values()
        )

    def controlled_human_mask(self, engine: Any) -> torch.Tensor:
        mask = torch.zeros(engine.state.h_tensor.shape[0], dtype=torch.bool, device=engine.state.device)
        for session in self.sessions_by_controller.values():
            if not self._has_direct_control(session, target_kind="human"):
                continue
            slot = int(session.get("slot", -1))
            if 0 <= slot < mask.shape[0]:
                mask[slot] = True
        return mask

    def controlled_entity_mask(self, engine: Any) -> torch.Tensor:
        mask = torch.zeros(engine.state.m_tensor.shape[0], dtype=torch.bool, device=engine.state.device)
        for session in self.sessions_by_controller.values():
            if not self._has_direct_control(session, target_kind="entity"):
                continue
            slot = int(session.get("slot", -1))
            if 0 <= slot < mask.shape[0]:
                mask[slot] = True
        return mask

    def controlled_mask(self, engine: Any) -> torch.Tensor:
        return self.controlled_human_mask(engine)

    def _describe_slot(self, slot: int, target_kind: str) -> dict[str, Any] | None:
        for session in self.sessions_by_controller.values():
            if session.get("target_kind") != target_kind:
                continue
            if int(session.get("slot", -1)) == slot:
                return self._session_payload(session)
        return None

    def describe_human_slot(self, slot: int) -> dict[str, Any] | None:
        return self._describe_slot(slot, "human")

    def describe_entity_slot(self, slot: int) -> dict[str, Any] | None:
        return self._describe_slot(slot, "entity")

    def describe_slot(self, slot: int) -> dict[str, Any] | None:
        return self.describe_human_slot(slot)

    def build_tick_context(self, engine: Any) -> dict[str, Any]:
        human_mask = self.controlled_human_mask(engine)
        entity_mask = self.controlled_entity_mask(engine)
        human_by_slot: dict[int, dict[str, Any]] = {}
        entity_by_slot: dict[int, dict[str, Any]] = {}
        sessions: list[dict[str, Any]] = []
        for session in self.sessions_by_controller.values():
            if not self._has_direct_control(session):
                continue
            slot = int(session.get("slot", -1))
            if slot < 0:
                continue
            buttons = dict(session.get("buttons", {}))
            command_state = dict(session.get("command_state", {}))
            selected_target_kind = str(command_state.get("selected_target_kind") or "")
            selected_target_id = str(command_state.get("selected_target_id") or "")
            payload = {
                "controller_id": session["controller_id"],
                "target_kind": session["target_kind"],
                "target_id": session["target_id"],
                "control_context": session.get("control_context"),
                "view_style": session.get("view_style"),
                "move_x": float(session.get("move_vector", {}).get("x", 0.0)),
                "move_y": float(session.get("move_vector", {}).get("y", 0.0)),
                "sprint": bool(buttons.get("sprint", False)),
                "attack": bool(buttons.get("attack", False)),
                "interact": bool(buttons.get("interact", False)),
                "move_target": command_state.get("move_target"),
                "aim_world": session.get("aim_world"),
                "look_yaw": session.get("look_yaw"),
                "look_pitch": session.get("look_pitch"),
                "intent_state": dict(session.get("intent_state", {})),
                "selected_target_kind": command_state.get("selected_target_kind"),
                "selected_target_id": command_state.get("selected_target_id"),
                "selected_target_name": command_state.get("selected_target_name"),
                "selected_target_tag": command_state.get("selected_target_tag"),
                "selected_world": command_state.get("selected_world"),
                "pending_action": command_state.get("pending_action"),
                "pending_semantic_action": command_state.get("pending_semantic_action"),
                "pending_action_family": command_state.get("pending_action_family"),
                "selected_target_slot": self._resolve_target_slot_from_id(
                    engine,
                    selected_target_kind or "human",
                    selected_target_id or None,
                ) if selected_target_id else -1,
            }
            sessions.append(payload)
            if session["target_kind"] == "human":
                human_by_slot[slot] = payload
            elif session["target_kind"] == "entity":
                entity_by_slot[slot] = payload
        return {
            "sessions": sessions,
            "human_controlled_mask": human_mask,
            "human_by_slot": human_by_slot,
            "entity_controlled_mask": entity_mask,
            "entity_by_slot": entity_by_slot,
            "controlled_mask": human_mask,
            "by_slot": human_by_slot,
        }

    def claim_target(
        self,
        engine: Any,
        *,
        controller_id: str = "local_player",
        target_kind: str = "human",
        target_id: str | None = None,
        target_name: str | None = None,
        mode: str = "possess",
        human_id: str | None = None,
        human_name: str | None = None,
        entity_id: str | None = None,
        entity_name: str | None = None,
    ) -> dict[str, Any]:
        controller_id = str(controller_id or "local_player").strip() or "local_player"
        target = self._resolve_target(
            engine,
            target_kind=target_kind,
            target_id=target_id,
            target_name=target_name,
            human_id=human_id,
            human_name=human_name,
            entity_id=entity_id,
            entity_name=entity_name,
        )
        if target is None:
            self.last_error = {
                "tick": engine.tick,
                "reason": "target_not_found",
                "target_kind": self._normalize_target_kind(target_kind),
                "target_id": target_id or human_id or entity_id,
                "target_name": target_name or human_name or entity_name,
            }
            return {
                "ok": False,
                "reason": "target_not_found",
                "target_kind": self._normalize_target_kind(target_kind),
                "target_id": target_id or human_id or entity_id,
                "target_name": target_name or human_name or entity_name,
            }

        target_key = self._target_key(target["target_kind"], target["target_id"])
        claimed_by = self.controller_by_target.get(target_key)
        if claimed_by is not None and claimed_by != controller_id:
            self.last_error = {
                "tick": engine.tick,
                "reason": "target_already_controlled",
                "target_kind": target["target_kind"],
                "target_id": target["target_id"],
                "controller_id": claimed_by,
            }
            return {
                "ok": False,
                "reason": "target_already_controlled",
                "target_kind": target["target_kind"],
                "target_id": target["target_id"],
                "controller_id": claimed_by,
            }

        if controller_id in self.sessions_by_controller:
            self.release_target(engine, controller_id=controller_id, emit_event=False)

        session = {
            "world_epoch": engine.world_epoch,
            "possession_epoch": uuid.uuid4().hex,
            "controller_id": controller_id,
            "target_kind": target["target_kind"],
            "target_id": target["target_id"],
            "target_name": target["target_name"],
            "slot": int(target["slot"]),
            "mode": self._normalize_mode(mode),
            "last_input_seq": -1,
            "last_applied_input_seq": -1,
            "last_consumed_command_seq": -1,
            "pending_inputs": [],
            "event_receipts": {},
            "last_seen_tick": engine.tick,
            "last_received_at": self.clock(),
            "move_vector": {"x": 0.0, "y": 0.0},
            "buttons": {"attack": False, "interact": False, "sprint": False},
            "aim_world": None,
            "look_yaw": 0.0,
            "look_pitch": 0.0,
            "intent_state": {},
            "control_context": None,
            "view_style": None,
            "queued_events": [],
            "command_state": self._empty_command_state(),
        }
        session["control_context"], session["view_style"] = merge_control_semantic_state(
            target_kind=target["target_kind"],
            current_context=session.get("control_context"),
            current_view_style=session.get("view_style"),
        )
        self.sessions_by_controller[controller_id] = session
        self.controller_by_target[target_key] = controller_id
        if hasattr(engine, "_queue_event"):
            engine._queue_event(
                "control_claimed",
                target["target_id"],
                int(target["slot"]),
                controller_id=controller_id,
                target_kind=target["target_kind"],
                mode=session["mode"],
            )
        self._record(
            engine.tick,
            "claim",
            controller_id=controller_id,
            target_kind=target["target_kind"],
            target_id=target["target_id"],
            target_name=target["target_name"],
            slot=int(target["slot"]),
            mode=session["mode"],
        )
        return {"ok": True, **self._session_payload(session)}

    def claim_control(
        self,
        engine: Any,
        *,
        controller_id: str = "local_player",
        human_id: str | None = None,
        human_name: str | None = None,
        mode: str = "possess",
    ) -> dict[str, Any]:
        return self.claim_target(
            engine,
            controller_id=controller_id,
            target_kind="human",
            target_id=human_id,
            target_name=human_name,
            mode=mode,
            human_id=human_id,
            human_name=human_name,
        )

    def release_target(
        self,
        engine: Any,
        *,
        controller_id: str | None = None,
        target_kind: str | None = None,
        target_id: str | None = None,
        human_id: str | None = None,
        entity_id: str | None = None,
        emit_event: bool = True,
    ) -> dict[str, Any]:
        controller_key = str(controller_id or "").strip()
        if not controller_key:
            lookup_kind = self._normalize_target_kind(target_kind or ("entity" if entity_id else "human"))
            lookup_id = str(target_id or human_id or entity_id or "").strip()
            if lookup_id:
                controller_key = self.controller_by_target.get(self._target_key(lookup_kind, lookup_id), "")
        if not controller_key:
            return {"ok": False, "reason": "session_not_found"}

        session = self.sessions_by_controller.pop(controller_key, None)
        if session is None:
            return {"ok": False, "reason": "session_not_found", "controller_id": controller_key}

        self.controller_by_target.pop(self._target_key(session["target_kind"], session["target_id"]), None)
        if emit_event and hasattr(engine, "_queue_event"):
            engine._queue_event(
                "control_released",
                session["target_id"],
                int(session["slot"]),
                controller_id=controller_key,
                target_kind=session["target_kind"],
            )
        self._record(
            engine.tick,
            "release",
            controller_id=controller_key,
            target_kind=session["target_kind"],
            target_id=session["target_id"],
            target_name=session["target_name"],
            slot=int(session["slot"]),
        )
        return {"ok": True, **self._session_payload(session)}

    def release_control(
        self,
        engine: Any,
        *,
        controller_id: str | None = None,
        human_id: str | None = None,
        emit_event: bool = True,
    ) -> dict[str, Any]:
        return self.release_target(
            engine,
            controller_id=controller_id,
            target_kind="human",
            target_id=human_id,
            human_id=human_id,
            emit_event=emit_event,
        )

    def set_mode(self, engine: Any, *, controller_id: str, mode: str) -> dict[str, Any]:
        controller_id = str(controller_id or "").strip()
        session = self.sessions_by_controller.get(controller_id)
        if session is None:
            return {"ok": False, "reason": "session_not_found", "controller_id": controller_id}
        session["mode"] = self._normalize_mode(mode)
        self._record(
            engine.tick,
            "set_mode",
            controller_id=controller_id,
            target_kind=session["target_kind"],
            target_id=session["target_id"],
            mode=session["mode"],
        )
        return {"ok": True, **self._session_payload(session)}

    @staticmethod
    def _validate_envelope(engine, session, payload):
        if payload.get("protocol_version") != 1:
            return {"ok": False, "reason": "unsupported_protocol"}
        if payload.get("world_epoch") != engine.world_epoch:
            return {"ok": False, "reason": "stale_world_epoch"}
        if payload.get("possession_epoch") != session["possession_epoch"]:
            return {"ok": False, "reason": "stale_possession_epoch"}
        seq = payload.get("seq")
        if type(seq) is not int or not 0 <= seq <= 9007199254740991:
            return {"ok": False, "reason": "invalid_input_seq"}
        if outside_placed_maps(engine, session):  # authored worlds only: the actor is not inside any placed map
            return {"ok": False, "reason": "outside_placed_map"}
        return None

    def submit_input(self, engine: Any, controller_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        controller_id = str(controller_id or "").strip()
        session = self.sessions_by_controller.get(controller_id)
        if session is None:
            self.last_error = {"tick": engine.tick, "reason": "session_not_found", "controller_id": controller_id}
            return {"ok": False, "reason": "session_not_found", "controller_id": controller_id}

        error = self._validate_envelope(engine, session, payload)
        if error:
            return error
        if payload.get("target_id") != session["target_id"] or payload.get("target_kind") != session["target_kind"]:
            return {"ok": False, "reason": "controlled_target_mismatch"}
        try:
            move = payload.get("move", {})
            values = [move.get("x", 0), move.get("y", 0), payload.get("look_yaw", 0), payload.get("look_pitch", 0)]
            aim = payload.get("aim_world")
            if aim is not None:
                values.extend([aim.get("x", 0), aim.get("y", 0)])
            if any(isinstance(value, bool) or not math.isfinite(float(value)) for value in values):
                raise ValueError("Non-finite input")
        except (ValueError, TypeError, AttributeError, OverflowError):
            return {"ok": False, "reason": "invalid_control_input"}
        seq = payload["seq"]
        if seq <= int(session.get("last_input_seq", -1)):
            self.last_error = {
                "tick": engine.tick,
                "reason": "stale_input_seq",
                "controller_id": controller_id,
                "seq": seq,
                "last_input_seq": int(session.get("last_input_seq", -1)),
            }
            return {
                "ok": False,
                "reason": "stale_input_seq",
                "controller_id": controller_id,
                "seq": seq,
                "last_input_seq": int(session.get("last_input_seq", -1)),
            }

        move = payload.get("move", {}) if isinstance(payload.get("move", {}), dict) else {}
        move_x = _clamp(float(move.get("x", 0.0)), -1.0, 1.0)
        move_y = _clamp(float(move.get("y", 0.0)), -1.0, 1.0)
        length = (move_x ** 2 + move_y ** 2) ** 0.5
        if length > 1e-6 and length > 1.0:
            move_x /= length
            move_y /= length

        buttons = payload.get("buttons", {}) if isinstance(payload.get("buttons", {}), dict) else {}
        aim = payload.get("aim_world") if isinstance(payload.get("aim_world"), dict) else None
        intent_state = payload.get("intent_state") if isinstance(payload.get("intent_state"), dict) else {}
        look_yaw = _clamp(float(payload.get("look_yaw", session.get("look_yaw", 0.0) or 0.0)), -math.tau, math.tau)
        look_pitch = _clamp(float(payload.get("look_pitch", session.get("look_pitch", 0.0) or 0.0)), -1.57, 1.57)

        if len(session["pending_inputs"]) >= 64:
            return {"ok": False, "reason": "input_queue_full"}
        updates = {}
        updates["control_context"], updates["view_style"] = merge_control_semantic_state(
            target_kind=session.get("target_kind"),
            current_context=session.get("control_context"),
            current_view_style=session.get("view_style"),
            incoming_context=payload.get("context"),
            incoming_view_style=payload.get("view_style"),
        )

        updates["move_vector"] = {"x": round(move_x, 4), "y": round(move_y, 4)}
        updates["buttons"] = {
            "attack": bool(buttons.get("attack", False)),
            "interact": bool(buttons.get("interact", False)),
            "sprint": bool(buttons.get("sprint", False)),
        }
        updates["aim_world"] = (
            {
                "x": round(float(aim.get("x", 0.0)), 2),
                "y": round(float(aim.get("y", 0.0)), 2),
            }
            if aim is not None
            else None
        )
        updates["look_yaw"] = round(float(look_yaw), 4)
        updates["look_pitch"] = round(float(look_pitch), 4)
        updates["intent_state"] = {
            "moving": bool(intent_state.get("moving", False)),
            "sprinting": bool(intent_state.get("sprinting", False)),
            "attacking": bool(intent_state.get("attacking", False)),
            "talking": bool(intent_state.get("talking", False)),
        }
        session["pending_inputs"].append({"seq": seq, "received_at": self.clock(), "updates": updates,
                                          "clear_move_target": abs(move_x) > 0.001 or abs(move_y) > 0.001})
        session["last_input_seq"] = seq
        session["last_seen_tick"] = engine.tick
        session["last_received_at"] = self.clock()
        return {
            "ok": True,
            "controller_id": controller_id,
            "target_kind": session["target_kind"],
            "target_id": session["target_id"],
            "slot": int(session["slot"]),
            "seq": seq,
        }

    def submit_event(self, engine: Any, controller_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        controller_id = str(controller_id or "").strip()
        session = self.sessions_by_controller.get(controller_id)
        if session is None:
            return {"ok": False, "reason": "session_not_found", "controller_id": controller_id}

        error = self._validate_envelope(engine, session, payload)
        if error:
            return error
        seq = payload["seq"]
        event_id = payload.get("event_id")
        fingerprint = None
        if event_id is not None:
            try:
                if not isinstance(event_id, str):
                    raise ValueError("Invalid ID")
                event_id = uuid.UUID(event_id).hex
                encoded = json.dumps({k: v for k, v in payload.items() if k not in ("seq", "event_id")},
                                     sort_keys=True, allow_nan=False).encode("utf-8")
                if len(encoded) > 16384:
                    raise ValueError("Oversized event")
                fingerprint = hashlib.sha256(encoded).hexdigest()
            except (ValueError, TypeError, AttributeError):
                return {"ok": False, "reason": "invalid_control_event"}
            previous = session["event_receipts"].get(event_id)
            if previous is not None:
                if previous["fingerprint"] != fingerprint:
                    return {"ok": False, "reason": "event_id_conflict"}
                return {**previous["result"], "duplicate": True}
            # Never evict IDs within a possession: eviction would permit old retries.
            if len(session["event_receipts"]) >= 4096:
                return {"ok": False, "reason": "event_receipts_full"}
        # Legacy clients retain shared sequencing. Identified events are independent
        # of movement sequence, so a later-arriving click survives a newer input.
        if event_id is None and seq <= int(session.get("last_input_seq", -1)):
            return {
                "ok": False,
                "reason": "stale_input_seq",
                "controller_id": controller_id,
                "seq": seq,
                "last_input_seq": int(session.get("last_input_seq", -1)),
            }
        if len(session["pending_inputs"]) >= 64:
            return {"ok": False, "reason": "input_queue_full"}
        event_payload = self._normalize_control_event(engine, payload, session=session)
        event_payload["seq"] = seq
        if event_id is not None:
            event_payload["event_id"] = event_id
        session["pending_inputs"].append({"seq": seq, "received_at": self.clock(), "event": event_payload})
        if event_id is None:
            session["last_input_seq"] = seq
        session["last_seen_tick"] = engine.tick
        session["last_received_at"] = self.clock()
        result = {
            "ok": True,
            "controller_id": controller_id,
            "event": event_payload["event"],
            "action": event_payload["action"],
            "semantic_action": event_payload.get("semantic_action"),
            "target_kind": event_payload.get("target_kind"),
            "target_id": event_payload.get("target_id"),
            "seq": seq,
        }
        if event_id is not None:
            result.update(event_id=event_id, status="received")
            session["event_receipts"][event_id] = {"fingerprint": fingerprint, "result": result}
        return dict(result)

    @staticmethod
    def _event_status(session, event_payload, status, tick):
        receipt = session["event_receipts"].get(event_payload.get("event_id"))
        if receipt is not None:
            receipt["result"].update(status=status, consumed_tick=tick)

    def event_result(self, engine, controller_id, event_id, world_epoch, possession_epoch):
        session = self.sessions_by_controller.get(controller_id)
        if session is None:
            return {"ok": False, "reason": "session_not_found"}
        error = self._validate_envelope(engine, session, {"protocol_version": 1, "seq": 0,
                                       "world_epoch": world_epoch, "possession_epoch": possession_epoch})
        if error:
            return error
        try:
            event_id = uuid.UUID(event_id).hex
        except (ValueError, TypeError, AttributeError):
            return {"ok": False, "reason": "invalid_event_id"}
        receipt = session["event_receipts"].get(event_id)
        return copy.deepcopy(receipt["result"]) if receipt else {"ok": False, "reason": "event_not_found"}

    def _commit_event(self, engine, session, event_payload):
        controller_id = session["controller_id"]
        seq = event_payload["seq"]
        # Only talk events need a separate drain; other actions live in command_state.
        if event_payload.get("semantic_action") == "talk_command" or event_payload.get("action") == "talk":
            session["queued_events"].append(event_payload)
        self._apply_event_to_session(session, event_payload)
        if event_payload.get("event_id") and (event_payload.get("action") == "attack" or event_payload.get("semantic_action") == "attack_target"):
            session["tick_attack_event_id"] = event_payload["event_id"]
        # Consumed means dispatched to the semantic command state, not combat success.
        self._event_status(session, event_payload, "consumed", engine.tick)
        self._record(
            engine.tick,
            "event",
            controller_id=controller_id,
            target_kind=session["target_kind"],
            target_id=session["target_id"],
            event=event_payload["event"],
            action=event_payload["action"],
            semantic_action=event_payload.get("semantic_action"),
            click_target_kind=event_payload.get("target_kind"),
            click_target_id=event_payload.get("target_id"),
            text=event_payload.get("text"),
            talk_mode=event_payload.get("talk_mode"),
            context=event_payload.get("context"),
            view_style=event_payload.get("view_style"),
            seq=seq,
            event_id=event_payload.get("event_id"),
        )

    def drain_talk_events(self, engine: Any) -> list[dict[str, Any]]:
        drained: list[dict[str, Any]] = []
        for controller_id, session in self.sessions_by_controller.items():
            queued_events = list(session.get("queued_events", []))
            if not queued_events:
                continue
            drained_any = False
            kept_events: list[dict[str, Any]] = []
            for event_payload in queued_events:
                semantic_action = str(event_payload.get("semantic_action", "")).strip().lower()
                legacy_action = str(event_payload.get("action", "")).strip().lower()
                if semantic_action != "talk_command" and legacy_action != "talk":
                    kept_events.append(event_payload)
                    continue
                drained_any = True
                drained.append(
                    {
                        "controller_id": controller_id,
                        "session": self._session_payload(session),
                        "event": dict(event_payload),
                    }
                )
            session["queued_events"] = kept_events
            if drained_any:
                command_state = dict(session.get("command_state", self._empty_command_state()))
                pending_semantic_action = str(command_state.get("pending_semantic_action", "")).strip().lower()
                pending_action = str(command_state.get("pending_action", "")).strip().lower()
                if pending_semantic_action == "talk_command" or pending_action == "talk":
                    command_state["pending_action"] = None
                    command_state["pending_semantic_action"] = None
                    command_state["pending_action_family"] = None
                session["command_state"] = command_state
        return drained

    def begin_tick_inputs(self, engine):
        """Consume bounded ingress at the authoritative tick boundary."""
        for session in self.sessions_by_controller.values():
            processed = 0
            for command in session["pending_inputs"]:
                processed += 1
                if self.clock() - command["received_at"] >= self.input_timeout:
                    self._event_status(session, command.get("event", {}), "expired", engine.tick)
                    continue
                session["tick_command_seq"] = max(command["seq"], session.get("tick_command_seq", session["last_consumed_command_seq"]))
                if "event" in command:
                    self._commit_event(engine, session, command["event"])
                    if command["event"].get("event_id") and (command["event"].get("action") == "attack" or command["event"].get("semantic_action") == "attack_target"):
                        # The combat phase consumes one pending attack per actor.
                        # Preserve following commands until that phase has run.
                        break
                    continue
                session.update(command["updates"])
                if command["clear_move_target"]:
                    state = dict(session["command_state"])
                    for key in ("move_target", "pending_action", "pending_semantic_action", "pending_action_family"):
                        state[key] = None
                    session["command_state"] = state
                session["tick_input_seq"] = command["seq"]
            del session["pending_inputs"][:processed]

    def commit_tick_inputs(self, engine):
        """Pair applied acknowledgments with exact post-collision state.

        Ingress may advance last_input_seq between ticks, but this snapshot is
        replaced only at commit. A snapshot tick is the zero-based completed tick.
        """
        for session in self.sessions_by_controller.values():
            if "tick_command_seq" in session:
                session["last_consumed_command_seq"] = session.pop("tick_command_seq")
            if "tick_input_seq" in session:
                session["last_applied_input_seq"] = session.pop("tick_input_seq")
                session["active_input_ticks"] = 0
            if session["last_applied_input_seq"] >= 0:
                session["active_input_ticks"] = session.get("active_input_ticks", 0) + 1
            slot = int(session["slot"])
            entity = session["target_kind"] == "entity"
            tensor = engine.state.m_tensor if entity else engine.state.h_tensor
            ids = engine._entity_uid_by_slot if entity else engine._human_uid_by_slot
            if slot < 0 or slot >= len(ids) or ids[slot] != session["target_id"]:
                session["committed_state"] = None
                continue
            x_col, y_col = (cfg.CX, cfg.CY) if entity else (cfg.X, cfg.Y)
            session["committed_state"] = {
                "protocol_version": 1,
                "world_epoch": session["world_epoch"],
                "possession_epoch": session["possession_epoch"],
                "target_kind": session["target_kind"],
                "target_id": session["target_id"],
                "completed_tick": int(engine.tick),
                "last_applied_input_seq": int(session["last_applied_input_seq"]),
                "input_applied_seconds": session.get("active_input_ticks", 0) / cfg.TICK_RATE_HZ,
                "position": {"x": float(tensor[slot, x_col]), "y": float(tensor[slot, y_col])},
            }
            teleports = getattr(engine, "_teleport_seq", {}).get(session["target_id"], 0) if not entity else 0
            if teleports:  # absent means "never teleported"; the client snaps when it increases
                session["committed_state"]["teleport_seq"] = teleports

    def tick_maintenance(self, engine: Any) -> None:
        for controller_id, session in list(self.sessions_by_controller.items()):
            age = self.clock() - session["last_received_at"]
            if age >= self.possession_timeout:
                self.release_target(engine, controller_id=controller_id)
                self._record(engine.tick, "timeout", controller_id=controller_id)
                continue
            if age >= self.input_timeout:
                session["move_vector"] = {"x": 0.0, "y": 0.0}
                session["buttons"] = {"attack": False, "interact": False, "sprint": False}
                session["intent_state"] = {}
                session["command_state"] = self._empty_command_state()
                for command in session["pending_inputs"]:
                    self._event_status(session, command.get("event", {}), "expired", engine.tick)
                session["pending_inputs"].clear()
                session["queued_events"].clear()
            slot = int(session.get("slot", -1))
            target_kind = str(session.get("target_kind", "human"))
            target_id = str(session.get("target_id", ""))
            if target_kind == "entity":
                valid = (
                    0 <= slot < engine.state.m_tensor.shape[0]
                    and bool(engine.state.m_tensor[slot, cfg.M_TYPE] > 0)
                    and engine._entity_uid_by_slot[slot] == target_id
                )
            else:
                valid = (
                    0 <= slot < engine.state.h_tensor.shape[0]
                    and bool(engine.state.h_tensor[slot, cfg.TYPE] == cfg.AGENT_TYPE_HUMAN)
                    and engine._human_uid_by_slot[slot] == target_id
                )
            if valid:
                continue
            self.sessions_by_controller.pop(controller_id, None)
            self.controller_by_target.pop(self._target_key(target_kind, target_id), None)
            self._record(
                engine.tick,
                "lost",
                controller_id=controller_id,
                target_kind=target_kind,
                target_id=target_id,
                slot=slot,
            )

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "active_sessions": len(self.sessions_by_controller),
            "sessions": [self._session_payload(session) for session in self.sessions_by_controller.values()],
            "history": self.history[-10:],
            "last_error": self.last_error,
        }
