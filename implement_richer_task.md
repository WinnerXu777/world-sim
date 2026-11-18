# Richer Task Implementation

This document covers the next stage after the task-migration handoff is done.

The main question is no longer:

- "how do we move behavior out of `instincts_and_tools.py`?"

The main question is now:

- "how do we make `systems/tasks` deeper, more varied, and more believable?"

The direction is:

- keep `systems/tasks` as the main execution orchestrator
- keep reflex outside tasks
- keep reasoning / goals / planning as the intent orchestrator
- expand the live task families so residents feel more socially alive, more
  occupationally diverse, and more strategically capable

## Current Base

The current live base is:

- `occupation`
  - provisioning
  - `woodcutter`
  - `fisherman`
  - `farmer`
  - `guard`
  - `builder`
  - `gatherer`
  - `hunter`
  - `healer`
  - `trader`
- `survival`
  - `fetch_water`
  - `eat_food`
  - `sleep`
  - `seek_shelter`
  - `flee_target`
- `social`
  - `socialize`
  - `approach_target`
  - `follow_target`
  - `talk_to_target`
  - `warn_target`
  - `call_for_help`
  - `help_target`
  - `deliver_item`
  - `escort_target`
  - `return_to_group`
  - `thank_helper`
  - `comfort_target`
  - `report_crime`
  - `challenge_target`
  - `seek_mate`
  - `mate_with_target`
- `combat`
  - `attack_target`
  - `chase_target`
  - `retreat_from_target`
  - `guard_area`
  - `guard_target`
  - `hold_position`
  - `finish_hunt`
  - `loot_after_kill`
  - `protect_target`
  - `intercept_target`
- `strategic`
  - `acquire_weapon`
  - `move_to_ambush_point`
  - `wait_in_hiding`
  - `recruit_ally`
  - `steal_from_container`
  - `escape_area`
  - `scout_area`
  - `protect_home`
  - `gather_food_buffer`
- `routine follow-through`
  - simple task-owned movement fallback
- `interruption / resumption`
  - paused task queues
  - resume candidates
  - non-interruptible combat / flee handling
  - queue replacement that no longer wipes active work just because no
    lower-priority producer fired that tick

## Current Live Expansion

The current richer pass now also includes these live improvements:

- `social`
  - `call_for_help` can now signal a nearby support resident through the task
    bridge instead of staying isolated to the caller
  - `help_target` can now trigger `thank_helper`, `comfort_target`, or
    `escort_target` follow-through depending on the target's post-help state
  - `escort_target` can now ask the escorted resident to `follow_target` while
    moving toward a safer anchor
  - `report_crime` can now hand off an `intercept_target` combat signal to the
    reported guard target
- `combat`
  - hunting can now continue past the strike with `finish_hunt`, which turns a
    downed prey target into carried food for later storage
  - `protect_target` is now live as a first guard-side support task
- `occupation`
  - gatherers now cycle between `herb_bundle`, `fiber_bundle`, and `rations`
    instead of harvesting only one fixed output
  - traders now withdraw a sale good from nearby storage before a trade run if
    they are not already carrying something worth selling
- `strategic`
  - plan ops now cover `avoid_target`, `guard_place`, and
    `gather_food_buffer`
  - plan-kind fallback now covers `fortify_home` and `avoid_target`
  - strategic escape / food-buffer tasks now use the shared task bridge rather
    than a one-off runtime path

That gives us the execution backbone. The next work is now about making those
live slices deeper and more believable, not about wiring the first ownership
handoff.

## Main Expansion Areas

The next richer-task phase should now focus on 5 areas:

1. deepen the new social chains
2. deepen the new occupations
3. deepen combat follow-through
4. expand strategic plan execution coverage
5. tighten group coordination and interruption semantics

These should all still flow through the same dispatcher and bridge contract.

## 1. Richer Social Chains

`families/social.py` is live now, but it still needs to evolve from isolated
single-purpose tasks into believable local chains.

The important rule stays the same:

- `talk`, `escalation`, `schedule`, `memory`, and `planning` decide that a
  social consequence should happen
- `families/social.py` carries it out step by step

### Current live base

- `socialize`
- `approach_target`
- `follow_target`
- `talk_to_target`
- `warn_target`
- `call_for_help`
- `help_target`
- `deliver_item`
- `seek_mate`
- `mate_with_target`

### Next social task kinds

- `escort_target`
- `return_to_group`
- `thank_helper`
- `comfort_target`
- `report_crime`
- `mourn_target`
- `flee_from_speaker`
- `greet_target`
- `challenge_target`
- `dismiss_target`

### Desired social chains

#### Threat warning chain

- hear or witness danger
- `approach_target`
- `warn_target`
- listener either `follow_target`, `seek_shelter`, or `call_for_help`
- both residents later return to routine if safe

#### Help / rescue chain

- detect wounded or fearful target
- `approach_target`
- `help_target`
- if threat remains: `escort_target`
- if target stabilizes: `return_to_group` or `talk_to_target`

#### Delivery / support chain

- withdraw or craft item
- `approach_target`
- `deliver_item`
- short `talk_to_target` or `thank_helper`
- return to occupation or schedule

#### Courtship chain

- `approach_target`
- `talk_to_target`
- `follow_target`
- `seek_mate`
- `mate_with_target`
- later `return_home` / `socialize`

#### Local crowd chain

- one resident `call_for_help`
- nearby ally emits `approach_target` or `guard_area`
- wounded ally emits `help_target`
- non-combat witness emits `warn_target`

### Social producer sources

These chains should be emitted by:

- `systems/talk`
  - direct threats
  - direct pleas
  - apologies
  - offers
  - insults
- `systems/escalation`
  - fear / ally / witness follow-through
- `systems/schedule`
  - ordinary socialize windows
- `systems/planning`
  - recruit support
  - warn kin
  - deliver aid
- `systems/memory`
  - recent attack witness
  - recent death witness
  - unresolved grievance

### Important social design rule

Do not let `talk` execute movement or body behavior directly.

Instead:

- talk appraises speech
- talk produces signal(s)
- social task family executes the consequence

That keeps the social surface and the action surface cleanly separated.

## 2. Deeper Occupations

The current new occupations are live, but still narrow. The next step is not to
add dozens more jobs immediately. It is to make the current jobs feel more like
real medieval work loops.

### Current live expansion set

- `builder`
- `gatherer`
- `hunter`
- `healer`
- `trader`

### Deeper occupation design principle

Each occupation should eventually have:

- a baseline tool chain
- a worksite / place preference
- a resource loop
- a storage / delivery loop
- a failure / interruption path
- a social side effect

So the occupation feels like a real life pattern, not just one harvesting
action.

### Builder next expansion

Current live shape:

- ensure `hammer`
- move to worksite
- produce `plank_bundle`

Next expansion:

- ensure `hammer`
- gather `wood_bundle` / `stone_chunk`
- craft `plank_bundle` / `rope` if missing
- move to damaged or unfinished structure
- consume materials into `construction`
- do `build_work` or `repair_work`
- store leftovers

Future elaboration:

- claim active worksite
- cooperate with other builders
- respond to `fortify_home` or `repair_wall` strategic plans

### Gatherer next expansion

Current live shape:

- ensure `basket`
- move to wild area
- gather `herb_bundle`

Next expansion:

- choose local gather type:
  - `herb_bundle`
  - `fiber_bundle`
  - `rations`
- avoid danger while gathering
- return to nearest useful storage
- preferentially deliver herbs to healer storage

Future elaboration:

- season / biome-sensitive gathering
- village supply balancing
- opportunistic witness / warning behavior in the wild

### Hunter next expansion

Current live shape:

- ensure `spear`
- move to wild area
- produce `rations`

Next expansion:

- scout for prey
- `chase_target`
- `attack_target`
- `finish_hunt`
- convert kill into food or material output
- store catch

Future elaboration:

- pack hunting with allies
- torch-at-night hunting
- risk-based retreat when prey is dangerous

### Healer next expansion

Current live shape:

- ensure `bandage`
- move to wounded target
- heal target

Next expansion:

- maintain local stock of `bandage`
- gather `herb_bundle` when low
- prioritize target by:
  - HP
  - threat
  - proximity
  - kin / ally relationship
- heal in place or escort to shelter

Future elaboration:

- triage queue
- home hearth recovery zone
- social comfort and follow-up checks

### Trader next expansion

Current live shape:

- ensure `pack` / `coin`
- move to market
- trade a simple item for coin

Next expansion:

- choose trade goods from local storage
- withdraw goods
- move between storage and market / settlement anchors
- convert goods to `coin`
- restock or deliver coin home

Future elaboration:

- village-to-village route later
- price/value weighting from future economy module
- escort or warn behavior under threat

### Next occupations after current depth is improved

Only after the above five feel deeper should we add:

- `smith`
- `miner` / `quarrier`
- `innkeeper`
- `elder` / `priest`
- `ferryman`
- `shepherd`

## 3. More Advanced Combat

Combat is live now, but it still needs better follow-through and role-specific
variation.

### Current live base

- `attack_target`
- `chase_target`
- `retreat_from_target`
- `guard_area`

### Next combat task kinds

- `guard_target`
- `hold_position`
- `finish_hunt`
- `loot_after_kill`
- `protect_target`
- `intercept_target`

### Better combat behavior examples

#### Guard response

- detect threat near settlement
- `intercept_target` or `chase_target`
- `attack_target`
- `guard_area`
- return to patrol when threat is gone

#### Cowardly resident

- reflex jolt outside tasks
- `flee_target`
- `seek_shelter`
- maybe `call_for_help`
- only re-enter ordinary life after threat decays

#### Hunter

- move toward prey
- chase if target moves
- strike when close
- `finish_hunt`
- `loot_after_kill`
- store output

### Combat design rule

Keep these split:

- reflex = instant body response
- combat family = short tactical execution
- strategic family = pre-fight setup and longer intent

Combat tasks should handle:

- chase
- strike
- hold
- retreat
- protect

But not long-horizon revenge plotting. That still belongs in strategic tasks.

## 4. Strategic Chains

`families/strategic.py` is live now, but only for the first simple plan-step
translation. It needs to become the execution family for the structured plans
coming out of reasoning / planning.

The rule is:

- planning creates structured steps
- strategic family translates them into executable shared task chains

### Current live base

- `acquire_weapon`
- `move_to_ambush_point`
- `wait_in_hiding`
- `recruit_ally`
- `steal_from_container`

### Next strategic task kinds

- `track_target`
- `deliver_warning`
- `escape_area`
- `sabotage_target`
- `scout_area`
- `protect_home`
- `gather_food_buffer`
- `revenge_attack`

### Strategic chain patterns

#### Revenge chain

- `acquire_weapon`
- `move_to_ambush_point`
- `wait_in_hiding`
- `attack_target`
- `retreat_from_target` or `return_home`

#### Recruit support chain

- identify ally target
- `approach_target` / `talk_to_target`
- `recruit_ally`
- ally emits `guard_area` or `follow_target`

#### Theft chain

- move near container / settlement
- `wait_in_hiding`
- `steal_from_container`
- `move_to_place(home)`
- `store_item`

#### Escape and hide chain

- `move_to_ambush_point` toward safe place
- `wait_in_hiding`
- `fetch_water`
- `eat_food`
- later `return_home` only if safe

#### Fortify home chain

- gather materials
- `move_to_place(home)`
- `build_work`
- `guard_area`

### Plan-op to task mapping should eventually cover

- `move_to_place`
- `move_to_target`
- `observe_target`
- `avoid_target`
- `recruit_allies`
- `attack_target_when_close`
- `guard_place`
- `steal_from_target_when_safe`
- `return_home`
- `rest_until_safe`
- `gather_food_buffer`

That is the point where reasoning and execution really become cleanly layered:

- reasoning chooses the plan
- strategic chooses executable task chains
- social / combat / occupation / survival families carry out the pieces

## Shared Primitive Design

To keep the task system robust, richer families should reuse common task
primitives instead of inventing isolated flows.

### Primitive categories

- `movement`
  - `move_to_place`
  - `approach_target`
  - `return_home`
  - `follow_target`
- `inventory`
  - `withdraw_item`
  - `store_item`
  - `deliver_item`
  - `loot_item`
- `crafting`
  - `gather_material`
  - `craft_item`
  - `equip_item`
- `social`
  - `talk_to_target`
  - `warn_target`
  - `call_for_help`
- `combat`
  - `attack_target`
  - `chase_target`
  - `retreat_from_target`

The richer the sim gets, the more important it is that these primitives stay
shared instead of each family duplicating movement, storage, or combat logic.

## Interruption Model

Richer tasks need a clearer interruption policy.

Current tasks already replace each other by priority, but future depth needs a
more explicit model.

### Desired policy

- reflex interrupts everything instantly
- survival tasks can preempt ordinary work
- direct talk can preempt routine work
- combat can preempt routine work and most social tasks
- strategic tasks should be interruptible by survival and immediate danger
- some tasks should resume after interruption if still relevant

### Resident task state should eventually support

- `current_task`
- `queued_tasks`
- `paused_tasks`
- `last_interrupt_reason`
- `resume_candidate`

This does not need to be fully built immediately, but richer tasks will need
it.

## Bridge Expansion

The task bridge is already stable, but richer families will need more world
actions.

### Likely next additions

- `loot_target_action(target_kind, target_id)`
- `resolve_worksite_target(work_kind, px, py, radius)`
- `reserve_station(station_id, human_id)`
- `release_station(station_id, human_id)`
- `resolve_trade_target(px, py, radius)`
- `resolve_construction_target(px, py, radius)`

These should stay as bridge methods, not direct engine pokes from families.

## Suggested Next Waves

The original richer-task order is now implemented at a first pass. The next
work should happen in these waves:

### Wave 1: deepen social follow-through

Current live pass:

- `escort_target`
- `thank_helper`
- `comfort_target`
- `report_crime`
- `challenge_target`

- `escort_target`
- `thank_helper`
- `comfort_target`
- `report_crime`
- `challenge_target`

Reason:

- this makes nearby life feel more human immediately
- it improves the payoff of talk, injury, theft, and witness events

### Wave 2: deepen current occupations

Current live pass:

- gatherer output cycling
- trader storage withdraw before market exchange
- hunter kill processing through `finish_hunt`

- builder uses `construction` progress
- gatherer chooses output type by place
- hunter gets real hunt follow-through
- healer does triage and shelter escort
- trader uses storage withdraw / deposit loops

Reason:

- this makes villages feel productive instead of just reactive

### Wave 3: deepen strategic execution

Current live pass:

- `avoid_target -> escape_area`
- `guard_place -> guard_area`
- `gather_food_buffer -> gather_food_buffer`
- `fortify_home -> protect_home` fallback

- more plan-op coverage
- revenge / theft / fortify / escape chains
- stronger social + combat composition inside plans

Reason:

- this is what turns the reasoning queue into visible lived consequences

### Wave 4: deepen group coordination

- allies answering `call_for_help`
- guards protecting healers / traders
- recruited allies joining revenge or protection chains
- household / kin warning propagation

Reason:

- this is where the world stops feeling like isolated actors

### Wave 5: deepen interruption and resumption semantics

- explicit source priority matrix
- pause / resume metadata per family
- clearer "abandon task" vs "resume task" behavior
- better debug visibility

Reason:

- richer chains will feel brittle if interruption remains too implicit

## Verification Strategy

Each richer task slice should be verified in the same pattern:

### Social

- resident can approach, warn, help, deliver, and thank through tasks only
- talk-triggered social tasks do not bypass the dispatcher
- help chains can hand off into shelter or talk follow-up
- crowd help does not permanently deadlock ordinary schedules

### Occupation

- each current new occupation can provision tools
- each can complete a believable multi-step work loop
- outputs are stored, consumed, or delivered correctly
- interruptions by danger or survival resume correctly afterward

### Combat

- attack, chase, retreat, and guard do not stall
- help call and retreat can preempt ordinary work
- hunt follow-through produces believable outputs
- guard returns to ordinary patrol after threat ends

### Strategic

- a plan can emit multiple task steps
- task completion advances `current_step_index`
- strategic chains compose correctly with social / combat / occupation tasks
- interruption by survival / danger works and resumes when appropriate

## End Goal

The goal of richer tasks is:

- villagers do not just survive
- they work, socialize, react, help, warn, pursue, retaliate, and recover
- all of that still flows through one coherent execution language

That is what makes the simulation feel robust instead of brittle:

- one reasoning side
- one execution side
- one reflex side

with `systems/tasks` serving as the central execution backbone for richer,
believable resident life.
