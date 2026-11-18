"""
tools_and_instincts_registry.py
================================
The canonical reference for the Eden world agent (LoRA-A).

This file is NOT executable simulation code — it is a structured description
of every callable in instincts_and_tools.py, written so that:
  1. The LLM training prompt can inject the relevant sections
  2. A human developer can understand when to use each tool
  3. LightRAG can embed and index each entry for retrieval (Approach 3)

Structure per entry:
  name        — exact function name as it appears in output JSON tool_name
  tier        — A (core) | B (extended) | C (propose, last resort)
  signature   — parameters the world agent must supply
  what        — one sentence: what this function does to the simulation state
  reads       — which tensor columns or state it reads
  writes      — which tensor columns or state it modifies
  fires       — when it runs: one-shot call | each tick | death hook | birth hook
  use_when    — natural language scenarios where this is the right choice
  do_not_use  — common mistakes / when NOT to use this
  example_mask — a representative mask expression for context
"""

# =============================================================================
# COLUMN REFERENCE — inject this at the top of every LLM prompt
# =============================================================================

COLUMN_REFERENCE = """
=== HUMAN TENSOR (h_tensor) shape=(100, 32) ===
Shared:
  col0: X           position x (pixel)
  col1: Y           position y (pixel)
  col2: TYPE        1=human, 0=empty
  col3: HP          health points [0-100]

Human stats (col 4-9):
  col4: H_STRENGTH      physical strength [0-100]
  col5: H_FERTILITY      fertility multiplier [0-2]
  col6: H_AGGRESSION    aggression level [0-1], triggers attack at threshold
  col7: H_STAMINA       stamina [0-100], depletes on movement/attack
  col8: H_INFECTION     infection level [0-100], spreads to nearby agents
  col9: H_SHELTER       1 if inside a house/village entity, else 0

Human identity (col 10-19):
  col10: H_SEX          0=Male, 1=Female
  col11: H_AGE          age in float years
  col12: H_LIFE_EXP     life expectancy in float years
  col13: H_COOLDOWN     mating recovery timer, clamped >= 0
  col14: HUNGER         hunger level [0-100], HP decays when >= 90
  col15: THREAT         threat perception [0-100]
  col16: MOOD           mood [0-100]
  col17: CRITICAL_HEALTH  1 if starving/critically injured, else 0
  col18: ESCALATION_FLAG  1 if agent needs human agent LLM attention
  col19: ACQUIRED_INSTINCT_MASK  bitmask — bit N = acquired instinct N active

Extended identity (col 20-23):
  col20: H_CARRYING     resource being carried
  col21: H_SKILL        skill level [0-100]
  col22: H_TRIBE        tribe affiliation float
  col23: H_PARENT_INSTINCTS  inherited instinct bitmask from parent

=== MAP ENTITY TENSOR (m_tensor) shape=(1024, 32) ===
Shared (all entity types):
  col0: CX          anchor centre x (pixel)
  col1: CY          anchor centre y (pixel)
  col2: M_TYPE      entity type integer (see M_TYPE constants below)
  col3: M_HP        entity health [0-100], 0 = destroyed
  col4: SCALE       render scale (area radius in px)
  col5: SPRITE_ID   sprite index for rendering

Natural feature state (col 6-9):
  col6: M_FERTILITY     food regeneration rate [0-100]
  col7: M_ELEVATION     terrain height
  col8: M_BURNING       fire counter > 0 means burning (increments each tick)
  col9: M_FLOODED       1 if entity was converted by flood

Animal life stats (col 10-14) — only valid when M_TYPE in ANIMAL_TYPES:
  col10: A_AGE          animal age in years
  col11: A_LIFE_EXP     animal life expectancy
  col12: A_SEX          0=Male, 1=Female
  col13: A_COOLDOWN     mating recovery timer
  col14: A_HUNGER       hunger [0-100]

Structure state (col 15-18) — only valid when M_TYPE in STRUCTURE_TYPES:
  col15: S_DURABILITY       structure durability [0-100]
  col16: S_SHELTER_CAP      max occupants
  col17: S_OCCUPANT_COUNT   current occupants
  col18: S_BUILD_PROGRESS   build completion [0-100]

Resource / environment (col 19-20):
  col19: M_RESOURCE_FOOD    food stock available for eating
  col20: M_LAVA_COOLING     ticks remaining until lava cools to M_BARREN

=== M_TYPE CONSTANTS ===
Natural features (static area entities):
  M_LAKE=1      deep water, fish resource, has_water state
  M_FOREST=2    trees, food, burns, can regrow
  M_SEA=3       ocean boundary, floods adjacent land
  M_MOUNTAIN=4  impassable high terrain
  M_BEACH=5     sandy shoreline, low food
  M_GRASS=6     open plains, moderate food

Dynamic terrain:
  M_LAVA=7      hot lava — damages agents each tick, cools to M_BARREN
  M_BARREN=8    scorched/destroyed land — no food, regrows to M_GRASS over time

Structures (player-built):
  M_HOUSE=9     small shelter — grants H_SHELTER=1 to occupants
  M_VILLAGE=10  large shelter — higher shelter cap

Animals (mobile entities, point-positioned):
  M_SHEEP=11    passive prey — humans can hunt for food
  M_DEER=12     passive prey — fast, harder to catch
  M_TIGER=13    predator — attacks humans on sight
  M_WOLF=14     predator — pack hunter, attacks humans and prey
  M_FISH=15     aquatic — lives in lakes, catchable by fishing instinct

Dynamic entities (spawned at runtime, type_id >= 50):
  type_id >= 50  assigned by world agent for new entity types
"""

# =============================================================================
# TIER A — CORE INSTINCTS
# Always available. Prefer these before reaching for Tier B.
# =============================================================================

TIER_A = [
    {
        "name": "instinct_born",
        "tier": "A",
        "signature": "instinct_born(x, y, sex, life_exp, age=0, hunger=0, mood=80)",
        "what": "Spawn one new human agent into the first free h_tensor slot.",
        "reads": "h_tensor TYPE col2 (finds empty slot)",
        "writes": "h_tensor cols 0-23 for the new agent row; increments pop_count",
        "fires": "one-shot call — called by tools and genesis, NOT tick-registered",
        "use_when": [
            "spawning new humans on specific tiles or coordinates",
            "baby boom events where a fixed number of new humans appear",
            "genesis initialization of Adam and Eve",
        ],
        "do_not_use": [
            "to spawn map entities (lakes, animals) — use entity_born or animal_born instead",
            "when at population cap MAX_HUMANS=100 (returns False silently)",
        ],
        "example_mask": "x=sample(grass_tiles).x, y=sample(grass_tiles).y, sex=0.0, life_exp=75.0",
    },
    {
        "name": "instinct_die",
        "tier": "A",
        "signature": "instinct_die(mask)",
        "what": "Kill agents that have exceeded their life expectancy. Zeros the entire tensor row.",
        "reads": "H_AGE col11, H_LIFE_EXP col12",
        "writes": "zeros full row for dead agents; decrements pop_count; refreshes h_mask",
        "fires": "each tick — registered in engine loop at priority 20",
        "use_when": [
            "explicitly killing named or masked agents immediately (use tool_smite for targeted kills)",
            "age-based natural death is already running automatically — only call manually to force immediate death",
        ],
        "do_not_use": [
            "for HP-based death — instinct_hp_death handles that automatically",
            "for population culling — use tool_cull which targets by HP",
        ],
        "example_mask": "H_SEX==0 and H_AGE==max(H_AGE)",
    },
    {
        "name": "instinct_flee",
        "tier": "A",
        "signature": "instinct_flee(mask, threat_pos)",
        "what": "Apply a repulsion vector pushing masked agents away from threat_pos coordinates.",
        "reads": "X col0, Y col1",
        "writes": "X col0, Y col1 (moves agents away from threat)",
        "fires": "one-shot call — called by tools, can also be tick-registered",
        "use_when": [
            "fire or wildfire events where humans should flee the burning area",
            "predator attacks where humans run from an animal position",
            "explosions, earthquakes, volcanic eruptions — survivors flee epicenter",
            "any event with a clear spatial threat source (x, y coordinates)",
        ],
        "do_not_use": [
            "for persistent ongoing avoidance — this is one-shot; for permanent avoidance use propose_new_instinct",
            "when there is no clear threat position (use tool_set_threat instead for general threat)",
        ],
        "example_mask": "TYPE==1 and dist_to(M_TYPE==2)<80, threat_pos=centroid(M_TYPE==2)",
    },
    {
        "name": "instinct_move",
        "tier": "A",
        "signature": "instinct_move(mask, attraction_target=None)",
        "what": "Apply Brownian walk to agents. If attraction_target provided, add bias toward it.",
        "reads": "X col0, Y col1, H_STAMINA col7, seek_mask from ctx",
        "writes": "X col0, Y col1",
        "fires": "each tick — registered at priority 40",
        "use_when": [
            "directing agents toward a specific location or entity",
            "injured humans seeking a healing sanctuary",
            "migration events pushing population toward safe ground",
        ],
        "do_not_use": [
            "for flee behavior — use instinct_flee which applies repulsion",
            "for forced teleportation — this biases random walk, not instant relocation",
        ],
        "example_mask": "TYPE==1 and HP<30, attraction_target=M_TYPE==53",
    },
    {
        "name": "instinct_cooldown",
        "tier": "A",
        "signature": "instinct_cooldown(mask, col=H_COOLDOWN, rate=None)",
        "what": "Decay any timer column toward zero each tick. Reusable for any per-agent timer.",
        "reads": "col (default H_COOLDOWN col13)",
        "writes": "col, clamped to >= 0",
        "fires": "one-shot call or tick-registered — used both ways",
        "use_when": [
            "decaying mating recovery timer (default H_COOLDOWN)",
            "decaying any custom per-agent timer column",
            "quarantine duration countdown",
        ],
        "do_not_use": [
            "to instantly zero a cooldown — use tool_reset_cooldown for that",
        ],
        "example_mask": "TYPE==1, col=H_COOLDOWN",
    },
    {
        "name": "instinct_search",
        "tier": "A",
        "signature": "instinct_search(mask)",
        "what": "Compute seek_mask: agents who are alive, mature (age >= 18), and off cooldown.",
        "reads": "H_AGE col11, H_COOLDOWN col13",
        "writes": "seek_mask into ctx dict for downstream instinct_move and tool_reproduce",
        "fires": "each tick — registered at priority 30",
        "use_when": [
            "automatically used by tool_reproduce — no need to call manually",
            "checking which agents are ready to mate in custom instincts",
        ],
        "do_not_use": [
            "directly in world agent output — this runs automatically every tick",
        ],
        "example_mask": "TYPE==1",
    },
    {
        "name": "geo_mutate",
        "tier": "A",
        "signature": "geo_mutate(entity_id, new_type)",
        "what": "Change M_TYPE of a single map entity and recompute its MAP_GEO tile_mask.",
        "reads": "m_tensor M_TYPE col2",
        "writes": "m_tensor M_TYPE col2; MAP_GEO tile_mask; bumps geo_version for client re-fetch",
        "fires": "one-shot call — must be called after any M_TYPE change",
        "use_when": [
            "after changing M_TYPE of an entity (e.g. GRASS → FOREST, LAVA → BARREN)",
            "any time entity shape or type changes and the render client needs updating",
            "after tool_regrow_forest, tool_flood, tool_drought — these call it internally",
        ],
        "do_not_use": [
            "for changing h_tensor columns — use set_attr instead",
            "for human stat changes — geo_mutate is map-only",
            "when M_TYPE is NOT changing — unnecessary recompute overhead",
        ],
        "example_mask": "entity_id=lake_entity_id, new_type=M_BARREN",
    },
    {
        "name": "set_attr",
        "tier": "A",
        "signature": "set_attr(mask, col, value, mode)",
        "what": "Write a value to any h_tensor or m_tensor column for all masked agents/entities.",
        "reads": "col (target column)",
        "writes": "col for all rows matching mask",
        "fires": "one-shot call — the primary generic tensor write tool",
        "modes": {
            "set": "h_tensor[mask, col] = value",
            "add": "h_tensor[mask, col] += value",
            "multiply": "h_tensor[mask, col] *= value",
            "or": "h_tensor[mask, col] |= int(value)  # bitwise, for ACQUIRED_INSTINCT_MASK",
        },
        "use_when": [
            "modifying any stat directly: HUNGER, THREAT, MOOD, HP, H_AGE, H_LIFE_EXP",
            "setting ACQUIRED_INSTINCT_MASK bits (use mode='or')",
            "applying stat changes to a specific subset of agents",
            "simple direct stat manipulation not covered by a named Tier B tool",
        ],
        "do_not_use": [
            "when a named Tier B tool exists for the action (use tool_bless not raw set_attr on HP+MOOD+H_COOLDOWN)",
            "for aggregate conditions like 'if population < 10' — masks must be per-agent boolean",
            "with mode='subtract' — use mode='add' with negative value instead",
        ],
        "example_mask": "H_SEX==1 and H_AGE>40, col=H_COOLDOWN, value=999.0, mode=set",
    },
    {
        "name": "tool_reproduce",
        "tier": "A",
        "signature": "tool_reproduce(mask)",
        "what": "Mate opposite-sex mature agents in proximity; spawn child with inherited instincts.",
        "reads": "seek_mask from ctx, H_SEX col10, H_AGE col11, H_COOLDOWN col13, X col0, Y col1",
        "writes": "new agent row via instinct_born; H_COOLDOWN col13 on mother; pop_count",
        "fires": "each tick — registered at priority 50",
        "use_when": [
            "reproduction is already running automatically — rarely needed in world agent output",
            "triggering a forced reproduction event after resetting cooldowns",
        ],
        "do_not_use": [
            "directly in most commands — reproduction is automatic via tick loop",
        ],
        "example_mask": "TYPE==1",
    },
    {
        "name": "tool_area_attack",
        "tier": "A",
        "signature": "tool_area_attack(center_x, center_y, radius)",
        "what": "Kill all agents within radius of (center_x, center_y). Survivors in 2.5× radius flee.",
        "reads": "X col0, Y col1, HP col3",
        "writes": "zeros rows of killed agents; X/Y of fleeing survivors; decrements pop_count",
        "fires": "one-shot call",
        "use_when": [
            "meteor impact, explosion, bomb — kill core, flee outer ring",
            "volcanic eruption inner kill zone",
            "divine smite at a coordinate (use tool_smite for mask-based killing)",
            "any event with a circular kill zone centered on (x, y)",
        ],
        "do_not_use": [
            "for mask-based killing — use tool_smite(mask) if you have an agent mask",
            "for HP decay over time — use tool_epidemic or tool_plague",
        ],
        "example_mask": "center_x=380, center_y=120, radius=25",
    },
    {
        "name": "tool_epidemic",
        "tier": "A",
        "signature": "tool_epidemic(mask, decay_rate)",
        "what": "Apply HP decay to agents in mask each tick. Raises THREAT as sickness spreads.",
        "reads": "HP col3, THREAT col15, X col0, Y col1",
        "writes": "HP col3 (decay), THREAT col15 (raise)",
        "fires": "one-shot call — applied to mask immediately, not registered for future ticks",
        "use_when": [
            "disease outbreak with specified affected population mask",
            "environmental HP drain (standing in lava, poison gas)",
            "when you need fine control over which agents take damage",
        ],
        "do_not_use": [
            "for a full plague event — use tool_plague which chains H_INFECTION + THREAT + MOOD",
            "for one-shot kill — use tool_smite or tool_area_attack",
        ],
        "example_mask": "TYPE==1 and dist_to(M_TYPE==3)<50, decay_rate=2.0",
    },
    {
        "name": "tool_drought",
        "tier": "A",
        "signature": "tool_drought(entity_mask=None)",
        "what": "Drain lakes — sets M_RESOURCE_FOOD and M_FERTILITY to 0 for matching lake entities.",
        "reads": "m_tensor M_TYPE col2",
        "writes": "M_RESOURCE_FOOD col19, M_FERTILITY col6 for M_LAKE entities",
        "fires": "one-shot call",
        "use_when": [
            "drought events affecting all lakes",
            "drying a specific named lake",
            "removing food/water resources from a region",
        ],
        "do_not_use": [
            "for sea or ocean — only affects M_LAKE entities",
            "when you need shape geometry change — call geo_mutate additionally if lake should visually shrink",
        ],
        "example_mask": "entity_mask=None (all lakes)",
    },
]

# =============================================================================
# TIER B — EXTENDED TOOLS
# Use when Tier A tools don't cover the action.
# =============================================================================

TIER_B = [
    # ── ENVIRONMENTAL DISASTERS ──────────────────────────────────────────────
    {
        "name": "tool_flood",
        "tier": "B",
        "signature": "tool_flood()",
        "what": "Expand sea/lake entities into adjacent land entities. Damages agents on flooded tiles.",
        "reads": "m_tensor M_TYPE col2, CX col0, CY col1; h_tensor X col0, Y col1",
        "writes": "m_tensor M_TYPE → M_SEA for flooded entities; M_FLOODED col9=1; HP col3 of agents; MAP_GEO via geo_mutate",
        "fires": "one-shot call",
        "use_when": [
            "rising sea level events",
            "valley flooding after heavy rain",
            "coastal inundation",
        ],
        "do_not_use": [
            "for draining lakes — use tool_drought",
            "for small localized water — use entity_born to spawn a new lake entity",
        ],
        "example_mask": "no mask required — floods all adjacent land",
    },
    {
        "name": "tool_wildfire",
        "tier": "B",
        "signature": "tool_wildfire(center_x, center_y, radius)",
        "what": "Ignite all forest entities within radius. Sets M_BURNING=1. instinct_fire_tick handles spread/burnout each tick.",
        "reads": "m_tensor M_TYPE col2, CX col0, CY col1",
        "writes": "M_BURNING col8=1, M_RESOURCE_FOOD col19=0 for forest entities in radius",
        "fires": "one-shot ignition call; fire spread is automatic via instinct_fire_tick each tick",
        "use_when": [
            "starting a forest fire at a location",
            "lightning strike igniting forest",
            "player god command to set forest ablaze",
        ],
        "do_not_use": [
            "to spread fire to non-forest entities — fire naturally spreads between forests",
            "for burning individual agents — agents take fire damage automatically via instinct_fire_tick when standing on burning tiles",
        ],
        "example_mask": "center_x=forest_cx, center_y=forest_cy, radius=60",
    },
    {
        "name": "tool_earthquake",
        "tier": "B",
        "signature": "tool_earthquake(center_x, center_y, radius)",
        "what": "Damage and possibly destroy entities in radius. Damage and flee agents. Random chance of converting entities to M_BARREN.",
        "reads": "m_tensor M_TYPE col2, M_HP col3, CX/CY; h_tensor HP col3, X/Y",
        "writes": "m_tensor M_HP col3; M_TYPE → M_BARREN (probabilistic); h_tensor HP col3, THREAT col15; X/Y flee",
        "fires": "one-shot call",
        "use_when": [
            "earthquake events",
            "tremors near mountain or volcanic regions",
            "ground shaking that destroys structures and displaces population",
        ],
        "do_not_use": [
            "for targeted kills — use tool_smite or tool_area_attack",
            "for fire events — use tool_wildfire",
        ],
        "example_mask": "center_x=mountain_cx, center_y=mountain_cy, radius=80",
    },
    {
        "name": "tool_storm",
        "tier": "B",
        "signature": "tool_storm(center_x, center_y, radius)",
        "what": "Randomly displace agents in radius. Unsheltered agents lose HP. All agents lose MOOD and gain THREAT.",
        "reads": "h_tensor X/Y, HP col3, MOOD col16, THREAT col15, H_SHELTER col9",
        "writes": "h_tensor X/Y (displacement), HP col3 (unsheltered only), MOOD col16, THREAT col15",
        "fires": "one-shot call",
        "use_when": [
            "storm or hurricane events",
            "divine wrath affecting a region",
            "weather events that scatter population and reduce morale",
        ],
        "do_not_use": [
            "for fire — use tool_wildfire",
            "for floods — use tool_flood",
            "agents in houses (H_SHELTER==1) are protected from HP damage automatically",
        ],
        "example_mask": "center_x=400, center_y=300, radius=150",
    },
    {
        "name": "tool_volcanic_eruption",
        "tier": "B",
        "signature": "tool_volcanic_eruption(center_x, center_y)",
        "what": "Convert inner entities to M_LAVA. Ignite outer forests. Kill inner agents. Flee outer agents.",
        "reads": "m_tensor M_TYPE col2, CX/CY; h_tensor X/Y, HP col3",
        "writes": "m_tensor M_TYPE → M_LAVA (inner), M_BURNING (outer forests); h_tensor zeros (inner kills), X/Y flee (outer); geo_mutate called",
        "fires": "one-shot call; lava cooling is automatic via instinct_lava_tick each tick",
        "use_when": [
            "volcanic eruption events near mountain entities",
            "lava flow spawning",
            "catastrophic terrain destruction events",
        ],
        "do_not_use": [
            "for simple kill events — use tool_area_attack or tool_smite",
            "for fire without lava — use tool_wildfire",
        ],
        "example_mask": "center_x=mountain_cx, center_y=mountain_cy",
    },
    {
        "name": "tool_regrow_forest",
        "tier": "B",
        "signature": "tool_regrow_forest(entity_mask=None)",
        "what": "Convert M_GRASS or M_BARREN entities to M_FOREST. Restores food and fertility. Calls geo_mutate.",
        "reads": "m_tensor M_TYPE col2",
        "writes": "m_tensor M_TYPE → M_FOREST, M_RESOURCE_FOOD col19, M_FERTILITY col6, M_BURNING col8=0; MAP_GEO via geo_mutate",
        "fires": "one-shot call",
        "use_when": [
            "divine blessing to restore forest",
            "forest spreading into adjacent grassland or barren land",
            "reforestation after wildfire",
        ],
        "do_not_use": [
            "to convert sea or mountain tiles — only works on M_GRASS and M_BARREN",
        ],
        "example_mask": "entity_mask for M_GRASS entities south of forest",
    },

    # ── POPULATION & STAT TOOLS ───────────────────────────────────────────────
    {
        "name": "tool_plague",
        "tier": "B",
        "signature": "tool_plague(mask)",
        "what": "Chain: HP decay + H_INFECTION raise + THREAT raise + MOOD lower for affected agents.",
        "reads": "h_tensor HP col3, H_INFECTION col8, THREAT col15, MOOD col16",
        "writes": "HP col3, H_INFECTION col8, THREAT col15, MOOD col16",
        "fires": "one-shot call",
        "use_when": [
            "plague or epidemic god commands affecting a population region",
            "disease outbreak near sea, forest, or specific biome",
            "any command combining sickness + fear + despair",
        ],
        "do_not_use": [
            "for simple HP damage — use tool_epidemic or set_attr",
            "for infection without mood/threat change — use set_attr H_INFECTION directly",
        ],
        "example_mask": "TYPE==1 and dist_to(M_TYPE==3)<50",
    },
    {
        "name": "tool_bless",
        "tier": "B",
        "signature": "tool_bless(mask)",
        "what": "Chain: HP=100 + MOOD=90 + H_COOLDOWN=0 + H_INFECTION=0 + THREAT=0 for affected agents.",
        "reads": "h_tensor HP col3, MOOD col16, H_COOLDOWN col13, H_INFECTION col8, THREAT col15",
        "writes": "HP col3=100, MOOD col16=90, H_COOLDOWN col13=0, H_INFECTION col8=0, THREAT col15=0",
        "fires": "one-shot call",
        "use_when": [
            "divine blessing events",
            "healing the tribe after catastrophe",
            "fertility boost (also resets cooldown)",
            "any command combining HP restore + morale boost + cooldown reset",
        ],
        "do_not_use": [
            "when you only want to restore HP — use set_attr HP col3 value=100 mode=set",
            "when you only want mood boost — use tool_set_mood",
        ],
        "example_mask": "H_SEX==1 (bless all women)",
    },
    {
        "name": "tool_cull",
        "tier": "B",
        "signature": "tool_cull(target_population)",
        "what": "Kill the lowest-HP agents repeatedly until pop_count reaches target_population.",
        "reads": "HP col3, TYPE col2",
        "writes": "zeros rows of culled agents; decrements pop_count; refreshes h_mask",
        "fires": "one-shot call — runs a loop until population target reached",
        "use_when": [
            "explicit population control commands",
            "god commands to reduce population to a specific number",
            "killing the weakest members of the tribe",
        ],
        "do_not_use": [
            "for area-based killing — use tool_area_attack",
            "for mask-targeted killing — use tool_smite(mask)",
        ],
        "example_mask": "target_population=20",
    },
    {
        "name": "tool_smite",
        "tier": "B",
        "signature": "tool_smite(mask)",
        "what": "Immediately kill ALL agents matching mask. Zeros rows. Decrements pop_count.",
        "reads": "h_tensor TYPE col2",
        "writes": "zeros full rows of all matched agents; decrements pop_count",
        "fires": "one-shot call",
        "use_when": [
            "targeted kill of specific agents (by sex, age, tribe, location)",
            'divine punishment of specific group ("smite all men over 60")',
            "kill agents near a specific location via dist mask",
            "when you have a precise agent mask and want immediate death",
        ],
        "do_not_use": [
            "for area-of-effect kill — use tool_area_attack(center_x, center_y, radius)",
            "for gradual HP decay — use tool_epidemic or tool_plague",
        ],
        "example_mask": "H_AGE>70 and H_SEX==0",
    },
    {
        "name": "tool_baby_boom",
        "tier": "B",
        "signature": "tool_baby_boom(mask=None)",
        "what": "Boost fertility: zero H_COOLDOWN, increase H_FERTILITY, raise MOOD to 90 for affected agents.",
        "reads": "h_tensor H_SEX col10, H_COOLDOWN col13, H_FERTILITY col5, MOOD col16",
        "writes": "H_COOLDOWN col13=0, H_FERTILITY col5 += 0.5, MOOD col16=90",
        "fires": "one-shot call",
        "use_when": [
            "baby boom events — maximum fertility burst for the population",
            "divine blessing of reproduction",
            "resetting cooldowns AND boosting fertility in one call",
        ],
        "do_not_use": [
            "for spawning specific number of new humans — use instinct_born N times",
            "for cooldown reset only — use tool_reset_cooldown",
        ],
        "example_mask": "TYPE==1 (all agents)",
    },
    {
        "name": "tool_plague",
        "tier": "B",
        "signature": "tool_plague(mask)",
        "what": "Chain: HP decay + H_INFECTION raise + THREAT raise + MOOD lower.",
        "reads": "HP col3, H_INFECTION col8, THREAT col15, MOOD col16",
        "writes": "HP col3, H_INFECTION col8, THREAT col15, MOOD col16",
        "fires": "one-shot call",
        "use_when": ["plague, epidemic, disease outbreak commands"],
        "do_not_use": ["simple HP damage — use tool_epidemic or set_attr"],
        "example_mask": "TYPE==1 and dist_to(M_TYPE==3)<50",
    },
    {
        "name": "tool_set_mood",
        "tier": "B",
        "signature": "tool_set_mood(mask, value, mode='set')",
        "what": "Set/add/multiply MOOD col16 for masked agents.",
        "reads": "MOOD col16",
        "writes": "MOOD col16, clamped [0, 100]",
        "fires": "one-shot call",
        "use_when": [
            "grief events — lower mood for witnesses",
            "celebration events — raise mood",
            "divine mood manipulation",
        ],
        "do_not_use": [
            "for full blessing (HP + mood + cooldown) — use tool_bless",
            "mode='subtract' does not exist — use mode='add' with negative value",
        ],
        "example_mask": "dist_to(last_death_site)<50, value=10.0, mode=set",
    },
    {
        "name": "tool_set_threat",
        "tier": "B",
        "signature": "tool_set_threat(mask, value, mode='set')",
        "what": "Set/add/multiply THREAT col15 for masked agents.",
        "reads": "THREAT col15",
        "writes": "THREAT col15, clamped [0, 100]",
        "fires": "one-shot call",
        "use_when": [
            "predator sighting — raise threat for nearby humans",
            "peace event — clear all threat",
            "enemy approach — raise threat for a region",
        ],
        "do_not_use": [
            "for persistent ongoing threat — instinct_infection_tick and predator attacks handle automatic threat",
        ],
        "example_mask": "TYPE==1 and dist_to(M_TYPE==2)<40, value=100.0, mode=set",
    },
    {
        "name": "tool_reset_cooldown",
        "tier": "B",
        "signature": "tool_reset_cooldown(mask=None)",
        "what": "Zero H_COOLDOWN col13 for masked agents — maximum fertility burst.",
        "reads": "H_COOLDOWN col13",
        "writes": "H_COOLDOWN col13=0",
        "fires": "one-shot call",
        "use_when": [
            "fertility events: 'make everyone fertile now'",
            "resetting mating cooldown after a divine blessing",
        ],
        "do_not_use": [
            "when you want full blessing chain — use tool_bless instead",
        ],
        "example_mask": "TYPE==1 (all agents)",
    },
    {
        "name": "tool_age_shift",
        "tier": "B",
        "signature": "tool_age_shift(mask, years)",
        "what": "Add or subtract float years from H_AGE col11 for masked agents.",
        "reads": "H_AGE col11",
        "writes": "H_AGE col11, clamped >= 0",
        "fires": "one-shot call",
        "use_when": [
            "time skip events — instantly age all humans by N years",
            "aging curse — specific agents age rapidly",
            "youth blessing — reduce age of specific group",
        ],
        "do_not_use": [
            "for gradual aging — instinct_age runs automatically each tick",
        ],
        "example_mask": "TYPE==1, years=10.0",
    },
    {
        "name": "tool_life_exp_modify",
        "tier": "B",
        "signature": "tool_life_exp_modify(mask, value, mode='multiply')",
        "what": "Set/add/multiply H_LIFE_EXP col12 for masked agents.",
        "reads": "H_LIFE_EXP col12",
        "writes": "H_LIFE_EXP col12, clamped >= 1.0",
        "fires": "one-shot call",
        "use_when": [
            "blessing: 'double life expectancy of all women'",
            "curse: 'halve life expectancy of men'",
            "divine intervention on lifespan",
        ],
        "do_not_use": [
            "for birth-conditional life expectancy changes — that requires propose_new_instinct with a birth hook",
        ],
        "example_mask": "H_SEX==1, value=2.0, mode=multiply",
    },
    {
        "name": "tool_set_aggression",
        "tier": "B",
        "signature": "tool_set_aggression(mask, value=1.0, mode='set')",
        "what": "Set/add/multiply H_AGGRESSION col6 for masked agents. Agents attack others when H_AGGRESSION >= AGGRESSION_THRESHOLD.",
        "reads": "H_AGGRESSION col6",
        "writes": "H_AGGRESSION col6, clamped [0, 1]",
        "fires": "one-shot call",
        "use_when": [
            "war god commands — make tribe aggressive toward others",
            "calming events — reset aggression to 0",
            "cursing specific agents to fight",
        ],
        "do_not_use": [
            "for threat perception — use tool_set_threat (THREAT col15)",
            "H_AGGRESSION >= threshold triggers the attack instinct automatically",
        ],
        "example_mask": "TYPE==1 and H_TRIBE==0, value=1.0, mode=set",
    },
    {
        "name": "tool_migration",
        "tier": "B",
        "signature": "tool_migration(mask, target_x, target_y, force=10.0)",
        "what": "Apply a directed force pushing masked agents toward (target_x, target_y).",
        "reads": "X col0, Y col1",
        "writes": "X col0, Y col1",
        "fires": "one-shot call",
        "use_when": [
            "forced migration events — 'push all humans north'",
            "guiding survivors toward safe ground after disaster",
            "tribal movement toward a new location",
        ],
        "do_not_use": [
            "for flee behavior (away from threat) — use instinct_flee",
            "for attraction toward an entity type — use instinct_move with attraction_target",
        ],
        "example_mask": "TYPE==1 and H_TRIBE==1, target_x=400, target_y=100",
    },
    {
        "name": "tool_quarantine",
        "tier": "B",
        "signature": "tool_quarantine()",
        "what": "Freeze infected agents: max H_COOLDOWN, zero H_STAMINA, raise THREAT. Applies to all agents with H_INFECTION >= threshold.",
        "reads": "H_INFECTION col8",
        "writes": "H_COOLDOWN col13, H_STAMINA col7, THREAT col15",
        "fires": "one-shot call",
        "use_when": [
            "quarantine god commands during plague events",
            "isolating infected population",
        ],
        "do_not_use": [
            "for healthy agents — quarantine only affects agents above INFECTION_THRESHOLD",
        ],
        "example_mask": "no mask — applies to all infected agents automatically",
    },
    {
        "name": "tool_assign_control_target",
        "tier": "B",
        "signature": "tool_assign_control_target(controller_id='local_player', target_kind='human', target_id=None, target_name=None, mode='possess')",
        "what": "Bind a controller session to a controllable target such as a human now or a vehicle/mount later.",
        "reads": "stable target IDs, resident names, live human slots, live entity slots",
        "writes": "backend control-runtime session state and frame export metadata",
        "fires": "one-shot call",
        "use_when": [
            "a decree says the user will control a specific target",
            "claiming a human now while preserving a path for future cars, mounts, or machines",
            "switching from autonomous simulation to direct control",
        ],
        "do_not_use": [
            "for low-level keys or clicks - those stay in /control/input and /control/event",
            "for permanent skills or instincts - this is runtime control state only",
        ],
        "example_mask": "controller_id=local_player, target_kind=human, target_name=Adam, mode=possess",
    },
    {
        "name": "tool_release_control_target",
        "tier": "B",
        "signature": "tool_release_control_target(controller_id='local_player', target_kind='human', target_id=None)",
        "what": "Release a controller session from its current target so autonomous simulation can resume.",
        "reads": "backend control-runtime session state",
        "writes": "removes the active controller->target binding",
        "fires": "one-shot call",
        "use_when": [
            "releasing a possessed human back to the simulation",
            "dropping control of a future vehicle or mount",
        ],
        "do_not_use": [
            "for movement updates - use the control API instead",
        ],
        "example_mask": "controller_id=local_player",
    },
    {
        "name": "tool_set_control_target_mode",
        "tier": "B",
        "signature": "tool_set_control_target_mode(controller_id, mode)",
        "what": "Change an existing control session between observe / possess / assist modes.",
        "reads": "backend control-runtime session state",
        "writes": "session mode",
        "fires": "one-shot call",
        "use_when": [
            "switching an already-claimed controller between control styles",
        ],
        "do_not_use": [
            "to create a new control session - use tool_assign_control_target first",
        ],
        "example_mask": "controller_id=local_player, mode=possess",
    },
    {
        "name": "tool_assign_player_control",
        "tier": "B",
        "signature": "tool_assign_player_control(controller_id='local_player', human_id=None, human_name=None, mode='possess')",
        "what": "Bind a controller session to a live human so Godot input overrides autonomous movement.",
        "reads": "resident names, stable human IDs, live human slots",
        "writes": "backend player-control runtime session state and frame export metadata",
        "fires": "one-shot call",
        "use_when": [
            "a decree says the user will directly control Adam or another human",
            "switching one human from autonomous sim to possession mode",
            "testing bidirectional control without changing instincts permanently",
        ],
        "do_not_use": [
            "for low-level keys or clicks 鈥?those are /control/input and /control/event messages",
            "for permanent skills or learned instincts 鈥?this is runtime control state only",
        ],
        "example_mask": "controller_id=local_player, human_name=Adam, mode=possess",
    },
    {
        "name": "tool_release_player_control",
        "tier": "B",
        "signature": "tool_release_player_control(controller_id='local_player', human_id=None)",
        "what": "Release a player-control session so the human returns to autonomous simulation.",
        "reads": "backend player-control runtime session state",
        "writes": "removes the active controller->human binding",
        "fires": "one-shot call",
        "use_when": [
            "a decree says to release Adam back to autonomous behavior",
            "stopping possession before returning to pure god-view play",
        ],
        "do_not_use": [
            "for movement updates 鈥?use the control API instead",
        ],
        "example_mask": "controller_id=local_player",
    },
    {
        "name": "tool_set_control_mode",
        "tier": "B",
        "signature": "tool_set_control_mode(controller_id, mode)",
        "what": "Change an existing control session between observe / possess / assist modes.",
        "reads": "backend player-control runtime session state",
        "writes": "session mode",
        "fires": "one-shot call",
        "use_when": [
            "switching an already-claimed controller between control styles",
        ],
        "do_not_use": [
            "to create a new possession session 鈥?use tool_assign_player_control first",
        ],
        "example_mask": "controller_id=local_player, mode=possess",
    },
    {
        "name": "tool_grant_instinct",
        "tier": "B",
        "signature": "tool_grant_instinct(mask, bit, instinct_name, heritable=False)",
        "what": "Set bit N in ACQUIRED_INSTINCT_MASK col19 for masked agents, granting them a registered acquired instinct.",
        "reads": "ACQUIRED_INSTINCT_MASK col19",
        "writes": "ACQUIRED_INSTINCT_MASK col19 (bitwise OR with 1<<bit)",
        "fires": "one-shot call",
        "use_when": [
            "teaching the tribe a known skill (fishing, hunting, crafting)",
            "granting a registered instinct to a subset of agents",
            "when the instinct logic already exists in ACQUIRED_INSTINCTS registry",
        ],
        "do_not_use": [
            "for instincts that don't exist yet — pair with propose_new_instinct in new_instincts field",
            "for all agents universally — consider whether heritable=True covers future children",
        ],
        "example_mask": "TYPE==1, bit=1, instinct_name=instinct_fish, heritable=True",
    },
    {
        "name": "tool_revoke_instinct",
        "tier": "B",
        "signature": "tool_revoke_instinct(mask, bit)",
        "what": "Clear bit N in ACQUIRED_INSTINCT_MASK col19 for masked agents.",
        "reads": "ACQUIRED_INSTINCT_MASK col19",
        "writes": "ACQUIRED_INSTINCT_MASK col19 (bitwise AND with ~(1<<bit))",
        "fires": "one-shot call",
        "use_when": [
            "removing a skill from agents (curse: forget how to fish)",
            "divine punishment removing an ability",
        ],
        "do_not_use": [
            "for instincts that aren't set — no-op but harmless",
        ],
        "example_mask": "TYPE==1, bit=1",
    },
    {
        "name": "tool_inherit_instinct",
        "tier": "B",
        "signature": "tool_inherit_instinct()",
        "what": "Copy H_PARENT_INSTINCTS col23 bits into ACQUIRED_INSTINCT_MASK col19 for all young agents (age < 1 year with parent instincts set).",
        "reads": "H_AGE col11, H_PARENT_INSTINCTS col23, ACQUIRED_INSTINCT_MASK col19",
        "writes": "ACQUIRED_INSTINCT_MASK col19 (OR with parent bits)",
        "fires": "each tick — registered in engine loop; handles inheritance automatically",
        "use_when": [
            "runs automatically — rarely needed in world agent output",
            "explicitly trigger if you want immediate inheritance for existing young agents",
        ],
        "do_not_use": [
            "to grant instincts to adults — use tool_grant_instinct",
        ],
        "example_mask": "no mask required — applies to all young agents automatically",
    },
    {
        "name": "tool_enlighten",
        "tier": "B",
        "signature": "tool_enlighten(bit, mask=None)",
        "what": "Alias for tool_grant_instinct. Sets bit N in ACQUIRED_INSTINCT_MASK. Semantically: 'enlighten' population with a skill.",
        "reads": "ACQUIRED_INSTINCT_MASK col19",
        "writes": "ACQUIRED_INSTINCT_MASK col19",
        "fires": "one-shot call",
        "use_when": [
            "same as tool_grant_instinct — prefer tool_grant_instinct for clarity",
            "divine enlightenment narrative commands",
        ],
        "do_not_use": [
            "when the instinct doesn't exist in registry — use propose_new_instinct + tool_grant_instinct together",
        ],
        "example_mask": "bit=2, mask=TYPE==1",
    },

    # ── ANIMAL / ENTITY TOOLS ─────────────────────────────────────────────────
    {
        "name": "tool_spawn_animal_group",
        "tier": "B",
        "signature": "tool_spawn_animal_group(species, count, cx, cy, scatter=30.0)",
        "what": "Spawn `count` animals of given species near (cx, cy) with random scatter.",
        "reads": "m_tensor M_TYPE col2 (finds free slots)",
        "writes": "new m_tensor rows for each animal; increments entity_count",
        "fires": "one-shot call",
        "species_constants": {
            "M_SHEEP=11": "passive prey",
            "M_DEER=12": "passive prey, fast",
            "M_TIGER=13": "predator — attacks humans",
            "M_WOLF=14": "predator — pack hunter",
            "M_FISH=15": "aquatic — lives in lakes",
        },
        "use_when": [
            "spawning a herd of prey animals in a biome",
            "introducing predators into the ecosystem",
            "replenishing animal population after hunting events",
        ],
        "do_not_use": [
            "for spawning humans — use instinct_born",
            "for spawning map features like lakes or forests — use entity_born with register_geo=True",
        ],
        "example_mask": "species=M_SHEEP, count=5, cx=300, cy=200, scatter=50",
    },
    {
        "name": "entity_born",
        "tier": "B",
        "signature": "entity_born(cx, cy, m_type, hp=100, scale=50, register_geo=False, **col_vals)",
        "what": "Spawn one map entity (lake, forest, structure, or any type) into first free m_tensor slot.",
        "reads": "m_tensor M_TYPE col2 (finds empty slot)",
        "writes": "m_tensor row; MAP_GEO if register_geo=True; increments entity_count",
        "fires": "one-shot call",
        "use_when": [
            "spawning new map features: lakes, forests, structures at a location",
            "creating dynamic entities at runtime (new settlement, sacred site)",
            "spawning natural features that need tile_mask tracking (register_geo=True)",
        ],
        "do_not_use": [
            "for animals — use animal_born or tool_spawn_animal_group",
            "for humans — use instinct_born",
        ],
        "example_mask": "cx=300, cy=200, m_type=M_LAKE, hp=100, scale=40, register_geo=True",
    },
]

TIER_B.extend(
    [
        {
            "name": "tool_create_lake",
            "tier": "B",
            "signature": "tool_create_lake(center_x, center_y, scale=48.0, water_stock=100.0, fish_stock=30.0)",
            "what": "Create one new lake entity on valid land and seed it with water and fish resources.",
            "reads": "m_tensor M_TYPE col2, CX col0, CY col1, nearby geometry occupancy",
            "writes": "new lake entity row; MAP_GEO registration; entity_count",
            "fires": "one-shot call",
            "use_when": [
                "creating a lake at a chosen location",
                "adding a freshwater source for later fishing or drinking",
            ],
            "do_not_use": [
                "when the target area is already water or a blocked structure site",
            ],
            "example_mask": "center_x=500, center_y=320, scale=55",
        },
        {
            "name": "tool_settle_area",
            "tier": "B",
            "signature": "tool_settle_area(center_x, center_y)",
            "what": "Build a small settlement cluster: village core, houses, farm, and well.",
            "reads": "buildable terrain near the target coordinates",
            "writes": "multiple new structure entity rows and MAP_GEO entries",
            "fires": "one-shot call",
            "use_when": [
                "creating a starter settlement near a chosen landmark",
                "placing a village cluster without manually calling each building tool",
            ],
            "do_not_use": [
                "when you need exact manual building placement for each structure",
            ],
            "example_mask": "center_x=620, center_y=410",
        },
        {
            "name": "tool_create_wall",
            "tier": "B",
            "signature": "tool_create_wall(start_x, start_y, end_x, end_y, thickness=12.0, durability=180.0)",
            "what": "Create one polygon wall structure between two coordinates.",
            "reads": "requested endpoints",
            "writes": "new wall entity row and MAP_GEO polygon registration",
            "fires": "one-shot call",
            "use_when": [
                "blocking a pass or surrounding a settlement",
                "building a defensive boundary between two points",
            ],
            "do_not_use": [
                "for mountains or natural terrain ridges - use mountain tools instead",
            ],
            "example_mask": "start_x=200, start_y=200, end_x=300, end_y=240",
        },
        {
            "name": "tool_transform_area",
            "tier": "B",
            "signature": "tool_transform_area(center_x, center_y, radius=80.0, target_type=M_GRASS)",
            "what": "Retype a local patch of natural entities into another biome such as grass, forest, barren, or lake.",
            "reads": "m_tensor M_TYPE col2, CX col0, CY col1",
            "writes": "M_TYPE col2 and typed resource columns for nearby natural entities",
            "fires": "one-shot call",
            "use_when": [
                "turning a burned region back into grass",
                "converting a local area into forest or barren land",
            ],
            "do_not_use": [
                "for structures or animals - this is natural-terrain focused",
            ],
            "example_mask": "center_x=700, center_y=500, radius=120, target_type=M_FOREST",
        },
        {
            "name": "tool_create_forest_patch",
            "tier": "B",
            "signature": "tool_create_forest_patch(center_x, center_y, radius=120.0, count=3)",
            "what": "Scatter a small patch of forest entities around a center point.",
            "reads": "target center position",
            "writes": "new forest entity rows and MAP_GEO registration",
            "fires": "one-shot call",
            "use_when": [
                "creating woodland near a landmark",
                "thickening the frontier with a small forest patch",
            ],
            "do_not_use": [
                "when you need a single exact forest circle instead of a patch",
            ],
            "example_mask": "center_x=350, center_y=220, radius=90, count=4",
        },
        {
            "name": "tool_create_mountain_chain",
            "tier": "B",
            "signature": "tool_create_mountain_chain(start_x, start_y, end_x, end_y, segments=4, scale=34.0)",
            "what": "Create a short mountain ridge between two points using multiple mountain entities.",
            "reads": "requested endpoints",
            "writes": "new mountain entity rows and MAP_GEO registration",
            "fires": "one-shot call",
            "use_when": [
                "raising a ridge or barrier line",
                "adding mountains beside another feature",
            ],
            "do_not_use": [
                "for a full settlement or mixed terrain cluster",
            ],
            "example_mask": "start_x=450, start_y=280, end_x=550, end_y=280, segments=3",
        },
        {
            "name": "tool_create_feature_near_feature",
            "tier": "B",
            "signature": "tool_create_feature_near_feature(feature_type, anchor_entity_id=None, near_type=None, search_x=None, search_y=None, offset_distance=48.0, bearing_deg=None, scale=None, radius=120.0, count=3, segments=4)",
            "what": "Create a new feature relative to another feature, such as a mountain next to a lake or a forest near a village.",
            "reads": "m_tensor M_TYPE col2, CX col0, CY col1, anchor feature positions",
            "writes": "new entity rows appropriate to the requested feature type",
            "fires": "one-shot call",
            "use_when": [
                "a decree describes relative placement instead of absolute coordinates",
                "you want reusable 'near / beside / next to' map construction",
            ],
            "do_not_use": [
                "when exact absolute coordinates are already known and simpler direct tools are enough",
            ],
            "example_mask": "feature_type=M_MOUNTAIN, near_type=M_LAKE, offset_distance=40, segments=3",
        },
        {
            "name": "tool_expand_world_edge",
            "tier": "B",
            "legacy_frozen": True,      # D-005: kept for the record, never offered
            "signature": "tool_expand_world_edge(edge='auto', trigger_margin=96.0, band_depth=170.0)",
            "what": "Grow a new frontier strip along a world edge by spawning fresh terrain features inside the current canvas.",
            "reads": "human positions near edges and current edge density",
            "writes": "new natural-feature entity rows and frontier expansion events",
            "fires": "one-shot call; also paired with instinct_frontier_expand for automatic expansion",
            "use_when": [
                "manually pushing the frontier east/west/north/south",
                "testing the first-step infinite-map expansion behavior",
            ],
            "do_not_use": [
                "when you need truly unbounded coordinates or camera-space streaming - this is still bounded-canvas expansion",
            ],
            "example_mask": "edge=east",
        },
    ]
)

# =============================================================================
# TIER C — PROPOSE (LAST RESORT)
# Use ONLY when no Tier A or Tier B tool can handle the required behavior.
# =============================================================================

TIER_C = [
    {
        "name": "propose_new_instinct",
        "tier": "C",
        "signature": "propose_new_instinct(name, description, heritable, mask, why_existing_tools_insufficient)",
        "what": "Request LoRA-B to generate a new tick-registered or hook-registered instinct function.",
        "reads": "N/A — this is a code generation request, not a tensor op",
        "writes": "N/A — the generated instinct will write to tensors once registered",
        "fires": "one-shot proposal; generated code is registered and fires on future ticks",
        "use_when": [
            "behavior requires PER-AGENT STATE tracked across multiple ticks (HP trajectory, memory of past events)",
            "behavior requires a BIRTH HOOK: conditional modification at moment of birth based on env state",
            "behavior requires a DEATH HOOK: reaction when an agent dies that affects other agents",
            "behavior requires SELF-TRIGGERING based on global state (pop_count threshold) with self-cancellation",
            "behavior requires PAIRWISE RELATIONSHIPS between specific agents (rival_id, mate_id stored in sidecar)",
            "behavior requires PERSISTENT SPATIAL MEMORY (trauma locations, home territory)",
            "behavior requires overriding a PER-TICK RATE (hunger increment rate, HP decay rate)",
        ],
        "do_not_use": [
            "when tool_bless, tool_plague, tool_smite etc. already cover the action",
            "for simple stat changes — use set_attr",
            "for one-shot events — use existing Tier A/B tools",
            "as a shortcut for complex-sounding commands that existing tools handle",
        ],
        "required_fields": {
            "name": "must start with 'instinct_'",
            "description": "plain English — specify: which cols read/written, when fires (tick/hook), threshold condition, sidecar fields used, composed tools/instincts by exact name",
            "heritable": "bool — True if children should inherit this behavior via H_PARENT_INSTINCTS",
            "mask": "per-agent boolean expression",
            "why_existing_tools_insufficient": "explicitly name which Tier A and B tools were considered and why each fails",
        },
    },
    {
        "name": "propose_new_tool",
        "tier": "C",
        "signature": "propose_new_tool(name, description, why_existing_tools_insufficient)",
        "what": "Request LoRA-B to generate a new one-shot Tier B composite tool.",
        "use_when": [
            "a new chained combination of existing tools is needed repeatedly",
            "a new one-shot action that composes multiple existing tools in a novel way",
        ],
        "do_not_use": [
            "when a single existing tool covers the action",
            "for persistent tick-registered behaviors — use propose_new_instinct",
        ],
    },
]

# =============================================================================
# SCENARIO DECISION GUIDE
# Quick reference for the LLM: maps common command types to correct tools
# =============================================================================

SCENARIO_GUIDE = """
=== SCENARIO → TOOL DECISION GUIDE ===

KILL / DEATH:
  Kill agents at a location (radius)   → tool_area_attack(center_x, center_y, radius)
  Kill specific masked agents           → tool_smite(mask)
  Kill weakest until N remain           → tool_cull(target_population)
  Natural age death (auto)              → instinct_die runs automatically each tick

DAMAGE / HURT:
  HP decay per tick for mask            → tool_epidemic(mask, decay_rate)
  HP decay + infection + mood           → tool_plague(mask)
  One-shot HP change                    → set_attr(mask, col=HP, value, mode=add)

HEAL / BLESS:
  Full restore (HP + mood + cooldown)   → tool_bless(mask)
  HP only                               → set_attr(mask, col=HP, value=100, mode=set)
  Mood only                             → tool_set_mood(mask, value, mode=set)

MOVEMENT / POSITION:
  Push away from threat                 → instinct_flee(mask, threat_pos)
  Pull toward location                  → instinct_move(mask, attraction_target)
  Force migrate to coordinates          → tool_migration(mask, target_x, target_y)

REPRODUCTION / FERTILITY:
  Max fertility burst (all)             → tool_baby_boom() or tool_reset_cooldown()
  Full blessing (cooldown + mood)       → tool_bless(mask)
  Spawn specific number of humans       → instinct_born × N times at coordinates

FIRE / BURNING:
  Start wildfire at location            → tool_wildfire(center_x, center_y, radius)
  Flee from burning forest              → instinct_flee(mask, threat_pos=centroid(M_TYPE==2))
  Fire spread / burnout (auto)          → instinct_fire_tick runs each tick automatically

FLOODS / WATER:
  Flood land with sea                   → tool_flood()
  Drain lakes                           → tool_drought(entity_mask)

EARTHQUAKE / VOLCANO:
  Earthquake at location                → tool_earthquake(center_x, center_y, radius)
  Volcanic eruption                     → tool_volcanic_eruption(center_x, center_y)
  Lava cooling (auto)                   → instinct_lava_tick runs each tick automatically

DISEASE / INFECTION:
  Start epidemic with spread            → tool_plague(mask)
  Quarantine infected                   → tool_quarantine()
  Infection spread (auto)               → instinct_infection_tick runs each tick

TERRAIN / MAP:
  Grow forest onto grass/barren         → tool_regrow_forest(entity_mask)
  Flood land                            → tool_flood()
  Drain lake                            → tool_drought()
  Volcano converts to lava              → tool_volcanic_eruption()
  Change entity type                    → geo_mutate(entity_id, new_type)

ANIMALS:
  Spawn animal group                    → tool_spawn_animal_group(species, count, cx, cy)
  Predator attacks (auto)               → animal_instinct_predator_attack each tick
  Animal reproduction (auto)            → animal_tool_reproduce each tick

STATS — DIRECT:
  Any stat change (HUNGER, MOOD, etc)   → set_attr(mask, col, value, mode)
  Life expectancy change                → tool_life_exp_modify(mask, value, mode)
  Age shift                             → tool_age_shift(mask, years)
  Aggression change                     → tool_set_aggression(mask, value, mode)

INSTINCTS / SKILLS:
  Grant known skill to agents           → tool_grant_instinct(mask, bit, instinct_name, heritable)
  Remove skill from agents              → tool_revoke_instinct(mask, bit)
  New skill (logic needed)              → tool_grant_instinct + propose_new_instinct in new_instincts

REQUIRES propose_new_instinct WHEN:
  Behavior tracks per-agent history across ticks       (immunity from past illness)
  Behavior fires at birth based on env state           (born during flood/famine)
  Behavior fires at death affecting other agents       (grief, inheritance)
  Behavior self-triggers based on pop_count            (fertility frenzy below 10)
  Behavior has pairwise per-agent relationship         (rivalry, kinship bond)
  Behavior overrides a per-tick rate                   (slower hunger, faster aging)
  Behavior stores persistent spatial memory            (trauma aversion, territory)
"""

# =============================================================================
# BUILD FUNCTIONS — called by run2_trace_generator to assemble prompt sections
# =============================================================================

def build_registry_string(include_tiers: list[str] = None) -> str:
    """
    Build a compact tool registry string for LLM prompt injection.
    include_tiers: list of tiers to include, e.g. ["A", "B", "C"]
                   defaults to all tiers if None
    """
    if include_tiers is None:
        include_tiers = ["A", "B", "C"]

    lines = []

    if "A" in include_tiers:
        lines.append("=== TIER A — CORE TOOLS (use first) ===")
        for tool in TIER_A:
            sig = tool["signature"]
            what = tool["what"]
            lines.append(f"  {sig}")
            lines.append(f"    → {what}")
            if "modes" in tool:
                for mode, desc in tool["modes"].items():
                    lines.append(f"    mode={mode}: {desc}")
        lines.append("")

    if "B" in include_tiers:
        lines.append("=== TIER B — EXTENDED TOOLS (if Tier A insufficient) ===")
        seen = set()
        for tool in TIER_B:
            if tool.get("legacy_frozen"):
                continue
            if tool["name"] in seen:
                continue
            seen.add(tool["name"])
            sig = tool["signature"]
            what = tool["what"]
            lines.append(f"  {sig}")
            lines.append(f"    → {what}")
        lines.append("")

    if "C" in include_tiers:
        lines.append("=== TIER C — PROPOSE (LAST RESORT — only when A and B both fail) ===")
        for tool in TIER_C:
            lines.append(f"  {tool['signature']}")
            lines.append(f"    → {tool['what']}")
        lines.append("  REQUIRED: why_existing_tools_insufficient must name which Tier A/B tools were considered and why each fails.")
        lines.append("")

    return "\n".join(lines)


def build_scenario_guide() -> str:
    """Return the scenario decision guide for prompt injection."""
    return SCENARIO_GUIDE


def build_column_reference() -> str:
    """Return the column reference for prompt injection."""
    return COLUMN_REFERENCE


def build_full_prompt_context(include_tiers: list[str] = None) -> str:
    """
    Build the complete context block for LLM prompt injection:
    column reference + tool registry + scenario guide.
    """
    return (
        build_column_reference()
        + "\n"
        + build_registry_string(include_tiers)
        + "\n"
        + build_scenario_guide()
    )


if __name__ == "__main__":
    # Quick sanity check — print full context
    print(build_full_prompt_context())
    print(f"\nTier A tools: {len(TIER_A)}")
    print(f"Tier B tools: {len(set(t['name'] for t in TIER_B))}")
    print(f"Tier C tools: {len(TIER_C)}")
