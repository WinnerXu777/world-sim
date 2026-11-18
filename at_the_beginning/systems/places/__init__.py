"""Place memory of a resident (``EDEN_PLACES=1``, default off): ``mark_place``, ``remember_place``, ``ask_directions``.

A resident's known places live in its own record, ``record["known_places"] = {name: {"target_place": {"x", "y"}, "space", "tick", "source"}}``. The nested ``target_place`` dict is the key the
window re-base already shifts (``actions/rebase.py`` walks ``RECORD_FIELDS``, which gains ``known_places``), so a remembered place keeps pointing at the same spot after a re-base. At most
``MAX_PLACES`` per resident (the oldest is forgotten). Nothing reads the memory for movement yet (the consumers are Tier 2/3 and the explore macro, later); the verbs make it real, readable
and testable. Design: ``1008_actions.md`` section 10.16.
"""
from __future__ import annotations

import os

ENV = "EDEN_PLACES"
MAX_PLACES = 16
MAX_NAME = 32
FIELD = "known_places"


def enabled() -> bool:
    return os.environ.get(ENV, "") == "1"


def clean_name(name) -> str:
    """The stored name: stripped, at most ``MAX_NAME`` characters; '' when it is not a usable name."""
    if not isinstance(name, str):
        return ""
    return " ".join(name.split())[:MAX_NAME]


def remember(record: dict, name: str, x: float, y: float, space: float, tick: int, source: str) -> dict:
    """Write one place into a record (dict-level, used by the Static and Engine record ops); drops the oldest beyond ``MAX_PLACES``."""
    places = record.setdefault(FIELD, {})
    places[name] = {"target_place": {"x": float(x), "y": float(y)}, "space": float(space), "tick": int(tick), "source": source}
    while len(places) > MAX_PLACES:
        oldest = min(places, key=lambda k: (places[k]["tick"], k))
        del places[oldest]
    return places[name]


HOSTILE = -0.2          # a resident does not give directions to someone it holds below this


def answer_directions(asker: dict, teller: dict, asker_id: str, name: str, tick: int) -> dict:
    """The asked resident's rules answer, applied to the two records: ``{"ok": True, "place": ...}`` copies the place to the asker, else ``{"ok": False, "reason": refuse_*}``."""
    place = ((teller.get(FIELD) or {}).get(name))
    if place is None:
        return {"ok": False, "reason": "refuse_unknown"}
    relation = ((teller.get("relationships") or {}).get(asker_id) or {})
    if float(relation.get("closeness", 0.0)) < HOSTILE:
        return {"ok": False, "reason": "refuse_distrust"}
    target = place["target_place"]
    remember(asker, name, target["x"], target["y"], place.get("space", 0.0), tick, "told")
    return {"ok": True, "place": name, "x": target["x"], "y": target["y"]}
