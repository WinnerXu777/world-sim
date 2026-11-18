import json
import argparse
import random
import re
from vllm import LLM, SamplingParams
from tqdm import tqdm

# =============================================================================
# 1. CORE CONFIGURATION
# =============================================================================
MODEL_ID = "neuralmagic/Meta-Llama-3.1-70B-Instruct-quantized.w4a16"
MAX_MODEL_LEN = 8192
GPU_UTIL = 0.90

# =============================================================================
# 2. GROUND TRUTH: EXACT TENSOR SCHEMAS (from project spec)
#    NEVER reference columns that don't exist here.
# =============================================================================

HUMAN_TENSOR_SCHEMA = """
### HUMAN TENSOR (h_tensor) — shape (100, 32)
FIXED COLUMNS — always valid for any human agent:
  Col 0  : X             — position x (pixel)
  Col 1  : Y             — position y (pixel)
  Col 2  : TYPE          — entity type int
  Col 3  : HP            — health points
  Col 10 : H_SEX         — 0=Male, 1=Female
  Col 11 : H_AGE         — float years
  Col 12 : H_LIFE_EXP    — life expectancy float years
  Col 13 : H_COOLDOWN    — mating recovery timer, clamped >= 0
  Col 14 : HUNGER        — hunger level float
  Col 15 : THREAT        — threat perception float
  Col 16 : MOOD          — mood float
  Col 17 : CRITICAL_HEALTH — critical health flag float
  Col 18 : ESCALATION_FLAG — set by check_escalation, read by human agent
  Col 19 : ACQUIRED_INSTINCT_MASK — bitmask, bit N = acquired instinct N active
  Col 20-31: reserved

RULES:
- NEVER use columns that do not appear above (no C_THIRST, C_SPEED, C_BEANS_ELIXIR, etc.)
- Use column names exactly as written above (HUNGER not C_HUNGER, HP not C_HP)
- Hard cap: MAX_HUMANS = 100
"""

MAP_TENSOR_SCHEMA = """
### MAP TENSOR (m_tensor) — shape (256, 32)
FIXED: Col0:CX  Col1:CY  Col2:M_TYPE  Col3:M_HP  Col4:SCALE  Col5:SPRITE_ID  Col6-9:reserved
SPECIAL ATTRS (col10-31, typed by M_TYPE — always filter by M_TYPE first):
  M_LAKE=1: col10=has_water col11=depth col12=fish_count
  M_FOREST=2  M_SEA=3  M_MOUNTAIN=4  M_BEACH=5  M_GRASS=6  (new types: int >= 50)
RULE: call geo_mutate() whenever shape/geometry changes
"""

INSTINCT_REGISTRY = """
TIER A (use first): instinct_born/die/age/move/flee/cooldown/search | tool_reproduce/area_attack/epidemic/drought | geo_mutate | set_attr(mask,col,val,mode)
TIER B (if Tier A insufficient): tool_flood/wildfire/earthquake/storm/volcanic_eruption/spawn_resource/deplete_resource/regrow_forest/set_mood/set_threat/reset_cooldown/age_shift/life_exp_modify/cull/baby_boom/plague/bless/grant_instinct/revoke_instinct/inherit_instinct
TIER C — last resort only, MUST include why_existing_tools_insufficient: propose_new_tool | propose_new_instinct
"""

# =============================================================================
# 3. EXAMPLE POOLS — split by tier so build_prompt() can sample dynamically
#
# Each pool entry is a (command, json_string) tuple.
# build_prompt() selects N examples from the right pools based on the
# 70 / 15 / 15 tier mode, then assembles the final prompt string.
#
# Tier mode weights:
#   MODE_A  (70%) — 4 examples, all from TIER_A_EXAMPLES
#   MODE_AB (15%) — 2 Tier A + 2 Tier B examples
#   MODE_ABC(15%) — 1 Tier A + 1 Tier B + 2 Tier C (golden propose) examples
# =============================================================================

TIER_A_EXAMPLES = [
    (
        "Make Adam and Eve desperately hungry.",
        """{
  "thought": "Named humans; HUNGER is col 14; set_attr covers this directly.",
  "map_actions": [],
  "human_actions": [
    {"tool_name": "set_attr",
     "parameters": {"mask": "H_NAME in ['Adam','Eve']", "col": 14, "value": 95.0, "mode": "set"}}
  ]
}"""
    ),
    (
        "Drain the northern lake completely.",
        """{
  "thought": "Lake M_TYPE=1 col 10=has_water set to 0; shape change requires geo_mutate.",
  "map_actions": [
    {"tool_name": "set_attr",
     "parameters": {"mask": "M_TYPE == 1 and CY < 300", "col": 10, "value": 0, "mode": "set"}},
    {"tool_name": "geo_mutate",
     "parameters": {"mask": "M_TYPE == 1 and CY < 300", "new_shape": "shrink_to_zero"}}
  ],
  "human_actions": []
}"""
    ),
    (
        "Strike the oldest man dead.",
        """{
  "thought": "Find max H_AGE male; instinct_die zeros that row.",
  "map_actions": [],
  "human_actions": [
    {"tool_name": "instinct_die",
     "parameters": {"mask": "H_SEX == 0 and H_AGE == max(H_AGE)"}}
  ]
}"""
    ),
    (
        "A predator is sighted — raise threat for everyone in the forest.",
        """{
  "thought": "set_attr on THREAT col 15 for agents near M_TYPE==2.",
  "map_actions": [],
  "human_actions": [
    {"tool_name": "set_attr",
     "parameters": {"mask": "TYPE == 1 and dist_to(M_TYPE == 2) < 40", "col": 15, "value": 80.0, "mode": "set"}}
  ]
}"""
    ),
    (
        "Spawn five new humans on the grass.",
        """{
  "thought": "instinct_born five times across grass biome tiles.",
  "map_actions": [],
  "human_actions": [
    {"tool_name": "instinct_born",
     "parameters": {"x": "sample(grass_tiles, n=5).x", "y": "sample(grass_tiles, n=5).y", "type_id": 1}}
  ]
}"""
    ),
    (
        "Reset all mating cooldowns — a fertility burst.",
        """{
  "thought": "H_COOLDOWN is col 13; set to 0 for all agents via set_attr.",
  "map_actions": [],
  "human_actions": [
    {"tool_name": "set_attr",
     "parameters": {"mask": "TYPE == 1", "col": 13, "value": 0.0, "mode": "set"}}
  ]
}"""
    ),
    (
        "A meteor lands at (380, 120) — destroy everything at the core, make survivors flee.",
        """{
  "thought": "Spawn crater entity; area_attack kills in core radius; instinct_flee for outer survivors.",
  "map_actions": [
    {"tool_name": "instinct_born",
     "parameters": {"x": 380, "y": 120, "type_id": 51}}
  ],
  "human_actions": [
    {"tool_name": "tool_area_attack",
     "parameters": {"center_x": 380, "center_y": 120, "radius": 25}},
    {"tool_name": "instinct_flee",
     "parameters": {"mask": "TYPE == 1 and dist(380, 120) < 80", "threat_pos": [380, 120]}}
  ]
}"""
    ),
    (
        "Double the life expectancy of every woman.",
        """{
  "thought": "H_SEX==1 is female; H_LIFE_EXP is col 12; multiply by 2.",
  "map_actions": [],
  "human_actions": [
    {"tool_name": "set_attr",
     "parameters": {"mask": "H_SEX == 1", "col": 12, "value": 2.0, "mode": "multiply"}}
  ]
}"""
    ),
]

TIER_B_EXAMPLES = [
    (
        "Flood the valley — raise the sea and kill anyone caught in it.",
        """{
  "thought": "tool_flood expands sea boundary; tool_area_attack kills agents in flooded zone.",
  "map_actions": [
    {"tool_name": "tool_flood",
     "parameters": {"direction": "inland", "distance_px": 40}}
  ],
  "human_actions": [
    {"tool_name": "tool_area_attack",
     "parameters": {"center_x": "sea_centroid_x", "center_y": "sea_centroid_y", "radius": 40}}
  ]
}"""
    ),
    (
        "Send a plague — all humans near the sea lose HP every tick and panic.",
        """{
  "thought": "tool_plague chains epidemic + threat raise + mood lower for the coastal mask.",
  "map_actions": [],
  "human_actions": [
    {"tool_name": "tool_plague",
     "parameters": {"mask": "TYPE == 1 and dist_to(M_TYPE == 3) < 50"}}
  ]
}"""
    ),
    (
        "Bless the women — restore their HP and reset their mating cooldowns.",
        """{
  "thought": "tool_bless chains HP restore + mood raise + cooldown reset for female mask.",
  "map_actions": [],
  "human_actions": [
    {"tool_name": "tool_bless",
     "parameters": {"mask": "H_SEX == 1"}}
  ]
}"""
    ),
    (
        "Teach the tribe to fish from the lake — and let their children inherit it.",
        """{
  "thought": "tool_grant_instinct sets the fishing bit with heritable=true.",
  "map_actions": [],
  "human_actions": [
    {"tool_name": "tool_grant_instinct",
     "parameters": {"mask": "TYPE == 1", "instinct_name": "instinct_fish", "heritable": true}}
  ]
}"""
    ),
    (
        "Spawn a wildfire in the forest and make everyone flee.",
        """{
  "thought": "tool_wildfire spreads fire on forest tiles; instinct_flee repels all humans.",
  "map_actions": [
    {"tool_name": "tool_wildfire",
     "parameters": {"mask": "M_TYPE == 2", "spread_rate": 0.3}}
  ],
  "human_actions": [
    {"tool_name": "instinct_flee",
     "parameters": {"mask": "TYPE == 1", "threat_pos": "centroid(M_TYPE == 2)"}}
  ]
}"""
    ),
    (
        "Cull the population down to 20 — kill the weakest first.",
        """{
  "thought": "tool_cull kills lowest-HP agents until pop_count reaches target.",
  "map_actions": [],
  "human_actions": [
    {"tool_name": "tool_cull",
     "parameters": {"target_population": 20}}
  ]
}"""
    ),
    (
        "An earthquake hits the mountain — shake everyone nearby and destroy the peak.",
        """{
  "thought": "tool_earthquake applies force in radius; set M_HP=0 on mountain entity.",
  "map_actions": [
    {"tool_name": "tool_earthquake",
     "parameters": {"center_x": "mountain_cx", "center_y": "mountain_cy", "radius": 80, "magnitude": 3.5}},
    {"tool_name": "set_attr",
     "parameters": {"mask": "M_TYPE == 4", "col": 3, "value": 0, "mode": "set"}}
  ],
  "human_actions": []
}"""
    ),
    (
        "The forest regrows southward into the grassland.",
        """{
  "thought": "tool_regrow_forest expands geometry; geo_mutate updates tile_mask.",
  "map_actions": [
    {"tool_name": "tool_regrow_forest",
     "parameters": {"mask": "M_TYPE == 2 and CY > 300", "expansion_px": 20}}
  ],
  "human_actions": []
}"""
    ),
]

# Golden propose examples — hand-written, used only in MODE_ABC
# Each is (command, json_string, pattern_tag)
TIER_C_EXAMPLES = [
    (
        "Humans who survive a plague should become immune and pass immunity to their children.",
        """{
  "thought": "Immunity requires blocking tool_epidemic per-agent based on HP recovery history — no existing tool tracks whether a specific agent previously crossed an HP threshold.",
  "map_actions": [],
  "human_actions": [
    {"tool_name": "propose_new_instinct",
     "parameters": {
       "name": "instinct_plague_immunity",
       "description": "Each tick: for agents with immunity bit (col 19 bit 3) set, zero out HP decay applied by tool_epidemic by storing pre-epidemic HP and restoring it. Immunity bit SET when agent HP crosses upward through 50.0 after having been below 20.0 in a prior tick — track with 'was_critical' boolean in ResidentAgent sidecar. On birth, if parent has immunity bit, child inherits via instinct_inherit.",
       "heritable": true,
       "mask": "TYPE == 1",
       "why_existing_tools_insufficient": "tool_epidemic applies decay uniformly with no per-agent exclusion mask. tool_grant_instinct sets bits immediately and unconditionally — it cannot fire based on HP recovery trajectory. No Tier A or B tool tracks whether a specific agent's HP previously crossed a threshold."
     }}
  ]
}""",
        "past_state_memory"
    ),
    (
        "When a lake dries up, the humans who depended on it should automatically seek a new water source.",
        """{
  "thought": "Requires monitoring m_tensor col 10 across ticks and reactively switching per-agent attraction targets — no Tier A or B tool polls map state and conditionally updates movement targets.",
  "map_actions": [],
  "human_actions": [
    {"tool_name": "propose_new_instinct",
     "parameters": {
       "name": "instinct_water_seek",
       "description": "Each tick: build mask of agents whose ResidentAgent 'water_source' entity_id now has m_tensor col 10 == 0. For those agents, find nearest M_TYPE==1 where col 10 == 1 and update attraction target to its (CX, CY). If none exists, raise THREAT += 5 and HUNGER += 2 via set_attr. Clear 'water_source' in sidecar when agent reaches new lake within 10px.",
       "heritable": false,
       "mask": "TYPE == 1",
       "why_existing_tools_insufficient": "tool_drought and instinct_move are stateless one-shot calls — tool_drought dries a lake once, instinct_move moves agents once toward a fixed target. No existing tool monitors m_tensor col 10 across ticks and reactively updates per-agent attraction targets stored in ResidentAgent sidecar."
     }}
  ]
}""",
        "conditional_tool_chaining"
    ),
    (
        "If the population drops below 10, all survivors enter a desperate fertility frenzy — no cooldowns, ignore threats.",
        """{
  "thought": "Threshold monitor that self-triggers and self-cancels based on pop_count — must live inside the tick loop, cannot be a one-shot world agent call.",
  "map_actions": [],
  "human_actions": [
    {"tool_name": "propose_new_instinct",
     "parameters": {
       "name": "instinct_survival_frenzy",
       "description": "Each tick: check pop_count (O(1)). If pop_count < 10: set FRENZY bit (col 19 bit 7) for all agents via set_attr col 19 mode=or; zero H_COOLDOWN col 13; set THREAT col 15 = 0; set MOOD col 16 = 80. If pop_count >= 10 and FRENZY bit set: clear bit via set_attr mode=and inverted mask; restore THREAT = 10.0.",
       "heritable": false,
       "mask": "TYPE == 1",
       "why_existing_tools_insufficient": "tool_reset_cooldown, tool_set_threat, and tool_set_mood are one-shot world agent calls dispatched from outside the tick loop — they cannot self-trigger on pop_count and cannot self-cancel when the condition resolves. The threshold monitor must be a registered instinct firing every tick."
     }}
  ]
}""",
        "threshold_cascade"
    ),
    (
        "Any human who witnesses a death should permanently avoid that location.",
        """{
  "thought": "Persistent spatial repulsion tied to a specific remembered coordinate — requires writing to ResidentAgent memory and re-firing instinct_flee every tick per stored location.",
  "map_actions": [],
  "human_actions": [
    {"tool_name": "propose_new_instinct",
     "parameters": {
       "name": "instinct_trauma_aversion",
       "description": "Death hook (after instinct_die): for all agents within 40px of death location (witness_mask), append {'type':'death_site','x':death_x,'y':death_y} to ResidentAgent memory ring buffer. Each tick: for each agent, iterate memory 'death_site' entries. If dist(agent_pos, site) < 50px, apply instinct_flee with threat_pos=(site.x, site.y), scale repulsion by 1 - dist/50. Entries expire after 500 ticks via ring buffer eviction.",
       "heritable": false,
       "mask": "TYPE == 1",
       "why_existing_tools_insufficient": "instinct_flee is a one-shot call with no persistence — it cannot re-fire every tick from stored coordinates. No Tier A or B tool reads from or writes to the ResidentAgent memory ring buffer. Each agent has a heterogeneous list of traumatic locations that cannot be encoded in the homogeneous h_tensor."
     }}
  ]
}""",
        "location_bound_trauma"
    ),
    (
        "Children born during a famine grow up hardier — higher life expectancy and slower hunger decay.",
        """{
  "thought": "Famine-born tag must be set at birth based on population hunger state and then permanently modify that agent's tick-rate — no tool hooks into instinct_born conditionally or overrides per-agent stat decay rates.",
  "map_actions": [],
  "human_actions": [
    {"tool_name": "propose_new_instinct",
     "parameters": {
       "name": "instinct_famine_hardening",
       "description": "Birth hook inside instinct_born: if mean(h_tensor[:,14][h_mask]) > 70.0, set 'famine_born'=True in new agent's ResidentAgent sidecar and apply set_attr H_LIFE_EXP col 12 *= 1.35 immediately. Each tick: for agents with 'famine_born'==True, subtract 0.4 from HUNGER col 14 after base instinct_age increment (net hunger rate reduced from 1.0 to 0.6 per tick).",
       "heritable": false,
       "mask": "TYPE == 1",
       "why_existing_tools_insufficient": "tool_life_exp_modify applies to a current mask at call time — it cannot hook into instinct_born to modify a newborn based on population state at birth. No Tier A or B tool can override the per-tick HUNGER increment rate, which is internal to instinct_age and not a configurable parameter."
     }}
  ]
}""",
        "multigenerational_trigger"
    ),
    (
        "Make the two strongest humans rivals — they get more aggressive whenever they are near each other.",
        """{
  "thought": "Pairwise relationship where buff magnitude scales with real-time distance to one specific agent — cannot be expressed as a uniform mask operation.",
  "map_actions": [],
  "human_actions": [
    {"tool_name": "propose_new_instinct",
     "parameters": {
       "name": "instinct_rivalry",
       "description": "Init: identify two agents with highest HP; store each other's row index in ResidentAgent sidecar 'rival_id'. Each tick: for agents with 'rival_id' set, compute dist=euclidean(agent_pos, rival_pos). If dist < 60px: MOOD -= 10 * (1 - dist/60), H_COOLDOWN *= 0.5 via set_attr. If dist > 200px: MOOD += 3. Buff scales linearly with proximity.",
       "heritable": false,
       "mask": "TYPE == 1 and rank(HP, descending) <= 2",
       "why_existing_tools_insufficient": "tool_set_mood and set_attr apply uniform values to a boolean mask — they cannot compute a per-agent modifier varying with real-time distance to one specific other agent. No Tier B tool stores pairwise relationships or reads ResidentAgent sidecar fields."
     }}
  ]
}""",
        "emergent_social_state"
    ),
]

# =============================================================================
# 4. DYNAMIC PROMPT BUILDER
#
# Tier modes and their example composition:
#   MODE_A   (prob=0.70) — 4 examples, all Tier A
#   MODE_AB  (prob=0.15) — 2 Tier A + 2 Tier B
#   MODE_ABC (prob=0.15) — 2 Tier A + 1 Tier B + 1 Tier C (golden propose)
#
# Example count rationale (token budget with compact system prompt):
#   System prompt:  ~900 tokens
#   4× Tier A:      ~720 tokens  → total ~1620, headroom +1900  ✓
#   2A+2B:          ~720 tokens  → total ~1620, headroom +1900  ✓
#   2A+1B+1C:       ~1260 tokens → total ~2160, headroom +1350  ✓
#   Using 2 Tier C would cost ~2800 → only +700 headroom, too tight for long commands.
# =============================================================================

TIER_MODE_WEIGHTS = [
    ("MODE_A",   0.70),
    ("MODE_AB",  0.15),
    ("MODE_ABC", 0.15),
]

SYSTEM_PROMPT = f"""You are the 'World Lead Architect' for Eden, a multi-agent world simulation.
Your job: decompose a God Command into structured JSON tool calls.
Output ONLY a JSON object — no markdown fences, no preamble, no extra text.

{HUMAN_TENSOR_SCHEMA}
{MAP_TENSOR_SCHEMA}
{INSTINCT_REGISTRY}

### TOOL SELECTION PRIORITY — follow this order strictly
1. Use TIER A tools (core instincts + composite tools) if they cover the action.
2. Use TIER B tools (extended library) if Tier A doesn't cover it.
3. Use propose_new_tool or propose_new_instinct ONLY as last resort when NEITHER
   Tier A nor Tier B can handle the action. You MUST include
   "why_existing_tools_insufficient" in parameters explaining why both tiers fail.

### OUTPUT FORMAT
Always output exactly this structure:
{{
  "thought": "<one-sentence reasoning>",
  "map_actions": [...],
  "human_actions": [...]
}}
"""


def _pick_mode() -> str:
    """Sample a tier mode according to TIER_MODE_WEIGHTS."""
    modes, weights = zip(*TIER_MODE_WEIGHTS)
    return random.choices(modes, weights=weights, k=1)[0]


def build_prompt(god_command: str) -> tuple[str, str]:
    """
    Build a fully assembled prompt for one god_command.
    Returns (prompt_string, tier_mode) so the tier can be saved alongside output.

    Example selection per mode:
      MODE_A   — 4 random Tier A examples
      MODE_AB  — 2 random Tier A + 2 random Tier B
      MODE_ABC — 1 random Tier A + 1 random Tier B + 2 random Tier C
    """
    mode = _pick_mode()

    if mode == "MODE_A":
        selected = random.sample(TIER_A_EXAMPLES, min(4, len(TIER_A_EXAMPLES)))
    elif mode == "MODE_AB":
        a_picks = random.sample(TIER_A_EXAMPLES, min(2, len(TIER_A_EXAMPLES)))
        b_picks = random.sample(TIER_B_EXAMPLES, min(2, len(TIER_B_EXAMPLES)))
        selected = a_picks + b_picks
        random.shuffle(selected)  # interleave so model doesn't pattern-match on order
    else:  # MODE_ABC — 2 Tier A + 1 Tier B + 1 Tier C
        a_picks = random.sample(TIER_A_EXAMPLES, min(2, len(TIER_A_EXAMPLES)))
        b_picks = random.sample(TIER_B_EXAMPLES, min(1, len(TIER_B_EXAMPLES)))
        c_pick  = random.sample(TIER_C_EXAMPLES, 1)
        c_picks_clean = [(cmd, json_str) for cmd, json_str, _ in c_pick]
        selected = a_picks + b_picks + c_picks_clean
        random.shuffle(selected)

    # Assemble example block
    example_block = ""
    for cmd, json_str in selected:
        example_block += f"\n---\nGod Command: \"{cmd}\"\n{json_str}\n"

    prompt = (
        f"{SYSTEM_PROMPT}"
        f"\n### EXAMPLES{example_block}"
        f"\n---\nGod Command: \"{god_command}\"\n"
    )
    return prompt, mode

# =============================================================================
# 4. GROUNDED SEED PROMPTS — cover every tensor surface area
#    These are the exemplars shown to the LLM during brainstorm expansion.
#    Each one maps cleanly to real columns / instincts.
# =============================================================================

SEED_PROMPTS = [
    # --- Population / reproduction ---
    "Make everyone fertile — reset all mating cooldowns to zero.",
    "Strike the two oldest humans with a heart attack.",
    "All women past age 40 become barren.",
    "A baby boom: spawn 5 new humans scattered across the grass biome.",
    "The eldest man passes his hunting knowledge to his children.",

    # --- Hunger / survival ---
    "A famine hits — set every human's hunger to critical.",
    "Rain fills the lake; fish_count doubles.",
    "The sea provides: all humans near the coast lose their hunger.",
    "Drought — drain every lake on the map.",
    "Hunters return with food; reduce hunger for the 3 hungriest humans by 50.",

    # --- Threat / mood / escalation ---
    "A predator is sighted; raise threat for all humans in the forest.",
    "Peaceful dawn — set every human's mood to calm and clear all threat.",
    "The tribe mourns a death; set mood low for every human near the dead body.",
    "A rival tribe approaches from the east; escalate threat for humans on that side.",

    # --- Terrain / map ---
    "The forest spreads south into the grassland.",
    "A wildfire: set the forest's burning flag and shrink its geometry.",
    "Earthquake cracks the mountain; spawn a rock slide entity at its peak.",
    "The sea rises — shallow water tiles advance 10 pixels inland.",
    "A meteor lands at the center of the map; spawn a crater and kill everything within 25 pixels.",

    # --- New instincts / behaviours ---
    "Teach the humans to fish from the lake.",
    "The tribe learns to craft tools — grant crafting instinct to all adults.",
    "Animals in the forest evolve to flee fire automatically.",
    "Survivors of the plague develop immunity — add a resistance instinct.",

    # --- HP / life expectancy ---
    "Bless the youngest generation: double the life expectancy of anyone under age 5.",
    "Curse the men: halve HP for all males.",
    "A healer visits: restore full HP to every critically injured human.",
    "Age accelerates: add 10 years to every human's age instantly.",

    # --- Mixed / multi-step ---
    "Flood the valley: drain both lakes, raise sea boundary, and make humans flee uphill.",
    "A disease spreads from the sea; humans near the coast take HP decay and raise threat.",
    "Night falls: lower mood for all, double cooldown timers, reduce movement attraction.",
    "The harvest festival: spawn food entities on grass tiles and reset hunger for all.",
]

# =============================================================================
# 5. JSON VALIDATION
# =============================================================================

REQUIRED_TOP_KEYS = {"thought", "map_actions", "human_actions"}
# =============================================================================
# TIERED TOOL REGISTRY
#
# TIER_A  — fully implemented, stable call signatures. Appear in ~70% of examples.
# TIER_B  — planned / partially stubbed tools the model should learn to call
#           correctly NOW so it's ready when they go live. ~15% of examples.
# TIER_C  — propose_* only. Model must show it tried A/B first. ~15% of examples.
#
# Validator logic:
#   - Any TIER_A or TIER_B name  → always valid
#   - propose_new_tool / propose_new_instinct → valid ONLY when no TIER_A/B tool
#     could plausibly have handled the action (checked via PROPOSE_JUSTIFICATION
#     key presence in parameters)
#   - Anything else              → hallucinated tool name → reject
# =============================================================================

TIER_A_TOOLS = {
    # --- core instincts (tensor ops) ---
    "instinct_born",          # spawn agent into free tensor slot
    "instinct_die",           # zero row, decrement pop_count
    "instinct_age",           # age += 1/TICKS_PER_YEAR
    "instinct_move",          # Brownian walk + optional attraction bias
    "instinct_flee",          # repulsion vector away from threat_pos
    "instinct_cooldown",      # decay any timer column toward zero
    "instinct_search",        # compute seek_mask (mature + cooldown == 0)
    # --- composite tools ---
    "tool_reproduce",         # search → proximity → instinct_born + cooldown
    "tool_area_attack",       # proximity → instinct_die + instinct_flee
    "tool_epidemic",          # proximity → HP decay per tick
    "tool_drought",           # m_tensor col write + geo_mutate
    # --- map / geometry ---
    "geo_mutate",             # atomically update MAP_GEO shape + bump geo_version
    "set_attr",               # write m_tensor or h_tensor col (mode: set/add/multiply/or)
}

TIER_B_TOOLS = {
    # --- weather & environment (stubbed, signatures defined) ---
    "tool_flood",             # raise sea boundary, push agents uphill
    "tool_wildfire",          # spread fire flag across forest tiles per tick
    "tool_earthquake",        # apply random force to all agents in radius
    "tool_storm",             # spawn storm entity + area HP decay + instinct_flee
    "tool_volcanic_eruption", # spawn lava entity, kill in core radius, flee outer
    # --- resource manipulation ---
    "tool_spawn_resource",    # place food/water/material entity on tile
    "tool_deplete_resource",  # reduce fish_count / has_water on map entity
    "tool_regrow_forest",     # geo_mutate forest outward + increment tree density col
    # --- social / relationship ---
    "tool_set_mood",          # set MOOD col for masked agents (wrapper around set_attr)
    "tool_set_threat",        # set THREAT col for masked agents
    "tool_reset_cooldown",    # zero H_COOLDOWN for masked agents (fertility burst)
    "tool_age_shift",         # add/subtract years to H_AGE for masked agents
    "tool_life_exp_modify",   # multiply H_LIFE_EXP for masked agents
    # --- population-level ---
    "tool_cull",              # kill lowest-HP agents until population <= N
    "tool_baby_boom",         # spawn N agents at random grass/beach tiles
    "tool_plague",            # epidemic + threat raise + mood lower, chained
    "tool_bless",             # HP restore + mood raise + cooldown reset, chained
    # --- instinct management ---
    "tool_grant_instinct",    # set bit N in ACQUIRED_INSTINCT_MASK for masked agents
    "tool_revoke_instinct",   # clear bit N in ACQUIRED_INSTINCT_MASK
    "tool_inherit_instinct",  # copy instinct bits from parent to all children mask
}

TIER_C_TOOLS = {
    # propose_* are valid ONLY as last resort — validator enforces this
    "propose_new_tool",       # request new Tier-1 composite tool from Coder LoRA
    "propose_new_instinct",   # request new acquired instinct (optionally heritable)
}

VALID_TOOL_NAMES = TIER_A_TOOLS | TIER_B_TOOLS | TIER_C_TOOLS

# Columns that existed in old (wrong) schema — reject if model hallucinates these
HALLUCINATED_COLUMNS = {
    "C_THIRST", "C_SPEED", "C_BEANS_ELIXIR", "C_HUNGER",
    "C_HP", "C_TYPE", "C_SCALE", "C_SPRITE_ID",
    "G_ARG1", "G_ARG2", "G_ARG3", "G_ARG4", "G_ARG5",
}


def _uses_only_propose(parsed: dict) -> bool:
    """True if every action in both lists is a propose_* call."""
    all_actions = parsed.get("map_actions", []) + parsed.get("human_actions", [])
    if not all_actions:
        return False
    return all(a.get("tool_name", "") in TIER_C_TOOLS for a in all_actions)


def _propose_has_justification(parsed: dict) -> bool:
    """
    When propose_* is used, require a 'why_existing_tools_insufficient' key
    in parameters — forces model to articulate why Tier A/B couldn't handle it.
    """
    all_actions = parsed.get("map_actions", []) + parsed.get("human_actions", [])
    for action in all_actions:
        if action.get("tool_name") in TIER_C_TOOLS:
            if "why_existing_tools_insufficient" not in action.get("parameters", {}):
                return False
    return True


def extract_json_block(text: str) -> str:
    """Pull the first {...} block out of model output."""
    # Try to find JSON object, accounting for leading "Thought:" noise
    match = re.search(r'\{.*\}', text, re.DOTALL)
    return match.group(0) if match else ""


def validate_output(raw_text: str) -> tuple[bool, dict | None, str]:
    """
    Returns (is_valid, parsed_dict, reason_if_invalid).

    Tiered validation:
      1. Extractable JSON block
      2. Required top-level keys: thought, map_actions, human_actions
      3. map_actions and human_actions are lists
      4. Each action has tool_name (str) and parameters (dict)
      5. tool_name is in TIER_A | TIER_B | TIER_C  (no hallucinated names)
      6. If ANY propose_* is used → every propose action must include
         'why_existing_tools_insufficient' in parameters
      7. No hallucinated column names anywhere in serialized output
    """
    json_str = extract_json_block(raw_text)
    if not json_str:
        return False, None, "no JSON block found"

    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as e:
        return False, None, f"JSON parse error: {e}"

    # 2. Required top-level keys
    missing = REQUIRED_TOP_KEYS - set(parsed.keys())
    if missing:
        return False, None, f"missing keys: {missing}"

    # 3. Lists
    for field in ("map_actions", "human_actions"):
        if not isinstance(parsed[field], list):
            return False, None, f"{field} is not a list"

    # 4 & 5. Per-action checks
    for field in ("map_actions", "human_actions"):
        for i, action in enumerate(parsed[field]):
            if not isinstance(action, dict):
                return False, None, f"{field}[{i}] is not a dict"
            if "tool_name" not in action:
                return False, None, f"{field}[{i}] missing tool_name"
            if not isinstance(action["tool_name"], str):
                return False, None, f"{field}[{i}].tool_name is not a string"
            if "parameters" not in action:
                return False, None, f"{field}[{i}] missing parameters"
            if not isinstance(action["parameters"], dict):
                return False, None, f"{field}[{i}].parameters is not a dict"
            if action["tool_name"] not in VALID_TOOL_NAMES:
                return False, None, f"unknown tool_name '{action['tool_name']}'"

    # 6. propose_* must carry justification — prevents lazy over-use
    if not _propose_has_justification(parsed):
        return False, None, (
            "propose_* used without 'why_existing_tools_insufficient' in parameters"
        )

    # 7. Hallucinated column names
    serialized = json.dumps(parsed)
    for bad_col in HALLUCINATED_COLUMNS:
        if bad_col in serialized:
            return False, None, f"hallucinated column name: {bad_col}"

    return True, parsed, ""


# =============================================================================
# 6. MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Generate SFT data for the World Agent.")
    parser.add_argument("--count",      type=int, default=200,  help="Target valid pairs to generate")
    parser.add_argument("--batch_size", type=int, default=16,   help="vLLM concurrent batch size")
    parser.add_argument("--output",     type=str, default="world_agent_sft.jsonl")
    parser.add_argument("--max_retries",type=int, default=3,    help="Retry multiplier for invalid outputs")
    args = parser.parse_args()

    print(f"--- Loading model: {MODEL_ID} ---")
    llm = LLM(model=MODEL_ID, max_model_len=MAX_MODEL_LEN, gpu_memory_utilization=GPU_UTIL)

    # -------------------------------------------------------------------------
    # PHASE 1: Build prompt pool — seed list + LLM expansion
    # -------------------------------------------------------------------------
    print("--- Phase 1: Building grounded prompt pool ---")

    # Always include all seeds
    prompt_pool = list(SEED_PROMPTS)
    prompt_set = set(SEED_PROMPTS)

    # Expand with LLM, using seeds as exemplars so it stays on-distribution
    target_pool_size = max(args.count * 2, len(SEED_PROMPTS) * 4)
    expand_params = SamplingParams(temperature=0.85, max_tokens=256)

    pbar = tqdm(total=target_pool_size, desc="Building prompt pool")
    pbar.update(len(prompt_pool))

    while len(prompt_pool) < target_pool_size:
        # Sample 5 random seeds as exemplars each time — forces diversity
        exemplars = random.sample(SEED_PROMPTS, min(5, len(SEED_PROMPTS)))
        exemplar_block = "\n".join(f"- {e}" for e in exemplars)

        expansion_instruction = (
            "You are generating training prompts for a world simulation game called Eden.\n"
            "Players issue 'God Commands' that affect a living population (up to 100 humans) "
            "and a map with these entity types: lake, forest, sea, mountain, beach, grass.\n"
            "Human attributes that exist: HP, hunger, mood, threat, age, life_expectancy, "
            "sex (male/female), mating_cooldown, acquired_instincts.\n\n"
            "Here are example God Commands:\n"
            f"{exemplar_block}\n\n"
            "Generate 8 NEW God Commands in the same style. "
            "Commands must reference real attributes (HP, hunger, mood, threat, age, sex, cooldown) "
            "or real map entities (lake, forest, sea, mountain, beach). "
            "Be creative but stay grounded — no made-up columns or fantasy nonsense. "
            "One command per line, no numbering, no quotes."
        )

        batch = [expansion_instruction] * args.batch_size
        outputs = llm.generate(batch, expand_params)

        for output in outputs:
            for line in output.outputs[0].text.split('\n'):
                clean = line.strip().lstrip('- ').strip()
                if (len(clean) > 15
                        and clean not in prompt_set
                        and not clean.startswith('#')
                        and len(clean) < 200):
                    prompt_set.add(clean)
                    prompt_pool.append(clean)
                    pbar.update(1)

    pbar.close()
    print(f"Prompt pool size: {len(prompt_pool)}")

    # -------------------------------------------------------------------------
    # PHASE 2: Generate SFT traces
    # -------------------------------------------------------------------------
    print(f"--- Phase 2: Generating SFT traces (target: {args.count} valid) ---")

    sft_params = SamplingParams(
        temperature=0.3,
        max_tokens=1024,
        stop=["\n---\nGod Command:"],  # clean boundary, won't appear inside JSON
    )

    valid_entries = []
    invalid_count = 0
    invalid_reasons: dict[str, int] = {}
    attempts = 0
    max_attempts = args.count * args.max_retries

    pbar = tqdm(total=args.count, desc="Valid entries")

    while len(valid_entries) < args.count and attempts < max_attempts:
        remaining_needed = args.count - len(valid_entries)
        batch_size = min(args.batch_size, remaining_needed * 2)
        batch_prompts = random.sample(prompt_pool, min(batch_size, len(prompt_pool)))

        # Build one prompt per command — each gets its own sampled tier mode
        built = [build_prompt(p) for p in batch_prompts]
        formatted   = [b[0] for b in built]
        tier_modes  = [b[1] for b in built]

        outputs = llm.generate(formatted, sft_params)
        attempts += len(outputs)

        for i, output in enumerate(outputs):
            if not output.outputs:
                continue
            raw = output.outputs[0].text.strip()
            is_valid, parsed, reason = validate_output(raw)

            if is_valid:
                valid_entries.append({
                    "input":     batch_prompts[i],
                    "output":    parsed,
                    "tier_mode": tier_modes[i],   # useful for post-hoc analysis
                })
                pbar.update(1)
                if len(valid_entries) >= args.count:
                    break
            else:
                invalid_count += 1
                invalid_reasons[reason] = invalid_reasons.get(reason, 0) + 1

    pbar.close()

    # -------------------------------------------------------------------------
    # PHASE 3: Save + report
    # -------------------------------------------------------------------------
    print(f"--- Phase 3: Saving {len(valid_entries)} entries to {args.output} ---")

    with open(args.output, "w") as f:
        for entry in valid_entries:
            f.write(json.dumps(entry) + "\n")

    acceptance_rate = len(valid_entries) / max(attempts, 1) * 100
    print(f"--- Done. Acceptance rate: {acceptance_rate:.1f}% ({len(valid_entries)}/{attempts}) ---")

    # Tier distribution
    from collections import Counter
    tier_counts = Counter(e["tier_mode"] for e in valid_entries)
    print("Tier distribution:")
    for mode, count in sorted(tier_counts.items()):
        print(f"  {mode:10s}: {count:4d}  ({count/len(valid_entries)*100:.1f}%)")

    # Rejection breakdown — helps diagnose which validation rule is firing most
    if invalid_reasons:
        print(f"\nRejection breakdown ({invalid_count} total discarded):")
        for reason, count in sorted(invalid_reasons.items(), key=lambda x: -x[1]):
            print(f"  [{count:4d}x] {reason}")

    if acceptance_rate < 50:
        print("\nWARNING: acceptance rate below 50% — check rejection breakdown above.")


if __name__ == "__main__":
    main()