# 1008 expansion proposals: tools, instincts and the systems behind them

This is the user's file of suggested expansions. It is a proposal list, not a commitment: nothing here is built unless a later assignment says so.
Each entry says what it adds, which existing systems it builds on, the state it needs, the verbs / tools / instincts involved, cost and risk, the role of
Tier 1 (rules / matrix macro choice), Tier 2 (DecisionService choice among legal options) and Tier 3 (plans), a priority and its dependencies.
Everything is written against the code as it is on branch `1008implementation` (HEAD at the time of writing: f4af803).

* **Part 1 (this part, Model plane): verbs, tools, economy and social systems.**
* **Part 2 (Harness plane): instincts, nature / world systems, god tools.** The Harness worker appends it below the marker at the end of this file.

## 0. How to read the entries

**What exists to build on (verified in the tree, not assumed):**

| Layer | Where | What it gives an expansion |
|---|---|---|
| Event ledger | `harness/events.py` | Every effect that matters is an event with id, place, visibility and **witnesses**. `Emit(event_id=...)` is idempotent and only adds witnesses: this is how news spreads (`share_news`, `gossip`). No subscribers are registered yet: the ledger is a record, not yet a reaction bus. |
| Action runner | `systems/actions/` | One path for every tier: schema, grounding, legality, rate and risk gate, atomic apply, record ops, audit. 30 of the 65 catalog verbs are implemented after batch 2, plus the three resource-node verbs. New verbs are data + one predicate + one Action. |
| Affordance engine | `systems/affordance/` | Legality is a pure function of one resident's observation (it never reads another resident's pack or memory). Tier 1 macro menu with a mask. |
| Resident records | `runtime/resident_store.py`, `systems/{goal,schedule,tasks,planning,memory,personality,occupation,health}` | Goals with priority, schedule routines, task queue, plans, memory (`recent_events`, `last_threats`, known food and water sources), 16 personality traits (`aggression, caution, vengefulness, greed, loyalty, mercy, pride, fearfulness, curiosity, ambition, deceitfulness, protectiveness, sociability, discipline, resourcefulness, resolve`), relationships with closeness and tags, occupation. |
| Items | `systems/inventory`, `harness/items.py` | Item kinds with `value`, conserved by atomic `Transfer`; creation and destruction need a declared `ItemPermit`. `coin` is an ordinary item. |
| Commission loop | `systems/commission` | The one existing economy: order, escrow, price table (`COMMISSION_CONFIG["prices"]`), the smith decides. |
| Map resources | `systems/map/resources.py`, `harness/resources.py` | Resource nodes with stock, regrowth, depletion events (flag `EDEN_MAP_RESOURCES=1`). |
| Roster / agent drivers | `systems/roster`, `systems/actions/agent_driver.py` | Tier 0 needs trips, Tier 1 macro scorer (rules or matrix), actions through the runner (flag `EDEN_AGENT_ACTIONS=1`). |
| Health, nature, combat, construction, crafting, talk, perception | `systems/*` | Wounds, infection, recovery; weather, hazards, disasters; combat; building and repair; recipes and stations; dialogue sessions; perception queries. |

**Priority:** P1 = next, needed by the first full-village scenario; P2 = valuable once P1 exists; P3 = later / optional. **Cost:** S / M / L / XL relative to one
verb batch (S = about a day of work, M = a few days, L = a week, XL = several weeks). **Risk:** what can go wrong (determinism, tick budget, balance, save format).

**Rules every entry follows (so they can ship behind flags):**
1. A flag, default off; with the flag off the strict golden (`tools/golden_trace.py --check --strict`) stays bit-identical.
2. State lives in resident records or a small non-saved runtime object with a documented save story; nothing is added to the tensors without a Harness-plane decision.
3. A predicate may only read the actor's own observation (the "Observation rule"). What other residents hold, know or feel is judged by their own rules at op time or by the Action.
4. Every consequence is a ledger event, so it can be witnessed, remembered, gossiped about and audited.
5. Rules first, then the matrix, then the model: Tier 1 rules must run the scenario alone (no model, no network); Tier 2 / 3 only widen the choice.

---

## Part 1: verbs, tools, economy and social systems (Model plane)

### 1. The escalation ladder of getting food (survival economics) - P1, M
* **Adds.** A rules-driven order of ways to meet a need, ordered by cost and moral weight: forage, work for food, beg (`request_item`), trade (`offer_trade`), borrow (debt), steal (`steal_when_safe`), rob (`attack` + take). A resident moves down the ladder as desperation rises and the cheaper rungs fail or are unavailable; personality and family set how far down it will go.
* **Builds on.** Tier 0 needs trips, `eat_from_node` / `gather_from_node` / `approach_node`, `request_item`, `offer_trade`, `steal_when_safe`, goals (`hoard_food`, `protect_kin`), personality traits, relationships.
* **State.** Per resident, non-saved: the rung currently tried, a per-rung cooldown and failure memory (who refused, which node was empty). Saved in the record: `desperation` is derived, not stored.
* **Desperation score (derived each decision).** `d = max(hunger, thirst) / 100`, plus 0.2 if the pack holds no edible, plus 0.15 per dependent (child, spouse) that is hungry, minus 0.1 for each rung that succeeded recently. Rung thresholds: forage 0.0, work 0.2, beg 0.4, trade 0.35, borrow 0.5, steal 0.65, rob 0.85, each shifted by the personality term `c = 0.35*mercy + 0.25*loyalty + 0.25*discipline - 0.35*deceitfulness - 0.25*greed - 0.2*aggression` (a high-conscience resident needs a higher `d` to steal; a low one steals earlier) and by `+0.15 * protectiveness` when a dependent is the one starving (family hunger lowers the barrier).
* **Gates for steal / rob.** No food in the pack, forage and beg and trade failed or are unavailable (nothing in range, no node with stock, everyone refused in the last N ticks), a target that holds an edible (known from what the resident has seen: it saw them eat, store, carry), the witness rule (nobody within help range for steal), and a risk estimate (`risk = P(caught) * (fine + relationship loss)` against `d`).
* **Tiers.** Tier 1 rules own the ladder (a pure function of the observation + record, deterministic). Tier 2 may re-order rungs among the legal ones (a model can decide to beg a friend instead of stealing). Tier 3 can plan a multi-step approach (walk to the storehouse at night). The ladder is the default when no model is present.
* **Verbs / tools.** Existing: `gather_from_node`, `approach_node`, `request_item`, `offer_trade`, `steal_when_safe`, `attack`. New: `borrow_item` (a request that creates a debt, see 3), `work_for_food` (task: `work_shift` for a payer in kind, see 2).
* **Cost / risk.** Balance (too much stealing empties a village; calibrate against the scenario), tick budget (the ladder runs on the decision cadence, not every tick).
* **Depends on.** Nothing new for rungs forage / beg / trade / steal (all exist). Reputation (4) for the consequences.

### 2. Market, prices and supply / demand - P1, L
* **Adds.** A real market so `buy`, `sell`, `set_price` mean something: shops and stalls with a stock and a price list, prices that move with scarcity, and barter where no currency exists.
* **Builds on.** Item `value` table, `coin` item, commission prices, `OfferBook` (batch 2: swap with a rules answer and a fairness test), `trade_run` task (a trader route), occupation (smith, farmer, trader), storage containers.
* **State.** `Market` object per settlement (a map entity or an area of the map): `{stall_id, owner, stock, prices, ledger of sales}`; a per-item **reference price** = item `value` x a scarcity factor `f = clamp((demand_ema + 1) / (supply_ema + 1), 0.5, 3.0)` updated daily from sales, stock levels and the unmet requests observed at the market. Saved in the world state beside inventories. Barter ratio = reference price ratio, so `offer_trade` and the market share one price source.
* **Verbs.** `buy(T, item, qty)`, `sell(T, item, qty)`, `set_price(item, price)`, `pay_debt` (see 3) become real; `haggle(T, offer)` (a counter-offer through the offer book, closeness and `greed` shift the margin); `open_stall` / `close_stall` (a shopkeeper's routine). Predicates `can_buy` (a stall in reach, enough currency), `can_sell` (a buyer or a stall that buys), `owns_shop`.
* **Instincts / tools.** A daily `market_update` system (the Harness plane registers it): reference prices from supply and demand. A god tool `set_scarcity` (see Part 2) to test shocks.
* **Tiers.** Tier 1: shopkeepers keep a stall open on their routine and restock; buyers buy when they lack an edible and have currency. Tier 2: choose which stall or which price to accept. Tier 3: trade circuits ("buy low at the farm, sell high in the village").
* **Cost / risk.** Currency sinks and sources (a closed economy drifts: coin must have a source, e.g. wages for work, and sinks, e.g. taxes and fines), price oscillation (damp the EMA), save format (new object).
* **Depends on.** Item store (exists), occupation (exists), coin policy decision (currency or barter), 3 (credit).

### 3. Debt, credit and lending - P2, M
* **Adds.** Promises that outlast the moment: borrow food or coin, repay later, interest or favour, default consequences.
* **Builds on.** `pay_debt` (catalog verb, predicate `has_debt`), `request_item`, relationships, `give_item`, the commission escrow (precedent for held value).
* **State.** `debts` list in the resident record: `{creditor, debtor, item, qty, due_tick, interest, origin_event}`; each is mirrored by a ledger event `debt_created`.
* **Verbs.** `borrow_item` (a request that the lender may grant as a loan), `lend_item`, `pay_debt`, `forgive_debt` (an act of mercy: closeness up), `demand_payment` (a social act with a threat of reputation loss).
* **Tiers.** Tier 1: repay when able and due, ask for forgiveness if not. Tier 2: choose whether to lend to a given asker (trust, kinship). Tier 3: debt-clearing plans.
* **Cost / risk.** Small. Unbounded debt chains (cap the number of open debts per resident), bookkeeping on death (inheritance, 9).
* **Depends on.** 2 for coin; reputation (4) so a defaulter is known.

### 4. Theft, reputation, justice and law - P1, L
* **Adds.** Consequences for harmful acts, so stealing is a decision and not a free action: the victim and witnesses know, opinions drop, the story spreads, the community answers.
* **Builds on.** The ledger (witnesses), `steal_when_safe` (now writes a private `theft` event), `share_news` / `gossip` (witness spreading + opinion shift), relationships (closeness, tags such as `rival`), goals (`retaliate`, `protect_kin`), `attack` / `report_crime` / `arrest_or_restrain` / `avoid` / `warn` verbs, personality (`vengefulness`, `mercy`, `pride`).
* **State.** `reputation` per (observer, subject) is **derived** from relationships and known events, not a global score: each resident forms its own opinion from what it witnessed or was told. Record fields: `known_crimes` (event ids with the culprit), `grudges` (a decaying hostile closeness), `restitution_owed`. A village-level `law` object (for justice): `{crime kind -> penalty, authority ids}`.
* **Loop (design).** (1) A theft is witnessed or discovered. Witnessed: a `theft` event with visibility `local`, so witnesses know the thief; unwitnessed: the owner finds the item missing (event `loss_discovered`, culprit unknown) and may suspect by opinion. (2) Each knower: opinion of the thief drops (closeness delta scaled by item value, relationship, and `mercy`), a memory entry. (3) `gossip` / `share_news` spread it with decay; each retelling is a new witness of the same event. (4) Responses by personality: `avoid` the thief, `warn` kin, confront (`warn` / `threaten`), `retaliate` (vengeful), `report_crime` to an authority, restitution demand. (5) Authority (guard, elder) acts by the law object: `arrest_or_restrain`, fine, forced restitution, banishment (a `settle_site` / travel restriction). (6) Resolution: `apologise`, `pay restitution`, `forgive` (closeness recovers slowly, a "forgiveness over time" half-life of about a game week). (7) Repeat offenders are marked (`tags: thief`), which changes how others trade with them (higher fairness threshold, refusals).
* **Verbs.** Existing: `warn`, `avoid`, `attack`, `report_crime`, `arrest_or_restrain`, `apologise`, `forgive`, `retaliate`, `gossip`. New: `confront` (a talk act with a demand), `demand_restitution`, `punish` (an authority act, bounded), `exile` (law).
* **Instincts.** `instinct_grudge_decay` (daily closeness recovery toward neutral), `instinct_theft_discovery` (an owner noticing a missing stack), `instinct_justice_patrol` (a guard's routine). These are Part 2 candidates.
* **Tiers.** Tier 1: the whole loop by rules (deterministic, from traits). Tier 2: the model decides *how* to respond to a known theft among the legal options. Tier 3: revenge or reconciliation plans.
* **Cost / risk.** Cascading violence (cap retaliation chains with `resolve` and a cooldown), false accusations (suspicion from opinion creates wrongful blame: a feature if bounded), tick cost (opinion updates are event-driven, not per tick).
* **Depends on.** The ledger subscribers (a minimal one: "opinion on witnessed harmful event"), 1 (the ladder produces the theft), authority roles (11).

### 5. Rumours and news - P2, M
* **Adds.** Information that travels, decays and distorts: a resident acts on what it has heard, not on ground truth.
* **Builds on.** `share_news`, `gossip` (batch 2), ledger witnesses, memory (`recent_events`), the talk system.
* **State.** For each told event: `heard_from`, `heard_at`, `confidence` (1.0 for a witness, x0.8 per retelling hop, decays with age). A "rumour" is a ledger event known second-hand.
* **Verbs / tools.** `share_news`, `gossip` (done); `ask_about(T, subject)` (query), `deny` / `spread_lie` (a deceitful resident invents or distorts: creates a `claim` event flagged false, with `deceitfulness` as the gate), `warn_group`.
* **Tiers.** Tier 1 rules: tell the most recent unknown event to a friend when idle; Tier 2: choose what to tell; Tier 3: a smear or reputation-repair plan.
* **Cost / risk.** Memory growth (retain a bounded number of heard events), manipulation by lies (needs trust modelling: weigh by closeness).
* **Depends on.** 4.

### 6. Family, kinship, marriage and inheritance - P2, L
* **Adds.** Households as the unit of need: dependants raise desperation, family shares food, marriages and births structure the village, death passes property on.
* **Builds on.** `systems/social/mating.py`, `grouping.py`, relationship `family` kind, `protect_kin`, `court` / `befriend` verbs, `child_birth` / `born_to_parent` events (already referenced by the resident store), `kinship` data in the roster.
* **State.** `household` id and `kin` links (parent, child, spouse, sibling) in the record; a shared **household pantry** (a container entity owned by the household); `will` (heirs in order) and `property` (owned containers, tools).
* **Verbs.** `court`, `propose`, `marry` (a ritual, see 14), `feed_dependant`, `share_with_household`, `bequeath`, `adopt`. Tools: `assign_heir` (resident), a god tool `set_kin` (Part 2).
* **Tiers.** Tier 1: households pool food, adults feed children first, spouses share; Tier 2: courtship choices; Tier 3: long plans (build a home, save for a marriage).
* **Cost / risk.** Large state surface, save-format change for households, genealogy bugs (cycles). Do this after the market so property has meaning.
* **Depends on.** 2, 3, 12 (professions inherit), 4 (family feuds).

### 7. Education, skills and apprenticeship - P2, M
* **Adds.** Skills that grow with practice and can be taught: better crafts, faster gathering, safer work.
* **Builds on.** `teach` verb (catalog), occupation, crafting recipes (station and ingredient checks), `skill` hooks in work tasks.
* **State.** `skills` map in the record `{skill: level 0..1}`, practice counters, a teacher link for an apprentice.
* **Verbs.** `teach(T, skill)` (the learner gains faster while the teacher is near), `practise`, `apprentice_to(T)`, `certify` (a guild act, see 8).
* **Effects.** Level scales craft yield and time, node-gather quantity, success of risky acts (hunting, treating a wound), and the price a resident can ask.
* **Tiers.** Tier 1: practise the occupation, teach a young kin the family trade; Tier 2: choose a teacher; Tier 3: a training plan.
* **Cost / risk.** Balance; saved state is small. Low risk.
* **Depends on.** 12 for guild-granted levels (optional).

### 8. Professions, guilds and labour - P2, M
* **Adds.** Occupations with demand, wages and institutions: work for pay, shared standards, mutual aid.
* **Builds on.** `systems/occupation` (catalog, assign, inheritance), `work_shift`, the commission loop (a smith being paid), `trade_run`.
* **State.** `job` (employer, wage in kind or coin, shift), `guild` membership with dues and benefits (loan fund, shared forge).
* **Verbs.** `hire(T, task, wage)`, `accept_job`, `quit_job`, `pay_wage`, `join_guild`, `pay_dues`, `post_notice` (a demand board that Tier 1 reads).
* **Tiers.** Tier 1: hire help when the work backlog is large, work for food when starving (ladder rung 2); Tier 2: pick a job; Tier 3: career plans.
* **Cost / risk.** Wage balance; employers who cannot pay (escrow like the commission loop avoids it).
* **Depends on.** 2, 3.

### 9. Health, medicine and care - P2, M
* **Adds.** Care as an economy: sickness spreads, healers treat, medicines are made and sold; caretaking as a social duty.
* **Builds on.** `systems/health` (damage, infection, recovery, status), `treat_wound` and `comfort` verbs, `bandage` item, herb nodes, `heal_work` task.
* **State.** Status effects already exist; add `care_request` events and an `infirmary` area.
* **Verbs.** `treat_wound`, `diagnose`, `brew_remedy` (craft), `quarantine`, `visit_sick` (a social act that raises recovery and mood), `ask_for_help` with a medical reason.
* **Tiers.** Tier 1: a healer answers care requests; family nurses kin; Tier 2: which patient first when several; Tier 3: epidemic response plans.
* **Cost / risk.** Epidemic balance (infection + disasters can wipe a village), tick cost of infection updates (already event-ish).
* **Depends on.** 2 (medicine as a good), 6 (family care).

### 10. Hospitality, shelter and charity - P2, S
* **Adds.** Strangers and the poor are housed and fed by custom: it gives the ladder a non-criminal rung and a social obligation that reputation rewards.
* **Builds on.** `invite` verb, beds / shelter anchors, `give_item`, `comfort`, relationship `known` / `friend`.
* **State.** `hosting` list (guest, until tick), `charity_given` counters for a generosity reputation.
* **Verbs.** `invite`, `offer_shelter`, `share_meal` (give + closeness), `accept_hospitality`, `donate(item)` to a communal store.
* **Tiers.** Tier 1: a resident with surplus food and `mercy` above a threshold gives to a hungry neighbour (the `help` macro already routes `give_item`); Tier 2: choose recipients; Tier 3: a feast plan.
* **Cost / risk.** Very small. Needs the reputation system to make generosity count.
* **Depends on.** 4.

### 11. Authority, governance and laws - P3, L
* **Adds.** Roles that act on crime and disputes (elder, guard, judge), rules the village agrees on, taxes and public works.
* **Builds on.** `holds_authority` predicate (catalog), `arrest_or_restrain`, occupations (guard exists in the patrol task), the law object of 4.
* **State.** `role` in the record, a `law` table per settlement (crime -> penalty, tax rate), a public store.
* **Verbs.** `decree`, `collect_tax`, `judge(case)`, `punish`, `pardon`, `vote` (a council act).
* **Tiers.** Tier 1: guards patrol and answer `report_crime`; Tier 2: the judge decides among legal penalties; Tier 3: law reform plans.
* **Cost / risk.** Complexity (politics), runaway tyranny (cap penalties; the god plane can override).
* **Depends on.** 4, 2 (taxes), 8.

### 12. Property, ownership and containers - P1, M
* **Adds.** Things belong to someone, so stealing, lending, inheritance and rent have a meaning: today an item is just in an inventory.
* **Builds on.** Containers (`storage`, `chest`, `crate`), `store_item` / `fetch_item`, `steal_when_safe` (container variant), structures from `systems/construction`.
* **State.** `owner` and `access` (public / household / owner only) on each container and structure; a `key` item optional.
* **Verbs.** `lock` / `unlock`, `claim`, `lend_tool`, `rent`, `transfer_ownership`. Predicates for `fetch_item` and `steal_when_safe` read the access rule (taking from your own household chest is not theft).
* **Tiers.** Tier 1: residents use their own storage; Tier 2: choose where to store; Tier 3: housing plans.
* **Cost / risk.** Small data, wide effect on the semantics of existing verbs: the "is it theft?" test depends on it (needed by 4).
* **Depends on.** Nothing. It is a prerequisite of 4 in its full form; a minimal "owner" field is enough for the first scenario.

### 13. Weather, season and calendar effects on behaviour - P2, M
* **Adds.** Behaviour that follows the year: harvest, scarcity in winter, rain keeps people home, festivals, sleep length.
* **Builds on.** `systems/nature/weather.py`, `hazards`, `disasters`, the schedule's time blocks, regrowth rates of nodes.
* **State.** A `season` clock (the engine day length is 2400 ticks; a year is a configurable number of days), seasonal multipliers for node regrowth, hunger rate, clothing need.
* **Tools / instincts.** `instinct_season_update` and a weather-driven `shelter_pressure` (Part 2 candidates); a god tool `set_season`.
* **Verbs.** `store_for_winter` (haul items to a pantry), `plant` / `harvest` (farm tasks become seasonal), `put_on_clothing`.
* **Tiers.** Tier 1: the schedule shifts with season; stockpile when winter nears (`hoard_food` goal priority rises); Tier 2: choose between travel and shelter in bad weather; Tier 3: a migration plan.
* **Cost / risk.** Balance of regrowth vs hunger across seasons (scarcity is what drives the ladder; tune with the scenario).
* **Depends on.** Part 2 (nature systems), 2 (storage / prices).

### 14. Religion, ritual and festivals - P3, M
* **Adds.** Shared meaning: rituals at fixed times, a shaman or priest, beliefs that bias behaviour, festivals that gather people and move goods.
* **Builds on.** Schedule routines, `invite`, the talk system, the personality traits (`discipline`, `loyalty`), `settle_site`.
* **State.** `faith` (belief set) in the record, a `shrine` entity, a calendar of festivals.
* **Verbs.** `pray`, `attend_ritual`, `officiate`, `sacrifice(item)` (a bounded item sink), `bless`.
* **Tiers.** Tier 1: attend the ritual on the schedule, a priest officiates; Tier 2: dilemma choices; Tier 3: pilgrimage plans.
* **Cost / risk.** Content-heavy rather than code-heavy; avoid claiming real-world doctrine, keep it as in-world custom.
* **Depends on.** 13 (calendar), 6 (marriage rite).

### 15. Travel, caravans and inter-settlement trade - P3, L
* **Adds.** Goods and news move between settlements; travellers arrive with things to sell and stories.
* **Builds on.** `trade_run` task (basic trader route), P4 / P5 window and chunk worldgen (more than one settlement), `explore_toward` and `approach_node`, portals, `lead_group_to` / `migrate_group` verbs.
* **State.** `caravan` (members, cargo, route, schedule), per-settlement `market` (2).
* **Verbs.** `join_caravan`, `lead_caravan`, `guard_caravan`, `haggle`, `arrive_at_market`.
* **Tiers.** Tier 1: a trader loops between two markets; Tier 2: choose routes by price difference; Tier 3: route planning with risk (bandits).
* **Cost / risk.** Long walks across window rebases (the position-holder scan handles it), bandit balance (links to `rob`).
* **Depends on.** 2, the window / chunk work, 4.

### 16. Craft, tools and durability - P2, M
* **Adds.** A fuller production chain (ore to ingot to tool), tool wear, repair, and demand that feeds the market.
* **Builds on.** `systems/crafting` recipes and stations, `systems/health/durability.py`, `repair` verb, `craft` Action (consumes + produces under a permit), commission loop.
* **State.** Tool durability on items (a count in the stack metadata), recipe unlocks by skill (7).
* **Verbs.** `craft` (done), `repair`, `smelt`, `salvage`, `sharpen`.
* **Tiers.** Tier 1: craft what is in demand at the stall; Tier 2: choose recipes; Tier 3: production plans.
* **Cost / risk.** Recipe data volume; conservation (every recipe declares its inputs and outputs, enforced by the permit).
* **Depends on.** 2, 7.

### 17. Crime beyond theft and personal safety - P2, M
* **Adds.** Assault, robbery, vandalism, poaching and their deterrents (guards, locks, groups travelling together).
* **Builds on.** `attack`, `retaliate`, `PLOT`, `ambush` plans, combat system, the theft loop (4).
* **Verbs.** `rob(T)` (threat + take), `ambush`, `vandalise`, `poach`, `flee_to`, `defend`.
* **Tiers.** Tier 1: a desperate, low-conscience resident may rob at the bottom of the ladder; Tier 2: choose victims; Tier 3: heist plans.
* **Cost / risk.** Violence escalates fast; every violent act is destructive (D-3 risk gate) and leaves a witnessed event.
* **Depends on.** 1, 4, the missing `defend` task.

### 18. Information tools for models (Tier 2 / 3 support) - P1, S
* **Adds.** The macro menu and its legal options turned into a compact decision request, and per-resident summaries (needs, ladder rung, reputation, debts) a model can read.
* **Builds on.** `AffordanceEngine.options`, `decision` module (matrix, features), `DecisionService`, the Tier 3 plan parsers and gates.
* **Verbs / tools.** `DecisionRequest` builder for the macro menu (planned), `explain_options`, `why_refused` (audit codes to text).
* **Cost / risk.** Prompt size; keep it to the top-k legal options.
* **Depends on.** Nothing new. It is the Tier 2 deliverable of this stage.

---

## Dependency order (Part 1)

1. **12 Property** (minimal owner field) and **2 Market** (barter + reference prices first, currency second): the world has to say what is whose and what things cost.
2. **1 Escalation ladder** and **4 Theft / reputation / justice (the loop up to gossip, avoidance, retaliation and restitution)**: the first scenario that needs both is S-1 on `family_farm`.
3. **18 Tier 2 request builder**, **5 Rumours**, **3 Debt**, **10 Hospitality**.
4. **7 Skills**, **8 Professions / guilds**, **16 Craft chain**, **9 Health care**, **13 Seasons**.
5. **6 Family / inheritance**, **17 Other crimes**, **11 Governance**.
6. **14 Religion**, **15 Caravans**.

## Open choices for the user

* Currency or barter first (recommended: barter with reference prices, then coin as one more item with a source and sinks).
* How harsh the community response to theft is (recommended: opinion + avoidance + gossip first; physical retaliation only for vengeful, low-mercy residents; guard / exile later).
* Whether a village needs an authority before the first market scenario (recommended: no, an elder role arrives with 11).

---

## Part 2: instincts, nature and world systems, god tools, infrastructure, engine implications (Harness plane)

<!-- Harness plane (837dca) section. Model plane: do not edit below. -->

### 2.0 What is true today (verified in the tree on 2026-10-08, HEAD a66ea86)

* **Instincts.** `instincts_and_tools.py` defines 46 `instinct_*`. The full-suite call trace (`1008_coverage_map.md`, `harness/coverage_map.py`, 831 tests) shows **25 called, 21 never called**. (The brief for this section said 25 never exercised; the measured split is the other way round.) The 25 called are the per-tick core: age, hunger, thirst, stamina, emotional recovery, die, hp death, heal, shelter check, structure occupancy, cooldown, infection, nature cycle, fire, lava, move, incarnation, player-control override, plus the creators the genesis and the god tests reach (`create_object`, `create_scattered_objects`, `born`, `attack` once, directly). The **21 never called**: `populate_animals`, `update_objects`, `retype_objects`, `create_line_objects`, `relocate_animals`, `designate_construction_site`, `gather_materials`, `build_with_humans`, `repair_with_humans`, `demolish_with_humans`, `find_buildable_site`, `proximity`, `flee`, `search`, `reproduction_strategy`, `survival_navigation`, `social_navigation`, `schedule_navigation`, `pairwise_relations`, `eat`, `drink`. Several of them are legacy duplicates of the task families (`eat`/`drink`/`gather_materials`/`build_*` are now done by `systems/tasks` and the action runner); calling a function is not the same as it mattering, so the entries below say which to wire, which to retire.
* **Tools.** 74 `tool_*`. The tests call 4. **10 are ported** as declared `Power`s with dry-run and events (`harness/powers.py`: `set_mood`, `plague`, `bless`, `calm_area`, `panic_area`, `baby_boom`, `cull`, `enlighten`, `bounty_area`, `scarcity_area`) and 4 Stage-1 god powers exist separately (`systems/god/powers.py`: `heal`, `spawn_resource`, `set_weather`, `time_control`). **64 legacy tools remain unported** (listed and ranked in 2.C).
* **Time and seasons.** `TICKS_PER_YEAR = 600` (30 s of wall time per year at 20 Hz). `season_for_tick` splits the year in quarters; each season and each of 8 weather kinds carries multipliers for three quantities only: `food_growth`, `water_growth`, `farm_growth` (`systems/nature/weather.py`). Weather also plans and executes extreme events (flood, storm, drought, wildfire, earthquake). **A coarse day exists, only in the Model plane's schedule:** `DEFAULT_DAY_LENGTH_TICKS = 2400` (`systems/schedule/resolver.py`) and `tick_to_time_block` split it into four equal blocks `dawn / day / dusk / night` (600 ticks each); schedule routines, `roster/driver.py` and `systems/actions/recordops.py` use the block, and the Tier 1 feature builder has one `night` feature (1.0 night, 0.5 dusk, else 0; `systems/decision/features.py`). The day is not tied to the year: the year is 600 ticks, exactly one schedule block, so **one schedule day spans four seasonal years** (2400 / 600). Nothing in the engine reads a light level or an hour; needs, ageing and weather are not clocked by the day. (First draft of this section said there was no day concept; that was wrong, corrected after reading the schedule module.)
* **Columns.** Both tensors have 32 columns. Humans: 0..24 used, 25..28 hold the extra acquired-instinct mask words, 29 is `H_SPACE`; **only 30 and 31 are free**. Entities: `M_GEN` (30) and `M_SPACE` (31) are taken; the node columns 13..16 overload other types' columns by type. A new per-tick scalar per resident therefore cannot just "get a column" (see 2.E).
* **Ledger.** Every power returns an `Emit` event with witnesses; resident memory, goals and gossip subscribe to events. This is the mechanism all entries below use to make a world change matter to someone.

**Conventions in this part.** Same entry fields as Part 1 (what it adds, builds on, state, verbs / tools / instincts, cost / risk, tier roles, priority, dependencies). Cost scale S/M/L/XL and priorities P1/P2/P3 as defined in section 0. "Tier 0" is deterministic per-tick code. Every instinct below is a registered, flag-gated, deterministic system that writes its consequences as events and never calls a model.

---

## 2.A Instincts

### 2.A1 Finish, wire or retire the 21 uncalled instincts - P1, M
* **Adds.** A decision for each dead function, so the legacy layer stops being a trap. Wire: `instinct_flee` (fear response, see 2.A3), `instinct_proximity` and `instinct_pairwise_relations` (the shared `cdist` pass the others should reuse), `instinct_search` and `instinct_survival/social/schedule_navigation` (the additive steering fields `instinct_move` sums; they are the force-field half of the one movement stack), `instinct_reproduction_strategy` (mate choice). Retire after parity tests: `instinct_eat`, `instinct_drink` (tasks do it), the `instinct_*_with_humans` and `designate/gather/find_buildable_site` set (construction verbs do it). Keep as god-only creators: `populate_animals`, `relocate_animals`, `update_objects`, `retype_objects`, `create_line_objects`.
* **Builds on.** `harness/coverage_map.py` (re-run after each step), strict golden (any wired instinct changes behaviour, so each lands behind its own flag with a new golden), `1008implementation.md` H.2 finding 7 (two movement systems).
* **State.** None new. The steering instincts read the same bias vectors `instinct_move` already sums.
* **Cost / risk.** M. Risk: wiring a dormant function changes the golden trace and population dynamics (reproduction, search); every step is flag-gated and gets its own golden. Retiring needs a parity test that the task-family path reproduces the old numbers, or an explicit note that it does not.
* **Tiers.** Tier 0 only. They are the physics the decision tiers act on.
* **Priority / depends.** P1 (it removes dead weight and unlocks A3). Depends on the coverage map, nothing else.

### 2.A2 Body and survival drives (the S-5 winter set) - P1, L
* **Adds.** Needs a real winter and a real night create, none of which exist now: `instinct_fatigue_sleep_pressure` (sleep debt that builds while awake and gates work, naps), `instinct_temperature_comfort` (cold and heat damage and mood from season, weather, clothing, fire and shelter), `instinct_wound_recovery` (bleeding, infection chance, healing rate; extends `systems/health` rather than replacing it), `instinct_darkness_unease` (night fear, needs 2.B1), `instinct_food_spoilage` (perishables lose value over time; storage and cold slow it), `instinct_boredom` and `instinct_loneliness` (feed mood and the explore and social goals).
* **Builds on.** `systems/health` (damage, infection, recovery), `systems/nature/weather.py` (season and weather already per tick), shelter (`H_SHELTER`, `instinct_shelter_check`, `structure_occupancy`), inventory item `value` (spoilage reduces it), goals.
* **State.** Per resident: `sleep_debt`, `body_temp` (derived from weather and clothing, one scalar), `wound` (bleeding rate) and the time since last social contact are **slow** values, kept in the resident record and updated on the decision cadence, not per tick; fast ones (`comfort` delta applied to mood and stamina) are applied by one vectorised pass over the aux tensor (2.E). Spoilage is a per-item timestamp in the inventory record.
* **Verbs / tools.** Verbs it makes useful: `sleep`, `rest`, `seek_shelter`, `light_fire`, `treat_wound`, `eat`. Tools: `set_temperature_offset` (god, 2.C).
* **Cost / risk.** L (six instincts, a clothing item class, fire as a heat source). Risk: balance (a hard winter that kills everyone is a bug, not a feature; tune with the scenario), tick budget (all run as masked tensor ops; target below 0.3 ms per tick together, to be measured), and determinism (no `random` in the per-tick path; use the counter-based RNG stream of 2.E).
* **Tiers.** Tier 0 applies all effects. Tier 1 matrix gets the derived features (`cold`, `tired`, `wounded`) and the legality of `sleep` / `seek_shelter`. Tier 2/3 only choose how (where to shelter, whether to risk the road).
* **Priority / depends.** P1 for temperature, sleep and wounds (scenario S-5 winter); P2 for boredom and loneliness. Depends on 2.B1 (day/night) for darkness unease and sleep timing, and on the aux tensor decision (2.E).

### 2.A3 Fear learning and the flight response - P1, M
* **Adds.** `instinct_fear_response`: threat level (`THREAT`) drives flee, freeze or hide by personality (courage, aggression), not only by a threshold. **Fear learning:** a place or a kind of creature where a resident was hurt becomes a remembered danger that raises the threat there next time (a wolf bite makes the forest edge at dusk feel dangerous). Uses `instinct_flee` from 2.A1.
* **Builds on.** `THREAT`, `CRITICAL_HEALTH`, `ESCALATION_FLAG`, memory (`remember_threat` already stores positions), the escalation system (`systems/escalation`), personality traits.
* **State.** `danger_memory` in the resident record: a short list of `{place (abs position, so it survives a window re-base), kind, strength, tick}` with exponential decay on the decision cadence. Per tick: one distance test of a resident against its own few danger places (not against everyone).
* **Verbs / tools.** `flee_to`, `hide`, `avoid`, `warn`; tool `tool_set_threat` (legacy, to port).
* **Cost / risk.** M. Risk: oscillation (flee, return, flee); give a danger place a minimum dwell time and a hysteresis band. Phobia lock-in: decay must be real.
* **Tiers.** Tier 0 does the flight; Tier 1 gets `fear` and the avoid-place mask; Tier 3 can reflect on it ("I do not go to the river at night").
* **Priority / depends.** P1. Depends on 2.A1 (`flee`), the event ledger (attack and wound events create the memory).

### 2.A4 Drives that make people different: curiosity, ambition, pride, hoarding, generosity, territoriality - P2, L
* **Adds.** Six slow drives, each a trait-scaled pressure that biases the macro menu and goal generation rather than moving bodies:
  * `instinct_curiosity`: pushes exploration into unseen chunks and untried objects when needs are quiet; scaled by an `openness` trait; satisfied by discovering a place, a recipe or a person (event `discovered`).
  * `ambition`: drives status-seeking goals (own a shop, lead a group, learn a craft); rises with skill and falls with failure; feeds `PLOT` and reputation goals.
  * `pride`: injured by public failure or insult, raised by praise and craft success; low pride lowers risk-taking, high pride makes refusal and apology costly (ties to `apologise` / `forgive` in Part 1).
  * `hoarding` and `generosity`: opposite ends of one `thrift` axis that shifts how much a resident keeps in reserve against how freely it gives (`give_item`, `share_food`); hoarding under scarcity is rational and then looks like greed to others.
  * `territoriality`: defence of a home or work place (`instinct_territory_guard`); an intruder with no standing triggers `warn`, then `threaten`.
* **Builds on.** `systems/personality` (trait table), `systems/goal` (priority and generators), relationships, memory, Part 1 entries 1 (food ladder), 3 (debt), 4 (reputation).
* **State.** The drive levels are **resident-record fields** (a few floats each) updated by a single daily system, not by a per-tick pass; the traits are already stored. Territory is a list of claimed places in the record (abs positions).
* **Verbs / tools.** `explore_toward`, `scout_region`, `settle_site`, `warn`, `threaten`, `give_item`; god tool `set_trait`.
* **Cost / risk.** L together, S each if sequenced. Risk: too many knobs produce noise, not character; ship two (curiosity, thrift) first and measure that they change behaviour over a 20-minute run without breaking the economy.
* **Tiers.** Tier 0 updates the levels from events; Tier 1 consumes them as features and goal weights; Tier 3 can narrate and reconsider them.
* **Priority / depends.** P2. Depends on goal generators accepting a new source, on Part 1 (4) reputation for pride and on (3) debt for hoarding.

### 2.A5 Social-emotional instincts: grief, jealousy, loyalty, gratitude and grudge decay - P1 (grudge) / P2 (rest), M
* **Adds.** `instinct_grief` (a death of kin, partner or close friend lowers mood and shifts goals for a period, then fades; mourning can lead to ritual, 2.A6), `jealousy` (a partner's attention to a rival raises tension, may become `warn`, `confront`, retaliation), `loyalty` (a bond that makes help and defence cheaper to choose and betrayal costlier; derived from the relationship record, not stored twice), `gratitude` and `resentment`. Part 1 depends on **`instinct_grudge_decay`**: a daily pass that decays negative opinions toward zero unless refreshed by new offences, with a floor for serious ones (a betrayal never fully fades), so feuds are possible but not eternal.
* **Builds on.** Relationship records and opinion (`systems/social`, Part 1 entry 8 family), the event ledger (death, theft and gift events), mood, `grief` event type for memory.
* **State.** Record fields: `grief` (level, subject, since), opinion deltas per relation. `instinct_grudge_decay` runs once per game day (or per 600/n ticks while no clock exists) over the relation lists of loaded residents only.
* **Verbs / tools.** `comfort`, `apologise`, `forgive`, `retaliate`, `befriend`, `court`; god tool `set_relationship`, `set_kin` (Part 1 asks for it).
* **Cost / risk.** M. Risk: runaway negative spirals (cap per-day opinion drop), and dormant residents (P6): decay must be applied lazily when a resident wakes (store `last_decay_tick`, apply `n` days at once).
* **Tiers.** Tier 0 for the decay and the mood; Tier 1 for the consequences (avoid, help, confront); Tier 3 for the words and for forgiving.
* **Priority / depends.** Grudge decay P1 (Part 1 entry 4 needs it); the rest P2. Depends on the relationship store and on lazy daily systems (2.E).

### 2.A6 Belief, ritual and meaning - P3, M
* **Adds.** A religion / ritual drive: residents who lose someone, survive a disaster or share a season turn gather at a place for a repeated act (`ritual` event: burial, harvest thanks, a spring fire), carry shared beliefs (a small tag set: "the river gives", "the mountain is angry") that spread by talk like rumours, and may attribute disasters to causes. It makes the world feel inhabited and gives Tier 3 something to say.
* **Builds on.** Rumour and gossip (`share_news`), grief (2.A5), disaster events, `PLOT`, group goals, Part 1 religion entry (the social side).
* **State.** Resident record: a few belief tags with strength; a world-level ritual calendar (place, season, kind) produced by a world system, not by each resident.
* **Cost / risk.** M. Risk: content-heavy and easy to make shallow; keep it event-driven and optional. No mechanical bonuses at first (only mood and cohesion).
* **Tiers.** Tier 3 does the substance; Tier 0 only schedules the ritual and applies the mood.
* **Priority / depends.** P3. Depends on 2.A5, 2.B3 (disasters as causes) and the rumour system below.

### 2.A7 Rumour, reputation, theft discovery and the watch - P1, L
* **Adds.** The information instincts Part 1's justice chain needs. `instinct_rumor_spread`: a witnessed event becomes a rumour that travels along conversations with decay, distortion and a source; `instinct_reputation_update`: opinions of a person aggregate into a bounded reputation score per observer group; **`instinct_theft_discovery`**: when an owner's container or pack count is lower than their record, with no consent event, they discover a loss (checked on opening, on a daily inventory glance, or on seeing the thief carry the item) and emit `theft_discovered`; **`instinct_justice_patrol`**: a resident holding the watch role walks a route, sees events, and answers `report_crime` or detects a crime in progress (`arrest_or_restrain`).
* **Builds on.** The event ledger witnesses (the rumour begins as a witness set), `share_news` (idempotent `Emit` that only adds witnesses), inventory conservation (`Transfer` is atomic, so a loss has a ledger trail), occupation (watch is an occupation), `systems/escalation`.
* **State.** Rumours are ledger events plus a per-resident "heard" list in the record (already how memory works); reputation is derived from opinions, cached daily; discovery needs the owner's last-known count per container (a small dict in the record).
* **Verbs / tools.** `gossip`, `report_crime`, `arrest_or_restrain`, `warn`; god tool `seed_rumor` (2.C).
* **Cost / risk.** L. Risk: gossip graphs explode with residents (bound by conversation count; cap the heard list), and false accusations (distortion must be deterministic and bounded).
* **Tiers.** Tier 0 does propagation and discovery arithmetic; Tier 1 chooses report / confront / ignore; Tier 3 words the gossip and judges.
* **Priority / depends.** P1 (Part 1 entry 4). Depends on 2.A5 (grudges), roles (occupation), and the aux decision only if a per-tick pass is wanted (it is not; all of these are cadence systems).

---

## 2.B Nature and world systems

### 2.B1 A clock: day and night, light, and the daily system slot - P1, M
* **Adds.** one calendar module that replaces the two unrelated clocks (`TICKS_PER_YEAR = 600` in `genesis_config.py`, `DEFAULT_DAY_LENGTH_TICKS = 2400` in the schedule) with a single source: `tick -> (day, time_of_day, season, year)`, a light level, dawn and dusk events, and **the daily system slot**: systems registered `every_day` run once at dawn over loaded residents (market update, grudge decay, crop stage, ritual calendar, reputation cache). Residents' schedule blocks bind to the clock; night raises `darkness_unease`, lowers visibility (perception radius scales with light), and moves nocturnal animals.
* **Builds on.** `season_for_tick`, the schedule system, `perception` radius bounding (`EDEN_PERCEPTION_BOUNDED`), `time_control`.
* **State.** Two derived numbers from `tick` (no saved state). Optional god `set_time_of_day` writes an offset in `_nature_state`, which is saved.
* **Cost / risk.** M. **Decided by the user (relayed by c3, 2026-10-08):** a game day is 12000 ticks (10 real minutes at 20 ticks per second), a year is 8 days (about 80 minutes), seasons about 2 days each; implemented as a separate calendar module behind a default-off flag, with the per-tick need, ageing and crop rates rescaled behind the same flag, Stage 1 untouched by default. The mapping from the current constants and the design are in the calendar [GAP] (`1008_calendar_gap.md`). The year length changes every rate that divides by `TICKS_PER_YEAR` (`COOLDOWN_DECAY_RATE`, `instinct_age`, human and animal ageing, resident ttl in years) and the golden trace; hence the flag.
* **Tiers.** Tier 0 only. Tier 1 gets `is_night` and `hour` features.
* **Priority / depends.** P1 (everything seasonal and daily sits on it). No dependencies; the calendar design [GAP] comes first.

### 2.B2 Seasons that change what people do - P1, M
* **Adds.** Season is more than three growth multipliers: **`instinct_season_update`** (Part 1 depends on it) rolls the season and publishes `season_changed` once, then sets: daylight length (2.B1), base temperature (2.A2), crop calendar (sow / grow / harvest windows), animal behaviour (migration, breeding season, hibernation), travel difficulty (snow, mud), and the market's demand curve (Part 1 entry 2: winter raises food and wood prices). A god tool `set_season` (Part 1 depends on it) forces it for tests.
* **Builds on.** `SEASON_MODIFIERS`, `advance_nature_cycle`, `maybe_rebalance_ecology`, farms (`M_FARM`, `farm_growth`).
* **State.** Already in `_nature_state` (season, weather, modifiers, history). Add `season_day` and the planted-crop list per farm (entity columns by type, or a farm record, 2.B5).
* **Cost / risk.** M. Risk: calibration; the food supply must still balance in winter (stockpiles, preservation, hunting) or the first winter ends the world.
* **Tiers.** Tier 0 owns the cycle; Tier 1 gets `season` and `winter_prep` features (store food, repair shelter, gather wood); Tier 3 plans a winter strategy.
* **Priority / depends.** P1 (S-5 winter). Depends on 2.B1 and on 2.A2 (temperature).

### 2.B3 Weather that acts on bodies, tools and fire - P1, M
* **Adds.** Today weather only scales growth. Add: rain wets and cools (more comfort loss without shelter, fire put out, lower travel speed), snow and cold (frostbite wounds, frozen water), heat (thirst rate up, stamina down), wind (fire spread direction and speed, sound carries), storm (shelter-seeking forced, lightning ignition, flooding risk), fog (perception radius). Local weather fronts (a region, not the whole map) once the window exists: a front is a moving disc with a type, intensity and path.
* **Builds on.** `WEATHER_MODIFIERS`, `hazards.py` (fire ticks), `disasters.py` (storm, flood), `instinct_nature_cycle`, perception bounding.
* **State.** Global weather stays in `_nature_state`; local fronts are a small list of discs `{abs position, radius, type, intensity, velocity}` in `_nature_state` (abs coordinates so a re-base does not matter; shifted lazily).
* **Cost / risk.** M. Risk: weather effects on every resident per tick are a tensor pass (cheap); fronts add a point-in-disc test per resident (cheap). Balance again.
* **Tiers.** Tier 0. Tier 1 gets `weather_exposed`, `shelter_needed` features.
* **Priority / depends.** P1 for effects, P2 for local fronts. Depends on 2.A2.

### 2.B4 Ecology and food webs - P2, L
* **Adds.** Animal life with consequences: `instinct_herd_follow` (herbivores cluster and follow a leader), `instinct_predator_stalk` (predators track prey and territory, not random walks), carrying capacity per area, predator-prey cycles, fish stocks in lakes, hunting pressure (over-hunting a region lowers its population and animals avoid humans there), animal fear of fire and settlements, scavengers on corpses. Domestication later: sheep as a herd owned by a resident (property).
* **Builds on.** `animal_instinct_*` (age, hunger, thirst, move, eat, drink, predator attack, reproduce: all reached by the golden), `maybe_rebalance_ecology` (population summary, rebalance), `tool_populate_*` and `tool_herd/scatter/stampede` (legacy god tools, 2.C), node regrowth.
* **State.** Animals are entity rows (`animal_born`, in the window they are spawn entries near residents, step c2 of P5); herd leader and territory are per-animal columns by type or a small per-herd record. Population targets per chunk in the world generator's spawn entries (already generated as data).
* **Cost / risk.** L. Risk: it must work on the chunk window: only animals near residents are rows, so ecology far away is statistical (a coarse population number per chunk updated lazily, then materialised); that is the P6 dormancy design and the hard part. Row budget: animals compete with built structures for the 800 rows.
* **Tiers.** Tier 0 only (animals have no decision tiers); Tier 1 sees `predator_near`, `game_near`.
* **Priority / depends.** P2. Depends on P5 step c2 (animals materialised), P6 (dormant regions), 2.B1/2.B2.

### 2.B5 Resource depletion, regrowth and agriculture - P1, M
* **Adds.** Regrowth that has memory and consequences: nodes already deplete and regrow (`apply_node_regrow`, `M_DEPLETED_TICK`); add overharvest damage (regrowth rate falls if harvested to zero repeatedly), soil fertility (`M_FERTILITY`) that rises with fallow and manure and falls with repeated planting, forests that regrow only if seeds survive (`tool_regrow_forest` as a natural process), and **farming as a state machine**: till, sow, grow through stages (season windows), tend, harvest, with weather and pests as risks; irrigation links a farm to water (`M_RESOURCE_WATER`, `tool_irrigate_area`). Lazy per chunk: a chunk not simulated for N days applies N days of regrowth at once when it wakes (closed-form), so the infinite world does not cost per-tick work.
* **Builds on.** `apply_node_regrow`, `apply_resource_regrow`, `apply_water_cycle`, the map-resource rows (`EDEN_MAP_RESOURCES`), chunk deltas (a depleted node survives unload), `farm_growth` multipliers, verbs `farm_tend`, `gather_from_node`.
* **State.** Entity columns already exist for nodes (stock, cap, depleted tick) and farms (`M_FERTILITY`, growth); the crop stage per farm needs one column or a farm record; chunk deltas already store changed columns.
* **Cost / risk.** M. Risk: closed-form lazy regrowth must equal ticked regrowth within tolerance (test it); save and delta size.
* **Tiers.** Tier 0 for growth; Tier 1 gets `field_ready`, `field_needs_tending`; Tier 3 plans a farm year.
* **Priority / depends.** P1 for depletion memory and farm stages (food is the base of the whole scenario); P2 for fertility. Depends on 2.B2.

### 2.B6 Disease and medicine - P2, M
* **Adds.** `instinct_infection_tick` exists (spread by proximity, `H_INFECTION`). Add named diseases with an incubation period, a contagion route (air, water, food, contact), immunity after recovery, seasonal peaks, weakened people dying first, and **responses**: avoid the sick (a fear), `quarantine` (legacy tool, port), herbs and treatment (`treat_wound`, a medicine item), a healer occupation, and epidemics as world events with an origin that the rumour system carries.
* **Builds on.** `systems/health` (infection, recovery, status, durability), `tool_plague` (ported), `tool_quarantine` (legacy), inventory items, occupation.
* **State.** `H_INFECTION` stays the intensity; disease kind and immunity are resident-record fields (small ints); water contamination is a flag in the water node row.
* **Cost / risk.** M. Risk: epidemics can wipe a small village; guard with caps and a god dial; tick cost is the existing pairwise pass.
* **Tiers.** Tier 0 for spread and effects; Tier 1 `avoid_sick`, `seek_healer`; Tier 3 decisions about quarantine and blame.
* **Priority / depends.** P2. Depends on 2.A2 (wounds), Part 1 health entry, 2.A3 (avoid).

### 2.B7 Disasters with aftermath and warning - P2, M
* **Adds.** The seven legacy disasters (wildfire, earthquake, storm, volcanic eruption, drought, flood, plague) are instantaneous. Add **warning signs** (animals flee first, smoke, a tremor; residents with the right trait notice and spread the word), **aftermath** (rubble, damaged buildings, displaced people, a recovery task list that the goal generators pick up, relief by neighbours) and **region history** (a place remembers its flood, and builds higher next time).
* **Builds on.** `disasters.py`, `hazards.py`, `weather.py` `_plan_extreme_event` (pending event with a trigger tick: a natural place to emit the warning), events, construction repair verbs, goal generators.
* **State.** `_nature_state` history already appends records; add per-region danger counts (abs chunk keyed).
* **Cost / risk.** M. Risk: chunk deltas must record damage (a burned forest persists across unload).
* **Tiers.** Tier 0 executes; Tier 1 `evacuate`, `help`, `rebuild`; Tier 3 coordination.
* **Priority / depends.** P2. Depends on 2.A3, 2.A7, construction.

### 2.B8 The daily market tick and world events - P1 (market) / P2 (events), M
* **Adds.** **`market_update`** (Part 1 entry 2 depends on it): a daily system that recomputes each market's reference prices from supply and demand (damped EMA), expires stale stall stock and posts price events. **World events** as scheduled things: market day, harvest festival, a travelling trader, a famine year, a raid: each is an `Emit` plus a state change and a goal source, driven by the ritual / event calendar and a god `trigger_event` (2.C).
* **Builds on.** The daily slot (2.B1), item `value`, the commission price table, `OfferBook`.
* **State.** Market objects are Part 1's; the calendar is a list in `_nature_state`.
* **Cost / risk.** M. Risk: currency drift (Part 1 flags it); ensure the system is lazy when no market is loaded.
* **Tiers.** Tier 0; Tier 1/2 consume prices.
* **Priority / depends.** P1 for `market_update`. Depends on 2.B1 and Part 1 entry 2.

---

## 2.C God tools and powers

**Ported so far (10 powers, 4 Stage-1 powers)** are listed in 2.0. A `Power` here means: declared parameters, a pure `plan()` that returns the effect set and a preview, an `apply()` that writes it, a declared `risk` (reversible / destructive / irreversible), a manifest row (so ToolRAG and the god panel see it) and a witnessed event. Cost per port: S for a tensor tool, M when it touches geometry or the window. The **64 legacy tools remaining**, grouped and ranked:

### 2.C1 Disasters and hazards - P1, S each (8 of 64)
`tool_wildfire`, `tool_earthquake`, `tool_storm`, `tool_volcanic_eruption`, `tool_drought`, `tool_flood`, `tool_area_attack`, `tool_smite`. Port with dry-run (list the affected rows and residents before applying), the witnessed `Emit`, and `risk=destructive`. The disaster math already lives in `systems/nature/disasters.py`; the port is the wrapper. Depends on nothing; gives the user and Tier 3 `world` role their first dependable disaster tools. These are the highest-value ports because the user can see them.

### 2.C2 Mind and body adjustments - P1, S each (13 of 64)
`tool_set_threat`, `tool_set_aggression`, `tool_age_shift`, `tool_life_exp_modify`, `tool_reset_cooldown`, `tool_grant_instinct`, `tool_revoke_instinct`, `tool_inherit_instinct`, `tool_migration`, `tool_quarantine`, `tool_reproduce`, `tool_harvest_food`, `tool_draw_water`. The instinct grant / revoke / inherit trio already has the 64-bit acquired mask split into three 24-bit words (`harness/instinct_bits.py`); the port must use it. `tool_harvest_food` and `tool_draw_water` overlap with resident verbs and should become thin wrappers over the same grounded actions.

### 2.C3 Terraform and map edits - P2, M each (14 of 64)
`tool_create_lake`, `tool_create_forest_patch`, `tool_create_mountain_chain`, `tool_create_feature_near_feature`, `tool_create_wall`, `tool_transform_area`, `tool_irrigate_area`, `tool_fertilize_area`, `tool_clear_land`, `tool_settle_area`, `tool_regrow_forest`, `tool_seed_world`, `tool_expand_world_edge`, `tool_upgrade_houses_to_village`. **Window implication:** under `EDEN_WINDOW` an edit to a chunk's terrain must survive an unload. Today the delta store records changed columns of generated rows and removals; terrain edits that create or move rows (a new lake, a mountain chain) are runtime-created rows that no chunk owns, and they would be lost beyond the window or hold the 800-row budget forever. A prerequisite is the second half of decision Q1 (full row records assigned to the chunk of their position). `tool_expand_world_edge` becomes meaningless in the infinite world and should be retired.

### 2.C4 Animals - P2, S each (12 of 64; `tool_cull` is already ported)
`tool_spawn_animal_group`, `tool_populate_area_with_animals`, `tool_fill_land_with_animals`, `tool_populate_biome_with_animals`, `tool_restock_lakes_with_fish`, `tool_herd_animals_to_area`, `tool_scatter_animals_from_area`, `tool_feed_animals`, `tool_heal_animals`, `tool_make_animals_flee`, `tool_draw_animals_to_area`, `tool_stampede`. Valuable for demos and for testing the ecology (2.B4). Depends on animals being materialised in the window (P5 step c2).

### 2.C5 Construction family - retire or fold, 17 of 64
`tool_build_house`, `tool_build_village`, `tool_build_farm`, `tool_build_well`, `tool_construct_house`, `tool_construct_village`, `tool_construct_farm`, `tool_construct_well`, `tool_construct_wall_with_humans`, `tool_build_structure_with_humans`, `tool_build_settlement_with_humans`, `tool_designate_structure_site`, `tool_find_buildable_site`, `tool_gather_building_materials`, `tool_repair_area_with_humans`, `tool_demolish_area_with_humans`, `tool_repair_structures`. These are two generations of the same idea (instant build versus build with humans). The resident verbs (`build_structure`, `repair`) and `systems/construction` now own this; do not port them as separate god tools. Keep one god tool, `place_structure` (instant, for scenario setup), and one `designate_site` (the thing residents then build).

### 2.C6 New god tools (not in the 74) - priority per row
| Tool | What | Priority | Notes |
|---|---|---|---|
| `set_season` | force a season (and weather dial) | P1 | Part 1 depends on it. Reversible. Emits `season_changed`. |
| `set_time_of_day` | jump the clock | P1 | needs 2.B1. |
| `set_scarcity` | scale a good's supply or a market's stock / price | P1 | Part 1 depends on it. Not the same as `scarcity_area` (that one lowers a region's resources); this one acts on a market and on an item. |
| `set_kin` | declare a parent / child / spouse relation between two residents | P1 | Part 1 depends on it. Updates both records and emits one event; refuses cycles and ages that cannot work. |
| `set_relationship` | set an opinion or bond | P1 | also the lever for tests of 2.A5. |
| `seed_rumor` | inject a witnessed-looking event at a place | P1 | needs 2.A7. |
| `grant_item` | give an item through an `ItemPermit` | P1 | creation of items needs a declared permit (harness rule). |
| `spawn_traveller` | a stranger with a seeded backstory arrives | P1 | scenario S-2; uses chunk generation. |
| `trigger_event` | festival, market day, raid, famine | P2 | 2.B8. |
| `reveal_resource_node` | add a node near a place | P2 | can reuse `spawn_resource`. |
| `found_settlement_site` | mark a site for settlers | P2 | pairs with `designate_site`. |
| `teleport_actor` | move a resident (or the incarnated one) | P2 | must handle spaces (a portal-free move) and the window (abs target). |
| `pin_chunk` / `regenerate_chunk` | keep a region loaded; rebuild one from the seed | P2 / P3 | `regenerate` is destructive: needs confirmation and drops that chunk's delta. |
| `set_trait` | change a personality trait | P2 | for tests of 2.A4. |
| `inspect_*` (read-only) | why did X do Y: last decision, danger memory, opinions | P1 | the dry-run philosophy extended to residents; costs little, helps everyone. |

**Cross-cutting.** All of these are `Power`s: not callable by a resident, callable by the user, by Tier 3 `world` (with validation and a rate limit) and by tests; each has a dry-run and an event; each is in the manifest so ToolRAG can find it. Cost S for a tensor-only one, M when it touches the window or the delta store.

---

## 2.D Infrastructure: construction, roads, settlements

### 2.D1 Construction as a living process - P1, M
* **Adds.** `systems/construction` already has a catalogue, sites, materials, lifecycle, repair and needs. What is missing for a rich world: structures that **age and decay** (weather damage, repair, abandonment), **upgrades** (hut to house to workshop), **capacity** (a house shelters N, a granary stores M), **ownership** (Part 1 property), and buildings that give **functions** (a well provides water, a granary slows spoilage, a hearth is a warm place). 
* **Builds on.** `M_HOUSE`, `M_WELL`, `M_FARM`, `M_WALL`, `M_STORAGE_CASE`, `instinct_structure_occupancy`, `systems/construction/{catalog,lifecycle,repair,needs}.py`, `build_structure`, `repair` verbs.
* **State.** Structures are entity rows (type, hp, a few columns). Under the window **built structures are runtime rows that no chunk owns**: they persist in the tensors, count against the row budget (800) and are saved with the world, but they never unload. A settlement with 150 buildings uses a fifth of the window's rows for good. That is the design limit to settle first (2.E).
* **Cost / risk.** M. Risk: the row budget; save size; repair work as the economy's sink.
* **Tiers.** Tier 0 applies decay and function effects; Tier 1 `repair`, `build`; Tier 3 decides what a village needs.
* **Priority / depends.** P1. Depends on the row-budget decision (2.E) and on Part 1 (property, craft).

### 2.D2 Roads and paths that people make - P2, M
* **Adds.** Desire lines: movement leaves a trace; repeated travel between two places upgrades the ground (grass, path, road) and lowers its movement cost, so paths between wells, farms and markets emerge. Builders can also lay a road deliberately. Pathing then prefers roads. Bridges over water as a structure type. Roads are what a settlement looks like from the air.
* **Builds on.** `systems/movement/pathing.py` (A* with the contract's boxes), `plan_path`, `anchor_mover`, tiles, the map-resource and chunk tile layers (the generator already outputs layers).
* **State.** A sparse per-tile traffic counter keyed by absolute tile (window re-base safe), saved in the chunk delta store as a tile-layer delta (a new kind of delta: tile edits, not row edits); path cost multipliers by tile kind in the pathing cost function.
* **Cost / risk.** M. Risks: the delta store gains a tile-layer kind (client must redraw tiles; the chunk document is immutable by design: `ETag = sha256`, so roads need an overlay layer on the wire, which is a **client-contract change**), and pathing cost per query must not grow.
* **Tiers.** Tier 0; the decision tiers only benefit.
* **Priority / depends.** P2. Depends on the delta store extension and a client overlay.

### 2.D3 Settlement growth - P2, L
* **Adds.** A settlement is a record, not just buildings: a name, a centre, a founding event, a population, a market (Part 1), a governance form (Part 1), claimed land and a growth rule (when food surplus and housing shortage persist, residents designate sites; when people leave, buildings decay). `found_settlement_site` (2.C6) plants one; migrants (`migrate_group`, `lead_group_to`) found new ones. Several settlements make trade, rivalry and caravans meaningful.
* **Builds on.** `M_VILLAGE`, `tool_upgrade_houses_to_village`, group goals, `settle_site` verb, the market and governance entries.
* **State.** A `Settlement` registry in `_nature_state` or its own saved object, keyed by absolute position; membership derived from residence.
* **Cost / risk.** L. Risk: dormancy (a settlement far from every player must keep living at a coarse level: P6), save format.
* **Priority / depends.** P2/P3. Depends on 2.D1, Part 1 entries 2, 8, P6.

---

## 2.E Engine implications (what the expansions cost the platform)

1. **State has to live somewhere.** 2.A2, 2.A3, 2.A5 need per-resident scalars updated every tick or every few ticks; the human tensor has **two free columns (30, 31)**. Options: (a) put them in resident records and update on the decision cadence (cheap, no format change; fine for slow state: grief, danger memory, thrift, drives); (b) add one auxiliary tensor `h_aux` of shape (MAX_HUMANS x 16) for the fast ones (sleep debt, body temperature, comfort, fear), saved in the world format with the window's format bump. **Recommendation:** (a) for everything slow, and (b) with 8 to 16 columns only if profiling shows the record path is too slow. Decision needed from the user / orchestrator before 2.A2 starts.
2. **Daily systems and lazy catch-up.** A `Daily` slot (2.B1) over loaded residents, with `last_run_tick` per resident so a resident or a chunk that was dormant applies `n` missed days in closed form on wake (regrowth, grudge decay, crop growth, spoilage). Required by P6 dormancy; do it from the first daily system so none needs retrofitting.
3. **Counter-based RNG.** Every new stochastic effect (illness onset, rumour distortion, animal choice) must use `rng(world_seed, tick, system, entity_uid)` (WS-H H.3 item 9), not the process-global generators; otherwise shadow comparison and replay fail and the new instincts make the golden trace order-dependent.
4. **Systems migrate to declared form.** Each new instinct is written as a declared system (name, phase, reads, writes, cadence) producing `Effect`s through the one applier, with a manifest row. The 25 live legacy instincts migrate on the strangler plan (H.3) only when they are touched; the golden trace is the contract.
5. **Window and abs positions.** All remembered places (danger memory, territory, roads, settlement centres, fronts) store **absolute** positions or `(chunk, offset)`, never window-local floats (`harness/window.absolute_position`); the re-base position-holder scan test gets each new holder added to its list.
6. **Row budget.** The window holds at most 800 entity rows (`WINDOW_ROW_BUDGET`). Generated chunk entities are the large consumer; built structures (2.D1), animals (2.B4) and dropped items add more and never unload. A **dormant structure store** (full row records keyed by chunk, loaded when the chunk integrates, outside the tensors when not) is the missing piece and is the first prerequisite of 2.C3, 2.D1, 2.D3. Without it the world's growth is capped by the budget.
7. **Save format.** Resident-record fields are free (schema-free dicts). A new tensor, a delta kind (tile layers), a settlement registry or a changed year length each bump the world format and need approved refusal wording (the format-3 texts are the pattern).
8. **Tick budget.** Today's profile is in `1008_tick_profile.md`; the window's own cost is 0.7 ms mean per tick (measured). New per-tick tensor passes should be budgeted together at below about 1 ms; cadence systems (decision cadence, daily) are not on the tick path. Every entry above states which kind it is. A budget test (the profile tool) gates each flag.
9. **Tests and goldens.** Every entry ships behind a flag and, flag off, leaves the strict golden bit-identical (the rule since Stage 1). The legacy instincts the plan wires (2.A1) need their own golden and a coverage-map re-run so "called" turns into "tested".
10. **Client and wire.** Roads (2.D2) and local weather fronts (2.B3) need client rendering and a wire field; the client contract is the place to add them. Day/night (2.B1) needs a clock field in `/frame`. All additive keys.

## 2.F Summary: order, priority and dependencies

| # | Entry | Priority | Cost | Depends on |
|---|---|---|---|---|
| 2.B1 | Calendar, day/night, daily slot (decision made: 12000-tick day, 8-day year, flag) | P1 | M | calendar [GAP] |
| 2.E1 | State home for fast scalars (records vs `h_aux`) | P1 | S (decision) | none |
| 2.A1 | Wire or retire the 21 uncalled instincts | P1 | M | coverage map |
| 2.A3 | Fear response and fear learning | P1 | M | 2.A1 |
| 2.A2 | Temperature, sleep, wounds, spoilage (S-5 winter) | P1 | L | 2.B1, 2.E1 |
| 2.B2 | Seasons that change behaviour (`instinct_season_update`, `set_season`) | P1 | M | 2.B1, 2.A2 |
| 2.B3 | Weather acting on bodies and fire | P1 / P2 fronts | M | 2.A2 |
| 2.B5 | Depletion memory, farm stages, lazy regrowth | P1 | M | 2.B2 |
| 2.B8 | `market_update` and world events | P1 / P2 | M | 2.B1, Part 1 (2) |
| 2.A5 | `instinct_grudge_decay`, grief, loyalty | P1 / P2 | M | relationships |
| 2.A7 | Rumour, reputation, `theft_discovery`, `justice_patrol` | P1 | L | 2.A5, roles |
| 2.C1, 2.C2 | Port disasters and mind / body tools (21 tools) | P1 | S each | none |
| 2.C6 | `set_season`, `set_scarcity`, `set_kin`, `set_relationship`, `seed_rumor`, `grant_item`, `spawn_traveller`, `inspect_*` | P1 | S each | owners above |
| 2.D1 | Construction as a living process | P1 | M | 2.E6 row budget |
| 2.A4 | Curiosity, ambition, pride, thrift, territoriality | P2 | L | goals, Part 1 (3, 4) |
| 2.B6 | Disease and medicine | P2 | M | 2.A2, 2.A3 |
| 2.B7 | Disasters with warning and aftermath | P2 | M | 2.A3, 2.A7 |
| 2.B4 | Ecology and food webs | P2 | L | P5 c2, P6 |
| 2.C3, 2.C4 | Terraform and animal tools | P2 | M / S | 2.E6, P5 c2 |
| 2.D2, 2.D3 | Roads, settlement growth | P2 | M / L | 2.E6, client overlay, P6 |
| 2.A6 | Belief and ritual | P3 | M | 2.A5, 2.B7 |

**Decisions this part needs from the user (or the orchestrator):** (1) the length of a day and of a year (2.B1) **[decided: 12000-tick day, 8-day year, behind a flag]**; (2) records only, or an auxiliary tensor, for fast per-resident state (2.E1); (3) whether the world should keep a hard row budget with a dormant structure store, or raise the budget (2.E6); (4) which of the 21 uncalled instincts to wire and which to retire (2.A1); (5) whether roads need a client overlay layer in the chunk contract (2.D2).
