import json
import argparse
import os
import random
from vllm import LLM, SamplingParams
from tqdm import tqdm

# --- 1. CORE CONFIGURATION ---
MODEL_ID = "neuralmagic/Meta-Llama-3.1-70B-Instruct-quantized.w4a16"
MAX_MODEL_LEN = 4096
GPU_UTIL = 0.90  

# --- 2. THE OPEN-WORLD PLANNER LIBRARY ---
FEW_SHOT_LIBRARY = """You are the 'World Lead Architect'. 
Decompose God Commands into 'map_actions' (rendering/terrain) and 'human_actions' (entity logic/stats).

### 1. TENSOR SCHEMAS (N=32)
- HUMAN TENSOR (Fixed Biology): Always use C_X, C_Y, C_TYPE, C_HP, C_HUNGER, C_THIRST, C_SPEED, C_SCALE, C_SPRITE_ID.
- MAP TENSOR (Sandbox): Use C_X, C_Y, C_TYPE. Use G_ARG1 through G_ARG5 for custom attributes. 

### 2. AVAILABLE BASIC INSTINCTS (Tier 0 - Use these first!)
- basic_instincts.modify_attr(mask, col, val, mode): Update a tensor column (mode: 'set', 'add', 'multiply').
- basic_instincts.apply_force(mask, vector): Apply physics/movement vectors.
- basic_instincts.agent_died(mask): Remove entities from the simulation.
- basic_instincts.agent_born(x, y, type_id): Spawn a new entity at coordinates.
- basic_instincts.sync_visuals(mask): Force-refresh the rendering state for specific indices.

### 3. THE "PROPOSE" PROTOCOL
If the Standard Library or Basic Instincts cannot fulfill the request, you MUST:
1. Use 'propose_new_tool' or 'propose_new_rule' in the JSON.
2. Provide a 'description' that explains the vectorized PyTorch logic for the Coder LoRA.

### EXAMPLES:

User: "Turn Adam into a giant and make him hungry."
Thought: Target is a Human. Human Tensor has fixed columns for C_SCALE and C_HUNGER. No map changes needed.
JSON:
{
  "map_actions": [],
  "human_actions": [
    {
      "tool_name": "basic_instincts.modify_attr",
      "parameters": {
        "query": "entity_id == 'Adam'",
        "modifications": [
          {"column": "C_SCALE", "value": 3.0, "mode": "set"},
          {"column": "C_HUNGER", "value": 100.0, "mode": "set"}
        ]
      }
    }
  ]
}

User: "Set the forest on fire and make the animals flee."
Thought: 
- Map Action: Update 'Tree' (Type 5) G_ARG3 (Is_Burning bit). 
- Human Action: Propose a 'flee_behavior' rule for Animals (Type 8).
JSON:
{
  "map_actions": [
    {
      "tool_name": "basic_instincts.modify_attr",
      "parameters": {"query": "C_TYPE == 5", "column": "G_ARG3", "value": "bit_set(1)", "mode": "or"}
    }
  ],
  "human_actions": [
    {
      "tool_name": "propose_new_rule",
      "parameters": {
        "name": "flee_from_fire",
        "description": "For Type 8, if distance to Type 5 (where G_ARG3 bit 1 is set) < 10, apply_force in opposite direction.",
        "is_continuous": true
      }
    }
  ]
}

User: "A meteor strikes the village at (100, 100). Destroy everything at the center and make the survivors weep."
Thought: 
- Map Action 1: Spawn a 'Crater' (Type 51) at the impact site.
- Map Action 2: Set HP to 0 for all Buildings (Type 20) within 10 units.
- Human Action 1: Kill all Humans (Type 1) within 5 units of the epicenter.
- Human Action 2: For survivors (dist < 20), set 'Mourning' bit (G_ARG3 bit 5) and reduce C_SPEED.
JSON:
{
  "map_actions": [
    {
      "tool_name": "basic_instincts.agent_born", 
      "parameters": {"x": 100, "y": 100, "type_id": 51}
    },
    {
      "tool_name": "basic_instincts.modify_attr",
      "parameters": {
        "query": "C_TYPE == 20 and dist(100, 100) < 10",
        "column": "C_HP",
        "value": 0,
        "mode": "set"
      }
    }
  ],
  "human_actions": [
    {
      "tool_name": "basic_instincts.agent_died",
      "parameters": {"mask": "C_TYPE == 1 and dist(100, 100) < 5"}
    },
    {
      "tool_name": "basic_instincts.modify_attr",
      "parameters": {
        "query": "C_TYPE == 1 and dist(100, 100) < 20",
        "modifications": [
          {"column": "G_ARG3", "value": "bit_set(5)", "mode": "or"},
          {"column": "C_SPEED", "value": 0.5, "mode": "multiply"}
        ]
      }
    }
  ]
}


"""

def main():
    parser = argparse.ArgumentParser(description="Generate SFT data for the World Agent.")
    parser.add_argument("--count", type=int, default=100, help="Total pairs to generate")
    parser.add_argument("--batch_size", type=int, default=20, help="Number of concurrent requests to vLLM")
    parser.add_argument("--output", type=str, default="world_agent_sft.jsonl", help="Output filename")
    args = parser.parse_args()

    # Initialize vLLM
    print(f"--- Loading Model: {MODEL_ID} ---")
    llm = LLM(model=MODEL_ID, max_model_len=MAX_MODEL_LEN, gpu_memory_utilization=GPU_UTIL)

    # --- PHASE 1: BATCH BRAINSTORMING PROMPTS ---
    print(f"--- Phase 1: Brainstorming {args.count} God Prompts ---")
    prompts = []
    prompt_set = set() # For O(1) duplicate checking
    bp_params = SamplingParams(temperature=1.0, max_tokens=512)
    
    # Diversification themes to prevent "stuck" duplication loops
    #themes = ["sci-fi nanotechnology", "ancient lovecraftian horror", "absurdist comedy", "biological evolution", "extreme weather", "magic systems"]
    chaos_styles = [
    "High Fantasy (Magic, Dragons, Spells)",
    "Hard Sci-Fi (Nanotech, Radiation, Gravity)",
    "Absurdist/Surrealist (Sentient food, gravity-defying liquids)",
    "Micro-Management (Individual stats, specific coordinates)",
    "Global Catastrophe (World-ending physics, terrain shifting)",
    "Social Engineering (Emotions, trade, complex bitmask behaviors)"
]
    pbar = tqdm(total=args.count)
    while len(prompts) < args.count:
        #current_theme = random.choice(themes)
        # Create a batch of identical instructions to saturate the GPU
        current_style = random.choice(chaos_styles)
        brainstorm_batch = [
            f"Generate 10 'God commands' in a {current_style} style. "
            "Mix serious ideas with complete nonsense and creative player-style requests. "
            "One per line."
] * args.batch_size
        
        outputs = llm.generate(brainstorm_batch, bp_params)
        
        for output in outputs:
            generated_lines = output.outputs[0].text.split('\n')
            for line in generated_lines:
                clean_line = line.strip().lstrip('- ').lstrip('0123456789. ')
                if len(clean_line) > 10 and clean_line not in prompt_set:
                    prompt_set.add(clean_line)
                    prompts.append(clean_line)
                    pbar.update(1)
                    if len(prompts) >= args.count:
                        break
            if len(prompts) >= args.count:
                break
    pbar.close()

    # --- PHASE 2: GENERATING SFT TRACES (Thought + JSON) ---
    print(f"--- Phase 2: Generating {len(prompts)} ReAct Traces ---")
    
    sft_params = SamplingParams(temperature=0.4, max_tokens=1024, stop=["User:"]) 
    
    formatted_prompts = [f"{FEW_SHOT_LIBRARY}\nUser: {p}\nThought:" for p in prompts]
    results = llm.generate(formatted_prompts, sft_params)

    # --- PHASE 3: SAVING TO JSONL ---
    print(f"--- Phase 3: Saving to {args.output} ---")
    with open(args.output, "w") as f:
        for i, output in enumerate(results):
            if not output.outputs:
                continue
            
            generated_text = "Thought:" + output.outputs[0].text.strip()
            
            entry = {
                "input": prompts[i],
                "output": generated_text
            }
            f.write(json.dumps(entry) + "\n")

    print(f"--- Finished! Created {len(prompts)} SFT examples. ---")

if __name__ == "__main__":
    main()