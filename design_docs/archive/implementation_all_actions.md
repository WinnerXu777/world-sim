# All Actions Implementation

## Purpose

This document defines the next-step action implementation plan for the project.

The goal is not just to add more animations.

The goal is to:

- expose the full action vocabulary that already exists in the backend
- make those actions readable in `godot_client`
- keep one shared action contract for:
  - NPC simulation
  - manual player control
  - future UI/debug tools


## What The Repo Already Has

After reviewing `godot_client` and `at_the_beginning`, the important picture is:

- `godot_client/scripts/incarnation_human.gd` already supports:
  - locomotion
  - `attack`
  - `pain`
  - `fall`
  - `get_up`
  - `talk`
- `godot_client/scripts/human_mode_3d.gd` already consumes backend `render` hints:
  - `locomotion`
  - `action`
  - `facing_yaw`
  - `velocity_world`
- `at_the_beginning/map_test.py` already exports per-actor render hints and a short-lived render action channel
- `at_the_beginning/systems/tasks/catalog.py` and `systems/tasks/families/` already define and execute a much richer task/action vocabulary
- `at_the_beginning/systems/control/schema.py` already defines richer semantic actions than the client currently sends

So the main gap is not simulation depth.

The main gap is:

- backend action semantics are much richer than current render semantics
- the client still presents most behavior as only:
  - idle
  - walk
  - run
  - attack
  - talk
  - hurt/down


## Current Strengths

These parts are already in good shape:

- movement and locomotion hints already exist end-to-end
- combat hit reactions already have a basic backend-to-client loop
- talk is already routed through control/runtime
- the task system already owns a broad slice of autonomous behavior
- the task bridge in `map_test.py` is already good enough to drive action presentation from authoritative execution


## Current Gaps

These are the main implementation gaps:

- `render.action` is still a tiny vocabulary
- many live task kinds have no first-class presentation family
- manual control currently only drives:
  - `move`
  - `select_target`
  - `attack_target`
  - `interact_target`
  - `talk_command`
- the client does not yet drive:
  - `work_on_target`
  - `pickup_target`
  - `use_item`
- most non-combat actions are inferred indirectly instead of being declared explicitly by the backend
- some systems are still partial:
  - `systems/interaction/resolver.py` is still scaffold-level
  - `loot_after_kill` is still a placeholder task outcome


## Main Advice

Do not implement this as one hardcoded Godot branch per task kind.

That will turn into a maintenance trap very quickly.

Implement it as:

1. `task kind / semantic action`
2. `presentation family`
3. `clip set + props + VFX`

The key rule should be:

- backend decides what action is happening
- Godot decides how that action is blended and shown

That means the project needs a stable action-presentation contract.


## Action Inventory Already Present

The repo already contains these meaningful action groups.

| Group | Actions already present in repo | Maturity |
| --- | --- | --- |
| Manual semantic control | `move`, `look`, `jump`, `sprint`, `select_target`, `inspect_target`, `attack_target`, `work_on_target`, `interact_target`, `pickup_target`, `use_item`, `talk_command` | Schema is present, client only uses part of it |
| Movement | `move_to_place`, `approach_target`, `follow_target`, `return_home`, `return_to_group` | Live |
| Inventory / provisioning | `withdraw_item`, `store_item`, `equip_item`, `gather_material`, `craft_item`, `ensure_required_tool` | Live / medium |
| Occupation work | `chop_wood`, `fish_work`, `farm_work`, `gather_work`, `build_work`, `hunt_work`, `heal_work`, `trade_run`, `patrol_area` | Live / medium |
| Construction | `designate_build_site`, `build_project` | Live / medium |
| Survival | `fetch_water`, `eat_food`, `sleep`, `seek_shelter`, `flee_target` | Live |
| Social | `socialize`, `talk_to_target`, `warn_target`, `call_for_help`, `help_target`, `deliver_item`, `escort_target`, `thank_helper`, `comfort_target`, `report_crime`, `challenge_target`, `seek_mate`, `mate_with_target` | Live / medium |
| Combat | `attack_target`, `chase_target`, `retreat_from_target`, `guard_area`, `guard_target`, `hold_position`, `finish_hunt`, `loot_after_kill`, `protect_target`, `intercept_target` | Live, with some shallow branches |
| Strategic | `acquire_weapon`, `move_to_ambush_point`, `wait_in_hiding`, `recruit_ally`, `steal_from_container`, `escape_area`, `scout_area`, `protect_home`, `gather_food_buffer` | Live / first-pass |


## What This Means

The project already has enough action depth to justify a proper presentation layer.

The correct next step is not:

- add a few more one-shot clips to `incarnation_human.gd`

The correct next step is:

- formalize action families
- map all live task kinds into those families
- drive Godot from the family descriptor


## Recommended Presentation Model

Every actor should be presented through five layers:

### 1. Locomotion

Continuous lower-body state:

- `idle`
- `walk`
- `run`
- `flee`
- later: `strafe`, `backpedal`, `crouch_walk`, `carry_walk`

### 2. Stance

Longer-lived posture / readiness state:

- `relaxed`
- `combat`
- `work`
- `carry`
- `hurt`
- `guard`
- `sleep`
- `stealth`

### 3. Action Family

Short or looping upper-body / full-body intent:

- `combat_melee`
- `combat_finish`
- `work_chop`
- `work_build`
- `work_farm`
- `work_fish`
- `work_gather`
- `equip`
- `interact`
- `carry`
- `heal`
- `consume`
- `rest`
- `talk`
- `emote`
- `social_special`
- `guard`
- `flee`
- `stealth`
- `loot`

### 4. Prop / Equipment Layer

Visual attachments:

- weapon
- tool
- carried item
- bandage / food / cup

### 5. FX / UI Layer

Readable gameplay feedback:

- hit flash
- speech marker
- work sparks / dust
- heal marker
- theft / loot indicator
- build progress marker


## Do Not Map Task Kind Directly To Clip

Use this instead:

`task kind -> presentation family -> clip choice`

Examples:

- `build_project` -> `work_build` -> `hammer_loop`
- `heal_work` -> `heal` -> `bandage_apply`
- `warn_target` -> `talk` or `emote` -> `point_and_talk`
- `steal_from_container` -> `interact` or `stealth` -> `crouch_open`
- `fetch_water` -> `consume` or `interact` -> `drink_from_source`

This gives much better reuse and keeps the system scalable.


## Proposed Render Payload

The current `render` payload should grow from a light hint into a small presentation contract.

Suggested shape:

```json
{
  "server_tick": 1234,
  "server_time": 61.7,
  "velocity_world": { "x": 0.0, "y": 0.0 },
  "speed": 0.0,
  "moving": false,
  "facing_yaw": 1.57,
  "locomotion": "idle",
  "stance": "work",
  "action_family": "work_build",
  "action_name": "build_project",
  "action_phase": "perform",
  "tool_kind": "hammer",
  "carried_kind": "",
  "target_kind": "construction_project",
  "target_id": "project_need_0001",
  "loop": true,
  "interruptible": true,
  "progress_01": 0.42,
  "action_speed": 1.0,
  "action_instance_id": "1234:human_07:build_project",
  "action_started_tick": 1234,
  "action_until_tick": 1246,
  "action": "build"
}
```

Important notes:

- keep `action` as a compatibility fallback during migration
- add `action_instance_id` so the client can avoid replaying the same one-shot twice
- `action_family` is the most important new field
- `action_name` can remain task-kind-shaped for debugging
- `tool_kind` and `carried_kind` are necessary for believable work animations
- `progress_01` is especially useful for:
  - building
  - crafting
  - fishing
  - healing
  - paired social actions


## Recommended Action Family Mapping

Start with these family mappings.

| Task kinds | First presentation family | First-pass visual plan |
| --- | --- | --- |
| `move_to_place`, `approach_target`, `follow_target`, `return_home`, `return_to_group`, `move_to_ambush_point`, `scout_area` | locomotion only | walk/run/flee with facing and target-aware turns |
| `withdraw_item`, `store_item`, `deliver_item`, `steal_from_container`, `loot_after_kill`, `trade_run` | `interact` / `carry` | reach, pickup, open, stow, carry, exchange |
| `gather_material`, `chop_wood`, `gather_work` | `work_gather` / `work_chop` | chop / forage loop with tool prop |
| `fish_work` | `work_fish` | cast / reel / wait loop |
| `farm_work` | `work_farm` | hoe / gather crop loop |
| `build_work`, `designate_build_site`, `build_project` | `work_build` | inspect site, place marker, hammer/build loop |
| `craft_item`, `equip_item`, `acquire_weapon`, `use_item` | `interact` / `equip` | craft bench placeholder, equip gesture, item-use gesture |
| `heal_work`, `help_target` | `heal` | kneel / bandage / assist |
| `fetch_water`, `eat_food` | `consume` | drink / eat |
| `sleep` | `rest` | sit / lie / sleep loop |
| `seek_shelter`, `flee_target`, `retreat_from_target`, `escape_area` | `flee` / locomotion | run/flee, panic posture |
| `socialize`, `talk_to_target`, `warn_target`, `call_for_help`, `thank_helper`, `comfort_target`, `report_crime`, `challenge_target`, `recruit_ally` | `talk` / `emote` | talk, point, beckon, shout, reassure |
| `seek_mate`, `mate_with_target` | `social_special` | first pass should reuse talk/emote, then later add paired clips |
| `attack_target`, `chase_target`, `intercept_target`, `finish_hunt` | `combat_melee` / `combat_finish` | attack, chase, butcher/loot finish |
| `guard_area`, `guard_target`, `hold_position`, `protect_target`, `protect_home`, `patrol_area` | `guard` | guard idle, patrol walk, ready stance |
| `wait_in_hiding` | `stealth` | crouch/low idle if clip exists, else subdued idle fallback |


## Implementation Principle

Every live task kind should have:

- a valid presentation family
- a fallback clip path
- a prop policy
- a debug-visible descriptor

That should happen before bespoke polish.


## Backend Implementation Plan

## Phase 1: Formalize The Presentation Layer

Create a new backend module instead of growing more ad hoc logic in `map_test.py`.

Recommended new package:

- `at_the_beginning/systems/presentation/schema.py`
- `at_the_beginning/systems/presentation/catalog.py`
- `at_the_beginning/systems/presentation/runtime.py`
- `at_the_beginning/systems/presentation/mappers.py`

Responsibilities:

- define the render action schema
- map task kinds to presentation families
- manage short-lived one-shots and looping action descriptors
- expose compatibility helpers for `map_test.py`

Short-term fallback:

- keep the first pass in `map_test.py` if speed matters
- but do not keep expanding `_set_actor_render_action()` as the long-term home


## Phase 2: Emit Presentation From Real Execution

Presentation should come from the actual authoritative execution path:

- manual control events
- task execution
- combat outcomes
- talk outcomes
- construction progress

That means:

- task execution should set `action_family`, not just `current_intent`
- manual actions should emit the same families the autonomous path uses
- combat should keep explicit one-shots
- non-combat actions should stop being inferred only from movement or HP deltas

For example:

- `build_project` should emit `work_build`
- `heal_work` should emit `heal`
- `trade_run` should emit `carry` during travel and `interact` during trade
- `warn_target` should emit `talk` or `emote`
- `wait_in_hiding` should emit `stealth`


## Phase 3: Expand Render Hint Export

Update the actor render export path so `render` includes:

- `stance`
- `action_family`
- `action_name`
- `action_phase`
- `tool_kind`
- `carried_kind`
- `loop`
- `progress_01`
- `action_instance_id`
- `action_until_tick`

Keep these current fields:

- `locomotion`
- `velocity_world`
- `speed`
- `moving`
- `facing_yaw`
- `action_started_tick`


## Phase 4: Keep Backward Compatibility During Migration

Do not break the current client immediately.

Keep:

- `render.action`
- current combat fall/get-up behavior
- current locomotion hints

Migration rule:

- new client path reads `action_family`
- old path falls back to `action`


## Phase 5: Manual Control Expansion

The client should start using the semantic actions that already exist in the control schema.

Next actions to wire:

- `work_on_target`
- `pickup_target`
- `use_item`

Recommended behavior:

- trees / stone / worksites / farms should prefer `work_on_target`
- loose loot or nearby dropped goods should use `pickup_target`
- bandages / food / water / equipped tools should use `use_item`

This is important because:

- autonomous NPC behavior and manual player behavior should use the same presentation families
- otherwise the incarnation path will always lag behind the simulation path


## Godot Implementation Plan

## Phase 1: Replace String-Only Action Matching

Right now the client mostly reacts to:

- `locomotion`
- `action`

That is not enough for the richer task vocabulary.

Add a descriptor-driven method in `incarnation_human.gd`, such as:

```gdscript
func apply_action_descriptor(render: Dictionary) -> void:
	pass
```

Keep the current methods as wrappers:

- `play_motion`
- `play_attack`
- `play_pain`
- `play_fall`
- `play_get_up`
- `play_talk`

Then add first-pass family methods:

- `play_interact`
- `play_work`
- `play_heal`
- `play_consume`
- `play_rest`
- `play_guard`
- `play_carry`
- `play_emote`
- `play_stealth`


## Phase 2: Separate Lower Body And Upper Body Conceptually

Even if the first pass is still clip-based, treat the animation model as:

- lower body locomotion
- upper body / full body action

That makes later migration to:

- `AnimationTree`
- additive layers
- weapon/tool overlays
- IK

much easier.


## Phase 3: Add Tool And Carry Props

The first big readability upgrade will come from tools and carry props.

Priority props:

- `axe`
- `hammer`
- `hoe`
- `fishing_rod`
- `spear`
- `basket`
- `bandage`
- simple food / drink placeholder

These do not need perfect art on day one.

Simple low-poly placeholders are enough to make actions legible.


## Phase 4: Add Family-Specific FX

Priority VFX / feedback:

- build dust / impact puffs
- gather hit spark / wood chip effect
- heal marker
- talk bubble / speech icon
- theft / loot icon
- guard target / patrol marker
- sleep / rest marker


## Phase 5: Keep Client Prediction Narrow

For the controlled character:

- keep local prediction for locomotion
- let one-shot actions be confirmed by backend action descriptors

Best practice:

- allow optional local anticipation for input feel
- reconcile using `action_instance_id` or `action_started_tick`

This avoids duplicated attack/build/heal/talk replays.


## Clip Acquisition Backlog

The current clip set is enough for the baseline, but not for the full task vocabulary.

Priority clip backlog:

- `interact_open`
- `pickup_ground`
- `carry_idle`
- `carry_walk`
- `chop_loop`
- `mine_loop`
- `hammer_build`
- `hoe_farm`
- `fish_cast`
- `fish_reel`
- `heal_bandage`
- `eat`
- `drink`
- `sit_rest`
- `sleep_loop`
- `guard_idle`
- `point_talk`
- `beckon`
- `threaten`
- `comfort`
- `loot`
- `steal`
- `crouch_idle`
- `crouch_interact`

The first implementation pass should not block on having all of these.

Use family fallbacks first.


## Recommended Delivery Order

## Milestone 1: Contract And Debugging

Deliver:

- render action schema
- task-kind to family mapping
- debug overlay that shows:
  - active task kind
  - locomotion
  - stance
  - action family
  - tool kind
  - progress

Success means:

- every live task kind resolves to a valid presentation family


## Milestone 2: Work / Interact / Carry

Deliver:

- `work_on_target`
- `pickup_target`
- `use_item`
- first-pass work/interact/carry clips
- tool props

Success means:

- woodcutting, farming, building, gathering, storing, delivery, and looting are visibly distinct


## Milestone 3: Survival And Social

Deliver:

- drink / eat / sleep presentation
- talk / warn / help / comfort / thank / challenge presentation
- direct talk and ambient talk animation triggers

Success means:

- NPC life reads as social behavior, not just motion between points


## Milestone 4: Guard / Strategic / Stealth

Deliver:

- guard stance
- patrol presentation
- stealth placeholder
- recruit / scout / escape / ambush presentation

Success means:

- strategic behaviors become readable before deep tactical AI polish


## Milestone 5: Polish

Deliver:

- better blending
- more family-specific clips
- target-aware facing / look-at
- interaction anchors
- optional IK


## What Should Be Deferred

These should not block the first broad implementation pass:

- perfect IK
- perfect paired animations
- bespoke clip for every single task kind
- full interaction-system rewrite
- deep loot-after-kill polish before the gameplay logic is expanded


## Definition Of Done

This effort is in good shape when:

- every live task family in `at_the_beginning/systems/tasks/families/` produces a readable presentation family
- manual control and NPC control use the same action families
- the client no longer has to guess most non-combat actions from HP changes or movement alone
- work actions visibly use tools or props
- social / survival / construction actions are readable from a distance
- the debug UI can explain why any actor is playing a given action


## Final Recommendation

Treat this as a `shared action language` project, not an `animation import` project.

The repo already has enough backend action depth that the right investment is:

- formal action descriptors
- action family mapping
- tool/carry presentation
- phased clip coverage

If we do that first, implementing all the advanced actions becomes manageable.

If we skip that and keep adding one-off client rules, the action system will become fragile very quickly.
