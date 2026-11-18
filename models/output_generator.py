"""
run2_trace_generator.py
=======================
Phase 2 of the Eden SFT pipeline.

Reads the reviewed prompts.jsonl produced by run1_prompt_generator.py
and generates validated JSON SFT traces for each prompt.

OUTPUT SCHEMA — world agent always emits all 5 fields:
    {
      "thought":        "<one sentence reasoning>",
      "map_actions":    [...],   // tensor ops for map entities
      "human_actions":  [...],   // tensor ops for human agents
      "new_entities":   [...],   // new map entity types needing sprite generation
      "new_instincts":  [...]    // new instinct code gen requests
    }
    new_entities and new_instincts are always present, empty list [] when unused.
    graph_edges for LightRAG are derived deterministically by Python script
    from new_instinct descriptions — NOT part of LLM output.

TIER TAXONOMY:
    tier_hint "A" → MODE_A   (4 Tier A examples)         ~70% of data
    tier_hint "B" → MODE_AB  (2 Tier A + 2 Tier B)       ~20% of data
    tier_hint "C" → MODE_ABC (2 Tier A + 1 Tier B + 1 Tier C)  ~10% of data
    Tier B examples now include new_entities and new_instincts structured outputs.
    Tier C examples show propose_* reasoning-heavy boundary cases.

Usage:
    python run2_trace_generator.py --input prompts.jsonl --output sft_dataset.jsonl
    python run2_trace_generator.py --input prompts.jsonl --output sft_dataset.jsonl \\
        --batch_size 64 --max_retries 5
"""

import json
import argparse
import random
import re
from vllm import LLM, SamplingParams
from tqdm import tqdm
from collections import Counter

# =============================================================================
# CONFIGURATION
# =============================================================================
MODEL_ID      = "neuralmagic/Meta-Llama-3.1-70B-Instruct-quantized.w4a16"
MAX_MODEL_LEN = 8192
GPU_UTIL      = 0.85

# =============================================================================
# TENSOR SCHEMAS — compact form to preserve context budget
# =============================================================================

HUMAN_TENSOR_SCHEMA = """### HUMAN TENSOR (h_tensor) shape=(100,32)
FIXED COLS: 0:X  1:Y  2:TYPE  3:HP  10:H_SEX(0=M,1=F)  11:H_AGE  12:H_LIFE_EXP
            13:H_COOLDOWN  14:HUNGER  15:THREAT  16:MOOD  17:CRITICAL_HEALTH
            18:ESCALATION_FLAG  19:ACQUIRED_INSTINCT_MASK  20-31:reserved
RULES: exact col names only; no C_THIRST/C_SPEED/G_ARG* etc; cap=100 agents"""

MAP_TENSOR_SCHEMA = """### MAP TENSOR (m_tensor) shape=(256,32)
FIXED COLS: 0:CX  1:CY  2:M_TYPE  3:M_HP  4:SCALE  5:SPRITE_ID  6-9:reserved
SPECIAL(col10-31, typed by M_TYPE — filter by M_TYPE first):
  M_LAKE=1: col10=has_water col11=depth col12=fish_count
  M_FOREST=2  M_SEA=3  M_MOUNTAIN=4  M_BEACH=5  M_GRASS=6  (new types: int>=50)
RULE: call geo_mutate() whenever shape/geometry changes"""

INSTINCT_REGISTRY = """TIER A (use first): instinct_born/die/age/move/flee/cooldown/search | tool_reproduce/area_attack/epidemic/drought | geo_mutate | set_attr(mask,col,val,mode)
TIER B (if Tier A insufficient): tool_flood/wildfire/earthquake/storm/volcanic_eruption/spawn_resource/deplete_resource/regrow_forest/set_mood/set_threat/reset_cooldown/age_shift/life_exp_modify/cull/baby_boom/plague/bless/grant_instinct/revoke_instinct/inherit_instinct
TIER C — last resort, MUST include why_existing_tools_insufficient: propose_new_tool | propose_new_instinct"""

# =============================================================================
# SYSTEM PROMPT — injected once per prompt, always the same
# =============================================================================

SYSTEM_PROMPT = f"""You are the World Lead Architect for Eden, a multi-agent world simulation.
Your role is STRUCTURED DISPATCH only — interpret god commands and output a complete
instruction packet. A separate code generation model (LoRA-B) reads your new_instincts
descriptions and writes the actual Python. Your job: write descriptions precise enough
that LoRA-B needs no clarification. The execution agent always runs the hardcoded Python
tools first. Treat new_instincts and new_entities as proposals for downstream systems,
not automatic side effects.

Output ONLY a valid JSON object — no markdown fences, no preamble, no extra text.

{HUMAN_TENSOR_SCHEMA}

{MAP_TENSOR_SCHEMA}

{INSTINCT_REGISTRY}

TOOL SELECTION PRIORITY (follow strictly):
1. Use TIER A if it covers the action.
2. Use TIER B if Tier A is insufficient.
3. Use propose_new_tool or propose_new_instinct ONLY when NEITHER Tier A nor B can
   handle it. You MUST include "why_existing_tools_insufficient" in parameters.

NEW ENTITIES — populate when a god command spawns an entity type not in the registry.
  type_id must be an integer >= 50 (reserved range for dynamic entities).
  style_family must be one of: water_entities, fire_entities, nature_entities,
                                disaster_entities, human_entities
  Each entry: {{"type_id":<int>,"label":"<n>","description":"<what it is>",
               "style_family":"<family>",
               "diffusion_prompt":"top-down pixel art, 32x32, <specific visuals>",
               "diffusion_negative":"3d, realistic, side view, blurry"}}
  diffusion_prompt belongs inside each new_entities item. Downstream sprite generation
  only runs if execution succeeds and the local sprite/entity registry still lacks it.
  Leave new_entities:[] if all spawned types already exist in the registry.

NEW INSTINCTS — populate when propose_new_instinct appears in human_actions.
  LoRA-B implements Python directly from your description — write it precisely:
  - Specify EXACTLY which tensor columns are read and written (e.g. reads THREAT col15, writes HP col3)
  - Specify EXACTLY when logic fires: each tick | death hook | birth hook
  - Specify EXACTLY the threshold or condition that triggers the effect
  - Name any ResidentAgent sidecar fields used (e.g. stores rival_id in sidecar)
  - Reference existing tools/instincts by exact name if they are composed internally
  - Plain English only — NO Python code, pseudocode, or syntax of any kind
  - Do NOT include graph_edges — derived automatically by a separate script
  Each entry: {{"name":"instinct_<n>","description":"<precise natural language spec>",
                "heritable":<bool>,"mask":"<agent mask expression>"}}
  new_instincts is a proposal list. Downstream code generation only runs if execution
  succeeds and the execution agent confirms the instinct is not already registered.
  Leave new_instincts:[] if no new instinct is proposed.

OUTPUT FORMAT — always output exactly all 5 fields, use empty lists when unused:
{{"thought":"<one sentence>","map_actions":[...],"human_actions":[...],"new_entities":[],"new_instincts":[]}}
"""

# =============================================================================
# EXAMPLE POOLS
# =============================================================================

TIER_A_EXAMPLES = [
    (
        "Make Adam and Eve desperately hungry.",
        '{"thought":"HUNGER col14; set_attr.","map_actions":[],"human_actions":[{"tool_name":"set_attr","parameters":{"mask":"H_NAME in [\'Adam\',\'Eve\']","col":14,"value":95.0,"mode":"set"}}],"new_entities":[],"new_instincts":[]}'
    ),
    (
        "Strike the two oldest humans dead.",
        '{"thought":"Max H_AGE; instinct_die; two agents.","map_actions":[],"human_actions":[{"tool_name":"instinct_die","parameters":{"mask":"H_AGE==max(H_AGE) or H_AGE==second_max(H_AGE)"}}],"new_entities":[],"new_instincts":[]}'
    ),
    (
        "Send a drought across the land.",
        '{"thought":"tool_drought lowers water availability.","map_actions":[{"tool_name":"tool_drought","parameters":{}}],"human_actions":[],"new_entities":[],"new_instincts":[]}'
    ),
    (
        "Raise threat to maximum for all humans in the forest.",
        '{"thought":"THREAT col15; dist_to M_TYPE=2; set_attr.","map_actions":[],"human_actions":[{"tool_name":"set_attr","parameters":{"mask":"TYPE==1 and dist_to(M_TYPE==2)<40","col":15,"value":100.0,"mode":"set"}}],"new_entities":[],"new_instincts":[]}'
    ),
    (
        "Reset all mating cooldowns — a fertility burst.",
        '{"thought":"H_COOLDOWN col13 set to 0 for all.","map_actions":[],"human_actions":[{"tool_name":"set_attr","parameters":{"mask":"TYPE==1","col":13,"value":0.0,"mode":"set"}}],"new_entities":[],"new_instincts":[]}'
    ),
    (
        "Double the life expectancy of every woman.",
        '{"thought":"H_SEX==1 female; H_LIFE_EXP col12 multiply 2.","map_actions":[],"human_actions":[{"tool_name":"set_attr","parameters":{"mask":"H_SEX==1","col":12,"value":2.0,"mode":"multiply"}}],"new_entities":[],"new_instincts":[]}'
    ),
    (
        "Spawn five new humans on the grass biome.",
        '{"thought":"instinct_born across grass tiles.","map_actions":[],"human_actions":[{"tool_name":"instinct_born","parameters":{"spawn_points":{"kind":"sample_tiles","biome":"grass","count":5}}}],"new_entities":[],"new_instincts":[]}'
    ),
    (
        "A meteor lands at (380,120) — destroy the core, survivors flee.",
        '{"thought":"Spawn crater type_id=51 (new entity); area_attack core; flee outer ring.","map_actions":[{"tool_name":"entity_born","parameters":{"cx":380,"cy":120,"m_type":51,"register_geo":true}}],"human_actions":[{"tool_name":"tool_area_attack","parameters":{"center_x":380,"center_y":120,"radius":25}},{"tool_name":"instinct_flee","parameters":{"mask":"TYPE==1 and dist(380,120)<80","threat_pos":[380,120]}}],"new_entities":[{"type_id":51,"label":"crater","description":"scorched impact crater left by meteorite strike","style_family":"disaster_entities","diffusion_prompt":"top-down pixel art impact crater, scorched earth, dark ash ring, glowing edges, 32x32","diffusion_negative":"3d, realistic, side view, blurry"}],"new_instincts":[]}'
    ),
]

TIER_B_EXAMPLES = [
    # --- existing tool examples updated with new fields ---
    (
        "Flood the valley — raise the sea and kill anyone caught in it.",
        '{"thought":"tool_flood expands sea; area_attack kills flooded agents.","map_actions":[{"tool_name":"tool_flood","parameters":{}}],"human_actions":[{"tool_name":"tool_area_attack","parameters":{"center_x":"sea_cx","center_y":"sea_cy","radius":40}}],"new_entities":[],"new_instincts":[]}'
    ),
    (
        "Send a plague to all humans near the sea.",
        '{"thought":"tool_plague chains epidemic+threat+mood for coastal mask.","map_actions":[],"human_actions":[{"tool_name":"tool_plague","parameters":{"mask":"TYPE==1 and dist_to(M_TYPE==3)<50"}}],"new_entities":[],"new_instincts":[]}'
    ),
    (
        "Bless the women — restore HP and reset mating cooldowns.",
        '{"thought":"tool_bless chains HP restore+mood+cooldown reset for H_SEX==1.","map_actions":[],"human_actions":[{"tool_name":"tool_bless","parameters":{"mask":"H_SEX==1"}}],"new_entities":[],"new_instincts":[]}'
    ),
    (
        "Teach the tribe to fish and let children inherit the skill.",
        '{"thought":"tool_grant_instinct with heritable=true.","map_actions":[],"human_actions":[{"tool_name":"tool_grant_instinct","parameters":{"mask":"TYPE==1","instinct_name":"instinct_fish","heritable":true}}],"new_entities":[],"new_instincts":[]}'
    ),
    (
        "A wildfire breaks out in the forest — everyone flees.",
        '{"thought":"tool_wildfire on forest; instinct_flee all humans.","map_actions":[{"tool_name":"tool_wildfire","parameters":{"center_x":"forest_cx","center_y":"forest_cy","radius":90}}],"human_actions":[{"tool_name":"instinct_flee","parameters":{"mask":"TYPE==1","threat_pos":"centroid(M_TYPE==2)"}}],"new_entities":[],"new_instincts":[]}'
    ),
    (
        "Cull the population down to 20 — kill the weakest first.",
        '{"thought":"tool_cull kills lowest-HP agents to target.","map_actions":[],"human_actions":[{"tool_name":"tool_cull","parameters":{"target_population":20}}],"new_entities":[],"new_instincts":[]}'
    ),
    # --- new_entities examples: spawning novel entity types with diffusion ---
    (
        "A volcano erupts at the mountain peak — spawn lava flows across the slope.",
        '{"thought":"tool_volcanic_eruption handles kill+flee; lava_flow is a new entity type needing sprite.","map_actions":[{"tool_name":"tool_volcanic_eruption","parameters":{"center_x":"mountain_cx","center_y":"mountain_cy"}},{"tool_name":"entity_born","parameters":{"cx":"mountain_cx","cy":"mountain_cy","m_type":52,"register_geo":true}}],"human_actions":[],"new_entities":[{"type_id":52,"label":"lava_flow","description":"slow-moving molten rock flowing downhill from volcano","style_family":"fire_entities","diffusion_prompt":"top-down pixel art lava flow, glowing orange molten rock, dark crust edges, volcanic terrain, 32x32","diffusion_negative":"3d, realistic, side view, blue, cold"}],"new_instincts":[]}'
    ),
    (
        "Spawn a sacred grove in the forest — a healing sanctuary for injured humans.",
        '{"thought":"Sacred grove is a new map entity; spawn it inside forest boundary; injured humans migrate toward it.","map_actions":[{"tool_name":"entity_born","parameters":{"cx":"forest_cx","cy":"forest_cy","m_type":53,"register_geo":true}}],"human_actions":[{"tool_name":"tool_migration","parameters":{"mask":"TYPE==1 and HP<30","target_x":"forest_cx","target_y":"forest_cy","force":12.0}}],"new_entities":[{"type_id":53,"label":"sacred_grove","description":"ancient healing grove glowing with soft light inside the forest","style_family":"nature_entities","diffusion_prompt":"top-down pixel art sacred grove, ancient trees, soft green glow, mystical light rays, forest clearing, 32x32","diffusion_negative":"3d, realistic, side view, dark, fire, desert"}],"new_instincts":[]}'
    ),
    # --- new_instincts examples: structured code gen request alongside tool use ---
    (
        "Grant the tribe a hunting instinct — they should chase and kill prey automatically.",
        '{"thought":"tool_grant_instinct sets the bit; new instinct logic needed for active hunt behavior.","map_actions":[],"human_actions":[{"tool_name":"tool_grant_instinct","parameters":{"mask":"TYPE==1","instinct_name":"instinct_hunt","heritable":true}}],"new_entities":[],"new_instincts":[{"name":"instinct_hunt","description":"Each tick: agents with hunt bit active compute nearest entity with TYPE>1 (prey). If dist<80px apply instinct_move attraction toward prey. If dist<8px apply set_attr HP col3 -= 15 on prey and HP col3 += 5 on hunter. Uses instinct_move attraction + set_attr HP.","heritable":true,"mask":"TYPE==1 and col19_bit(2)==1"}]}'
    ),
    (
        "Teach humans to craft tools — adults who craft pass the skill to their children.",
        '{"thought":"tool_grant_instinct sets craft bit; new instinct defines the crafting tick logic.","map_actions":[],"human_actions":[{"tool_name":"tool_grant_instinct","parameters":{"mask":"TYPE==1 and H_AGE>16","instinct_name":"instinct_craft","heritable":true}}],"new_entities":[],"new_instincts":[{"name":"instinct_craft","description":"Each tick: agents with craft bit and HUNGER<60 move to nearest tool_spawn_resource entity. On proximity<10px spawn new resource entity (type_id=54, quantity=1) representing crafted tool and set MOOD col16 += 5 via set_attr. Cooldown 200 ticks stored in ResidentAgent sidecar craft_cooldown.","heritable":true,"mask":"TYPE==1 and col19_bit(3)==1"}]}'
    ),
]

TIER_C_EXAMPLES = [
    (
        "Humans who survive a plague become immune and pass it to children.",
        '{"thought":"Per-agent HP trajectory blocking — no existing tool tracks this.","map_actions":[],"human_actions":[{"tool_name":"propose_new_instinct","parameters":{"name":"instinct_plague_immunity","description":"Each tick: agents with immunity bit(col19 bit3) have tool_epidemic HP decay zeroed. Bit SET when HP crosses up through 50 after being below 20 — track was_critical in ResidentAgent sidecar. Children inherit bit at birth.","heritable":true,"mask":"TYPE==1","why_existing_tools_insufficient":"tool_epidemic has no per-agent exclusion mask. tool_grant_instinct fires unconditionally and cannot trigger on HP recovery trajectory. No Tier A/B tool tracks per-agent HP threshold history."}}],"new_entities":[],"new_instincts":[{"name":"instinct_plague_immunity","description":"Each tick: agents with immunity bit(col19 bit3) have tool_epidemic HP decay zeroed. Bit SET when HP crosses up through 50 after being below 20 — track was_critical in ResidentAgent sidecar. Children inherit bit at birth.","heritable":true,"mask":"TYPE==1"}]}',
        "past_state_memory"
    ),
    (
        "When a lake dries up, humans who depended on it automatically seek a new water source.",
        '{"thought":"Requires monitoring m_tensor col10 across ticks and reactively switching per-agent attraction targets.","map_actions":[],"human_actions":[{"tool_name":"propose_new_instinct","parameters":{"name":"instinct_water_seek","description":"Each tick: agents whose ResidentAgent water_source entity has col10==0 find nearest M_TYPE==1 where col10==1 and update attraction target. If none exists THREAT+=5 HUNGER+=2. Clear water_source when agent reaches new lake within 10px.","heritable":false,"mask":"TYPE==1","why_existing_tools_insufficient":"tool_drought and instinct_move are one-shot calls — neither monitors col10 across ticks nor reactively updates per-agent attraction targets stored in ResidentAgent sidecar."}}],"new_entities":[],"new_instincts":[{"name":"instinct_water_seek","description":"Each tick: agents whose ResidentAgent water_source entity has col10==0 find nearest M_TYPE==1 where col10==1 and update attraction target. If none exists THREAT+=5 HUNGER+=2. Clear water_source when agent reaches new lake within 10px.","heritable":false,"mask":"TYPE==1"}]}',
        "conditional_tool_chaining"
    ),
    (
        "If population drops below 10, all survivors enter a desperate fertility frenzy.",
        '{"thought":"Self-triggering threshold monitor that self-cancels — must be tick-registered, not a one-shot call.","map_actions":[],"human_actions":[{"tool_name":"propose_new_instinct","parameters":{"name":"instinct_survival_frenzy","description":"Each tick: if pop_count<10 set FRENZY bit(col19 bit7) for all; zero H_COOLDOWN col13; THREAT col15=0; MOOD col16=80. If pop_count>=10 and FRENZY bit set: clear bit; restore THREAT=10.","heritable":false,"mask":"TYPE==1","why_existing_tools_insufficient":"tool_reset_cooldown/set_threat/set_mood are one-shot world agent calls that cannot self-trigger on pop_count or self-cancel when condition resolves. Requires a registered instinct firing every tick."}}],"new_entities":[],"new_instincts":[{"name":"instinct_survival_frenzy","description":"Each tick: if pop_count<10 set FRENZY bit(col19 bit7) for all; zero H_COOLDOWN col13; THREAT col15=0; MOOD col16=80. If pop_count>=10 and FRENZY bit set: clear bit; restore THREAT=10.","heritable":false,"mask":"TYPE==1"}]}',
        "threshold_cascade"
    ),
    (
        "Any human who witnesses a death permanently avoids that location.",
        '{"thought":"Persistent spatial repulsion from stored coordinates — requires ResidentAgent memory and per-tick re-firing.","map_actions":[],"human_actions":[{"tool_name":"propose_new_instinct","parameters":{"name":"instinct_trauma_aversion","description":"Death hook: agents within 40px append death_site {x,y} to ResidentAgent memory ring buffer. Each tick: for each death_site in memory within 50px apply instinct_flee scaled by 1-dist/50. Entries expire after 500 ticks.","heritable":false,"mask":"TYPE==1","why_existing_tools_insufficient":"instinct_flee is one-shot with no persistence. No Tier A/B tool reads/writes ResidentAgent memory ring buffer. Per-agent traumatic location lists are heterogeneous and cannot be encoded in h_tensor."}}],"new_entities":[],"new_instincts":[{"name":"instinct_trauma_aversion","description":"Death hook: agents within 40px append death_site {x,y} to ResidentAgent memory ring buffer. Each tick: for each death_site in memory within 50px apply instinct_flee scaled by 1-dist/50. Entries expire after 500 ticks.","heritable":false,"mask":"TYPE==1"}]}',
        "location_bound_trauma"
    ),
    (
        "Children born during a famine grow up with higher life expectancy and slower hunger.",
        '{"thought":"Birth-conditional stat modification and per-tick rate override — no tool hooks into instinct_born conditionally.","map_actions":[],"human_actions":[{"tool_name":"propose_new_instinct","parameters":{"name":"instinct_famine_hardening","description":"Birth hook: if mean(h_tensor[:,14][h_mask])>70 set famine_born=True in ResidentAgent sidecar and H_LIFE_EXP col12*=1.35. Each tick: famine_born agents subtract 0.4 from HUNGER col14 after base instinct_age increment.","heritable":false,"mask":"TYPE==1","why_existing_tools_insufficient":"tool_life_exp_modify applies to current mask at call time — cannot hook into instinct_born conditionally. No Tier A/B tool overrides per-tick HUNGER increment rate internal to instinct_age."}}],"new_entities":[],"new_instincts":[{"name":"instinct_famine_hardening","description":"Birth hook: if mean(h_tensor[:,14][h_mask])>70 set famine_born=True in ResidentAgent sidecar and H_LIFE_EXP col12*=1.35. Each tick: famine_born agents subtract 0.4 from HUNGER col14 after base instinct_age increment.","heritable":false,"mask":"TYPE==1"}]}',
        "multigenerational_trigger"
    ),
    (
        "The two strongest humans become rivals — aggression scales with proximity to each other.",
        '{"thought":"Pairwise per-agent modifier scaling with real-time distance to one specific other agent.","map_actions":[],"human_actions":[{"tool_name":"propose_new_instinct","parameters":{"name":"instinct_rivalry","description":"Init: top-2 HP agents store each other row index as rival_id in ResidentAgent. Each tick: compute dist to rival. If dist<60px: MOOD-=10*(1-dist/60), H_COOLDOWN*=0.5. If dist>200px: MOOD+=3.","heritable":false,"mask":"TYPE==1 and rank(HP,desc)<=2","why_existing_tools_insufficient":"set_attr applies uniform values to boolean masks — cannot compute per-agent modifier varying with real-time distance to one specific agent. No Tier B tool stores pairwise relationships or reads ResidentAgent sidecar."}}],"new_entities":[],"new_instincts":[{"name":"instinct_rivalry","description":"Init: top-2 HP agents store each other row index as rival_id in ResidentAgent. Each tick: compute dist to rival. If dist<60px: MOOD-=10*(1-dist/60), H_COOLDOWN*=0.5. If dist>200px: MOOD+=3.","heritable":false,"mask":"TYPE==1 and rank(HP,desc)<=2"}]}',
        "emergent_social_state"
    ),
]

# =============================================================================
# VALIDATION
# =============================================================================

TIER_A_TOOLS = {
    "instinct_born","instinct_die","instinct_age","instinct_move",
    "instinct_flee","instinct_cooldown","instinct_search",
    "tool_reproduce","tool_area_attack","tool_epidemic","tool_drought",
    "geo_mutate","set_attr",
}
TIER_B_TOOLS = {
    "tool_flood","tool_wildfire","tool_earthquake","tool_storm",
    "tool_volcanic_eruption","tool_spawn_resource","tool_deplete_resource",
    "tool_regrow_forest","tool_set_mood","tool_set_threat","tool_reset_cooldown",
    "tool_age_shift","tool_life_exp_modify","tool_cull","tool_baby_boom",
    "tool_plague","tool_bless","tool_grant_instinct","tool_revoke_instinct",
    "tool_inherit_instinct",
}
TIER_C_TOOLS = {"propose_new_tool","propose_new_instinct"}
VALID_TOOL_NAMES = TIER_A_TOOLS | TIER_B_TOOLS | TIER_C_TOOLS

REQUIRED_TOP_KEYS = {"thought","map_actions","human_actions","new_entities","new_instincts"}

# Required keys inside each new_entity entry
REQUIRED_ENTITY_KEYS = {"type_id","label","description","style_family",
                        "diffusion_prompt","diffusion_negative"}

# Required keys inside each new_instinct entry
REQUIRED_INSTINCT_KEYS = {"name","description","heritable","mask"}

VALID_STYLE_FAMILIES = {
    "water_entities","fire_entities","nature_entities",
    "disaster_entities","human_entities",
}


def extract_json_block(text: str) -> str:
    match = re.search(r'\{.*\}', text, re.DOTALL)
    return match.group(0) if match else ""


def validate(raw: str) -> tuple[bool, dict | None, str]:
    json_str = extract_json_block(raw)
    if not json_str:
        return False, None, "no JSON block"

    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as e:
        return False, None, f"JSON parse error: {e}"

    # 1. All 5 top-level keys must be present
    missing = REQUIRED_TOP_KEYS - set(parsed.keys())
    if missing:
        return False, None, f"missing top-level keys: {missing}"

    # 2. map_actions and human_actions must be lists
    for field in ("map_actions","human_actions","new_entities","new_instincts"):
        if not isinstance(parsed[field], list):
            return False, None, f"{field} not a list"

    # 3. Validate each action in map_actions and human_actions
    for field in ("map_actions","human_actions"):
        for i, action in enumerate(parsed[field]):
            if not isinstance(action, dict):
                return False, None, f"{field}[{i}] not a dict"
            tool = action.get("tool_name","")
            if not isinstance(tool, str):
                return False, None, f"{field}[{i}].tool_name not a string"
            if "parameters" not in action or not isinstance(action["parameters"], dict):
                return False, None, f"{field}[{i}] missing/invalid parameters"
            if tool not in VALID_TOOL_NAMES:
                return False, None, f"unknown tool: {tool}"
            # for bad in HALLUCINATED_TOOL_PREFIXES:
            #     if tool.startswith(bad) or tool == bad.rstrip("."):
            #         return False, None, f"hallucinated tool pattern: {tool}"

    # 4. propose_* must carry justification
    all_actions = parsed["map_actions"] + parsed["human_actions"]
    for action in all_actions:
        if action.get("tool_name") in TIER_C_TOOLS:
            if "why_existing_tools_insufficient" not in action.get("parameters",{}):
                return False, None, "propose_* missing why_existing_tools_insufficient"

    # 5. Validate new_entities entries
    for i, entity in enumerate(parsed["new_entities"]):
        if not isinstance(entity, dict):
            return False, None, f"new_entities[{i}] not a dict"
        missing_e = REQUIRED_ENTITY_KEYS - set(entity.keys())
        if missing_e:
            return False, None, f"new_entities[{i}] missing keys: {missing_e}"
        if not isinstance(entity.get("type_id"), int):
            return False, None, f"new_entities[{i}].type_id not an int"
        if entity.get("type_id", 0) < 50:
            return False, None, f"new_entities[{i}].type_id must be >= 50 (reserved range)"
        if entity.get("style_family") not in VALID_STYLE_FAMILIES:
            return False, None, f"new_entities[{i}].style_family invalid: {entity.get('style_family')}"

    # 6. Validate new_instincts entries
    # Code syntax patterns that should never appear in LoRA-A descriptions
    CODE_SYNTAX_PATTERNS = (
        "def ", "return ", "import ", "h_tensor[", "m_tensor[",
        "torch.", "np.", ".any()", ".bool()", "for ", "while ",
        "if __", "lambda ", "ctx[",
    )
    # Precision markers — at least one must appear in each description
    # indicating the description is specific enough for LoRA-B to implement
    PRECISION_MARKERS = (
        "col", "tick", "hook", "sidecar", "mask", "threshold",
        "dist", "bit", "hp", "hunger", "threat", "mood",
    )
    for i, instinct in enumerate(parsed["new_instincts"]):
        if not isinstance(instinct, dict):
            return False, None, f"new_instincts[{i}] not a dict"
        missing_i = REQUIRED_INSTINCT_KEYS - set(instinct.keys())
        if missing_i:
            return False, None, f"new_instincts[{i}] missing keys: {missing_i}"
        if not instinct.get("name","").startswith("instinct_"):
            return False, None, f"new_instincts[{i}].name must start with 'instinct_'"
        if not isinstance(instinct.get("heritable"), bool):
            return False, None, f"new_instincts[{i}].heritable must be bool"
        desc = instinct.get("description", "")
        if len(desc) < 40:
            return False, None, f"new_instincts[{i}].description too short — LoRA-B needs precision"
        # Reject if model hallucinated Python code into the description
        for pattern in CODE_SYNTAX_PATTERNS:
            if pattern in desc:
                return False, None, f"new_instincts[{i}].description contains code syntax '{pattern}' — plain English only"
        # Reject if description is too vague to implement
        desc_lower = desc.lower()
        if not any(marker in desc_lower for marker in PRECISION_MARKERS):
            return False, None, f"new_instincts[{i}].description lacks precision markers (col/tick/hook/threshold etc)"

    # 7. Consistency: if propose_new_instinct used, new_instincts must be populated
    has_propose = any(
        a.get("tool_name") == "propose_new_instinct"
        for a in all_actions
    )
    if has_propose and len(parsed["new_instincts"]) == 0:
        return False, None, "propose_new_instinct used but new_instincts is empty"

    # 8. Hallucinated column names
    # serialized = json.dumps(parsed)
    # for bad in HALLUCINATED_COLUMNS:
    #     if bad in serialized:
    #         return False, None, f"hallucinated column: {bad}"

    return True, parsed, ""


# =============================================================================
# DYNAMIC PROMPT BUILDER
# Selects example pool based on tier_hint from prompts.jsonl.
# tier_hint "A" → MODE_A, "B" → MODE_AB, "C" → MODE_ABC
# =============================================================================

def build_prompt(god_command: str, tier_hint: str) -> tuple[str, str]:
    if tier_hint == "C":
        mode = "MODE_ABC"
        a = random.sample(TIER_A_EXAMPLES, 2)
        b = random.sample(TIER_B_EXAMPLES, 1)
        c = random.sample(TIER_C_EXAMPLES, 1)
        selected = a + b + [(cmd, js) for cmd, js, _ in c]
    elif tier_hint == "B":
        mode = "MODE_AB"
        a = random.sample(TIER_A_EXAMPLES, 2)
        b = random.sample(TIER_B_EXAMPLES, 2)
        selected = a + b
    else:
        mode = "MODE_A"
        selected = random.sample(TIER_A_EXAMPLES, 4)

    random.shuffle(selected)
    examples = "".join(
        f'\n---\nGod Command: "{cmd}"\n{js}\n'
        for cmd, js in selected
    )

    prompt = (
        f"{SYSTEM_PROMPT}"
        f"\n### EXAMPLES{examples}"
        f'\n---\nGod Command: "{god_command}"\n'
    )
    return prompt, mode


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input",       type=str, default="prompts.jsonl")
    parser.add_argument("--output",      type=str, default="sft_dataset.jsonl")
    parser.add_argument("--batch_size",  type=int, default=64)
    parser.add_argument("--max_retries", type=int, default=5,
                        help="Max generation attempts per prompt before skipping")
    args = parser.parse_args()

    # --- load prompts ---
    with open(args.input) as f:
        prompt_entries = [json.loads(line) for line in f if line.strip()]
    print(f"Loaded {len(prompt_entries)} prompts from {args.input}")

    tier_dist = Counter(e.get("tier_hint","A") for e in prompt_entries)
    print(f"Tier distribution in input: {dict(sorted(tier_dist.items()))}")

    # --- load model ---
    print(f"--- Loading model: {MODEL_ID} ---")
    llm = LLM(model=MODEL_ID, max_model_len=MAX_MODEL_LEN,
               gpu_memory_utilization=GPU_UTIL)

    sft_params = SamplingParams(
        temperature=0.3,
        max_tokens=1024,
        stop=["\n---\nGod Command:"],
    )

    # --- generate in batches ---
    valid_entries   = []
    skipped         = []
    invalid_reasons: dict[str,int] = {}

    # Track retry counts per prompt id
    retry_counts: dict[str,int] = {e["id"]: 0 for e in prompt_entries}
    # Queue: list of prompt entries still needing a valid trace
    pending = list(prompt_entries)

    pbar = tqdm(total=len(prompt_entries), desc="Valid traces")

    while pending:
        # Take up to batch_size from pending
        batch = pending[:args.batch_size]
        pending = pending[args.batch_size:]

        prompts_built = [build_prompt(e["prompt"], e.get("tier_hint","A")) for e in batch]
        formatted     = [p for p, _ in prompts_built]
        modes         = [m for _, m in prompts_built]

        outputs = llm.generate(formatted, sft_params)

        retry_these = []
        for i, output in enumerate(outputs):
            entry = batch[i]
            if not output.outputs:
                retry_these.append(entry)
                continue

            raw = output.outputs[0].text.strip()
            ok, parsed, reason = validate(raw)

            if ok:
                valid_entries.append({
                    "id":        entry["id"],
                    "input":     entry["prompt"],
                    "output":    parsed,
                    "tier_hint": entry.get("tier_hint","A"),
                    "tier_mode": modes[i],
                })
                pbar.update(1)
            else:
                invalid_reasons[reason] = invalid_reasons.get(reason,0) + 1
                retry_counts[entry["id"]] += 1
                if retry_counts[entry["id"]] < args.max_retries:
                    retry_these.append(entry)
                else:
                    skipped.append({
                        "id":     entry["id"],
                        "prompt": entry["prompt"],
                        "reason": reason,
                    })

        # Re-queue failed prompts for retry
        pending = retry_these + pending

    pbar.close()

    # --- save ---
    with open(args.output, "w") as f:
        for e in valid_entries:
            f.write(json.dumps(e) + "\n")

    skipped_path = args.output.replace(".jsonl", "_skipped.jsonl")
    if skipped:
        with open(skipped_path, "w") as f:
            for e in skipped:
                f.write(json.dumps(e) + "\n")

    # --- report ---
    total = len(prompt_entries)
    print(f"\n{'='*55}")
    print(f"Results: {len(valid_entries)}/{total} prompts produced valid traces")
    if skipped:
        print(f"Skipped: {len(skipped)} prompts (saved to {skipped_path})")

    out_tier = Counter(e["tier_hint"] for e in valid_entries)
    print(f"\nOutput tier distribution:")
    for tier, count in sorted(out_tier.items()):
        print(f"  Tier {tier}: {count:4d}  ({count/max(len(valid_entries),1)*100:.1f}%)")

    acceptance = len(valid_entries) / max(total,1) * 100
    print(f"\nAcceptance rate: {acceptance:.1f}%")

    if invalid_reasons:
        print(f"\nRejection breakdown:")
        for reason, count in sorted(invalid_reasons.items(), key=lambda x: -x[1]):
            print(f"  [{count:4d}x] {reason}")

    if acceptance < 70:
        print("\nWARNING: acceptance below 70% — check rejection breakdown above")


if __name__ == "__main__":
    main()
