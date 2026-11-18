"""The creature definition table (``1008_creatures_gap.md`` section 3). DATA only: no torch, no engine, importable anywhere.

One row per species, keyed by name, resolved to an ``M_TYPE`` in 40..79. Ids and names are a contract with the asset side and are never renumbered (the tests pin
them). Numbers in the rows that are not the legacy five are PROPOSALS (the bible says the simulation owners choose temperament); rows with ``enabled=False`` carry
identity (id, name, frame, pivot, footprint) and a neutral body so a spawn plan can ignore them. ``validate()`` runs at import: a bad row stops the import with the
species name in the message.

Nothing here changes behaviour by itself. ``EDEN_CREATURES`` (``systems/creatures/__init__.py``) decides whether any consumer reads it.

Balance note (c3): tune after seeing the numbers in a village scenario. Targets: a wolf pack against the family farm kills rarely but really (casualties per day rare
but real), hunters can win, and deer are not extinct after 10 game days.
"""
from __future__ import annotations

from typing import Any, Optional

# size classes of the bible: (frame w, frame h, pivot x, pivot y)
FRAME_A = (128, 128, 64, 112)     # wolf, boar, fox, sheep, dog, cat, goat, goblin, skeleton, giant spider, brambleback, rootling, hollow rook
FRAME_B = (64, 64, 32, 56)        # rabbit, songbird, crow, chicken, fish, mire lantern, cinder moth, thread thief, glassfin
FRAME_C = (160, 160, 80, 144)     # deer, cow, horse, cairn keeper, bellhorn, moonhart

TIME_BLOCKS = ("dawn", "day", "dusk", "night")
TAME_MODES = ("wild", "tameable", "domestic")
TAME_ROLES = ("", "guard", "companion", "livestock", "mount", "pest")
PRODUCT_NEEDS = ("fed", "tame", "none")
BIG_CARCASS = 3000          # ticks a large kill stays harvestable (a proposal; the butchery verb belongs to the model plane)
DIET_EATS = ("grass", "carrion", "meat", "fish", "forest", "none")
HUMANS = ("never", "hungry", "cornered", "always")
GROUPS = ("solitary", "herd", "pack", "band")
BRAINS = ("legacy", "table")
STATES = {"idle": 0, "wander": 1, "flee": 2, "chase": 3, "rest": 4, "return": 5, "attack": 6}
# columns of a creature row beyond the A_* ones (all inside the free 17..29 range; 0 for every row that exists today)
C_VARIANT, C_STATE, C_STATE_TICKS, C_GROUP = 17, 18, 19, 20
MIN_ID, MAX_ID = 40, 79
ASSET_ROOT_STATIC = "a4/static/static-{name}-a4-v1.png"
STATIC_SPRITES = {"deer", "goat", "sheep"}      # the only wildlife art that exists today (worldgen/assets.py SPECIES_SPRITES)

_KEYS = {"id", "label", "frame", "footprint", "hp", "speed", "damage", "range", "cooldown", "aggro", "aggro_range", "flee_hp", "fear", "diet", "activity",
         "group", "territory", "life_exp", "mature", "habitat", "spawn_p", "loot", "hostile", "huntable", "flight", "swim", "brain", "variants", "enabled", "notes",
         "tame", "products", "threat", "perceive_radius", "carcass"}

_ALWAYS = {b: 1.0 for b in TIME_BLOCKS}


def _row(id_, label, frame, footprint, **kw) -> dict:
    row: dict[str, Any] = {
        "id": id_, "label": label, "frame": frame, "footprint": footprint,
        "hp": 40.0, "speed": {"walk": 1.0, "run": 2.5}, "damage": 0.0, "range": 0.0, "cooldown": 20,
        "aggro": 0.0, "aggro_range": 0.0, "flee_hp": 1.0, "fear": {"humans": False, "radius": 0.0, "species": []},
        "diet": {"eats": ["grass"], "prey": [], "humans": "never"}, "activity": dict(_ALWAYS),
        "group": {"kind": "solitary", "size": [1, 1], "cohesion": 0.0}, "territory": {"radius": 200.0, "leash": 320.0},
        "life_exp": [6.0, 14.0], "mature": 2.0, "habitat": {}, "spawn_p": 0.0, "loot": [], "hostile": False, "huntable": False, "flight": False, "swim": False,
        "brain": "table", "variants": [], "enabled": False, "notes": "",
        "tame": {"mode": "wild", "food": [], "to_tame": 0, "decay_per_day": 0.0, "role": ""}, "products": [], "threat": None, "perceive_radius": None,
        "carcass": {"ticks": 0},
    }
    row.update(kw)
    return row


def _loot(*items) -> list:
    return [{"item": i, "min": lo, "max": hi, "p": p} for i, lo, hi, p in items]


def _act(dawn, day, dusk, night) -> dict:
    return {"dawn": dawn, "day": day, "dusk": dusk, "night": night}


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------
# The five legacy species (ids, life expectancy, aggression, step, prey as in genesis_config; hp 100 as animal_born writes it today). ``brain: legacy`` until the
# kernel passes the parity tests; the rest of each row is the proposal.
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------
CREATURES: dict[str, dict] = {
    "sheep": _row(40, "sheep", FRAME_A, [10, 7], hp=100.0, speed={"walk": 2.0, "run": 3.0}, life_exp=[6.0, 12.0], aggro=0.0, brain="legacy", enabled=True,
                  fear={"humans": False, "radius": 0.0, "species": ["wolf", "tiger"]}, group={"kind": "herd", "size": [4, 10], "cohesion": 60.0},
                  activity=_act(0.7, 0.8, 0.7, 0.1), habitat={"spawn_entry": "sheep"}, spawn_p=0.10, huntable=True, territory={"radius": 250.0, "leash": 400.0},
                  loot=_loot(("meat", 1, 2, 1.0), ("wool", 1, 2, 0.8), ("hide", 1, 1, 0.5)), notes="existing; switch to the kernel after the parity test", tame={"mode": "domestic", "food": ['grass'], "to_tame": 0, "decay_per_day": 0.0, "role": 'livestock'}, products=[{"item": "wool", "every_days": 2, "needs": "fed"}], carcass={"ticks": BIG_CARCASS}),
    "deer": _row(41, "deer", FRAME_C, [12, 8], hp=100.0, speed={"walk": 3.5, "run": 5.0}, life_exp=[8.0, 16.0], flee_hp=1.0, brain="legacy", enabled=True,
                 fear={"humans": True, "radius": 70.0, "species": ["wolf", "tiger"]}, group={"kind": "herd", "size": [3, 8], "cohesion": 50.0},
                 activity=_act(0.8, 0.6, 0.9, 0.4), habitat={"spawn_entry": "deer"}, spawn_p=0.12, huntable=True, territory={"radius": 350.0, "leash": 500.0},
                 loot=_loot(("meat", 2, 3, 1.0), ("hide", 1, 1, 0.8), ("bone", 1, 2, 0.5)), notes="existing", carcass={"ticks": BIG_CARCASS}),
    "tiger": _row(42, "tiger", FRAME_A, [14, 8], hp=100.0, speed={"walk": 4.0, "run": 5.0}, damage=15.0, range=20.0, cooldown=1, life_exp=[10.0, 20.0],
                  aggro=0.9, aggro_range=60.0, flee_hp=0.2, diet={"eats": ["meat"], "prey": ["sheep", "deer"], "humans": "always"}, hostile=True,
                  brain="legacy", enabled=True, loot=_loot(("meat", 2, 3, 1.0), ("hide", 1, 1, 0.9)), territory={"radius": 300.0, "leash": 450.0},
                  activity=_act(0.7, 0.4, 0.8, 0.9), notes="existing; no spawn entry from the generator (god tools only)", carcass={"ticks": BIG_CARCASS}),
    "wolf": _row(43, "wolf", FRAME_A, [12, 7], hp=100.0, speed={"walk": 3.5, "run": 4.5}, damage=15.0, range=20.0, cooldown=1, life_exp=[8.0, 18.0],
                 aggro=0.7, aggro_range=60.0, flee_hp=0.25, diet={"eats": ["meat"], "prey": ["sheep", "deer"], "humans": "hungry"}, hostile=True,
                 group={"kind": "pack", "size": [3, 6], "cohesion": 80.0}, activity=_act(0.5, 0.4, 0.9, 1.0), brain="legacy", enabled=True,
                 habitat={"spawn_entry": "wolf"}, spawn_p=0.08, territory={"radius": 300.0, "leash": 450.0}, variants=["winter_wolf", "pack_leader"],
                 loot=_loot(("meat", 1, 2, 1.0), ("hide", 1, 1, 0.8), ("bone", 1, 1, 0.4)),
                 notes="existing; the legacy ANIMAL_PREY has no humans for wolves, the table says 'hungry' and takes effect only with the kernel", tame={"mode": "tameable", "food": ["meat"], "to_tame": 12, "decay_per_day": 1.0, "role": "guard"}, carcass={"ticks": BIG_CARCASS}),
    "fish": _row(44, "fish", FRAME_B, [6, 3], hp=100.0, speed={"walk": 1.5, "run": 2.0}, life_exp=[2.0, 6.0], swim=True, brain="legacy", enabled=True,
                 diet={"eats": ["none"], "prey": [], "humans": "never"}, huntable=True, loot=_loot(("fish_catch", 1, 1, 1.0)),
                 notes="lake loop stays legacy until a swim brain exists"),

    # ---- first set (proposals: 1008_creatures_gap.md section 8) ---------------------------------------------------------------------------------------------
    "boar": _row(45, "boar", FRAME_A, [12, 8], hp=80.0, speed={"walk": 1.2, "run": 3.4}, damage=14.0, range=12.0, cooldown=24, life_exp=[8.0, 15.0],
                 aggro=0.35, aggro_range=60.0, flee_hp=0.15, diet={"eats": ["forest", "carrion"], "prey": [], "humans": "cornered"}, hostile=True, huntable=True,
                 group={"kind": "solitary", "size": [1, 4], "cohesion": 30.0}, activity=_act(0.6, 0.8, 0.7, 0.3), territory={"radius": 200.0, "leash": 320.0},
                 habitat={"spawn_entry": "boar"}, spawn_p=0.15, variants=["bristle_boar"], loot=_loot(("meat", 2, 3, 1.0), ("hide", 1, 1, 0.7), ("bone", 1, 1, 0.4)),
                 enabled=True, notes="charges when hit; hunts nothing", carcass={"ticks": BIG_CARCASS}),
    "fox": _row(46, "fox", FRAME_A, [8, 5], hp=30.0, speed={"walk": 1.8, "run": 4.2}, damage=5.0, range=8.0, cooldown=16, life_exp=[5.0, 12.0],
                aggro=0.3, aggro_range=50.0, flee_hp=0.5, fear={"humans": True, "radius": 60.0, "species": ["wolf"]},
                diet={"eats": ["meat", "carrion"], "prey": ["rabbit", "chicken"], "humans": "never"}, group={"kind": "solitary", "size": [1, 2], "cohesion": 20.0},
                activity=_act(0.4, 0.3, 0.9, 1.0), territory={"radius": 180.0, "leash": 280.0}, habitat={"companion": "rabbit"}, spawn_p=0.12,
                variants=["red_fox", "grey_fox"], loot=_loot(("meat", 1, 1, 1.0), ("hide", 1, 1, 0.6)), enabled=True,
                notes="scavenger; steals from open stores when a model-plane rule lets it", tame={"mode": "tameable", "food": ["meat"], "to_tame": 15, "decay_per_day": 1.0, "role": "companion"}),
    "goblin": _row(47, "goblin", FRAME_A, [7, 7], hp=50.0, speed={"walk": 1.6, "run": 3.2}, damage=8.0, range=10.0, cooldown=22, life_exp=[10.0, 25.0],
                   aggro=0.6, aggro_range=90.0, flee_hp=0.3, diet={"eats": ["meat"], "prey": [], "humans": "hungry"}, hostile=True,
                   group={"kind": "band", "size": [2, 5], "cohesion": 50.0}, activity=_act(0.2, 0.3, 0.7, 1.0), territory={"radius": 220.0, "leash": 360.0},
                   habitat={"poi": ["camp"]}, spawn_p=0.6, variants=["goblin_barterer", "scrap_raider"],
                   loot=_loot(("scrap", 1, 2, 0.8), ("bone", 1, 1, 0.3)), enabled=True, notes="the barterer variant is peaceful (aggro 0, model-plane trade)"),
    "skeleton": _row(48, "skeleton", FRAME_A, [7, 7], hp=70.0, speed={"walk": 1.2, "run": 2.4}, damage=14.0, range=12.0, cooldown=26, life_exp=[1000.0, 1000.0],
                     aggro=0.9, aggro_range=70.0, flee_hp=0.0, diet={"eats": ["none"], "prey": [], "humans": "always"}, hostile=True,
                     activity=_act(0.0, 0.2, 0.6, 1.0), territory={"radius": 160.0, "leash": 240.0}, habitat={"poi": ["ruin"]}, spawn_p=0.7,
                     variants=["armoured_skeleton"], loot=_loot(("bone", 1, 3, 1.0)), enabled=True, notes="guardian of ruins; no hunger (diet none)"),
    "giant_spider": _row(49, "giant_spider", FRAME_A, [14, 14], hp=90.0, speed={"walk": 1.5, "run": 3.6}, damage=18.0, range=16.0, cooldown=28, life_exp=[4.0, 10.0],
                         aggro=0.8, aggro_range=100.0, flee_hp=0.1, diet={"eats": ["meat"], "prey": [], "humans": "always"}, hostile=True,
                         activity=_act(0.3, 0.3, 0.6, 1.0), territory={"radius": 140.0, "leash": 220.0}, habitat={"poi": ["cave", "ruin"]}, spawn_p=0.5,
                         variants=["cave_spider", "orchard_spider"], loot=_loot(("silk", 1, 2, 0.8)), enabled=True, notes="ambush; web territory is a later hook"),

    # ---- the rest of the grounded fauna: identity only (enabled False until the simulation owners choose) ---------------------------------------------------------
    "goat": _row(50, "goat", FRAME_A, [10, 7], hp=45.0, huntable=True, group={"kind": "herd", "size": [2, 5], "cohesion": 40.0}, habitat={"spawn_entry": "goat"}, spawn_p=0.10, tame={"mode": "domestic", "food": ['grass'], "to_tame": 0, "decay_per_day": 0.0, "role": 'livestock'}, carcass={"ticks": BIG_CARCASS}),
    "rabbit": _row(51, "rabbit", FRAME_B, [5, 4], hp=15.0, speed={"walk": 1.0, "run": 4.0}, huntable=True, flee_hp=1.0, habitat={"spawn_entry": "rabbit"}, spawn_p=0.20,
                   fear={"humans": True, "radius": 40.0, "species": ["fox", "wolf"]}, group={"kind": "herd", "size": [1, 4], "cohesion": 25.0}),
    "dog": _row(52, "dog", FRAME_A, [10, 6], hp=50.0, notes="companion hook; warning/bond are model-plane", tame={"mode": "domestic", "food": ['meat'], "to_tame": 0, "decay_per_day": 0.0, "role": 'guard'}),
    "cat": _row(53, "cat", FRAME_A, [7, 5], hp=25.0, notes="pest control hook", tame={"mode": "domestic", "food": ['meat'], "to_tame": 0, "decay_per_day": 0.0, "role": 'pest'}),
    "cow": _row(54, "cow", FRAME_C, [16, 9], hp=90.0, huntable=True, group={"kind": "herd", "size": [2, 6], "cohesion": 40.0}, tame={"mode": "domestic", "food": ['grass'], "to_tame": 0, "decay_per_day": 0.0, "role": 'livestock'}, carcass={"ticks": BIG_CARCASS}),
    "horse": _row(55, "horse", FRAME_C, [16, 8], hp=90.0, speed={"walk": 1.8, "run": 5.0}, notes="merchant transport hook", tame={"mode": "tameable", "food": ["grass"], "to_tame": 8, "decay_per_day": 0.5, "role": "mount"}, carcass={"ticks": BIG_CARCASS}),
    "chicken": _row(56, "chicken", FRAME_B, [5, 5], hp=10.0, huntable=True, group={"kind": "herd", "size": [2, 6], "cohesion": 20.0}, tame={"mode": "domestic", "food": ['grass'], "to_tame": 0, "decay_per_day": 0.0, "role": 'livestock'}, products=[{"item": "egg", "every_days": 1, "needs": "fed"}]),
    "songbird": _row(57, "songbird", FRAME_B, [3, 3], hp=5.0, flight=True, speed={"walk": 1.0, "run": 4.0}),
    "crow": _row(58, "crow", FRAME_B, [4, 4], hp=8.0, flight=True, speed={"walk": 1.0, "run": 4.0}, diet={"eats": ["carrion"], "prey": [], "humans": "never"}),
    # 59 spare

    # ---- invented species (bible "creative creature bible"): identity only ------------------------------------------------------------------------------------
    "brambleback": _row(60, "brambleback", FRAME_A, [11, 7], hp=60.0, notes="orchard pest; defensive curled posture"),
    "mire_lantern": _row(61, "mire_lantern", FRAME_B, [4, 4], hp=8.0, activity=_act(0.3, 0.1, 0.6, 1.0), notes="nocturnal swamp amphibian"),
    "cinder_moth": _row(62, "cinder_moth", FRAME_B, [4, 4], hp=3.0, flight=True, notes="scavenger near hearths"),
    "cairn_keeper": _row(63, "cairn_keeper", FRAME_C, [14, 14], hp=150.0, variants=["moss_cairn_keeper", "frost_cairn_keeper"], notes="shrine guardian"),
    "thread_thief": _row(64, "thread_thief", FRAME_B, [5, 4], hp=12.0, notes="workshop/pantry pest"),
    "bellhorn": _row(65, "bellhorn", FRAME_C, [18, 10], hp=110.0, group={"kind": "herd", "size": [1, 3], "cohesion": 40.0}, notes="caravan beast"),
    "glassfin": _row(66, "glassfin", FRAME_B, [6, 3], hp=10.0, swim=True, notes="rare river fish"),
    "moonhart": _row(67, "moonhart", FRAME_C, [14, 8], hp=70.0, speed={"walk": 1.8, "run": 5.0}, flee_hp=1.0, notes="rare omen deer"),
    "rootling": _row(68, "rootling", FRAME_A, [7, 7], hp=40.0, variants=["autumn_rootling"], notes="grove guardian/forager"),
    "hollow_rook": _row(69, "hollow_rook", FRAME_A, [8, 8], hp=20.0, notes="scavenger, alarm caller"),
}


def _sprite_for(name: str) -> Optional[str]:
    return ASSET_ROOT_STATIC.format(name=name) if name in STATIC_SPRITES else None


def validate(table: Optional[dict] = None) -> list:
    """Problems found in ``table`` (default: ``CREATURES``) as ``"<name>: message"`` strings; empty = fine."""
    table = CREATURES if table is None else table
    problems: list = []
    ids: dict = {}
    names = set(table)
    for name, row in table.items():
        def bad(msg, name=name):
            problems.append(f"{name}: {msg}")
        if name != name.lower() or " " in name:
            bad("name must be lowercase snake_case")
        unknown = set(row) - _KEYS
        if unknown:
            bad(f"unknown keys {sorted(unknown)}")
        missing = _KEYS - set(row)
        if missing:
            bad(f"missing keys {sorted(missing)}")
            continue
        if not isinstance(row["id"], int) or not MIN_ID <= row["id"] <= MAX_ID:
            bad(f"id {row['id']!r} outside {MIN_ID}..{MAX_ID}")
        elif row["id"] in ids:
            bad(f"id {row['id']} already used by {ids[row['id']]}")
        else:
            ids[row["id"]] = name
        if row["label"] != name:
            bad("label must equal the name")
        if len(row["frame"]) != 4 or len(row["footprint"]) != 2 or min(row["footprint"]) <= 0:
            bad("frame needs 4 numbers and footprint 2 positive numbers")
        if not (row["hp"] > 0):
            bad("hp must be positive")
        if not (0.0 <= row["aggro"] <= 1.0 and 0.0 <= row["flee_hp"] <= 1.0):
            bad("aggro and flee_hp are fractions 0..1")
        if min(row["damage"], row["range"], row["aggro_range"]) < 0 or row["cooldown"] < 1:
            bad("damage, range, aggro_range >= 0 and cooldown >= 1 tick")
        if row["damage"] > 0 and row["range"] <= 0:
            bad("a creature that does damage needs a range")
        speed = row["speed"]
        if not (0 < speed.get("walk", 0) <= speed.get("run", 0)):
            bad("speed needs 0 < walk <= run")
        if set(row["activity"]) != set(TIME_BLOCKS) or not all(0.0 <= v <= 1.0 for v in row["activity"].values()):
            bad(f"activity needs exactly {TIME_BLOCKS} with values 0..1")
        diet = row["diet"]
        if not set(diet.get("eats", [])) <= set(DIET_EATS) or diet.get("humans") not in HUMANS:
            bad("diet.eats / diet.humans out of vocabulary")
        for other in list(diet.get("prey", [])) + list(row["fear"].get("species", [])):
            if other not in names:
                bad(f"unknown species {other!r} in prey/fear")
        group = row["group"]
        if group.get("kind") not in GROUPS or not (1 <= group["size"][0] <= group["size"][1] <= 16):
            bad("group.kind / group.size (1 <= lo <= hi <= 16)")
        if not (row["territory"]["radius"] > 0 and row["territory"]["leash"] >= row["territory"]["radius"]):
            bad("territory needs 0 < radius <= leash")
        lo, hi = row["life_exp"]
        if not 0 < lo <= hi:
            bad("life_exp needs 0 < lo <= hi")
        for entry in row["loot"]:
            if set(entry) != {"item", "min", "max", "p"} or not (0 <= entry["min"] <= entry["max"] and 0.0 < entry["p"] <= 1.0):
                bad(f"loot entry {entry!r}")
        habitat = row["habitat"]
        if habitat:
            kinds = [k for k in ("spawn_entry", "companion", "poi") if k in habitat]
            if len(kinds) != 1:
                bad("habitat needs exactly one of spawn_entry, companion, poi")
            elif kinds[0] == "companion" and habitat["companion"] not in names:
                bad(f"unknown companion {habitat['companion']!r}")
        if not (isinstance(row["spawn_p"], (int, float)) and 0.0 <= row["spawn_p"] <= 1.0):
            bad("spawn_p is a probability 0..1")
        if row["habitat"] and row["spawn_p"] <= 0.0:
            bad("a species with a habitat needs spawn_p > 0")
        tame = row["tame"]
        if tame.get("mode") not in TAME_MODES or tame.get("role") not in TAME_ROLES or not (tame.get("to_tame", -1) >= 0 and tame.get("decay_per_day", -1) >= 0):
            bad("tame needs mode/role from the vocabulary and non-negative to_tame, decay_per_day")
        if not all(isinstance(f, str) for f in tame.get("food", [])):
            bad("tame.food is a list of item or diet names")
        for product in row["products"]:
            if set(product) != {"item", "every_days", "needs"} or product["needs"] not in PRODUCT_NEEDS or not product["every_days"] > 0:
                bad(f"product {product!r}")
        if row["threat"] is not None and not 0.0 <= row["threat"] <= 100.0:
            bad("threat is None or 0..100")
        if row["perceive_radius"] is not None and row["perceive_radius"] < 0:
            bad("perceive_radius is None or >= 0")
        if not (isinstance(row["carcass"].get("ticks"), int) and row["carcass"]["ticks"] >= 0):
            bad("carcass.ticks is an integer >= 0")
        if row["brain"] not in BRAINS:
            bad("brain must be legacy or table")
    return problems


_problems = validate()
if _problems:      # pragma: no cover - a data error is fixed in this file
    raise ValueError("creature table: " + "; ".join(_problems))


# ---- lookups ------------------------------------------------------------------------------------------------------------------------------------------------
BY_ID: dict[int, str] = {row["id"]: name for name, row in CREATURES.items()}


def get(key) -> Optional[dict]:
    """Row by name or by ``M_TYPE``; None if unknown."""
    if isinstance(key, str):
        return CREATURES.get(key)
    name = BY_ID.get(int(key))
    return CREATURES[name] if name else None


def id_of(name: str) -> int:
    return CREATURES[name]["id"]


def prey_ids(name: str) -> set:
    return {id_of(p) for p in CREATURES[name]["diet"]["prey"]}


LEGACY_HOSTILE = frozenset({42, 43})          # M_TIGER, M_WOLF: what services.hostile_count counted before the table
LEGACY_HUNTABLE = frozenset({40, 41, 44})     # M_SHEEP, M_DEER, M_FISH: combat/hunting.HUNTABLE_ANIMAL_TYPES


def _on() -> bool:
    from . import enabled
    return enabled()


def by_type(m_type) -> Optional[dict]:
    """The row of an ``M_TYPE`` (None for anything that is not a creature). Pure; works with the flag off."""
    try:
        return get(int(m_type))
    except (TypeError, ValueError):
        return None


def name_of(m_type) -> Optional[str]:
    try:
        return BY_ID.get(int(m_type))
    except (TypeError, ValueError):
        return None


def hostile_types() -> frozenset:
    """``M_TYPE``s that count as dangerous. ``EDEN_CREATURES`` unset: exactly the legacy pair {tiger, wolf}. Set: every row with ``hostile``."""
    return frozenset(r["id"] for r in CREATURES.values() if r["hostile"]) if _on() else LEGACY_HOSTILE


def huntable_types() -> frozenset:
    """``M_TYPE``s a hunt can complete on. ``EDEN_CREATURES`` unset: the legacy {sheep, deer, fish}. Set: every row with ``huntable``."""
    return frozenset(r["id"] for r in CREATURES.values() if r["huntable"]) if _on() else LEGACY_HUNTABLE


def loot_of(m_type) -> list:
    row = by_type(m_type)
    return [dict(entry) for entry in row["loot"]] if row else []


def threat_of(m_type) -> float:
    """The THREAT 0..100 a resident feels with this creature in perception: the row's ``threat``, else derived from damage x aggression."""
    row = by_type(m_type)
    if row is None:
        return 0.0
    if row["threat"] is not None:
        return float(row["threat"])
    return float(min(100.0, round(row["damage"] * (0.5 + row["aggro"]) * 3.0)))


def perceive_radius_of(m_type) -> float:
    row = by_type(m_type)
    if row is None:
        return 0.0
    return float(row["aggro_range"] if row["perceive_radius"] is None else row["perceive_radius"])


def enabled_names() -> list:
    return [n for n, r in CREATURES.items() if r["enabled"]]


def legacy_dicts(human_type: int) -> dict:
    """The ``genesis_config`` dictionaries as the table says they should be, keyed by M_TYPE (``install()`` writes them in place for the table-brained species; the
    parity test compares the five legacy species). ``ANIMAL_SCALE`` is the legacy 'visual radius': half of the footprint's longer side. Humans are prey only for
    ``diet.humans == "always"`` (the legacy tiger); 'hungry' and 'cornered' are kernel rules that the legacy dict cannot express."""
    out = {"ANIMAL_LIFE_EXP": {}, "ANIMAL_SCALE": {}, "ANIMAL_BASE_AGGRESSION": {}, "ANIMAL_MOVE_STEP": {}, "ANIMAL_PREY": {}}
    for name, row in CREATURES.items():
        i = row["id"]
        out["ANIMAL_LIFE_EXP"][i] = (float(row["life_exp"][0]), float(row["life_exp"][1]))
        out["ANIMAL_SCALE"][i] = max(row["footprint"]) / 2.0
        out["ANIMAL_BASE_AGGRESSION"][i] = float(row["aggro"])
        out["ANIMAL_MOVE_STEP"][i] = float(row["speed"]["walk"])
        prey = prey_ids(name)
        if row["diet"]["humans"] == "always":
            prey.add(int(human_type))
        if prey:
            out["ANIMAL_PREY"][i] = prey
    return out


def export() -> dict:
    """The JSON-able contract for the asset side and the client: ids, names, sprite, frame, pivot, footprint, variants, enabled. No behaviour numbers."""
    species = []
    for name, row in sorted(CREATURES.items(), key=lambda kv: kv[1]["id"]):
        w, h, px, py = row["frame"]
        species.append({"id": row["id"], "name": name, "sprite": _sprite_for(name), "frame": [w, h], "pivot": [px, py], "footprint": list(row["footprint"]),
                        "variants": list(row["variants"]), "enabled": bool(row["enabled"]), "flight": bool(row["flight"]), "swim": bool(row["swim"])})
    return {"version": 1, "id_range": [MIN_ID, MAX_ID], "species": species}
