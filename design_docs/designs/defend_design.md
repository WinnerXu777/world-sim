# 1008 - `defend`, `attack`, `flee` as real verbs: what exists, what is missing, who owns the edit (model plane, [GAP] design)

Status: design only (nothing built). Written 2026-10-09 for c3. The user wants creatures and fantasy hostiles, so combat verbs must eventually be real, bounded, auditable verbs that guards, justice and creatures all use. Nothing below is registered or changes behaviour today.

## 1. What exists today (read from the code, not from the catalog)

| piece | where | what it does |
|---|---|---|
| attack intent | `systems/combat/intents.py`, `resolver.resolve_human_attack_intents` | a human attacker (slot) vs a human or an animal entity: range `ATTACK_RANGE`, stamina cost, damage `ATTACK_DAMAGE`, wall line-of-attack test, threat +40 on the target. The only damage path for human-vs-human. |
| who attacks | `systems/combat/sim.py` (`collect_sim_attack_intents`), `manual.py`, task `attack_target` (`tasks/families/combat.py`) | autonomous: pairs flagged `aggressive` x `peaceful` in range; click-driven manual; the task queue. |
| creatures vs humans | `instincts_and_tools.py:1888` | `ANIMAL_PREY` (`genesis_config.py:428`): tigers hunt sheep, deer **and humans** (`ANIMAL_PREDATOR_ATTACK_DAMAGE` 15, range 20); wolves do not. Animals are rows of `m_tensor` with `M_TYPE` in `ANIMAL_TYPES = range(40, 80)`. |
| damage | `systems/health/damage.py` | `apply_human_damage(mask, h, amount, hp_col)`: HP is the single injury variable; there is no wound, bleeding, armour or weapon modifier in the damage path. |
| guarding | tasks `guard_area` (open-ended), `guard_target`, `protect_target`, `protect_home`, `hold_position` | movement/intent tasks; none ends by itself, none changes who gets hurt. |
| model-plane verbs | `verbs/conflict.py`: `attack` (destructive, `attack_target` task), `avoid`, `warn`; `flee_to` in survival | `attack` and `avoid` are demoted to `roster_driven` for anchor residents, legal for agent residents. `defend` is **not registered** (`./actions.md` 10.10: `guard_area` never ends, so a plan step could not finish). The predicate `can_defend` exists (`predicates.py:599`) and says yes to anyone with a live neighbour or a home anchor. |
| law | `systems/justice/*` (mine) | no violence by design: report, damages, levy. `arrest_or_restrain` and the `rob` rung wait for `defend`. |

## 2. What `defend` has to mean

Two bounded things, both about protecting *someone or somewhere* for a *finite time*:

* `defend(target)`: stay within `GUARD_RADIUS` of a person for `GUARD_TICKS`; if that person is attacked (HP drop with an attacker in range, or a threat spike) answer the attacker: `warn` first, then `attack` only if the attacker is a hostile creature, a repeat attacker, or the target is a child/kin (rules, same table style as the ladder).
* `defend(place)`: the same for a place (home, stall, field) - the `guard_post` of a guard on shift.

The model plane owns the *decision and the bounded commitment*; the engine owns *who gets hurt*. That split gives three phases.

### Phase 0 - model plane only (mine, no engine edit) - AS BUILT, see `./actions.md` 10.18 (flag `EDEN_DEFEND`; with Phase 1 landed the guard shields: it takes the blow at 0.6 of the damage)

* New runtime book `GuardPosts` on `services.__dict__` (like OfferBook/Docket): `post(actor, target|place, until_tick)`, `expire`, `against`.
* New Action `defend` on a flag-gated registry (`EDEN_DEFEND`, same pattern as `EDEN_JUSTICE`): opens a post, emits `began_guarding`, queues nothing open-ended. The agent driver turns a post into a following errand (`errand_goal` recomputes the position from the person each tick, as for `visit`/`enforce`) and closes it at `until_tick`.
* The answer to an attacker uses what already exists: the driver already tracks `last_hp`; a guarded person's HP drop inside the radius makes the guard's next decision `warn` then `attack_target` through the existing task, which the resolver already handles. No resolver edit.
* Tests: post lifecycle, dormancy (a dormant guard keeps its post frozen, dropped on wake), re-base (posts hold no coordinates), determinism, flag-off identity.

### Phase 1 - harness/combat edit (not mine; needs c3's OK and an owner)

What the model plane cannot do alone: make a guard actually *change the outcome* of an attack. The smallest edit is one optional hook in `resolve_human_attack_intents`: `mitigate(attacker_slot, target_slot) -> (damage_multiplier, redirect_slot|None)`, default `None` = today's behaviour bit for bit. The model plane would supply it from `GuardPosts` (a guard in range takes the hit or halves it). Also needed for `arrest_or_restrain`: a `restrained_until` column or flag the movement step respects (the movement files are 9d882a's). **Owner proposal: 9d882a (harness/engine) for the hook and the restraint flag, me for what feeds them.** Without Phase 1 `defend` is a visible, auditable intention with a verbal/combat response, not a damage shield.

### Phase 2 - creatures and fantasy hostiles (engine + data: landed as `./creatures_gap.md`, `systems/creatures/table.py`)

The creature table (9d882a's schema: `hp`, `speed`, `damage`, `range`, `cooldown`, `aggro`, `aggro_range`, `flee_hp`, `fear`, `diet {eats, prey, humans}`, `activity` by time block, `group`, `territory`, `habitat`/`spawn_p`, `loot`, `hostile`, `huntable`, `brain`, `variants`) replaces the idea of a separate definition table here; the kernel, spawn plan and window store are theirs (`EDEN_CREATURES`, needs `EDEN_WINDOW`). What the model plane adds, against that schema and nothing else:

* **Perception.** `EngineServices.entities` lists living animals (`kind` = species name via `table.by_type`) so affordance predicates see creatures; `hostile_count` reads `table.hostile_types()` instead of the tiger/wolf pair (identity with the flag off).
* **Fear / flee / defend.** `can_flee` is true when a perceived creature is `hostile` inside its `aggro_range` (or `threat` above a bound) and a safe target exists; `can_defend` for a charge needs the same creature near the charge; Tier 1 gets cold/fear/wounded features from `threat` (schema version change, flag-gated, the rules prior is untouched). Residents flee by default, guards and armed residents engage by the rules table (flee unless armed and healthy; guards at a post engage), others call for help (`ask_for_help` exists).
* **Hunt / butcher.** `hunt(target)` is legal for `huntable` species in reach with a weapon or tool; the kill emits `creature_killed`; the loot grant is a model-plane effect that reads `loot` (items now exist: meat, hide, bone, feather, egg, wool, silk, scrap) and, if the table says `carcass.ticks`, a `butcher` verb harvests a body that is still there.
* **Taming.** Fields requested from the table (`tame {mode, food, to_tame, decay_per_day, role}`, `products [{item, every_days, needs}]`); verbs `feed_animal`, `tame`, `collect_product` (egg, wool) are model-plane verbs over those fields, domestic animals as guards/companions/livestock/mounts.
* **Hostile creature vs human damage** stays in the kernel (`apply_human_damage`, threat 100); human victims are not offered to `COMBAT_MODIFIER` in that phase. Guards mitigating a creature attack would need a `target_kind` extension to the Phase 1 hook (a later model-plane decision).

## 3. Injury model (proposal, smallest that is honest)

* Keep HP as the one injury variable for now. Add two cheap, deterministic modifiers in `apply_human_damage` callers via the Phase 1 hook: weapon bonus (item in pack: `sword`, `spear`; values from a table) and guard mitigation. No armour until items carry stats.
* Wounds are a *record*, not a tensor: `treat_wound` (glue verb, not yet registered) reads HP deficit and a `bandage`/`herb` item and heals through `help_target`; bleeding is out of scope until the user asks.
* Death handling stays the engine's; the model plane only reads `alive`.

## 4. How the users of `defend` plug in

| user | uses | notes |
|---|---|---|
| guard (occupation) | a standing `defend(place)` post per shift, `enforce` for cases | the shift length is `GUARD_TICKS`; `justice_day` already finds guards |
| parent/kin | `defend(child|kin)` when a threat spike is near them | rules table, cooldown |
| justice | `arrest_or_restrain` (Phase 1), `rob` rung for thieves only when the victim `can_defend` | keeps "no rob before defend" |
| creatures | attack/avoid/flee like any actor via `CombatIntent(attacker_kind="entity")` (Phase 2) | one resolver, one audit |
| Tier 2/3 | `defend` / `attack` appear as typed options; `attack` stays destructive (risk gate), `defend` is reversible | plan op `defend` exists in `plan_adapter` |

## 5. Decisions for c3

1. Approve Phase 0 now (flag `EDEN_DEFEND`, default off, goldens unchanged by construction).
2. Choose the owner for the Phase 1 `mitigate` hook and the `restrained_until` flag (proposal: 9d882a; this is a harness edit, I will send the exact hook signature).
3. Decide when creatures (Phase 2) are scheduled; I can do the affordance/features/rules side first against the existing tiger so the rules are exercised before the data table lands.
