# 1008 dead-clamp audit (G-D0-3 / G-D0-4): `t[mask, col].clamp_(...)` clamps a copy

Measured by the scratch tooling described below, seed 1008, the authored starter village (8 residents), **no god powers**. This documents the state BEFORE the fix commit that replaced these 30 statements with `harness.clamp.clamp_rows_`.

## Result

- 30 clamp statements were dead: advanced indexing (`t[bool_mask, col]`, `t[index_tensor, col]`) returns a copy, so `.clamp_()` clamped the copy and the tensor kept the unclamped value. Two further sites index with an integer (`resolver.py` `hunter_slot`, `thirst.py` `slot`): that is a view, those clamps always worked and were left alone.
- In **36000 ticks (30 game minutes) of normal play, 2 of the 30 sites ran at all**; the other 28 (combat damage, infection spread, storm/plague, mating, animal tools, god tools, irrigation/lake/well water) never executed in this scenario, so there is NO measurement for them: their effect is unknown, not zero.
- **Site `instincts_and_tools.py` `instinct_cooldown` (human cooldown decay): out of range on every tick for every resident.** `H_COOLDOWN` is decremented by 0.00167 per tick with no floor, so it drifted linearly to **-6.0 at tick 3600 and -60.0 at tick 36000** (288,000 of 288,000 row-calls below 0). The consumers (`map_test.py` `cooldown > 0.0`; `social/mating.py` `<= 0.0`) treat negative and zero the same, so game behaviour was unaffected; the stored value, the resident snapshot's `cooldown` field and the tensor hash were.
- **Site `systems/nature/ecology.py` food regrow: 19 row-calls over the cap in 6755 calls**, by at most 0.0027 (first at tick 1569). Cumulative effect on total food in the world: +0.044 by tick 1800 (1767.810 vs 1767.766 capped) and the same +0.044 at ticks 2400, 3000 and 3600.
- Stage 1 play was therefore affected only cosmetically (negative cooldown values; sub-0.003 food overshoot). God powers and hazards (set_mood/threat/age/aggression, plague, storm, quarantine, heal_animals) were affected for real: values could leave their documented range.

## Effect of the fix on the golden trace (seed 1008, 3600 ticks)

Strict compare against the old golden: resident fields (x, y, hp, hunger, thirst, stamina, mood, goal) are **identical at all 11 checkpoints**. Differences: `h_sha256` from tick 1 (the cooldown column no longer goes negative) and, from tick 1800, `m_sha256` and `m_sums.food` (-0.044, the food cap taking effect). Nothing else changed. The new golden was recorded and re-verified strictly in a second fresh process.

## Per-site table (line numbers are before the fix; bounds are what the code states)

| site | statement | bound | 36000-tick measurement |
| --- | --- | --- | --- |
| `instincts_and_tools.py:948` | `h_tensor[h_mask, col].clamp_(min=0.0)` | min=0.0 | 36000 calls, 288000 rows: 288000 below 0.0 (max 60.01), 0 above None (max 0); first tick 0 |
| `instincts_and_tools.py:1646` | `m_tensor[a_mask, A_HUNGER].clamp_(max=100.0)` | max=100.0 | never executed |
| `instincts_and_tools.py:1657` | `m_tensor[a_mask, A_THIRST].clamp_(max=100.0)` | max=100.0 | never executed |
| `instincts_and_tools.py:1916` | `m_tensor[a_mask, A_COOLDOWN].clamp_(min=0.0)` | min=0.0 | never executed |
| `instincts_and_tools.py:2629` | `h_tensor[affected, MOOD].clamp_(0.0, 100.0)` | 0.0, 100.0 | never executed |
| `instincts_and_tools.py:2637` | `h_tensor[affected, THREAT].clamp_(0.0, 100.0)` | 0.0, 100.0 | never executed |
| `instincts_and_tools.py:2724` | `h_tensor[females, H_FERTILITY].clamp_(max=2.0)` | max=2.0 | never executed |
| `instincts_and_tools.py:2761` | `h_tensor[affected, H_AGE].clamp_(min=0.0)` | min=0.0 | never executed |
| `instincts_and_tools.py:2769` | `h_tensor[affected, H_LIFE_EXP].clamp_(min=1.0)` | min=1.0 | never executed |
| `instincts_and_tools.py:2777` | `h_tensor[affected, H_AGGRESSION].clamp_(0.0, 1.0)` | 0.0, 1.0 | never executed |
| `instincts_and_tools.py:2803` | `h_tensor[infected, THREAT].clamp_(max=100.0)` | max=100.0 | never executed |
| `instincts_and_tools.py:3187` | `m_tensor[affected, A_HUNGER].clamp_(min=0.0)` | min=0.0 | never executed |
| `instincts_and_tools.py:3204` | `m_tensor[affected, M_HP].clamp_(max=100.0)` | max=100.0 | never executed |
| `systems/combat/resolver.py:162` | `h_tensor[human_hit_mask, THREAT].clamp_(max=100.0)` | max=100.0 | never executed |
| `systems/combat/resolver.py:174` | `h_tensor[attacker_idx, H_STAMINA].clamp_(min=0.0)` | min=0.0 | never executed |
| `systems/health/effects.py:27` | `h_tensor[affected, H_INFECTION].clamp_(max=100.0)` | max=100.0 | never executed |
| `systems/health/effects.py:29` | `h_tensor[affected, THREAT].clamp_(max=100.0)` | max=100.0 | never executed |
| `systems/health/effects.py:31` | `h_tensor[affected, MOOD].clamp_(min=0.0)` | min=0.0 | never executed |
| `systems/health/infection.py:51` | `h_tensor[spreads_to, H_INFECTION].clamp_(max=100.0)` | max=100.0 | never executed |
| `systems/health/infection.py:57` | `h_tensor[isolated, H_INFECTION].clamp_(min=0.0)` | min=0.0 | never executed |
| `systems/health/infection.py:65` | `h_tensor[spreads_to, H_INFECTION].clamp_(max=100.0)` | max=100.0 | never executed |
| `systems/health/infection.py:70` | `h_tensor[isolated, H_INFECTION].clamp_(min=0.0)` | min=0.0 | never executed |
| `systems/nature/disasters.py:176` | `h_tensor[storm_agents, MOOD].clamp_(min=0.0)` | min=0.0 | never executed |
| `systems/nature/disasters.py:178` | `h_tensor[storm_agents, THREAT].clamp_(max=100.0)` | max=100.0 | never executed |
| `systems/nature/ecology.py:95` | `m_tensor[:n][not_fire, M_RESOURCE_FOOD].clamp_(max=MAX_ENTITY_FOOD)` | max=MAX_ENTITY_FOOD | 6755 calls, 45102 rows: 0 below None (max 0), 19 above 100.0 (max 0.002739); first tick 1569 |
| `systems/nature/ecology.py:121` | `m_tensor[:n][lake_mask, M_RESOURCE_WATER].clamp_(max=MAX_ENTITY_WATER)` | max=MAX_ENTITY_WATER | never executed |
| `systems/nature/ecology.py:129` | `m_tensor[:n][well_mask, M_RESOURCE_WATER].clamp_(max=MAX_ENTITY_WATER)` | max=MAX_ENTITY_WATER | never executed |
| `systems/nature/ecology.py:144` | `m_tensor[:n][irrigated, M_RESOURCE_FOOD].clamp_(max=MAX_ENTITY_FOOD)` | max=MAX_ENTITY_FOOD | never executed |
| `systems/nature/ecology.py:146` | `m_tensor[:n][irrigated, M_RESOURCE_WATER].clamp_(min=0.0)` | min=0.0 | never executed |
| `systems/social/mating.py:131` | `h_tensor[h_mask, col].clamp_(min=0.0)` | min=0.0 | never executed |

## Intended bounds

Every site states its bound in the statement itself (min 0 for timers, hunger, stamina, infection floors, water; max 100 for threat, infection, animal hunger/thirst/hp, mood; `MAX_ENTITY_FOOD` and `MAX_ENTITY_WATER` = 100.0 in `genesis_config.py`; fertility max 2.0; aggression 0..1; life expectancy min 1.0; age min 0). The fix keeps exactly those bounds. Checked for contradictions: animals spawn at hp 100 and the 140-hp entities are mountains (not in `a_mask`), so the animal heal cap of 100 is consistent. No site needed a `[VERIFY]`.

## Method

A scratch copy of the tree (outside the repo) had the 30 statements rewritten to a counting `clamp_rows_` that OBSERVES (records rows selected, rows out of range, maximum excess, first tick) and does not write, so the run follows the unmodified legacy trajectory; its tick-3600 state hashes equal the committed golden's (h `336cb700cd92`, m `fa36e5ec18b2`). Tooling lives in the session scratch directory and is not committed. Counting only covers the scenario above.
