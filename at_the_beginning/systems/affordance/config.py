"""Tunable numbers of the affordance engine. Radii deliberately equal the ones the task resolvers use in ``map_test.py``
(``_resolve_task_resource_target`` 220, ``_resolve_task_safe_target`` 240, help 72, support 96) so a resident is offered only what an
executor would also look for; every one is a placeholder to be tuned, not a measured value."""

RADIUS = {
    "resource": 220.0,    # food, water, gatherable nodes
    "safe": 240.0,        # shelter, beds, hiding places
    "social": 96.0,       # residents a person can talk to, follow, ask, attack, avoid
    "help": 72.0,         # residents a person would notice are in need
    "interact": 16.0,     # DEFAULT_INTERACT_RADIUS of systems/commission/access.py (2 tiles); an entity may declare its own
    "explore_step": 40.0,
}
EDIBLE_ITEMS = ("rations", "fish_catch", "crop_bundle", "berries", "mushrooms")        # = systems/tasks/families/survival.py EDIBLE_ITEM_KINDS (drift-tested)
NEED_MIN = 1.0                 # below this hunger/thirst a meal or a drink is "not_needed"
REST_MIN_DEFICIT = 1.0         # rest/recover is not_needed when stamina and hp are both within this of 100
AT_WORK_TOLERANCE = 3.0        # = systems/commission/engine.py AT_WORK_TOLERANCE
MOOD_LOW = 45.0                # a resident with mood at or below this can be comforted
NEED_HELP_HUNGER = 60.0        # neighbour hunger/thirst at or above this, or hp/mood below the next two, counts as "in need"
NEED_HELP_HP = 40.0
NEED_HELP_MOOD = 25.0
THREAT_BLOCKS_SLEEP = 45.0     # = genesis_config.SHELTER_SEEK_THREAT
WORK_TOLERANCE_KINDS = ("work",)
DRIVER_MODE = "roster"        # D-008: "roster" = residents with a roster record are moved by the roster driver (driver.py demotes some verbs); "agent" = off

# map entity kinds that are something to gather, and what they give
GATHER_NODES = {"wood_pile": "wood_bundle", "stone_pile": "stone_chunk", "berry_bush": "berries", "iron_pile": "iron_ingot"}
STORAGE_KINDS = ("storage", "chest", "storage_case", "crate")
BED_KINDS = ("bed",)

# reachability
REACH_MAX_EXPANSIONS = 6000    # per plan_path attempt; a hit falls back to the straight-line answer, marked "approx"
REACH_MAX_DISTANCE_ENV = "EDEN_REACH_MAX_DISTANCE"   # unset / 0 = no cap (today). Else a path search is not started for a goal farther than this (world units, straight line): the answer is the approx straight-line one
REACH_CELL_QUANT = 2.0         # cache key resolution in world units (start and goal are rounded to this grid)
REACH_CACHE_SIZE = 4096
