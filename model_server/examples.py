"""Worked request/response examples per role, generated from the mock server so they cannot drift from the contract.

``python -m model_server.examples --write`` rewrites ``model_server/examples/*.json``; a test fails if the committed files differ
from what the contract and the mock produce, and checks every pair against ``parse_response``. ``latency_ms`` is pinned for display.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import contract as c

HERE = Path(__file__).resolve().parent / "examples"
EPOCH = "6f1c0d52-3a5e-4c1b-9d0a-0b5e7a1f2c11"

EXAMPLES = {
    "decide_commission": ("decide", {
        "job_id": "o_000001:decide", "role": "decide", "world_epoch": EPOCH, "state_revision": 3, "priority": "active",
        "deadline_ms": 1000, "cancel_token": "o_000001", "schema_version": 1,
        "payload": {"resident_id": "h_000004", "trigger": "commission_request:o_000001", "question_kind": "choice", "tick": 5120,
                    "topic": "commission",
                    "state": {"closeness": 0.4, "rival": False, "traits": {"greed": 0.6, "discipline": 0.7}, "pressures": {"security": 0.1},
                              "price": 18, "open_orders": 1, "capacity": 3, "missing": [], "forge_available": True},
                    "options": [
                        {"id": "accept_commission", "description": "Accept the commission and reserve the materials and payment.",
                         "tags": ["commission"]},
                        {"id": "refuse_busy", "description": "Refuse: too many open orders already.", "tags": ["commission"]}]}}),
    "decide_yes_no": ("decide", {
        "job_id": "j_17:decide", "role": "decide", "world_epoch": EPOCH, "state_revision": 12, "priority": "background",
        "deadline_ms": 2500, "cancel_token": "", "schema_version": 1,
        "payload": {"resident_id": "h_000002", "trigger": "plan_step_failed:e_000931", "question_kind": "yes_no", "tick": 9001,
                    "topic": "generic", "state": {"hunger": 71.0, "hp": 88.0},
                    "options": [{"id": "yes", "description": "Keep the current plan."}, {"id": "no", "description": "Drop the plan and ask for a new one."}]}}),
    "resident_urgent_react": ("resident", {
        "job_id": "resident:u1", "role": "resident", "world_epoch": EPOCH, "state_revision": 5120, "priority": "critical",
        "deadline_ms": 400, "cancel_token": "", "schema_version": 1,
        "payload": {"mode": "urgent_react", "cases": [{
            "resident_model_mode": "urgent_react", "human_id": "h_000123",
            "local_state": {"distress": 0.74, "threat": 82.0, "hp": 54.0, "stamina": 33.0},
            "nearby": {"predator": {"eid": 47, "distance": 6.5}}, "primary_goal": {"id": "survive"},
            "personality_summary": "guarded (caution=0.84)", "escalation": {}}]}}),
    "resident_resident_reasoning": ("resident", {
        "job_id": "resident:r1", "role": "resident", "world_epoch": EPOCH, "state_revision": 5120, "priority": "background",
        "deadline_ms": 8000, "cancel_token": "", "schema_version": 1,
        "payload": {"mode": "resident_reasoning", "cases": [{
            "world_model_mode": "resident_reasoning", "resident_id": "h_000123", "reason": "attack_event",
            "resident_context": {"goal_summary": "protect the family", "plan_summary": "none"}, "review_requested": True,
            "auto_plan": True}]}}),
    "resident_plan_ops": ("resident", {
        "job_id": "resident:p1", "role": "resident", "world_epoch": EPOCH, "state_revision": 5120, "priority": "background",
        "deadline_ms": 8000, "cancel_token": "", "schema_version": 1,
        "payload": {"mode": "plan_ops", "cases": [{
            "resident_id": "h_000123", "tick": 5120, "reason": "replan",
            "needs": {"hunger": 82.0, "thirst": 35.0, "stamina": 61.0, "hp": 90.0, "threat": 0.0, "mood": 55.0},
            "scene": {"neighbours": 1, "hostiles": 0, "at_home": False, "at_station": False, "is_night": False},
            "goals": ["keep the family fed"], "plan": "none",
            "options": [{"verb": "eat", "params": {"item": "rations"}}, {"verb": "rest", "params": {}},
                        {"verb": "go_to_work", "params": {}}],
            "plan_ops": ["eat", "rest", "go_to_work"], "limits": {"max_steps": 3, "min_confidence": 0.6}}]}}),
    "world_director": ("world", {
        "job_id": "world:d1", "role": "world", "world_epoch": EPOCH, "state_revision": 5120, "priority": "active",
        "deadline_ms": 8000, "cancel_token": "", "schema_version": 1,
        "payload": {"mode": "director", "cases": [{
            "query": "bless the harvest", "reason": "decree", "world": {"tick": 5120, "residents": 8},
            "powers": [{"name": "bless", "risk": "reversible", "example": {"targets": {"ids": ["h_000123"]}}},
                       {"name": "plague", "risk": "destructive", "example": {}}],
            "limits": {"max_intents": 2}}]}}),
    "dialogue_talk_reply": ("dialogue", {
        "job_id": "dialogue:t1", "role": "dialogue", "world_epoch": EPOCH, "state_revision": 5120, "priority": "active",
        "deadline_ms": 1500, "cancel_token": "", "schema_version": 1,
        "payload": {"mode": "talk_reply", "cases": [{
            "resident_model_mode": "talk_reply", "talk_mode": "direct_talk", "speaker_id": "h_player", "listener_id": "h_000123",
            "prompt_case": {"utterance": "I am going to kill you", "personality_summary": "guarded (caution=0.84, aggression=0.31)",
                            "relationship_summary": "neighbor",
                            "allowed_physical_intents": ["flee", "back_away", "scan_and_prepare", "counterattack", "call_help"]}}]}}),
    "world_decree": ("world", {
        "job_id": "world:d1", "role": "world", "world_epoch": EPOCH, "state_revision": 5120, "priority": "active",
        "deadline_ms": 8000, "cancel_token": "", "schema_version": 1,
        "payload": {"mode": "decree", "cases": [{
            "world_model_mode": "decree", "query": "let rain fall on the north fields", "sub_queries": [], "tool_bundle": {},
            "execution_limits": {"max_actions": 8}, "raw_payload": {"god_decree": "let rain fall on the north fields"}}]}}),
}


def build() -> dict:
    """{name: {"request": ..., "response": ...}} using the in-process mock server."""
    from fastapi.testclient import TestClient

    from .app import create_app
    from .config import ServerConfig

    client = TestClient(create_app(ServerConfig()))
    out = {}
    for name, (role, request) in EXAMPLES.items():
        c.parse_envelope(request)
        reply = client.post(c.ROLE_ROUTES[role], json=request)
        body = reply.json()
        body["latency_ms"] = 1.0
        if role == "decide":   # rounded for display and so the files are identical on every platform's libm
            body["result"]["probabilities"] = {k: round(v, 6) for k, v in body["result"]["probabilities"].items()}
        out[name] = {"request": request, "response": body}
    return out


def render(doc: dict) -> str:
    return json.dumps(doc, indent=2, sort_keys=False, ensure_ascii=False) + "\n"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    built = build()
    if "--write" in argv:
        HERE.mkdir(exist_ok=True)
        for name, pair in built.items():
            (HERE / f"{name}.json").write_text(render(pair), encoding="utf-8", newline="\n")
        print(f"wrote {len(built)} examples to {HERE}")
    else:
        print(render(built))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
