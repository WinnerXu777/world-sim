"""Roster file: which named residents a map starts with, their roles, anchors, traits and stock.

``world_data/rosters/<map_id>.json`` is backend-owned (the map file only labels anchors with ``for_role``; the
roster binds actual residents to anchors). Format::

    {"map_id": "starter_village", "needs_scale": 0.05, "age_scale": 0.05,
     "needs": {"threshold": 30, "ration": 25, "water": {"anchor": "village:use_well", "ticks": 40},
               "food": {"anchor": "village:use_campfire", "ticks": 60}},
     "residents": [{"key": "smith", "name": "Brann", "sex": 0, "age": 38, "role": "smith",
                    "archetype": "stoic_survivor", "traits": {"greed": 0.4},
                    "anchors": {"spawn": "...", "work": "...", "talk": "...", "sleep": "..."},
                    "stock": {"iron_ingot": 4}, "personal": {"hammer": 1, "coin": 20},
                    "inventory": {"slots": 16, "weight": 60.0}, "work_mode": "occupation"}]}
"""
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

ANCHOR_KEYS = {"spawn": ("spawn",), "work": ("work",), "talk": ("talk",), "sleep": ("sleep",), "home": ("door",), "rest": ("work", "sleep")}
WORK_MODES = ("occupation", "anchor_only")
RESIDENT_KEYS = {"key", "name", "sex", "age", "role", "archetype", "traits", "anchors", "stock", "personal", "inventory", "work_mode",
                 "needs_sites"}
ROSTER_KEYS = {"map_id", "needs_scale", "age_scale", "needs", "residents"}
NEEDS_KEYS = {"threshold", "ration", "trip_timeout_ticks", "water", "food"}
SITE_KEYS = {"anchor", "ticks"}
DEFAULT_NEEDS = {"threshold": 30.0, "ration": 25.0, "trip_timeout_ticks": 2400,
                 "water": {"anchor": None, "ticks": 40}, "food": {"anchor": None, "ticks": 60}}


@dataclass(frozen=True)
class Issue:
    """One finding of the roster parser or validator (severity ``error`` or ``warning``)."""
    severity: str
    path: str
    message: str

    def __str__(self):
        return f"{self.severity.upper()} {self.path}: {self.message}"


@dataclass(frozen=True)
class RosterResident:
    """One named resident as the roster file describes him."""
    key: str
    name: str
    sex: int
    age: float
    role: Optional[str]
    archetype: Optional[str]
    traits: dict
    anchors: dict
    stock: dict
    personal: dict
    inventory: Optional[dict]
    work_mode: str
    needs_sites: bool = True  # False: this resident never walks to the well/fire, he gets the free ration instead


@dataclass(frozen=True)
class Roster:
    """A parsed roster: its map, the pacing scales, the food/water settings and its residents."""
    map_id: str
    needs_scale: float
    residents: tuple = ()
    warnings: tuple = field(default=(), compare=False)
    age_scale: float = 1.0  # aging rate multiplier (1 game year is 30 s at 1.0; 0 stops aging)
    needs: dict = field(default_factory=lambda: json.loads(json.dumps(DEFAULT_NEEDS)), compare=False)  # food/water loop

    def by_key(self, key):
        return next((r for r in self.residents if r.key == key), None)


def _is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _loads_strict(text):
    def no_dupes(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError(f"duplicate JSON key {key!r}")
            out[key] = value
        return out

    def no_constant(name):
        raise ValueError(f"non-finite JSON constant {name}")
    return json.loads(text, object_pairs_hook=no_dupes, parse_constant=no_constant)


def _parse_needs(raw, error):
    """The food/water loop settings: defaults filled in, bad values reported through ``error``."""
    needs = json.loads(json.dumps(DEFAULT_NEEDS))
    if raw is None:
        return needs
    if not isinstance(raw, dict):
        error("needs", "must be an object")
        return needs
    for key in sorted(set(raw) - NEEDS_KEYS):
        error(f"needs.{key}", f"unknown key (known: {sorted(NEEDS_KEYS)})")
    for key, low, high in (("threshold", 5, 60), ("ration", 0, 100)):
        if key in raw:
            if _is_num(raw[key]) and low <= raw[key] <= high:
                needs[key] = float(raw[key])
            else:
                error(f"needs.{key}", f"must be a number in [{low}, {high}], got {raw[key]!r}")
    if "trip_timeout_ticks" in raw:
        value = raw["trip_timeout_ticks"]
        if isinstance(value, int) and not isinstance(value, bool) and 100 <= value <= 20000:
            needs["trip_timeout_ticks"] = value
        else:
            error("needs.trip_timeout_ticks", f"must be an integer in 100..20000, got {value!r}")
    for kind in ("water", "food"):
        if kind not in raw:
            continue
        site = raw[kind]
        if not isinstance(site, dict):
            error(f"needs.{kind}", "must be an object {anchor, ticks}")
            continue
        for key in sorted(set(site) - SITE_KEYS):
            error(f"needs.{kind}.{key}", f"unknown key (known: {sorted(SITE_KEYS)})")
        anchor = site.get("anchor")
        if anchor is not None and not (isinstance(anchor, str) and anchor):
            error(f"needs.{kind}.anchor", "must be an anchor id string or null (null = free ration)")
        elif "anchor" in site:
            needs[kind]["anchor"] = anchor
        if "ticks" in site:
            ticks = site["ticks"]
            if isinstance(ticks, int) and not isinstance(ticks, bool) and 1 <= ticks <= 1200:
                needs[kind]["ticks"] = ticks
            else:
                error(f"needs.{kind}.ticks", f"must be an integer in 1..1200, got {ticks!r}")
    return needs


def parse_roster(data):
    """Structural parse: (Roster | None, issues). Semantic checks against the maps live in validate.py."""
    from systems.crafting.resolver import crafting_recipe_ids  # noqa: F401  (import check: item data available)
    from systems.inventory.schema import ITEM_KIND_DEFS
    from systems.occupation.catalog import ALL_OCCUPATION_NAMES
    from systems.personality.catalog import ARCHETYPE_PRESETS, TRAIT_NAMES

    issues = []

    def error(path, message):
        issues.append(Issue("error", path, message))

    if not isinstance(data, dict):
        return None, [Issue("error", "$", "roster must be a JSON object")]
    for key in sorted(set(data) - ROSTER_KEYS):
        issues.append(Issue("warning", key, "unknown top-level key (ignored)"))
    map_id = data.get("map_id")
    if not isinstance(map_id, str) or not map_id:
        error("map_id", "must be a non-empty string")
    needs_scale = data.get("needs_scale", 1.0)
    if not (_is_num(needs_scale) and 0 < needs_scale <= 1.0):
        error("needs_scale", f"must be a number in (0, 1], got {needs_scale!r}")
    age_scale = data.get("age_scale", 1.0)
    if not (_is_num(age_scale) and 0 <= age_scale <= 1.0):
        error("age_scale", f"must be a number in [0, 1], got {age_scale!r}")
    needs = _parse_needs(data.get("needs"), error)
    entries = data.get("residents")
    if not isinstance(entries, list) or not entries:
        error("residents", "must be a non-empty list")
        entries = []
    residents, seen_keys, seen_names = [], set(), set()
    for index, item in enumerate(entries):
        path = f"residents[{index}]"
        if not isinstance(item, dict):
            error(path, "must be an object")
            continue
        for key in sorted(set(item) - RESIDENT_KEYS):
            issues.append(Issue("warning", f"{path}.{key}", "unknown key (ignored)"))
        key, name = item.get("key"), item.get("name")
        if not isinstance(key, str) or not key.isidentifier():
            error(f"{path}.key", f"must be an identifier string, got {key!r}")
        elif key in seen_keys:
            error(f"{path}.key", f"duplicate key {key!r}")
        seen_keys.add(key)
        if not isinstance(name, str) or not name.strip():
            error(f"{path}.name", "must be a non-empty string")
        elif name in seen_names:
            error(f"{path}.name", f"duplicate name {name!r}")
        seen_names.add(name)
        sex = item.get("sex", 0)
        if sex not in (0, 1) or isinstance(sex, bool):
            error(f"{path}.sex", f"must be 0 or 1, got {sex!r}")
        age = item.get("age", 25)
        if not (_is_num(age) and 16 <= age <= 90):
            error(f"{path}.age", f"must be a number in 16..90, got {age!r}")
        role = item.get("role")
        if role is not None and role not in ALL_OCCUPATION_NAMES:
            error(f"{path}.role", f"unknown occupation {role!r} (known: {list(ALL_OCCUPATION_NAMES)})")
        archetype = item.get("archetype")
        if archetype is not None and archetype not in ARCHETYPE_PRESETS:
            error(f"{path}.archetype", f"unknown archetype {archetype!r}")
        traits = item.get("traits", {})
        if not isinstance(traits, dict):
            error(f"{path}.traits", "must be an object")
            traits = {}
        for trait, value in traits.items():
            if trait not in TRAIT_NAMES:
                error(f"{path}.traits.{trait}", f"unknown trait (known: {list(TRAIT_NAMES)})")
            elif not (_is_num(value) and 0 <= value <= 1):
                error(f"{path}.traits.{trait}", f"must be a number in [0, 1], got {value!r}")
        anchors = item.get("anchors", {})
        if not isinstance(anchors, dict) or not anchors:
            error(f"{path}.anchors", "must be a non-empty object")
            anchors = {}
        for anchor_key, anchor_id in anchors.items():
            if anchor_key not in ANCHOR_KEYS:
                error(f"{path}.anchors.{anchor_key}", f"unknown anchor key (known: {sorted(ANCHOR_KEYS)})")
            elif not isinstance(anchor_id, str) or not anchor_id:
                error(f"{path}.anchors.{anchor_key}", "must be an anchor id string")
        if "spawn" not in anchors:
            error(f"{path}.anchors", "a resident needs a 'spawn' anchor")
        for label in ("stock", "personal"):
            bag = item.get(label, {})
            if not isinstance(bag, dict):
                error(f"{path}.{label}", "must be an object of item kind -> quantity")
                continue
            for kind, quantity in bag.items():
                if kind not in ITEM_KIND_DEFS:
                    error(f"{path}.{label}.{kind}", "unknown item kind")
                elif not (isinstance(quantity, int) and not isinstance(quantity, bool) and 0 < quantity <= 999):
                    error(f"{path}.{label}.{kind}", f"must be an integer in 1..999, got {quantity!r}")
        inventory = item.get("inventory")
        if inventory is not None:
            ok = (isinstance(inventory, dict) and set(inventory) <= {"slots", "weight"}
                  and isinstance(inventory.get("slots", 4), int) and not isinstance(inventory.get("slots", 4), bool)
                  and 1 <= inventory.get("slots", 4) <= 64 and _is_num(inventory.get("weight", 8.0)) and inventory.get("weight", 8.0) > 0)
            if not ok:
                error(f"{path}.inventory", "must be {slots: 1..64, weight: > 0}")
        work_mode = item.get("work_mode", "occupation")
        if work_mode not in WORK_MODES:
            error(f"{path}.work_mode", f"must be one of {WORK_MODES}")
        needs_sites = item.get("needs_sites", True)
        if not isinstance(needs_sites, bool):
            error(f"{path}.needs_sites", "must be true or false")
            needs_sites = True
        if isinstance(key, str) and isinstance(name, str):
            residents.append(RosterResident(key, name, int(sex) if sex in (0, 1) else 0, float(age) if _is_num(age) else 25.0, role,
                                            archetype, dict(traits), dict(anchors), dict(item.get("stock", {})),
                                            dict(item.get("personal", {})), dict(inventory) if isinstance(inventory, dict) else None,
                                            work_mode, needs_sites))
    if any(i.severity == "error" for i in issues):
        return None, issues
    return Roster(map_id, float(needs_scale), tuple(residents), tuple(i for i in issues if i.severity == "warning"), float(age_scale), needs), issues


def load_roster(path):
    """Read and parse a roster file. Never raises on bad content: returns (Roster | None, issues)."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, [Issue("error", "$", f"cannot read {path}: {exc}")]
    try:
        data = _loads_strict(text)
    except ValueError as exc:
        return None, [Issue("error", "$", f"invalid JSON: {exc}")]
    return parse_roster(data)
