# R6.3 economy balance — implementation and evidence

Status: COMPLETE within the R6.3 measured scenario scope. Final gated scenario, exact flag-off repeat, 78 tests and all four strict goldens verified. No commit, default flip, golden re-recording, roadmap or decision-register edit.

## Outcome and scope

Default-off `EDEN_ECONOMY_BALANCE=1` connects residents to their existing household farm food and enables keeper withdrawal of earned stall proceeds, retaining a two-coin float. A root-coordinated minimal shared needs gate preserves water handling while preventing incidental free food below the unchanged emergency threshold. No prices, wages, growth rates, calendar rates, initial supplies or emergency thresholds changed.

All four 4,000-tick commons seeds feed residents after bootstrap without recurring free food rations. All emergency food calls occur before tick 288. This establishes the measured scenario's post-bootstrap acceptance, not indefinite irrigation or general-world/long-calendar sustainability.

## Final measurements

All runs are 4,000 ticks; tail covers ticks 3,001–4,000. `r63_fixed_after.json` is the final gated data, superseding the preliminary harvest-only table below.

| Seed | Final digest | Actual food calls total / tail | Causes | Latest emergency tick | Paid shifts | No-wage refusals | Harvested crops | Highest tail mean / peak | Keeper wage-capacity samples | Coin start/end |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1008 | ced1b2bc7e8e6693 | 2 / 0 | floor only | 199 | 4 | 0 | 34 | 24.34 / 35.00 | 51/80 | 49/49 |
| 1 | c5c9b72f7762302f | 2 / 0 | floor only | 287 | 4 | 0 | 36 | 22.92 / 34.36 | 49/80 | 49/49 |
| 2 | 2bf29d9420bc4201 | 1 / 0 | floor only | 90 | 4 | 1 | 40 | 26.00 / 44.97 | 49/80 | 49/49 |
| 3 | 4af2e14df5bc1c68 | 2 / 0 | floor only | 262 | 4 | 0 | 36 | 24.47 / 34.00 | 80/80 | 49/49 |

All four have no deaths, silent starvation, expired stuck errands, driver errors or unauthorized item creation. There are no thirst-triggered or other below-floor food calls. Emergency calls occur only during initial labour errands, before tick 288; there are **no food-ration calls anywhere after that**. This proves the four-thousand-tick scenario feeds itself after the bootstrap interval; it does not prove indefinite irrigation or long-calendar sustainability. The repeat of seed 1008 is `ced1b2bc7e8e6693` again. Exact loaded sources/commands are in `r63_fixed_after_manifest.json`.

## Diagnosis and decisions

The commons blights three edible bushes and the family pantry and injects six rations, but the whole world's starting inventory actually contains 20 rations and six crop bundles. Three existing farm plots retain water/growth; two neighbour plots start with 30 food each. The food ladder scans only resource nodes and misses farms.

Direct observational seed-1008 probes preserved exact archived digests. Original behavior (`2fbbeae222e2dbd0`) used 25 free food calls: one floor emergency and 24 thirst-then-food calls, with five calls in the final 1,000 ticks. Harvest/till-only behavior (`9c9597fca425d1a5`) still used 11: two floor emergencies and nine thirst-then-food calls, with two in the tail. Neither recorded successful rest routes; yielded resident-ticks are not worker rest. Thus zero approximate floor resets or low hunger peaks did not prove absence of free food. Preliminary artifacts remain for provenance and are superseded by the final gated results.

`needs.plan` loops water and food together. Its backward-compatible `allow_food=True` keyword now excludes starting new food handling while preserving water and existing trips. Only balance plus ladder enabled uses this through `AgentDriver._plan_tier0_needs`; flag-off retains the original five-argument call. Hunger limit 90 remains; starvation mode retains infinity. Root explicitly coordinated and authorized agent_driver.py and roster/needs.py ownership before these edits.

GAP-R63-PRODUCTION was recorded before shared edits: new production/regrowth rates would require ecology, map resources or occupation producers outside this ownership. These paths remain untouched. The optional action instead converts existing farm stock into declared inventory. Renewed irrigation and indefinite village sustainability remain future evidence gaps.

DR-19 recommendation is followed: scenario-backed tuning, restitution through justice, rules proposer. DR-2 remains **OPEN; preserve defaults meanwhile**. No paid model/API/training, new player restraint, API/client/backend changes or user decision was introduced.

## Implementation

- Optional `harvest_farm` requires balance and map-resource flags. It checks household ownership, a live non-burning farm, reach, positive integer quantity, stock and capacity. Each crop bundle atomically consumes one farm-food unit, with declared production. Missing columns yield no candidates.
- The existing forage rung selects owned farms, gathers bounded batches and uses existing bounded errands. Arrival refreshes stock/capacity; disappeared farms refuse safely.
- Daily keeper collection uses checked `fetch_item`, capacity limits, a two-coin float, existing alive/dormancy guards and bounded errands without replacing active work. Arrival refreshes the till and records no food relief. The final seeds record no collection routes, so their wage improvement is not attributed to measured till withdrawals; focused tests verify this behavior.
- `FoodRationAudit` delegates and restores the existing ration function even on exceptions. Actual counts/reasons/errand purposes and additive hunger/capacity metrics stay outside historical digest keys. The conservation verdict permits only successfully declared farm production; coin equality remains exact.

## Verification and provenance

Final command: `.venv/Scripts/python.exe coordination_evidence/r63_finish.py`, serial phases `fixed_tests`, `fixed_after`, `fixed_off`, `fixed_goldens`. Base archive: `b555adc33776696f529ae9e4047c88acdb42f408`. Each phase manifest records exact commands, base and SHA-256 of loaded owned sources. These clean archives exclude unrelated peer edits and do not constitute a full-suite/integration gate.

**78 tests pass**: 19 economy balance, 16 market book, 14 market verbs, 11 labour, 12 roster needs, six agent driver. Coverage includes stock-backed production, ownership/capacity/invalid quantity/burning/missing farm, till float and changed arrival state, water-only moderate hunger, emergency food, starvation mode, flag/ladder-off legacy behavior, existing trips and exception-safe auditing. Driver tests include prior-tick parity.

Flag-off seeds 1008/1/2/3 reproduce historical digests `2fbbeae222e2dbd0`, `506087d6cd7c03b7`, `0c1caa5f808ab31f`, `a346757a68219f68`; seed 1008 repeats exactly. All five verdicts pass. Actual food calls total/tail are 25/5, 23/5, 23/4, 25/5, and repeated 25/5. All four final manifests have identical base/source hashes and match live owned source files. Owned tracked diff passes `git diff --check`; whole-tree check reports trailing whitespace in peer-owned `tests/test_harness_chunk_routes.py`, left for its owner.

All four strict golden commands pass with no drift across 11 checkpoints each (72.3 / 82.2 / 74.5 / 83.8 seconds). The final pipeline exited 0 and its token-owned lock is released. Root integration/full-suite validation remains separate. Commands: `tools/golden_trace.py --check --strict`, additionally `--resources`, `--spaces`, and `--window-hook`. No fixture is re-recorded.

The runner atomically creates `.runtime/fullsuite.lock`, aborts if occupied and removes only its matching token. It correctly left R0.2's lock untouched. Initial sandbox attempts hit `WinError 5` in Python temporary directories; the identical owned runner succeeded through allowed escalation. No automatic approval rejection occurred.

## Changed files and artifacts

- `at_the_beginning/systems/actions/{agent_driver,ladder,market_day,resource_verbs,economy_verbs}.py`
- `at_the_beginning/systems/affordance/{predicates,economy_predicates}.py`
- `at_the_beginning/systems/roster/needs.py` (root-coordinated minimum gate)
- `model_server/{s1_commons,economy_audit}.py`
- `tests/test_economy_balance.py`
- This report, owned helpers `r63_checks.py`, `r63_finish.py`, `r63_ration_probe.py`, and their evidence JSON/manifests/logs.

Final authoritative artifacts are `r63_fixed_after.json`, `r63_fixed_off.json`, phase manifests and `r63_fixed_tests.log` / `r63_fixed_goldens.log`. Original exact ration probes are `r63_exact_rations_off.json` and `r63_exact_rations_after_final.json`. Legacy no-wage refusals were 22/31/21/22; paid shifts were 6/7/6/8. Wage capacity is sampled affordability, not reserved wages.

Economy handed off with frozen source hashes. Power ports are next; human-killer identity follows. AGY owns harness/needs.py, tests/test_harness_needs.py and the narrow map_test movement block; these remain read-only here. Settlement design was reassigned elsewhere.
