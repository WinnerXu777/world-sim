from __future__ import annotations

"""Structured plan ontology for reasoning-lane resident plans."""

from typing import Final


PLAN_KIND_DEFS: Final[dict[str, dict[str, object]]] = {
    "ambush": {"horizon": "long", "label": "Ambush", "default_confidence": 0.62},
    "revenge": {"horizon": "long", "label": "Revenge plan", "default_confidence": 0.58},
    "recruit_support": {"horizon": "medium", "label": "Recruit support", "default_confidence": 0.6},
    "theft": {"horizon": "medium", "label": "Theft plan", "default_confidence": 0.56},
    "fortify_home": {"horizon": "medium", "label": "Fortify home", "default_confidence": 0.64},
    "scout_region": {"horizon": "medium", "label": "Scout region", "default_confidence": 0.54},
    "resource_raid": {"horizon": "medium", "label": "Resource raid", "default_confidence": 0.52},
    "escape_and_hide": {"horizon": "short", "label": "Escape and hide", "default_confidence": 0.7},
}


PLAN_OP_DEFS: Final[dict[str, dict[str, object]]] = {
    "recover_until_hp": {"requires": ["threshold"], "label": "Recover until HP threshold"},
    "wait_until_tick": {"requires": ["target_tick"], "label": "Wait until future tick"},
    "move_to_place": {"requires": ["place_hint"], "label": "Move to named place hint"},
    "move_to_target": {"requires": ["target_id"], "label": "Move toward target"},
    "observe_target": {"requires": ["target_id"], "label": "Observe target"},
    "avoid_target": {"requires": ["target_id"], "label": "Avoid target"},
    "recruit_allies": {"requires": [], "label": "Recruit allies"},
    "attack_target_when_close": {"requires": ["target_id"], "label": "Attack target when close"},
    "guard_place": {"requires": ["place_hint"], "label": "Guard place"},
    "steal_from_target_when_safe": {"requires": ["target_id"], "label": "Steal when safe"},
    "return_home": {"requires": [], "label": "Return home"},
    "rest_until_safe": {"requires": [], "label": "Rest until safe"},
    "gather_food_buffer": {"requires": [], "label": "Gather food buffer"},
}
