# Tasks Future

Current limitations:
- The module now has a stable bridge contract, but still depends on `map_test.py`
  to implement that bridge against the live world state
- Only the first medium set of occupation loops (`woodcutter`, `fisherman`,
  `farmer`, `guard`, `builder`, `gatherer`, `hunter`, `healer`, `trader`) is
  task-driven so far, and several of those are still intentionally narrow
- Only the first baseline survival tasks (`fetch_water`, `eat_food`, `sleep`,
  `seek_shelter`, `flee_target`) are live so far
- Social tasks are now live for routine socialize, talk follow-through,
  warning, help, delivery, gratitude, escort, and courtship / mating, but
  they still lack deeper kin/faction semantics and longer multi-turn support
- Combat is now task-driven for attack, chase, retreat, area guard, protect,
  intercept, and first-pass hunt finishing, but it still lacks richer tactical
  coordination and meaningful loot-after-kill
- Interruption, suspension, and resumption now exist, but the policy is still
  simple and source/priority driven rather than fully explicit and debuggable
- Tasks are now emitted from the first planning / strategic path and from talk
  follow-through, but the coverage is still partial
- There is no station reservation, worksite reservation, or shared household task ownership
- `strategic` is live for the first plan-step translation, but it still only
  covers a medium subset of plan ops and plan kinds rather than the full
  planning vocabulary

Nuances:
- `tasks` should be the master executor, not the master thinker
- Higher-level systems should create tasks, but task execution itself should
  stay unified in one layer
- Reflexes still belong outside the task layer because they must happen
  instantly before any queue or family dispatch
- It is okay for the instinct layer to keep vital-sign ticking and low-level
  state sync while the higher execution behavior migrates into task families
- Survival, reflex, urgent reactions, and player control must still be able to
  interrupt or override ordinary work tasks
- Routine profession work and strategic plan execution should share task
  primitives where possible instead of becoming two completely separate systems
- Player-controlled human movement / attack now live outside the instinct
  registry, but they still use direct control runtime execution rather than the
  resident task queue, which is a deliberate manual-control exception

Suggested next elaborations:
- Keep shrinking and standardizing the task-world bridge until runtime code only exposes a small durable interface
- Deepen interruption rules for survival, escalation, social follow-through, and direct player interaction
- Expand plan-emitted task chains for revenge, theft, ambush, protection, escape, and scouting
- Deepen the new richer-task bridge hooks so support signaling, crime reports,
  and protective combat can coordinate more than one nearby resident at a time
- Add player-incarnation hooks for manual task assistance and queued crafting/building actions
- Deepen the new task-driven profession loops so they use more real resources, targets, and shared storage
- Continue deepening the live survival, social, and combat families through the
  shared dispatcher instead of adding new instinct-side execution paths
- Add explicit debug/status export for paused tasks, resume candidates, and current family ownership
