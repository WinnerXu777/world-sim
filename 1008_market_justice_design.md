# 1008 market, escalation ladder and theft / reputation / justice: design note

Model plane. Status: **design (docs only) plus the cut that is implemented in this round**. Flags default off; with the flags off the strict golden
(`tools/golden_trace.py --check --strict`, default and `--resources`) is unchanged. Proposal context: `1008expandtools_instincts.md` Part 1, entries 1, 2, 4, 12.

## 1. What exists today (verified in the tree)

* Verbs on the runner: `request_item` (the asked resident answers by rules: give / refuse_no_item / refuse_distrust / refuse_busy), `give_item`, `offer_trade` /
  `accept_trade` (OfferBook, `respond_to_trade`: accept / refuse_distrust / refuse_busy / refuse_no_item / refuse_needs / refuse_unfair, fairness = value received >= 0.9 x
  value given up, `item_kind_def.value`), `steal_when_safe` (destructive, no witness within help range 72, one `Transfer`, a `theft` ledger event visible only to thief
  and owner), `share_news` / `gossip` (a listener becomes a witness of the same ledger event; opinion of the person talked about moves by half the teller's closeness, cap 0.05),
  `avoid`, `warn`, `attack`, `approach_node` + `eat_from_node` / `gather_from_node`.
* Tier 0 (`systems/roster/needs.py`): at hunger or thirst >= threshold (30) the resident walks to the food / water anchor and the need resets; with no site it gets a free ration.
  **A resident never starves under Tier 0.** That is correct for Stage 1 and wrong for a scarcity scenario (see 4.5).
* Ledger (`harness/events.py`): events with witnesses; no subscribers are registered by the engine, so nothing reacts to an event yet except what a verb does itself.
* Personality: 16 traits in 0..1 (`mercy, loyalty, discipline, deceitfulness, greed, aggression, vengefulness, protectiveness, pride, resolve, caution, ...`). There is no `conscience`
  or `honesty` trait; this note defines `conscience` from the traits that exist.
* Items have a `value`; `coin` is an ordinary item (value 1.0). There is no market, no price list except `COMMISSION_CONFIG["prices"]` (smith recipes), no ownership of containers.

## 2. The market (design; first step is barter that already exists)

**M0 (built, batch 2): barter with reference prices.** `offer_trade` / `accept_trade` swap two stacks at a fairness test against the item `value` table. This is the price source.

**M1 (designed, not built this round): stalls, `buy`, `sell`, `set_price`.** A `Market` is a storage entity with an owner (a shopkeeper) and a price list. State (saved with the world,
beside inventories): `market = {entity_id, owner, prices: {item: price}, sales: ring buffer of {tick, item, qty, price}}`. `sell(T, item, qty)` and `buy(T, item, qty)` are
atomic `Transfer` pairs (item one way, coin the other) at the stall price; `can_buy` needs a stall in interaction range, stock >= qty and the buyer holding the coin;
`can_sell` needs the stall to want the item (stock below its target) and room. `set_price` is the owner's act, bounded to 0.5x..3x of the reference price. Coin source: wages
(`work_shift` for a payer, entry 8 in the proposal file) and the starting purse; sinks: fines and taxes (entry 11). Currency is optional: with no coin a stall prices in a
reference item and degenerates to M0.
**M2 (designed): supply / demand.** Daily: `scarcity = clamp((demand_ema + 1) / (supply_ema + 1), 0.5, 3)` per item from sales, stock and unmet requests; reference price =
`value * scarcity`; barter fairness and stall prices both read it. A daily `market_update` system (a Harness-plane registration) writes it; Tier 1 shopkeepers reprice from it.
Why not now: the S-1 scenario needs trade between two households, not a price-discovery economy; M0 gives that.

## 3. The escalation ladder (built this round, flag `EDEN_AGENT_LADDER=1`)

### 3.1 Desperation and conscience (pure functions, deterministic)
Per resident, evaluated on the decision cadence (every `EDEN_AGENT_DECIDE_PERIOD` = 10 ticks, staggered by slot) and whenever hunger crosses the trip threshold:

```
hunger_term   = hunger / 100
empty_pack    = 0.20 if no edible item in the pack else 0
kin_term      = 0.15 * min(3, hungry dependants)       # a kin with hunger >= 50 who is a child or whom the resident protects
relief        = 0.10 if a rung succeeded in the last 600 ticks
d             = clamp(hunger_term + empty_pack + kin_term - relief, 0, 1.2)

conscience c  = 0.35*mercy + 0.25*loyalty + 0.25*discipline - 0.35*deceitfulness - 0.25*greed - 0.20*aggression      (range about -0.8..0.85)
family_push   = 0.15 * protectiveness if a dependant (not the resident) is the hungry one else 0
rung threshold = base[rung] + 0.30 * c - family_push          # a high-conscience resident needs a higher d
base = forage 0.00, work 0.20, beg 0.35, trade 0.30, borrow 0.50, steal 0.65, rob 0.85
```
A rung is *allowed* when `d >= threshold` and it is not cooling down. Rungs are tried in cost order **forage, work, trade, beg, borrow, steal, rob** (trade before beg when the
resident holds something worth swapping: it keeps its dignity; `pride` > 0.7 swaps the order of beg and borrow). Only the first allowed and feasible rung is attempted per decision.

### 3.2 Rungs and their feasibility (what a rung needs and how it fails)
| rung | built | action | feasible when | failure and cooldown |
|---|---|---|---|---|
| forage | yes | eat from the pack; else `eat_from_node` / `gather_from_node` at a remembered node; if out of reach, `approach_node` or an errand to the node | a node with stock in sight or remembered | node empty -> that node cools down 300 ticks |
| work | designed | `work_shift` for a payer in kind (entry 8) | an employer with a task | n/a this round (documented gap) |
| trade | yes | `offer_trade` of a surplus item (largest stack, not edible, value >= 0.9 x wanted) for an edible | a neighbour in range and a surplus stack | `refuse_*` -> that neighbour cools down 200 ticks for trade |
| beg | yes | `request_item` to the nearest neighbour who is kin, friend or not hostile, empty item = whatever food they can spare | a neighbour in range | `refuse_*` -> that neighbour cools down 200 ticks for begging |
| borrow | designed | `borrow_item` (entry 3) | a creditor | not built; documented gap |
| steal | yes | errand to a known container with an edible, then `steal_when_safe`; or `steal_when_safe` from a resident only when it saw that resident carrying food | a known foreign container, no witness at arrival, risk estimate below the gate | `watched` -> wait up to 120 ticks at a distance, then abort and cool the container down 600 ticks |
| rob | designed | `attack` + take (entry 17) | n/a | not built; documented gap |

**Errands.** A rung that needs to walk (forage far from a node, steal at a container in another space) sets an `errand` on the agent driver: a goal position (an anchor or a
container position, portals handled by the existing AnchorMover) with a purpose and an expiry. An errand pre-empts the routine, never a Tier 0 water trip or a commission, and the
rung's verb is attempted on arrival. The errand is runtime state (not saved), like a trip.

**Ownership (minimal, entry 12).** A container belongs to a household when its entity id starts with `<household>:` and a resident belongs to the household of the prefix of its
roster key (`<household>_<name>`). Taking from an own-household container is `fetch_item` (not theft); from another household's container is theft. This convention is data in the
scenario roster, so no engine change is needed; a real `owner` field replaces it later.

**Risk gate for steal.** `risk = P(caught) * penalty`; `P(caught) = clamp(0.15 + 0.5 * witnesses_in_range + 0.3 * (owner within social range), 0, 0.95)`; `penalty = 0.3 + 0.5 * max(c, 0)` (the felt cost grows with conscience). Steal is attempted when `d - threshold(steal) >= risk * 0.5`. The same function decides rob later.

### 3.3 Tier 0 food loop under the ladder
With `EDEN_AGENT_LADDER=1` the agent driver skips Tier 0 when only hunger is over the threshold (water trips are unchanged), so hunger is solved by the ladder and a resident
can really go hungry. HP loss at high hunger and death are the engine's existing survival rules. The flag-off path is byte-identical.

## 4. Theft, reputation and justice (built this round, flag `EDEN_REPUTATION=1`; authority designed)

### 4.1 Detection
A successful `steal_when_safe` writes a `theft` ledger event. With the flag on:
* The event is `local` (radius 80) so any resident who is in range at the time is a witness and learns the culprit. By the predicate this set is normally empty for a resident's own
  theft (the predicate refuses when anyone is within 72); it is non-empty when the thief takes the risk of `watched` under desperation (rung `steal` with `d >= 1.0`, designed, off by default) or
  when the target is the one robbed.
* **Victim detection.** The victim (a resident owner) notices with `p = clamp(0.25 + 0.4 * (1 - hunger/100) + 0.2 * alertness)` where alertness = `caution`; for a container the nearest
  household member is the notional victim. The draw is deterministic: `world.rng("theft_detect", victim_id)` seeded by seed and tick. If detected and the thief was within interaction range the victim
  knows the culprit (`culprit_known`); if detected otherwise it knows only that something is missing (`loss_discovered`, culprit unknown, suspicion = the resident with the lowest closeness who was near).
* Not detected: a `loss_discovered` event fires when the owner next looks (fetch fails or pantry count drops), culprit unknown. **No theft is silent in the ledger.**

### 4.2 Consequences (rules, all event-driven, no per-tick cost)
For each knower K of a known culprit T (victim and witnesses):
* Opinion: `closeness(K -> T) -= (0.12 + 0.02 * item_value * qty) * (1 - 0.5 * mercy_K)`, clamped at -1; the relation tag `thief` is added; a `robbed_by` / `saw_theft` memory entry (record op `memory_note`).
* Gossip: K's Tier 1 tells its friends within social range (`gossip`, cooldown 300 ticks, at most 3 tellings per theft); every telling adds a witness of the same event and moves the
  listener's opinion of T by half of K's closeness, cap 0.05 (already built).
* Response by personality, chosen once per theft by K (`response_of(K)`): `avoid` if `fearfulness` or `caution` > 0.6; `confront` (a `warn` plus a restitution demand) if `protectiveness` or `pride` > 0.6;
  `retaliate` (a goal `retaliate` at priority `vengefulness`) only if `vengefulness > 0.7 and mercy < 0.4`; else `ignore_but_wary`.
* Social cost for T: residents refuse T's requests and trades by the existing `refuse_distrust` (closeness < -0.2) plus `refuse_thief` (the `thief` tag with closeness < 0.0). Hospitality verbs (give,
  shelter) are refused the same way.
* Restitution and forgiveness: T with `conscience > 0.1` and food again (an edible in the pack and hunger < 40) returns the item (a `give_item` to the victim) and `apologise`s; the victim's closeness
  recovers by `+0.1` per restitution and the `thief` tag is removed when closeness >= 0.0. Without restitution the grudge decays: a daily step moves hostile closeness 10% toward 0 for K
  with `mercy >= 0.5` and 4% for others (forgiveness over time, half-life about a week for the merciful). Repeat thefts reset the tag.

### 4.3 Justice (designed, not built this round)
An authority (guard / elder, entry 11) receives `report_crime` from knowers, holds a `law` table (crime -> penalty), and answers with `arrest_or_restrain`, forced restitution, a fine or exile. It
needs the governance objects and the missing `defend` task; this round the community response is social only (opinion, avoidance, refusals, retaliation by the vengeful, restitution).

### 4.4 What a model can do (Tier 2 / 3)
The same events and legal options are exposed to Tier 2: the ladder is only the default; a model may pick any legal verb (e.g. beg a friend instead of stealing). Steal / rob stay
`destructive` (the D-3 risk gate: only the rules proposer or a model above the confidence threshold passes).

### 4.5 Flags and compatibility
* `EDEN_AGENT_ACTIONS=1` (existing) is required for either new flag (routing through the runner).
* `EDEN_AGENT_LADDER=1`: the ladder, errands, Tier 0 food skip for agent residents. `EDEN_REPUTATION=1`: detection, opinion, gossip, avoidance, refusals, restitution, decay.
* All state: runtime (non-saved) cooldown and errand tables on the `AgentDriver`; saved state is only what already is saved (relationships, memory notes, goals, ledger).
* Position holders: errand targets are positions, so `rebase_model_plane` shifts them (added to the callback and its test).

## 5. Acceptance (S-1 scenario on `family_farm`, `EDEN_MAP_RESOURCES=1`, agent residents)
Defined before the code; results are reported with the commit.
* **Setup.** Map `family_farm` placed at origin (420, 0) with the two interiors; five residents (family: mother, father, child; neighbour: man and wife), roster file supplied by
  `EDEN_ROSTER_DIR` (a scenario directory in `model_server/scenarios`; the repo's `world_data/rosters` is untouched). The family pantry has 2 rations, the neighbour pantry 14 rations + 6 crop bundles
  (in the map). `scarcity_area` centred on the family plot and bushes removes the near food (the three far bushes keep a little; they are 150-200 units away, beside a hostile marker). Family starting hunger 55.
* **Ladder behaviour (rules, flag on).** The family eats its 2 rations (pack/pantry), forages at the bushes, tries to trade (wood bundles for rations) and to beg the neighbour; with desperation high and a
  low-conscience member it steals from the neighbour pantry when nobody is home. The neighbour (merciful, loyal) may give to a hungry child.
* **Pass criteria (N = 6000 ticks, rules; then matrix):** (1) no resident dies of hunger **unless** the ledger and the audit explain it (every rung tried is in the audit with its refusal reason; a death has a
  `starved` consequence record); (2) at least one rung beyond forage is used (beg / trade); (3) when a theft happens, ledger events `theft` and `loss_discovered` or a witnessed theft exist, the knowers' opinion
  of the thief dropped, at least one `gossip` / `share_news` of it is audited, at least one refusal or avoidance by a knower is audited; (4) ledger events present: `resource_depleted`, `traded` or `gave_item`,
  `theft`; (5) zero runner rejections that are unexplained (every `ok == False` has a documented code); (6) deterministic: two runs with the same seed give identical audit digests; (7) flag off: strict golden
  unchanged (default and `--resources`); (8) shadow vs on pass with the mock Tier 3 (Tier 3 shadow: same decisions, no effect; on: effects applied) reported separately.
* **Reported.** A timeline (tick of first rung, each refusal, theft, discovery, gossip, restitution), per-resident rung counts, final hunger / HP, and what each resident actually did.

## 6. Build order and tests
1. This note (docs).
2. `systems/actions/ladder.py` (desperation, conscience, rungs, feasibility; pure), tests with a synthetic world for every threshold and rung transition.
3. `agent_driver.py`: errands, ladder hook behind the flag, Tier 0 food skip. Tests: flag off identical, flag on routes the rungs.
4. `systems/actions/reputation.py` + record ops: detection, opinion, tag, memory notes, gossip rule, response, refusals (`respond_to_request` / `respond_to_trade`), restitution, decay. Tests.
5. `rebase_model_plane` learns errands (test).
6. Scenario module (`model_server/s1_family_farm.py` + roster) and the acceptance run; report.
7. Full suite on a clean archive when the Harness plane's P5 is in.


## 7. As built (partial, committed at the hand-over; both flags default off)

Status: **the ladder, the reputation module and the family_farm scenario run end to end; the acceptance of section 5 is NOT complete** (see "Not done").

**Built**
* `systems/actions/ladder.py`: pure part (`conscience`, `desperation`, `thresholds`, `allowed`, household helpers) and `Ladder` (rungs forage / trade / beg / steal, cooldowns, errands, a timeline log).
  Forage: eat from the pack, fetch from the own-household pantry, eat from a food node (errand to the nearest work/talk anchor beside the node: the node centre itself is not standable and the mover
  stalls there). Trade/beg: a legal target in reach (16) is asked at once, else a *visit* errand follows the person and asks on arrival (within 12). Steal: foreign-household storage, errand to
  the container, waits up to 120 ticks when a witness is within help range (`illegal:watched`).
  The ladder proposes as `rules:ladder` so the destructive `steal_when_safe` passes the D-3 risk gate as a rules call (a model proposer would still be gated).
* `agent_driver.py` (all behind `EDEN_AGENT_ACTIONS=1` + `EDEN_AGENT_LADDER=1`): the ladder pass every 10 ticks per resident (staggered), errand goals in pass 3, Tier 0 food skipped while only hunger is over
  the trip threshold and below 90 (`LADDER_TIER0_HUNGER`: from 90 the free ration of Tier 0 takes over, so nobody starves silently), a **task watchdog** (an action task that owns a roster resident's movement
  for 400 ticks, or while hunger/thirst >= 75, is cleared; found by the scenario: a `talk_to_target` task stayed active for ever and a neighbour died of thirst; **since fc5d127 (D5) it runs for every agent-driven resident, not only with the ladder**), `status()["ladder"]`.
* `systems/actions/reputation.py` (`EDEN_REPUTATION=1`): `theft_consequence` record op (added by `steal_when_safe` only when the flag is on; the runner supplies the ledger event id) -> `record_theft`
  (victim notices at once with a draw, else the household finds the loss after 120..360 ticks and traces the culprit with p = 0.35 + 0.4 caution) -> `loss_discovered` event, the `theft` event gains the
  household as witnesses when the culprit is known, opinion drop `(0.12 + 0.02 value)(1 - 0.5 mercy)` and tag `thief` per knower, a memory note, a response by personality (retaliate / confront via
  `warn` / avoid / wary), gossip to friends (max 3 per knower, 300 apart), `refuse_thief` in `respond_to_request` / `respond_to_trade`, restitution errand for a thief with conscience > 0.1 that is fed
  (code written, not exercised by a run), daily forgiveness decay. All draws are `world.rng`.
* `model_server/s1_family_farm.py`: the scenario (roster written to a temp `EDEN_ROSTER_DIR`, family_farm + interiors at (600,0) and (600,340) because the isolation distance is 220 outside `EDEN_WINDOW`),
  variants `forage | trade | beg | steal`, `--reputation`, `--no-ladder`, JSON timeline, deterministic digest, verdict checks. `tests/test_ladder_reputation.py`: 9 pure tests + 2 subprocess scenario tests.

**Measured (seed 1008, needs_scale 1.0, family hunger 40, one run each, not repeated)**
* forage 1500 ticks: peak hunger 47, 8 `ate_from_node`, no theft. trade 2500: 4 `traded`, peak 45.7, nobody dies. steal 2500 (neighbours distrust): 15 begs, 2 thefts, no deaths.
* steal + `--reputation` 3000: 2 `theft`, 2 `loss_discovered`, 2 `opinion_drop`, 7 `gossiped`, 1 `warned`, nobody dies.
* A first trade run without the watchdog: a neighbour died of thirst at tick 1688 (stuck `talk_to_target`); fixed by the watchdog.

**Not done at the hand-over** (do not read the scenario pass as the full section 5): determinism of the digest across two runs; matrix Tier 1 vs rules; shadow vs on with the mock Tier 3; the strict golden and the
affected suites were re-run only partly (see the commit message); `rebase_model_plane` does not yet shift ladder errand positions (the ladder's errands are recomputed from the live world on the next
decision only for visits; fetch / forage / steal errands carry fixed positions); restitution and forgiveness decay never fired in a run; ladder rungs work (borrow, rob), debt, the market M1/M2 and
justice/authority are designed only; the scenario does not use `scarcity_area` (stock is removed directly) and does not place a hostile creature.

### 7.1 Acceptance run (2026-10-08, model plane track after the hand-over)

`python -m model_server.s1_acceptance --ticks 3000 --family-hunger H` runs five fresh processes (rules twice, matrix, Tier 3 shadow, Tier 3 on with the mock server, `--reputation`, variant `steal`, seed 1008). The digest covers peak hunger, deaths, the ladder log, ledger event counts, the reputation log, relations, pantries and the position / needs timeline.

| H | rules a = rules b (determinism) | matrix = rules | shadow = rules | on | Tier 3 activity |
|---|---|---|---|---|---|
| 40 | yes (e84f276f7a4a229a) | yes | yes | equal | none: all 3000 sweeps `skipped:calm`, so the comparison is **vacuous** |
| 85 | yes (38a4992714402741) | yes | yes | **differs** (bec7ff4b6c3c2a87) | 1 `unmet_need` trigger, 1 request, plan accepted and run: `sleep`, `seek_shelter`, `flee_to` (the mock's choice for a hungry resident) |

No deaths, 0 errors, 1 theft, 5 gossips at H = 85. The first H = 85 pass used a digest without positions and showed on == off; that digest could not see a plan's effect, so it now includes the timeline. Findings:
* The mock Tier 3 plan for a hunger need is poor (it offers `sleep`); that is the mock heuristic, not the gate. A real model is the point of the gate (confidence, known ops, dry run of step 0).
* Forgiveness bug found by the new test and fixed: `_decay` rounded closeness to 3 places, so a grudge smaller than about 0.05 (0.02 for the merciful) rounded back to itself and was never forgiven. It now rounds to 6 places. A `thief` tag whose closeness had recovered by other means is dropped at the next decay (design 4.2).
* Restitution: `tests/test_reputation_restitution.py` (4 tests, real engine) exercises the errand to the victim, the `give_item`, the closeness recovery and tag removal, a thief without conscience or still hungry making no amends, and decay speed merciful vs hard. The scenario run itself still did not produce a restitution (the thief in the steal variant has conscience <= 0.1).
* `rebase_model_plane` now shifts ladder errand positions for overworld targets (`ladder_errands` holder).
* Decay step and day length: `reputation.DAY_TICKS = 2400` is the single constant to swap for the calendar module (day 12000); `DECAY_PERIOD = DAY_TICKS // 4`.
Still not done: borrow / work / rob rungs, debt, market M1/M2, justice / authority, `scarcity_area` in the scenario, a hostile creature, the full suite with the three flags on.

## 8. Market M1 scope (2026-10-08, model plane track; flag `EDEN_MARKET`, default off; needs `EDEN_AGENT_ACTIONS`)

Goal (user): a realistic, complicated market: stalls, prices from supply and demand, currency, spoilage, scarcity events, merchants who travel. M1 builds the part that needs no legacy file; the rest is listed with its dependency.

**No legacy file is touched by M1.** New code lives in `systems/market/` (new package) and in my own paths (`systems/actions`, `systems/affordance`). The daily update runs from `AgentDriver.step` (no new engine hook). Prices are runtime state: on load they restart from the reference price (the save story is "stock and coin are inventories and already saved; prices and the sales ring are derived"). A saved `market` object is a later item that needs a persistence edit and a decision.

### 8.1 Objects
* **Stall** = any `storage` entity whose id has a market binding (scenario data: `family:market_stall`, later a settlement stall list). Owner = the household prefix of the id, shopkeeper = a resident bound to it. The stall's goods and its **till** (coin) are the entity's own inventory, so both are visible to Observation (goods on display), conserved by the harness, saved with the world, and **stealable** (`steal_when_safe` from the container, owner's household notified through the reputation loop).
* **PriceBook** (runtime, per stall): `{item: price}` in whole coin. **Reference price** `R(item) = max(1, round(value * f(item)))` where `f` is the settlement scarcity factor. **Ask** (stall sells) = `R * markup`, **bid** (stall buys) = `R * 0.6` (a stall resells at a margin). `set_price` is the shopkeeper's act, bounded to `0.5R .. 3R`.
* **Scarcity** `f = clamp((demand_ema + 1) / (supply_ema + 1), 0.5, 3.0)`; one daily update (`DAY_TICKS`, the same swappable constant as reputation) reads the sales ring (units bought, units sold, unmet purchases = a `buy` refused for stock), stall stock and the resource nodes' stock; smoothing 0.3. **Scarcity events** (drought, blight, raid, market day) enter through the node stock (the `scarcity_area` power the scenario can use) and through a `demand_shock` multiplier a god tool can set; both move `f` without special cases.
* **Currency**: `coin` is an ordinary item (value 1.0). Sources: the starting purse, selling to a stall (bid), later wages. Sinks: nothing in M1 (fines/taxes with justice, spoilage below). A closed economy drifts, so the scenario reports total coin each day.
* **Spoilage**: not in M1. Needs per-item age on stacks (inventory schema, a legacy file) or a per-stall batch table; recorded as dependency D-spoil, owned with the Harness food_spoilage instinct (Part 2 A2). Until then perishables never rot, which removes one scarcity driver.

### 8.2 Verbs (catalog rows flip `new` -> `now`, registered on the economy registry)
* `buy(stall, item, qty)`: legal when a stall is in interaction range, stock >= qty, the buyer holds `ask*qty` coin, room in the pack. One atomic apply: coin buyer -> stall, goods stall -> buyer. Event `bought` (public radius 12, so neighbours learn prices by watching), sales ring entry.
* `sell(stall, item, qty)`: legal when the stall wants the item (stock below its target `max(2, 2 * daily sales)`), has `bid*qty` coin in the till, buyer holds the goods. Atomic.
* `set_price(stall, item, price)`: owner only (`owns_shop`: the actor's household prefix equals the stall's), bounded to `0.5R .. 3R`; a record op on the PriceBook plus event `price_set`.
* `restock` is not a new verb: the shopkeeper's routine uses `store_item` from the household pantry to the stall and `fetch_item` to empty the till.
* Refusals are stable codes: `no_stall`, `out_of_stock`, `cannot_afford`, `stall_full`, `not_wanted`, `till_empty`, `not_owner`, `price_out_of_bounds`.

### 8.3 Rules (Tier 1, no model)
* **Buyer**: the ladder gets a `buy` rung between `work` and `trade` (cost order forage, work, buy, trade, beg, borrow, steal, rob) with threshold `base 0.15`; feasible when a stall in sight sells an edible at a price the resident can pay; a resident that cannot afford it and holds a surplus item tries `sell` first. A refused `buy` (`out_of_stock`) is recorded as unmet demand for the next scarcity update.
* **Shopkeeper**: a roster binding `stall` makes the work anchor the stall; the daily routine restocks from the household pantry (keep goods up to the target, keep a float of coin), reprices from `R` with a personality markup (`greed` raises it, `mercy` and `sociability` lower it to a friend: a friend discount by `closeness`), and empties the till into the pantry at night.
* **Reputation**: gouging (ask above 2R while a buyer is starving) and a refusal to sell to a thief (`thief` tag, as `refuse_thief`) are events and opinion inputs, so the market feeds the same justice loop.

### 8.4 Tests and acceptance
Pure tests for `PriceBook` and the scarcity formula (monotone in demand, clamp, smoothing), the verbs' Gate C table rows, a real-engine test on `family_farm` (a stall with stock, a buyer with coin buys, the till grows, conservation holds, price follows a demand shock after two daily updates), flag off: strict golden unchanged. Scenario variant `market` for `s1_family_farm`: the family has coin and no food, the neighbour keeps a stall; pass = purchases happen at the stall price, nobody steals while they can afford it, prices rise after a blight and the family buys less.

### 8.5 Not in M1 (dependency)
Travelling merchants and caravans (window / chunks and a second settlement, entry 15), wages and the work rung (employer objects, entry 8), credit and `pay_debt` (entry 3), taxes and fines (justice, entry 11), spoilage (D-spoil above), a saved `market` object (persistence), and a client view of stalls and prices (wire contract: stall price list on the entity, Codex client).

### 8.6 As built (M1, flag `EDEN_MARKET=1`, default off; deviations from 8.1-8.5 in bold)
* `systems/actions/gameclock.py`: the one `DAY_TICKS` (2400; reputation imports it; the calendar swap changes only this). `systems/market/{book,runtime,ops}.py`: `MarketBook` (PriceBook per stall, scarcity, daily update, sales ring of 200), `of(services)`,
  `register_stall`, `is_stall` (registered, or the id's local part starts with `market`/`stall`: `family:market_stall` on the family_farm map is one), record ops `market_sale` / `price_set` (executed by the runner on the services' book).
* `systems/actions/market_verbs.py` (`MARKET_REGISTRY`: `buy`, `sell`, `set_price`, stall id in `container`) added to `default_registry()` while the flag is on; predicates `can_buy` / `can_sell` / `owns_shop` in `affordance/market_predicates.py`
  (imported at the end of `predicates.py`; flag off: `not_wired`, no candidates). Refusals: `no_stall`, `out_of_stock`, `cannot_afford`, `no_room`, `stall_full`, `not_wanted`, `till_empty`, `not_owner`, `price_out_of_bounds`. **The catalog rows stay `new`** (the 65-verb counts are pinned in the tests and in 1008_actions.md; like the node verbs these live on their own registry until the flag is on by default).
* Prices: ask `ceil(value * f * 1.25)`, bid `floor(value * f * 0.6)` (never above the ask), keeper ask bounded `0.5R..3R`. Daily: `f = clamp((demand+1)/(supply+1), 0.5, 3)`, demand = units bought + unmet (x a settable shock), supply = units sold to stalls + stall stock / 3 + a tenth of the food standing in the resource nodes; smoothing 0.3.
* Ladder `buy` rung between work and trade (threshold 0.15; built only while the flag is on): cheapest affordable edible at the nearest known stall; cannot pay -> sell a surplus stack first; nothing on the shelf or too dear -> recorded as unmet demand, 300-tick cooldown. `actions/market_day.py` runs from `AgentDriver.step`: the daily update plus the keepers' repricing (a roster record binds `stall`; temperament `greed`/`mercy` moves the ask; an errand walks the keeper to the stall).
* Scenario `s1_family_farm --variant market [--shock-at T --shock F --day-ticks N]` (day 600): family with coin and no food, the neighbour's pantry is the stall; checks bought event, no theft, coin conserved, price follows the shock. Tests: `test_market_book` (pure), `test_market_verbs` (runner on the synthetic Scene), `test_market_ladder` (ordering + scenario in a fresh process).
* Not yet: refusal to sell to a known thief and gouging as reputation inputs (needs the keeper identity at the predicate; Observation rule), restocking the stall from the pantry by the keeper (the scenario stocks it), spoilage, caravans, a saved book, wages/credit (see 8.5).


## 9. Credit and labour (2026-10-09, model plane track; flags `EDEN_CREDIT`, `EDEN_LABOUR`, default off; need `EDEN_AGENT_ACTIONS`)
Both follow the rule used for requests and trades: **the asked resident decides by rules at op time, and a yes is a verb call by the asked resident through the same runner.** Books live on `services.__dict__` (runtime state only, like the offer and market books).

### 9.1 Credit (`systems/credit/`, `actions/credit_verbs.py`, `actions/credit_day.py`, `affordance/credit_predicates.py`)
* Verbs on `CREDIT_REGISTRY`: `borrow_item` (ask; op `loan_request`, the lender answers with `respond_to_loan` and on `lend` the runner runs `lend_item` as the lender, proposer `rules:loan_response`), `lend_item` (atomic Transfer + `loan_open`), `pay_debt` (Transfer + `loan_pay`, any item, part payments allowed).
* Terms: loans are denominated in value; a friend (closeness >= 0.4) is lent at par, anyone else owes +25%; term one game day, then a grace day. One open loan per borrower. Lender refusals: `refuse_distrust`, `refuse_thief`, `refuse_defaulter`, `refuse_busy`, `refuse_stranger`, `refuse_indebted`, `refuse_no_item`.
* Daily pass (`credit_day.step`, every `CREDIT_PERIOD` = 100 ticks from `AgentDriver.step`): overdue -> one note, closeness -0.05; after the grace day -> default, closeness -0.30 and a `defaulter` tag on the lender's relationship (a defaulter is refused by every lender and every employer). Repayment: a borrower with conscience > -0.1 and hunger < 50 who holds enough pays back (starts a `repay` errand if away from the lender; the errand follows the lender).
* Ladder: `borrow` rung (threshold 0.50, between beg and steal; built only while the flag is on; 400-tick cooldown).

### 9.2 Labour (`systems/labour/`, `actions/labour_verbs.py`, `affordance/labour_predicates.py`)
* Verbs on `LABOUR_REGISTRY`: `work_for` (op `job_request`; the employer answers with `respond_to_job`: `hire | refuse_distrust | refuse_thief | refuse_defaulter | refuse_busy | refuse_staffed | refuse_no_wage`) and `collect_wage` (op `job_close` + one atomic Transfer employer -> worker, `shift_not_done` before `ready_at`, `employer_cannot_pay` if the wage was spent).
* Terms: a shift is `WORK_TICKS` = 200, the wage is worth `WAGE_VALUE` = 2.0, paid in the food the employer holds most of beyond one kept unit, else coin; claim window `CLAIM_TTL` = 600 after the shift, then it lapses; one shift per worker, `MAX_WORKERS` = 2 per employer. Nothing moves at hire time (the wage stays in the employer's pack), so the employer can still fail to pay: that is the risk the worker takes.
* Ladder: `work` rung (threshold 0.20, first after forage; 300-tick cooldown). A yes starts a `labour` errand that follows the employer; `arrive` runs every tick while near, does nothing until `ready_at`, then calls `collect_wage`.

### 9.3 Tests and flag-off identity
`test_credit` (book, verbs on the Scene), `test_credit_day` (engine daily pass), `test_labour` (book, verbs, refusals, conservation), `test_labour_ladder` (engine). Flag off: both predicates return `not_wired` after the `_alive` check, no candidates, the registries are not added, `Ladder.built()` is unchanged; strict goldens and the s1 digests do not move.

### 9.4 Not yet
Collateral and interest compounding, wages posted by a stall keeper (employer objects with a fixed workplace), skill-dependent wages, a saved loan/job book (persistence), and justice/authority (section 4.3) with fines and the `rob` rung.

## 10. Justice by an authority (2026-10-09, model plane track; flag `EDEN_JUSTICE`, default off; needs `EDEN_AGENT_ACTIONS` and `EDEN_REPUTATION`)
Builds section 4.3 as far as the tree allows today: reports, a docket, forced restitution plus damages. **No violence**: an authority only collects (`arrest_or_restrain` and the `rob` rung wait for a bounded `defend` task, entry 8).

### 10.1 Objects and rules
* An **authority** is a resident whose roster record says `authority`, or whose occupation is `guard` or `elder` (`systems/justice/law.is_authority`). No authority in the village means the whole pass does nothing.
* `report_theft(target=authority, about=thief, item, qty, victim)` (`JUSTICE_REGISTRY`): legal only for a reporter who holds `about` as a `thief` (the tag `EDEN_REPUTATION` sets), in reach of the authority. The authority answers by rules at op time (`respond_to_report`): `accept | refuse_not_authority | refuse_conflict | refuse_distrust | refuse_busy | refuse_known_case`; a yes opens a case on the services' `Docket` (case value = item value x qty, `CASE_TTL_DAYS` = 2 game days). A false report is possible (the authority cannot check the item), which is the point of keeping the answer a rule a model can later override.
* `levy_damages(target=thief)` is the authority's own verb: legal with an open case against the thief, in reach. The damages are `1.5 x` the case value (`law.COMPENSATION`), taken from the thief's pack as one atomic set of Transfers to the victim: the stolen item first, then coin, then other goods by value; **never the thief's last unit of food**; limited by the victim's room. Outcome `paid | part_paid | nothing_to_levy`, the case closes either way. Closeness: thief -> authority drops, victim -> authority and victim -> thief rise a little.
* Both verbs sit on `JUSTICE_REGISTRY` (added by `default_registry()` while the flag is on); flag off: `not_wired`, no candidates, `Ladder`/driver untouched.

### 10.2 The pass (`actions/justice_day.py`, every `JUSTICE_PERIOD` = 100 ticks from `AgentDriver.step`)
1. Lapse cases past their expiry (event `case_lapsed`).
2. For each theft with a known culprit that is discovered, not restituted and not yet reported: the victim (else the first knower who is free) reports it to the nearest authority unless its temperament is `retaliate` (`Ladder.start_report`: in reach it reports now, else a `report` errand follows the authority).
3. Each open case whose authority is free: `Ladder.start_enforce` (levy now if the thief is in reach, else an `enforce` errand follows the thief and `arrive` calls `levy_damages`).
The same pass can therefore report and levy in one go when all three stand together. Runtime state only (docket, reported set).

### 10.3 Tests and not yet
`test_justice` (law, docket, verbs and refusals on the Scene, conservation), `test_justice_day` (engine: report, errands, lapse, no authority). Not yet: fines paid to a common chest or a treasury, exile and imprisonment, laws per crime (only theft), appeal, an elected or appointed authority, bribery, penalties for false reports, a scenario variant in `s1_family_farm`.

## 11. The `commons` scenario (2026-10-09; `model_server/s1_commons.py`, test `tests/test_commons_scenario.py`)
All four flags on (`EDEN_MARKET`, `EDEN_CREDIT`, `EDEN_LABOUR`, `EDEN_JUSTICE`, plus `EDEN_REPUTATION`) on the authored `family_farm` map, deliberately messy: the bushes and the family's food are gone (blight), the family starts at hunger 80 (Mara 40), the stall holds 2 rations and Orrin carries 4, a demand shock (x3 on rations) hits at tick 1200, game days are 600 ticks.
* `neighbour_orrin`: stall keeper, employer, lender. `neighbour_elsa`: the guard (`roster.authority`) *and* a customer (hungry, 6 coin, no food). `family_mara`: honest debtor (owes Orrin one ration, conscience high, coin 3). `family_tomas`: defaulter and thief (owes Elsa one ration, conscience low, closeness 0.1). `family_lina`: the worker.
* Run: `python -m model_server.s1_commons --seeds 1008,1,2 --repeat --ticks 4000` (one fresh process per run; a table at the end; `--repeat` runs the first seed twice for the determinism digest). The seed sets the world's deterministic draws (`EDEN_SEED`) and, except 1008, a +-6 jitter of the starting hunger.
* Checks: nobody dies; no silent starvation (hunger past 90 with no ladder entry in the last 800 ticks); no errand left standing past its expiry; no deadlock (actions still happen in the second half); coin conserved and no item created; no errors.

| seed | digest | dead | peak hunger | thefts | cases / levied | loans opened / repaid / defaulted | shifts hired / paid | stall sales | pass |
|---|---|---|---|---|---|---|---|---|---|
| 1008 | 2fbbeae222e2dbd0 (identical on the repeat) | 0 | 90.0 | 1 | 1 / 1 | 2 / 1 / 1 | 8 / 6 | 2 | yes |
| 1 | 506087d6cd7c03b7 | 0 | 90.0 | 0 | 0 / 0 | 2 / 1 / 1 | 9 / 7 | 2 | yes |
| 2 | 0c1caa5f808ab31f | 0 | 90.0 | 1 | 1 / 1 | 2 / 1 / 1 | 8 / 6 | 2 | yes |
| 3 | a346757a68219f68 | 0 | 90.0 | 1 | 1 / 1 | 2 / 1 / 1 | 10 / 8 | 2 | yes |

What it shows, and what it does not:
* Peak hunger 90.0 is the Tier 0 last-resort ration floor (`LADDER_TIER0_HUNGER = 90`, D2), not a coincidence: the family sits at the floor for most of the run and is kept alive by it. `EDEN_LADDER_STARVE=1` removes the floor.
* The chain works end to end: Tomas defaults (overdue, then `defaulter`; later employers and lenders answer `refuse_defaulter`), steals, the neighbour who finds out and holds him as a thief reports to Elsa, Elsa walks to him and levies (`part_paid`: he keeps his last food), Mara repays Orrin. Most `work_for` asks are answered `refuse_no_wage` (22-31 per run): in a scarce village few employers can pay, which is the realistic outcome and the reason shifts are paid in coin as often as in food.
* Seen while building it, not yet changed: borrowing is rarely reached (the ladder gets relief from work, begging and trade first), `borrow_item` is mostly refused for `refuse_stranger` / `refuse_no_item`, and a thief watched at a container retries `steal_when_safe` many times (`illegal:watched`, capped per errand by `WATCHED_WAIT` but hundreds of calls over a run).


## 12. Economy balance as built (2026-10-10; ECONOMY-BALANCE-1010)

Default-off EDEN_ECONOMY_BALANCE enables checked household farm harvesting of existing farm food into declared crop bundles, and keeper collection of earned stall coins with a two-coin float. The shared roster-needs gate retains water trips while preventing incidental free food below the unchanged emergency threshold when the balance flag and ladder are on. Production rates, prices, wages, initial stocks, calendar rates and emergency thresholds are unchanged.

Four commons seeds (1008/1/2/3), each4,000ticks, have no deaths and conserve coin. Actual food-ration calls total2/2/1/2 are all early emergency calls, ending before tick288; every last1,000tick tail has zero food calls, with peak tail hunger35.00/34.36/44.97/34.00. Seed1008 repeats digestced1b2bc7e8e6693. Flag-off all four historical digests and repeat are unchanged.78 focused tests and four strict golden profiles pass in immutable base-plus-owned-source archives. Final source hashes match the working tree.

This proves the measured scenario feeds itself after bootstrap, not indefinite irrigation or general-world/long-calendar sustainability. Keeper withdrawal behavior is unit-tested but these seeds record no collection routes, so wage improvement is not attributed to such withdrawals. Full clean integration suite remains pending. Exact commands, hashes and results: coordination_evidence/codex_1010_r63_report.md and r63_fixed_* manifests/JSON/logs. No defaults, golden fixtures, save formats or open decisions changed.
