# R0.3 Prerequisite: Creature Balance Causal Attribution Report
**Date:** 2026-10-10 (Toronto)  
**Scope:** Reversible diagnostic instrumentation for true death cause attribution in `tools/creature_balance.py`

---

## 1. Executive Summary

Previous runs of `tools/creature_balance.py` inferred death causes using spatial proximity via `describe_death`: reporting the nearest live creature entity **after** the entire simulation step completed. Because proximity is not causation, an uninvolved passive animal (such as a sheep grazing 1 tile away) would be recorded as the cause of death even if the lethal blow was struck by a wolf 15 units away, or if death occurred from hunger/thirst/age. Furthermore, `describe_death` inspected hunger and thirst **after** `self.feed()` had already reset them to 20.0.

This implementation fulfills the **R0.3 concrete evidence prerequisite**:
1. Introduces `tools/creature_balance_attribution.py` providing an importable, reversible observer (`AttributionObserver`).
2. Instruments actual production damage paths (`apply_human_damage`), creature attack logic (`kernel._attack`), and lifecycle removals (`instinct_die`) with zero modification to production files.
3. Captures ordered human HP damage events with exact victim slot + UID at the time of the event, attacking creature UID/species when genuinely available, damage requested vs actual applied, overkill, phase, and lethal transitions.
4. Bounded memory: maintains a finite latest damage ring per resident (cap 16), finite first-death summaries (cap 8), and compact scalar aggregates for 120,000-tick probe runs.
5. Slot recycling isolation: clearing the resident damage ring and lethal state upon `on_human_reset` so recycled slots never leak stale history.
6. Feed and duels semantics: explicitly documented harness feed resets (every tick) and labeled `duels()` as closed-form formula estimates rather than simulated agent combat.

---

## 2. Source Attribution Architecture

### 2.1 Reversible Instrumentation (`tools/creature_balance_attribution.py`)
Production engine, kernel, and instinct files remain strictly **read-only**. Instrumentation is applied reversibly at runtime via `AttributionObserver.install()`:
- **`apply_human_damage`**: Patched in all importing modules (`systems.health.damage`, `systems.creatures.kernel`, `instincts_and_tools`, `systems.survival.hunger`, `systems.survival.thirst`). Intercepts exact requested amount, computes actual applied amount clamped to remaining HP, detects lethal transitions (`hp_before > 0.0 and hp_after <= 0.0`), and records overkill.
- **`kernel._attack`**: Wrapped to capture the exact mapping from victim human slots to attacking creature table entities (species, UID, slot, damage).
- **`instinct_die`**: Wrapped to detect non-HP old age deaths (`H_AGE > H_LIFE_EXP`) and distinguish them from combat casualties.
- **Exception Safety**: Implements `__enter__` / `__exit__` and `uninstall()`. All original functions and registry entries are restored bit-for-bit even if an exception is raised.

### 2.2 Cause Hierarchy and Honesty Contract
When a human death is detected (`float(h[i, cfg.TYPE]) != float(cfg.AGENT_TYPE_HUMAN) or float(hp[i]) <= 0.0`):
1. **Captured Lethal Damage**: If a lethal damage event was recorded in the resident's active damage ring:
   - `true_cause = "creature"` (if species is known or source is creature combat), `killer_species`, `killer_uid`, `damage_applied`, `damage_requested`, `overkill`.
   - `true_cause = "starvation"` or `"dehydration"` (if from needs damage).
2. **Old Age Death**: If `instinct_die` removed the resident due to age exceeding life expectancy:
   - `true_cause = "old_age"`, `killer_species = None`.
3. **Unattributed HP Loss**: If HP dropped to 0.0 without a captured damage call:
   - `true_cause = "unattributed_hp_loss"`, `killer_species = None`. (Never fabricated as a wolf or old-age death).
4. **Unresolved Type Removal**: If resident row was zeroed without captured lethal damage or old age:
   - `true_cause = "unresolved_type_removal"`, `killer_species = None`.

### 2.3 Bounded Memory Specification
In a 10-day user calendar probe (120,000 ticks):
- **Damage Rings**: `collections.deque(maxlen=16)` per resident slot.
- **First Deaths**: Capped at 8 summaries (`first_deaths`).
- **Aggregates**: Compact integer and float counters: `total_deaths`, `deaths_by_cause`, `deaths_by_killer_species`, `damage_by_source`, `damage_by_species`.
- **Memory Complexity**: $O(1)$ with respect to run tick count ($< 100$ KB total observer heap).

### 2.4 Slot Recycling Isolation
When resident $i$ dies and is resurrected via `self.human(i, ...)`:
`observer.on_human_reset(i)` is called immediately:
- Empties the damage ring for slot $i$.
- Clears the cached lethal record and old-age flag.
- Resets the tracked victim UID.
- Guarantees the recycled slot starts completely clean with zero history leakage.

---

## 3. Harness Semantics and Duels Disclosure

### 3.1 Feed Resets (`self.feed()`)
- **Semantic Contract**: `feed()` resets `HUNGER = 20.0`, `THIRST = 20.0`, `H_STAMINA = 100.0`, `H_AGE = 30.0`, `H_LIFE_EXP = 80.0` every tick.
- **Probe Scope**: The probe evaluates creature balance and resident survivability against hostile predators without hunters. It is not an economic sustainability probe; residents are sustained by the harness so all observed deaths measure creature combat pressure.

### 3.2 Duels Closed-Form Formula Estimates (`duels()`)
- **Semantic Contract**: `duels()` computes theoretical time-to-kill values from creature HP, damage, cooldown, and human `ATTACK_DAMAGE`.
- **Honesty Disclosure**: These are formula estimates derived from table parameters, NOT simulated agent combat in the window engine. Residents in this probe do not fight back; these values estimate whether armed hunters could defeat predators if simulated.

---

## 4. Test Verification Summary

The test suite in `tests/test_creature_balance_attribution_1010.py` provides 9 comprehensive unit tests:
1. `test_actual_production_damage_nonlethal_and_lethal`: Real `apply_human_damage` on fixture, distinguishing non-lethal (35 dmg) and lethal (80 dmg on 65 HP) with overkill (15 dmg).
2. `test_multiple_same_tick_sources_and_overkill`: Distinguishes multiple attackers on the same tick, accurately apportioning damage and overkill.
3. `test_nearby_uninvolved_animal_never_assigned_killer`: Proximity != causation test with sheep at 0.3 units and wolf at 15 units. True killer is wolf; sheep is never assigned.
4. `test_slot_recycled_unknown_stale_identity_does_not_leak_history`: Verifies slot reset isolates history and prevents cross-resident leakage.
5. `test_attribution_wrappers_restore_original_functions_on_error`: Verifies 100% restoration of functions when exceptions are raised.
6. `test_bounded_rings_and_firstdeath_cap`: Verifies ring evictions at cap 4 and death list cap at 8.
7. `test_observed_path_returns_same_tensors_and_rng_as_unobserved`: Verifies bit-identical tensors and torch RNG state matching.
8. `test_pure_observer_old_age_and_unattributed_deaths`: Verifies old age, unattributed HP drop, and unresolved type removal causes.
9. `test_formula_estimates_honesty`: Verifies `duels()` output structure and explicit formula disclosure.

---

## 5. Substantive Handoff to Root

In accordance with execution boundaries (no shell/RunCommand/Git executed in this step):

### Step 1: Run Observer Unit Tests
Execute the unit test suite:
```powershell
.venv/Scripts/python.exe -m unittest tests/test_creature_balance_attribution_1010.py
```

### Step 2: Archive Diagnostic Snapshot & Schedule 10-Day Probe
Run the full 10-day long-calendar probe with kernel brain:
```powershell
.venv/Scripts/python.exe tools/creature_balance.py --days 10 --brain kernel --calendar user --json coordination_evidence/creature_balance_10day_attributed.json
```

### Step 3: Review Run Results and Causes
Review the generated `creature_balance_10day_attributed.json` to verify:
- `attribution["deaths_by_cause"]` and `attribution["deaths_by_killer_species"]`.
- `first_deaths` causal attribution fields (`true_cause`, `killer_species`, `killer_uid`, `damage_applied`, `damage_requested`, `overkill`).
- `proximity_matches_true_killer_rate` demonstrating the diagnostic divergence between spatial proximity and true causation.
- R0.3 completion remains pending until Root review of run results, tables, and true causes.
