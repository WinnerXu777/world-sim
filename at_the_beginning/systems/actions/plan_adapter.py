"""Documented adapter between the legacy planning ontology (``systems/planning`` ``PLAN_OP_DEFS``: flat step fields such as ``target_id``) and the
S1 plan ops (``{"op": <verb id>, "args": {...}}``, ``plan_ops.PLAN_OPS``). ``systems/planning`` is not edited: its validator accepts only its own 13
ops, so a Tier 3 plan is held and run in the S1 form and, where a legacy op has an S1 verb, can be shown to / read from the planning side.

Both directions are conservative. A legacy op with no S1 verb, or one whose S1 arguments cannot be derived from the step (``gather_food_buffer``
has no ``source`` entity), is returned in ``unmapped`` with a stable reason; nothing is guessed. Pure functions, no world access.
"""
from __future__ import annotations

from .catalog import FROZEN_LEGACY

# legacy op -> (S1 verb, {legacy field: S1 arg}); fields not listed are dropped. ``None`` verb = no S1 verb yet (reason given).
LEGACY_TO_S1 = {
    "rest_until_safe": ("rest", {}),
    "recover_until_hp": ("rest", {}),                    # the S1 rest ends when stamina / hp are back; the threshold is not a verb argument
    "move_to_target": ("follow", {"target_id": "target"}),
    "move_to_place": ("go_to_work", {"place_hint": "place"}),
    "gather_food_buffer": (None, "needs_grounding"),     # gather_resource needs a source entity id the legacy step does not carry
    "wait_until_tick": (None, "no_s1_verb"),
    "observe_target": (None, "no_s1_verb"),
    "avoid_target": (None, "no_s1_verb"),
    "recruit_allies": (None, "no_s1_verb"),
    "attack_target_when_close": (None, "no_s1_verb"),
    "guard_place": (None, "no_s1_verb"),
    "steal_from_target_when_safe": (None, "no_s1_verb"),
    "return_home": (None, "no_s1_verb"),
}
S1_TO_LEGACY = {"rest": ("rest_until_safe", {}), "follow": ("move_to_target", {"target": "target_id"}),
                "go_to_work": ("move_to_place", {"place": "place_hint"})}


def from_legacy(steps) -> dict:
    """Legacy steps (``{"op", <fields>}``) -> ``{"steps": [S1 step], "unmapped": [(index, op, reason)]}``."""
    mapped, unmapped = [], []
    for index, step in enumerate(steps or []):
        op = str(step.get("op", "")) if isinstance(step, dict) else ""
        entry = LEGACY_TO_S1.get(op)
        if op in FROZEN_LEGACY:
            unmapped.append((index, op, "legacy_frozen"))
            continue
        if entry is None:
            unmapped.append((index, op, "unknown_legacy_op"))
            continue
        verb, fields = entry
        if verb is None:
            unmapped.append((index, op, fields))
            continue
        args = {s1: step[legacy] for legacy, s1 in fields.items() if step.get(legacy) not in (None, "", [])}
        if verb == "follow" and "target" not in args:
            unmapped.append((index, op, "missing_target"))
            continue
        mapped.append({"op": verb, "args": args})
    return {"steps": mapped, "unmapped": unmapped}


def to_legacy(steps) -> dict:
    """S1 steps -> ``{"steps": [legacy step], "unmapped": [(index, op, reason)]}`` (what the planning validator would accept)."""
    mapped, unmapped = [], []
    for index, step in enumerate(steps or []):
        op = str(step.get("op", "")) if isinstance(step, dict) else ""
        entry = S1_TO_LEGACY.get(op)
        if op in FROZEN_LEGACY:
            unmapped.append((index, op, "legacy_frozen"))
            continue
        if entry is None:
            unmapped.append((index, op, "no_legacy_op"))
            continue
        legacy_op, fields = entry
        args = step.get("args") or {}
        out = {"op": legacy_op, **{legacy: args[s1] for s1, legacy in fields.items() if args.get(s1) not in (None, "")}}
        mapped.append(out)
    return {"steps": mapped, "unmapped": unmapped}
