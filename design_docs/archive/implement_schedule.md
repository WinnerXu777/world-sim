# Schedule Module Plan

## Purpose

`systems/schedule` should become the default ordinary-life layer for residents.

It answers:

- what a resident should do when they are not starving, fleeing, or executing a special plot
- how settlements feel busy, sleepy, social, guarded, or quiet across the day
- how occupation defines ordinary life without requiring an LLM call
- how personality biases that occupation-driven routine selection

This module should be cheap, mostly deterministic in structure, and always lower priority than:

- reflex
- urgent reaction
- active special plan execution
- survival-critical needs


## Core Rule

Use schedule as the baseline life rhythm, not as the highest authority.

Recommended priority stack:

1. reflex
2. urgent reaction
3. active plan / special goal execution
4. survival-critical needs
5. schedule default
6. idle fallback

This means schedule should only matter when nothing more important is currently overriding the resident.


## Scope

First version should stay local and mostly deterministic in structure.

It should not depend on an LLM.

It should use:

- current tick / time of day
- occupation-driven routine preferences
- simple resident personality bias
- weighted probabilistic routine choice
- whether the resident has a known home or safe anchor
- whether the resident is already under a stronger override

It should not yet try to own:

- complex profession systems
- economic production chains
- deep settlement management


## First Routine Kinds

Recommended initial routine kinds:

- `sleep`
- `stay_home`
- `return_home`
- `wander_local`
- `gather`
- `work_site`
- `patrol`
- `guard`
- `socialize`
- `rest`
- `visit_water`


## Time Blocks

Use broad deterministic time blocks first:

- `dawn`
- `day`
- `dusk`
- `night`

Default routine tendencies:

- `dawn`
  - `visit_water`
  - `gather`
  - `wander_local`
- `day`
  - `work_site`
  - `gather`
  - `patrol`
  - `wander_local`
- `dusk`
  - `socialize`
  - `return_home`
  - `rest`
- `night`
  - `sleep`
  - `stay_home`
  - `guard`


## Occupation, Personality, And Variety

Schedule should be shaped primarily by occupation, and then modified by personality.

Use:

- deterministic candidate generation
- probabilistic candidate selection

That means residents still get sensible routines for the time block, but they do not always pick the exact same top option.

Recommended policy:

- expected routine usually wins
- off-routine variation happens occasionally
- disciplined or cautious residents stay more consistent
- curious or sociable residents deviate more often
- occupation determines the main candidate set

Example biases:

- high `caution`
  - prefers `return_home`, `stay_home`, `guard`
  - avoids long wandering
- high `sociability`
  - prefers `socialize`
- high `protectiveness` or `loyalty`
  - prefers `guard` or `patrol`
- high `curiosity`
  - prefers `wander_local`
- high `discipline`
  - prefers `work_site`
- high `resourcefulness`
  - prefers `gather`
- high `fearfulness`
  - prefers `stay_home` and `sleep`


## Owned Resident Data

Recommended resident-side fields:

- `schedule_profile`
  - stable default schedule preferences
  - time-block routine preferences
  - home-anchor preference
  - `stability`
  - `novelty_bias`
  - `commitment_window_ticks`
- `schedule_state`
  - current routine
  - last refresh tick
  - last time block
  - last reason

This should stay lightweight and JSON-friendly.


## Module Layout

Recommended files:

```text
at_the_beginning/
  systems/
    schedule/
      __init__.py
      catalog.py
      schema.py
      lifecycle.py
      resolver.py
      prompt_view.py
      ops.py
      design.md
      future.md
```

Ownership:

- `catalog.py`
  - routine definitions
  - time-block defaults
  - bias tables
- `schema.py`
  - schedule profile and routine record builders
- `lifecycle.py`
  - ensure schedule state
  - refresh cadence
  - set and clear current routine
- `resolver.py`
  - tick-to-block conversion
  - candidate routine selection
  - routine scoring
  - weighted probabilistic choice
- `prompt_view.py`
  - schedule summary and prompt-facing export
- `ops.py`
  - stable integration surface


## Runtime Wiring Plan

The first scaffold does not need to mutate the main runtime yet.

Planned later wiring:

- `resident_store.py`
  - ensure `schedule_profile` and `schedule_state` exist
- `human_runtime.py`
  - optional schedule summary in resident prompt payloads
- main sim loop
  - when no higher-priority override exists, ask schedule for a default routine

This should be introduced only after the scaffold is stable.


## Interaction With Other Systems

- `survival`
  - overrides schedule when hunger, thirst, or shelter become critical
- `goal`
  - special goals can temporarily outrank schedule
- `planning`
  - active plans can suspend schedule
- `personality`
  - biases occupation-driven routine choice
- `occupation`
  - supplies the primary routine blueprint
- `talk`
  - can interrupt schedule locally in human mode
- `inventory`
  - future work/gather routines may eventually consume or move items


## First Scaffold Goal

The first scaffold should provide:

- a stable routine ontology
- a stable schedule profile schema
- a current-routine state schema
- deterministic time-block routing
- occupation-led, personality-shaped weighted selection
- prompt/export helpers

It should not yet:

- drive movement directly
- assign jobs to all residents
- rewrite the sim loop


## Future Expansion

Likely next steps after scaffold:

1. ensure schedule data on resident creation/load
2. expose current schedule summary in prompt payloads
3. use schedule as default fallback behavior when no stronger override exists
4. later add profession, settlement, market, and territory-aware routines


## Selection Model

The intended first selection model is:

1. build valid routines for the current time block
2. get occupation-driven candidates for that block when occupation exists
3. score them deterministically from:
   - occupation blueprint
   - personality
   - lightweight local context
4. compute resident-specific:
   - `stability`
   - `novelty_bias`
5. usually keep the expected top routine
6. sometimes sample a different valid routine using weighted choice

This should create:

- believable village rhythm
- repeatable structure
- occasional surprises
- lower robotic repetition

Important:

- variation should happen on schedule decision points, not every tick
- current routine should still have stickiness through `commitment_window_ticks`
