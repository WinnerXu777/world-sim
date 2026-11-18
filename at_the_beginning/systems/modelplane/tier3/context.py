"""Typed prompt context for the three Tier 3 roles. Everything a model sees is built here from an explicit whitelist: the resident's own
needs, the perceived scene (feature columns), short goal and plan summaries, and the affordance options that are legal right now. Never a
dump of a record, a pack of someone else, or the world tensors; ``assert_case`` is the tripwire the tests use.

Resident case (``plan_ops`` mode)::

    {"resident_id", "tick", "reason", "needs": {hunger, thirst, stamina, hp, threat, mood: 0..100}, "scene": {feature name: value},
     "goals": str, "plan": str, "options": [{"verb", "params", "distance"?}], "plan_ops": [verb ids], "limits": {...}}
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional

MAX_CASE_CHARS = 6000
MAX_OPTIONS = 12
OPTIONS_PER_VERB = 2
SCENE_FEATURES = ("near_food", "near_water", "near_danger", "near_kin", "near_stranger", "has_food_item", "at_home", "at_station",
                  "is_night", "plan_active", "plan_step_failed", "goal_urgency", "closeness", "rival")
NEED_COLUMNS = ("hunger", "thirst", "stamina", "hp", "threat", "mood")
RESIDENT_CASE_KEYS = ("resident_id", "tick", "reason", "needs", "scene", "goals", "plan", "options", "plan_ops", "limits")
DIALOGUE_CASE_KEYS = ("resident_model_mode", "talk_mode", "speaker_id", "listener_id", "prompt_case")
PROMPT_CASE_KEYS = ("utterance", "speech_act", "tone", "topic", "outcome", "personality_summary", "relationship_summary",
                    "allowed_physical_intents")
WORLD_CASE_KEYS = ("query", "reason", "world", "powers", "limits")
FORBIDDEN_KEYS = ("inventory", "pack", "record", "relationships", "tensor", "h_tensor", "m_tensor", "memory", "memories", "secrets", "api_key")


class ContextError(ValueError):
    pass


def assert_case(case: dict, allowed_keys: tuple) -> dict:
    """Raise unless ``case`` has only whitelisted top-level keys, no forbidden key at any depth, and fits ``MAX_CASE_CHARS``."""
    extra = sorted(set(case) - set(allowed_keys))
    if extra:
        raise ContextError(f"case has keys outside the whitelist: {extra}")

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if str(key).lower() in FORBIDDEN_KEYS:
                    raise ContextError(f"forbidden key {key!r} in case")
                walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value)
    walk(case)
    size = len(json.dumps(case, separators=(",", ":"), default=str))
    if size > MAX_CASE_CHARS:
        raise ContextError(f"case is {size} characters, limit {MAX_CASE_CHARS}")
    return case


# -- resident ------------------------------------------------------------------------------------------------------------------------

def _destructive(verb: str) -> bool:
    from systems.actions.catalog import BY_ID
    return BY_ID[verb].risk != "reversible"


def resident_case(world, services, aff, actor: str, reason: str, *, batch=None, situation=None, max_options: int = MAX_OPTIONS,
                  max_steps: int = 6, min_confidence: float = 0.6, destructive_ops: bool = False) -> dict:
    """The ``plan_ops`` case for ``actor``: needs and scene from the Tier 1 feature builder, options from the affordance engine (legal now)."""
    from systems.actions.plan_ops import PLAN_OPS
    from systems.decision.features import build_features
    from systems.goal.prompt_view import summarize_goals
    from systems.planning.prompt_view import summarize_plans

    S = situation or aff.situation(actor, exact=False)
    obs = S.obs
    batch = batch if batch is not None and actor in batch.ids else build_features(world, services, [actor])
    row = batch.row(actor)
    record = obs.record or {}
    offered = sorted(v for v in PLAN_OPS if destructive_ops or not _destructive(v))      # a model is not shown destructive verbs unless the gate allows them
    legal = aff.options(actor, verbs=offered, situation=S)
    taken, ranked = {}, []
    for option in sorted(legal, key=lambda o: (o.distance if o.distance is not None else 0.0, o.verb, json.dumps(o.params, sort_keys=True, default=str))):
        taken[option.verb] = taken.get(option.verb, 0) + 1
        if taken[option.verb] <= OPTIONS_PER_VERB:
            ranked.append((taken[option.verb], option))
    ranked.sort(key=lambda pair: (pair[0], pair[1].distance if pair[1].distance is not None else 0.0, pair[1].verb))
    options = []
    for _, option in ranked[:max_options]:
        item = {"verb": option.verb, "params": dict(option.params)}
        if option.distance is not None:
            item["distance"] = round(float(option.distance), 1)
        options.append(item)
    case = {
        "resident_id": actor, "tick": int(obs.tick), "reason": str(reason),
        "needs": {"hunger": round(obs.hunger, 1), "thirst": round(obs.thirst, 1), "stamina": round(obs.stamina, 1), "hp": round(obs.hp, 1),
                  "threat": round(obs.threat, 1), "mood": round(obs.mood, 1)},
        "scene": {name: round(row[name], 3) for name in SCENE_FEATURES},
        "goals": summarize_goals(record, limit=3), "plan": summarize_plans(record, limit=2),
        "options": options, "plan_ops": offered,
        "limits": {"max_steps": int(max_steps), "min_confidence": float(min_confidence)},
    }
    return assert_case(case, RESIDENT_CASE_KEYS)


# -- dialogue ------------------------------------------------------------------------------------------------------------------------

@dataclass
class DecidedOutcome:
    """What Python already decided; the model only words it. ``outcome`` is a short factual sentence ("accepts the commission")."""
    speaker: str
    listener: str
    act: str = "greet"
    tone: str = "neutral"
    topic: str = ""
    outcome: str = ""
    utterance: str = ""                      # what was said to the speaker, if anything (direct talk)
    personality_summary: str = ""
    relationship_summary: str = ""
    allowed_intents: tuple = field(default_factory=tuple)
    mode: str = "talk_reply"                 # talk_reply | ambient_npc_talk


def relationship_words(record: Optional[dict], other: str) -> str:
    """"stranger" / "acquaintance" / "friend" / "rival" from the listener's own record of ``other`` (closeness and tags only)."""
    relation = ((record or {}).get("relationships") or {}).get(other)
    if not relation:
        return "stranger"
    if "rival" in (relation.get("tags") or []):
        return "rival"
    closeness = float(relation.get("closeness", 0.0))
    return "friend" if closeness >= 0.5 else "acquaintance" if closeness >= 0.1 else "wary" if closeness <= -0.2 else "stranger"


def dialogue_case(decided: DecidedOutcome) -> dict:
    prompt = {"speech_act": decided.act, "tone": decided.tone, "topic": decided.topic, "outcome": decided.outcome,
              "personality_summary": decided.personality_summary, "relationship_summary": decided.relationship_summary,
              "allowed_physical_intents": list(decided.allowed_intents)}
    if decided.utterance:
        prompt["utterance"] = decided.utterance[:300]
    case = {"resident_model_mode": decided.mode, "talk_mode": "direct_talk" if decided.utterance else "ambient", "speaker_id": decided.speaker,
            "listener_id": decided.listener, "prompt_case": prompt}
    assert_case(case, DIALOGUE_CASE_KEYS)
    assert_case(case["prompt_case"], PROMPT_CASE_KEYS)
    return case


# -- world ---------------------------------------------------------------------------------------------------------------------------

def power_catalog(registry=None, *, sample_ids=(), center=(0.0, 0.0)) -> list:
    """The god powers a director may propose: name, risk, argument names with their JSON types, and a minimal valid ``example`` call."""
    from harness import powers
    registry = registry or powers.REGISTRY
    out = []
    for name, spec in sorted(registry.powers.items()):
        props = (spec.schema or {}).get("properties", {})
        required = set((spec.schema or {}).get("required", []))
        example = {}
        for arg, prop in props.items():
            if arg not in required and arg != "targets":
                continue
            if arg == "targets":
                example[arg] = {"of": "humans", "ids": list(sample_ids)[:1]} if sample_ids else {"of": "humans", "limit": 1}
            elif arg == "center":
                example[arg] = [float(center[0]), float(center[1])]
            elif prop.get("type") == "number" or prop.get("type") == "integer":
                example[arg] = prop.get("default", 50 if prop.get("type") == "number" else 8)
            elif "enum" in prop:
                example[arg] = prop["enum"][0]
        out.append({"name": name, "risk": spec.extra.get("risk", "reversible"),
                    "args": {a: (p.get("type") or ("enum" if "enum" in p else "any")) for a, p in props.items()}, "example": example})
    return out


def world_case(query: str, reason: str, *, tick: int, residents: int, powers: list, max_intents: int = 3, extra: Optional[dict] = None) -> dict:
    world = {"tick": int(tick), "residents": int(residents), **{k: v for k, v in (extra or {}).items() if isinstance(v, (int, float, str, bool))}}
    case = {"query": str(query)[:500], "reason": str(reason), "world": world, "powers": [dict(p) for p in powers],
            "limits": {"max_intents": int(max_intents)}}
    return assert_case(case, WORLD_CASE_KEYS)
