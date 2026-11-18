"""Deterministic stand-in answers per role, used by the mock and rules backends. Pure functions of the request.

Packets follow the legacy structured contracts in implement_llm.md so the game's own normalisers accept them.
"""
from __future__ import annotations

import hashlib
import json
import math
import os


def seed() -> str:
    """``EDEN_MODEL_MOCK_SEED``: names a different but equally deterministic mock. Empty (the default) keeps every answer as before."""
    return os.environ.get("EDEN_MODEL_MOCK_SEED", "")


def unit(*parts) -> float:
    """Stable float in [0, 1) from the parts (sha256, not Python's salted hash, so it is identical across processes)."""
    salt = seed()
    text = "|".join(str(p) for p in parts)
    digest = hashlib.sha256((f"{salt}|{text}" if salt else text).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2.0 ** 64


def softmax(scores: dict, temperature: float = 0.35) -> dict:
    peak = max(scores.values())
    weights = {k: math.exp((v - peak) / temperature) for k, v in scores.items()}
    total = sum(weights.values())
    return {k: w / total for k, w in weights.items()}


def decide_probabilities(payload: dict) -> dict:
    ids = [o["id"] for o in payload["options"]]
    if len(ids) == 1:
        return {ids[0]: 1.0}
    scores = {i: unit(payload["resident_id"], payload["trigger"], i) for i in ids}
    return softmax(scores)


def _pick(options, *seed):
    options = list(options)
    return options[int(unit(*seed) * len(options)) % len(options)]


def _num(value) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def urgent_packet(case: dict, mode: str) -> dict:
    state = case.get("local_state") or {}
    threat = _num(state.get("threat", state.get("distress", 0.0)))
    hunger = _num(state.get("hunger"))
    thirst = _num(state.get("thirst"))
    human_id = str(case.get("human_id", ""))
    if mode == "urgent_react":
        intent = "flee_predator" if threat >= 60 else "guard"
        action = {"type": "move_away" if threat >= 60 else "hold", "magnitude": 3.0}
    else:
        intent = "seek_food" if hunger >= thirst and hunger >= 40 else "seek_water" if thirst >= 40 else "rest"
        action = {"type": "move_toward" if intent != "rest" else "hold", "magnitude": 2.0}
    return {"resident_model_mode": mode, "human_id": human_id, "lane": "urgent" if mode == "urgent_react" else "normal_candidate",
            "intent": intent, "reason": f"mock {mode}", "action": action, "confidence": round(0.5 + 0.4 * unit(human_id, intent), 3),
            "followup": {"goal_review_requested": False, "reaction_ticket_requested": False, "consequence_ticket_requested": False}}


def reasoning_packet(case: dict) -> dict:
    reason = str(case.get("reason", "scheduled_review"))
    return {"resident_id": str(case.get("resident_id", "")), "reasoning_mode": "resident_reasoning", "reason": reason,
            "goal_review": {"requested": True, "reason": reason, "force": False}, "goal_updates": [], "plans": [],
            "auto_plan": False}


SPEECH = {"threat_response": "Stay away from me!", "alarm_response": "I will raise the alarm.", "trade_response": "Let us talk terms.",
          "apology_response": "Fine. Let it go.", "warn": "Careful, danger is near!", "greet": "Good day to you.",
          "comfort": "It will be alright.", "gossip": "Have you heard the news?"}


def dialogue_packet(case: dict, mode: str) -> dict:
    prompt = case.get("prompt_case") or {}
    allowed = prompt.get("allowed_physical_intents") or []
    act = str(prompt.get("speech_act") or ("threat_response" if mode == "talk_reply" else "greet"))
    return {"resident_model_mode": mode, "mode": str(case.get("talk_mode", mode)), "speaker_id": str(case.get("speaker_id", "")),
            "listener_id": str(case.get("listener_id", "")), "speech_text": SPEECH.get(act, "..."), "speech_act": act,
            "tone": str(prompt.get("tone", "neutral")),
            "physical_intent": _pick(allowed, case.get("speaker_id"), act) if allowed else "",
            "danger_upgrade": False, "reasoning_followup": False, "witness_policy": "nearby_hear", "relationship_delta": "neutral",
            "pressure_deltas": {}, "memory_salience": 0.3}


def decree_packet(case: dict) -> dict:
    return {"thought": "mock decree: no world operation", "map_actions": [], "human_actions": [], "new_entities": [],
            "new_instincts": []}


NEED_VERBS = {"hunger": ("eat",), "thirst": ("drink",), "stamina": ("rest", "sleep"), "threat": ("flee_to",)}


def plan_ops_packet(case: dict) -> dict:
    """A plan of 1..3 steps chosen from the OFFERED options only (the case lists them): needs first, then a seeded tie-break."""
    resident = str(case.get("resident_id", ""))
    options = [o for o in (case.get("options") or []) if isinstance(o, dict) and isinstance(o.get("verb"), str)]
    needs = case.get("needs") or {}
    limit = max(1, min(int((case.get("limits") or {}).get("max_steps", 3)), 3))

    def key(option):
        return json.dumps(option.get("params") or {}, sort_keys=True)

    def score(option):
        urgency = max([_num(needs.get(need)) / 100.0 for need, verbs in NEED_VERBS.items() if option["verb"] in verbs] or [0.0])
        return urgency * 2.0 + unit(resident, case.get("tick"), case.get("reason"), option["verb"], key(option))

    count = 1 + int(unit(resident, case.get("tick"), "n") * limit) % limit
    picked, seen = [], set()
    for option in sorted(options, key=lambda o: (-score(o), o["verb"], key(o))):
        if option["verb"] in seen:
            continue
        seen.add(option["verb"])
        picked.append(option)
        if len(picked) >= count:
            break
    steps = [{"op": o["verb"], "args": dict(o.get("params") or {})} for o in picked]
    return {"resident_id": resident, "summary": ("mock plan: " + ", ".join(s["op"] for s in steps)) if steps else "mock plan: nothing to do",
            "confidence": round(0.5 + 0.45 * unit(resident, case.get("tick"), case.get("reason"), "confidence"), 3), "steps": steps}


def director_packet(case: dict) -> dict:
    """At most one intent, from the powers the case offers (reversible ones only), with the case's ``example`` arguments."""
    powers = [p for p in (case.get("powers") or []) if isinstance(p, dict) and isinstance(p.get("name"), str) and p.get("risk", "reversible") != "destructive"]
    if not powers:
        return {"thought": "mock director: no suitable power", "intents": []}
    pick = powers[int(unit(case.get("query"), case.get("reason"), "power") * len(powers)) % len(powers)]
    return {"thought": f"mock director: {pick['name']}",
            "intents": [{"power": pick["name"], "args": dict(pick.get("example") or {}), "reason": str(case.get("query", ""))[:120]}]}


def packet_for(mode: str, case: dict) -> dict:
    if mode == "plan_ops":
        return plan_ops_packet(case)
    if mode == "director":
        return director_packet(case)
    if mode in ("urgent_react", "normal_live"):
        return urgent_packet(case, mode)
    if mode == "resident_reasoning":
        return reasoning_packet(case)
    if mode in ("talk_reply", "ambient_npc_talk"):
        return dialogue_packet(case, mode)
    return decree_packet(case)


def batch_result(payload: dict, source: str) -> dict:
    mode = payload["mode"]
    return {"mode": mode, "responses": [{"packet": packet_for(mode, case), "source": source} for case in payload["cases"]]}
