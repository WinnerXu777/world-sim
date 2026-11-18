"""Bounded, idempotent commands owned by one world epoch."""
from collections import deque
from copy import deepcopy
import hashlib
import json
import uuid

try:
    from systems.movement.map_contract import outside_placed_maps
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.movement.map_contract import outside_placed_maps


class CommandInbox:
    def __init__(self, capacity=128, result_capacity=4096):
        self.pending = deque()
        self.records = {}
        self.capacity = capacity
        self.result_capacity = result_capacity

    @staticmethod
    def authorize(engine, payload, action=None):
        if not isinstance(payload, dict) or not isinstance(payload.get("controller_id"), str):
            return "invalid_command_envelope"
        if payload.get("protocol_version") != 1:
            return "unsupported_protocol"
        if payload.get("world_epoch") != engine.world_epoch:
            return "stale_world_epoch"
        if isinstance(action, str) and action.startswith("god_"):
            # god mode is the controller NOT possessing anyone: no possession epoch exists, and an embodied
            # controller must release first (embodied -> release -> god -> possess again)
            if payload.get("controller_id") in engine.player_control.sessions_by_controller:
                return "release_possession_first"
            return None
        session = engine.player_control.sessions_by_controller.get(payload.get("controller_id"))
        if session is None or payload.get("possession_epoch") != session["possession_epoch"]:
            return "stale_possession_epoch"
        if not engine.player_control._has_direct_control(session, target_kind="human"):
            return "human_control_required"
        if outside_placed_maps(engine, session):
            return "outside_placed_map"
        return None

    def submit(self, engine, action, payload):
        reason = self.authorize(engine, payload, action)
        if reason:
            return {"ok": False, "status": "rejected", "reason": reason}
        command_id = payload.get("command_id")
        try:
            if not isinstance(command_id, str) or str(uuid.UUID(command_id)) != command_id:
                raise ValueError()
            encoded = json.dumps([action, payload], sort_keys=True, allow_nan=False).encode()
            if len(encoded) > 8192:
                raise ValueError()
        except (ValueError, TypeError):
            return {"ok": False, "status": "rejected", "reason": "invalid_command"}
        fingerprint = hashlib.sha256(encoded).hexdigest()
        previous = self.records.get(command_id)
        if previous:
            if previous["fingerprint"] != fingerprint:
                return {"ok": False, "status": "rejected", "reason": "command_id_conflict"}
            return deepcopy(previous["result"])
        if len(self.pending) >= self.capacity or len(self.records) >= self.result_capacity:
            return {"ok": False, "status": "rejected", "reason": "command_capacity_reached"}
        result = {"ok": True, "status": "received", "command_id": command_id,
                  "world_epoch": engine.world_epoch, "received_tick": engine.tick}
        self.records[command_id] = {"fingerprint": fingerprint, "result": result}
        self.pending.append((command_id, action, deepcopy(payload)))
        return deepcopy(result)

    def drain(self, engine, execute, limit=16):
        for _ in range(min(limit, len(self.pending))):
            command_id, action, payload = self.pending.popleft()
            reason = self.authorize(engine, payload, action)
            outcome = {"ok": False, "reason": reason} if reason else execute(engine, action, payload)
            previous = self.records[command_id]["result"]
            self.records[command_id]["result"] = {
                **previous, **deepcopy(outcome), "status": "applied" if outcome.get("ok") else "rejected",
                "applied_tick": engine.tick, "event_id": f"{engine.world_epoch}:{command_id}"}

    def result(self, command_id):
        record = self.records.get(command_id)
        return deepcopy(record["result"]) if record else None
