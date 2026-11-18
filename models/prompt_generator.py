"""
run1_prompt_generator.py
========================
Phase 1 of the Eden SFT pipeline.

Generates and filters God Command prompts, saves them to a JSONL file
for human review before any trace generation compute is spent.

Output format (one JSON object per line):
    {
        "id":     "p_0001",
        "prompt": "Drain the northern lake and make everyone flee.",
        "source": "seed" | "generated",
        "tier_hint": "A" | "B" | "C"   # human-editable hint for Run 2
    }

After this run:
    1. Open prompts.jsonl and delete any bad rows
    2. Optionally edit prompts or add your own
    3. Optionally set tier_hint to "C" for prompts you want propose_* outputs
    4. Run run2_trace_generator.py

Usage:
    python run1_prompt_generator.py --count 400 --output prompts.jsonl
"""

import json
import argparse
import random
from vllm import LLM, SamplingParams
from tqdm import tqdm

# =============================================================================
# CONFIGURATION
# =============================================================================
MODEL_ID      = "neuralmagic/Meta-Llama-3.1-70B-Instruct-quantized.w4a16"
MAX_MODEL_LEN = 8192
GPU_UTIL      = 0.85

# =============================================================================
# SEED PROMPTS — ground truth exemplars, always included in output
# Cover every tensor surface: hunger, mood, threat, age, HP, sex,
# cooldown, life_exp, all 6 biomes, all event types.
# tier_hint tells Run 2 which example pool to bias toward.
# =============================================================================
SEED_PROMPTS = [
    # --- Tier A seeds (direct tensor ops) ---
    ("Make everyone's hunger critical.",                                          "A"),
    ("Reset all mating cooldowns to zero.",                                       "A"),
    ("Strike the two oldest humans dead.",                                        "A"),
    ("Double the life expectancy of every woman.",                                "A"),
    ("Raise threat to maximum for all humans in the forest.",                     "A"),
    ("Set every human's mood to calm and clear all threat.",                      "A"),
    ("Spawn five new humans on the grass biome.",                                 "A"),
    ("Drain the northern lake completely.",                                        "A"),
    ("Kill all humans within 30 pixels of the sea.",                              "A"),
    ("All women past age 40 become barren — set their cooldown to max.",          "A"),
    ("Age every human by 10 years instantly.",                                    "A"),
    ("Restore full HP to every critically injured human.",                        "A"),
    ("The eldest man dies of old age near the forest.",                           "A"),
    ("Fill the beach with new entity spawns.",                                    "A"),
    # --- Tier B seeds (extended tools) ---
    ("Flood the valley — raise the sea and kill anyone caught in it.",            "B"),
    ("Send a plague to all humans near the sea.",                                 "B"),
    ("A wildfire breaks out in the forest — everyone flees.",                     "B"),
    ("Bless all the women — restore HP and reset cooldowns.",                     "B"),
    ("Teach the tribe to fish and let children inherit the skill.",               "B"),
    ("Cull the population down to 20, killing the weakest first.",                "B"),
    ("An earthquake hits the mountain — shake all nearby humans.",                "B"),
    ("The forest regrows southward into the grassland.",                          "B"),
    ("A drought hits — drain every lake on the map.",                             "B"),
    ("Baby boom — spawn 8 new humans across the grass and beach.",                "B"),
    ("Hunters return: reduce hunger for the 5 hungriest humans by 50.",           "B"),
    ("A storm rolls in from the sea — HP decay for all coastal humans.",          "B"),
    ("Revoke the fishing instinct from all humans.",                              "B"),
    ("A volcanic eruption at the mountain peak — kill core, flee outer ring.",    "B"),
    ("Spawn a food resource on every grass tile near the lake.",                  "B"),
    ("The tribe mourns — set mood low for everyone near the last death site.",    "B"),
    # --- Tier C seeds (require propose_*) ---
    ("Humans who survive a plague become immune and pass it to children.",        "C"),
    ("When a lake dries up, humans who depended on it seek a new water source.",  "C"),
    ("If population drops below 10, all survivors enter a fertility frenzy.",     "C"),
    ("Any human who witnesses a death permanently avoids that location.",         "C"),
    ("Children born during a famine grow up with higher life expectancy.",        "C"),
    ("The two strongest humans become rivals — aggression scales with proximity.","C"),
    ("The more humans fish, the faster the lake depletes — starvation if empty.", "C"),
    ("When a parent dies, children grieve proportional to how young they are.",   "C"),
]

# =============================================================================
# BANNED TOKENS — any brainstorm line containing these is rejected
# Prevents archaic/fantasy drift from LLM pretraining priors
# =============================================================================
BANNED_TOKENS = {
    # archaic english
    "thou", "shalt", "thy", "thee", "dost", "lest", "hast", "hath",
    "thine", "wherefore", "henceforth", "forsooth", "verily",
    # fantasy/RPG
    "dragon", "wizard", "magic", "spell", "potion", "goblin", "centaur",
    "enchant", "curse", "sacred", "ritual", "offering", "consecrat",
    "wardrobe", "elixir", "copper penn", "walnut tree", "dungeon",
    "knight", "castle", "kingdom", "sorcerer", "demon", "angel",
    # game-mechanic hallucinations
    "gold", "mana", "experience", "level up", "inventory", "quest",
}

# =============================================================================
# TIER HINT CLASSIFIER
# Rough heuristic to auto-assign tier_hint to generated prompts.
# Run 2 uses this to select the right example pool.
# Humans can override in the JSONL before Run 2.
# =============================================================================
TIER_C_KEYWORDS = {
    "remember", "memory", "permanently", "persist", "witness", "survive",
    "immune", "inherit", "generation", "born during", "rival", "rivalry",
    "deplete", "feedback", "threshold", "frenzy", "dependent", "depended",
    "grieve", "grief", "trauma", "aversion", "seek new", "automatically seek",
}
TIER_B_KEYWORDS = {
    "flood", "wildfire", "fire", "earthquake", "storm", "volcano", "eruption",
    "plague", "famine", "drought", "bless", "cull", "boom", "regrow",
    "fish", "instinct", "grant", "revoke", "inherit", "resource", "spawn resource",
    "mood", "threat", "cooldown", "life expectancy", "age shift",
}

def classify_tier(prompt: str) -> str:
    lower = prompt.lower()
    if any(kw in lower for kw in TIER_C_KEYWORDS):
        return "C"
    if any(kw in lower for kw in TIER_B_KEYWORDS):
        return "B"
    return "A"


def is_valid_prompt(line: str) -> bool:
    """Return True if the line passes all quality filters."""
    clean = line.strip().lstrip("- ").strip()
    if not (15 < len(clean) < 220):
        return False
    if clean.startswith(('#', '*', '/', '"', "'")):
        return False
    # Must end with punctuation or a word (not a fragment)
    if clean[-1] in ('(', ',', '—', '-', ':'):
        return False
    lower = clean.lower()
    if any(banned in lower for banned in BANNED_TOKENS):
        return False
    return True


# =============================================================================
# EXPANSION INSTRUCTION
# Uses seed exemplars to keep the model on-distribution.
# Injected fresh each batch with 6 randomly sampled seeds.
# =============================================================================
def build_expansion_instruction(exemplars: list[tuple[str, str]]) -> str:
    exemplar_lines = "\n".join(f"- {p}" for p, _ in exemplars)
    return (
        "Generate God Commands for Eden, a world simulation game.\n"
        "A God Command is a short plain-English instruction that affects a living "
        "population of up to 100 humans on a map.\n\n"
        "WHAT EXISTS IN THE GAME:\n"
        "  Human stats: HP, hunger, mood, threat, age, sex (male/female), "
        "mating_cooldown, life_expectancy, acquired_instincts\n"
        "  Map entities: lake, forest, sea, mountain, beach, grass\n"
        "  Events: drought, flood, plague, wildfire, earthquake, famine, volcano\n\n"
        "STRICT RULES:\n"
        "  - Plain modern English only. No archaic words (thou/shalt/thy/thee/lest).\n"
        "  - No fantasy elements (no magic, spells, dragons, goblins, potions).\n"
        "  - No religious or ritual framing.\n"
        "  - Every command must reference at least one real game element above.\n"
        "  - One sentence or two. Specific and actionable.\n\n"
        "Example commands — match this style exactly:\n"
        f"{exemplar_lines}\n\n"
        "Write exactly 10 new commands now, one per line, no numbering:"
    )


# =============================================================================
# MAIN
# =============================================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count",      type=int, default=400,
                        help="Target number of prompts to generate (seeds always included)")
    parser.add_argument("--batch_size", type=int, default=64,
                        help="vLLM concurrent batch size")
    parser.add_argument("--output",     type=str, default="prompts.jsonl")
    parser.add_argument("--seed_only",  action="store_true",
                        help="Skip LLM expansion, output seeds only (useful for testing)")
    args = parser.parse_args()

    # --- always write seeds first ---
    entries: list[dict] = []
    prompt_set: set[str] = set()

    for i, (prompt, tier) in enumerate(SEED_PROMPTS):
        entry = {
            "id":        f"p_{i+1:04d}",
            "prompt":    prompt,
            "source":    "seed",
            "tier_hint": tier,
        }
        entries.append(entry)
        prompt_set.add(prompt.lower())

    print(f"Seeds loaded: {len(entries)}")

    if args.seed_only:
        _save(entries, args.output)
        return

    # --- LLM expansion ---
    print(f"--- Loading model: {MODEL_ID} ---")
    llm = LLM(model=MODEL_ID, max_model_len=MAX_MODEL_LEN,
               gpu_memory_utilization=GPU_UTIL)

    expand_params = SamplingParams(temperature=0.85, max_tokens=320)

    target = max(args.count, len(SEED_PROMPTS))
    pbar = tqdm(total=target, desc="Prompt pool")
    pbar.update(len(entries))

    id_counter = len(entries) + 1

    while len(entries) < target:
        # Sample 6 seeds as exemplars — mix tiers for diversity
        exemplars = random.sample(SEED_PROMPTS, min(6, len(SEED_PROMPTS)))
        instruction = build_expansion_instruction(exemplars)
        batch = [instruction] * args.batch_size
        outputs = llm.generate(batch, expand_params)

        for output in outputs:
            for line in output.outputs[0].text.split('\n'):
                clean = line.strip().lstrip('- ').strip()
                if not is_valid_prompt(clean):
                    continue
                if clean.lower() in prompt_set:
                    continue
                prompt_set.add(clean.lower())
                entries.append({
                    "id":        f"p_{id_counter:04d}",
                    "prompt":    clean,
                    "source":    "generated",
                    "tier_hint": classify_tier(clean),
                })
                id_counter += 1
                pbar.update(1)
                if len(entries) >= target:
                    break
            if len(entries) >= target:
                break

    pbar.close()

    tier_counts = {"A": 0, "B": 0, "C": 0}
    for e in entries:
        tier_counts[e["tier_hint"]] = tier_counts.get(e["tier_hint"], 0) + 1

    print(f"\nGenerated {len(entries)} prompts")
    print(f"Tier distribution (auto-classified, edit before Run 2):")
    for tier, count in sorted(tier_counts.items()):
        print(f"  Tier {tier}: {count:4d}  ({count/len(entries)*100:.1f}%)")

    _save(entries, args.output)


def _save(entries: list[dict], path: str) -> None:
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    print(f"\nSaved {len(entries)} prompts to {path}")
    print("Review and edit before running run2_trace_generator.py")


if __name__ == "__main__":
    main()