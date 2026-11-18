# 1008 `defend` Phase 1: the combat modifier hook and the restraint flag ([GAP], harness plane, design only, 2026-10-09)

Author: 8d998a ("1008latenight"). For c3's approval before any code. Reads `1008_defend_design.md` (latenight2) section 2 Phase 1 and section 3. Nothing here changes behaviour while the flag is off: the hook is `None`, the new column is 0 for every existing row.

## 1. What I read

* `resolve_human_attack_intents` (`systems/combat/resolver.py`) is the only human-vs-human damage path. Callers: `instincts_and_tools.py:1337` (autonomous and manual), `map_test.py:3053` and `3278` (task and direct attack), `systems/combat/ops.py:99`. Damage is accumulated per target (`human_damage[target_slot] += attack_damage`), applied once through `apply_human_damage`, threat +40 on the target. Entity (creature) targets use a separate accumulator.
* Movement choke points: the roster driver and `instinct_move` write positions, then the post-step hook `apply_motion_limits` (`systems/roster/motion.py`) limits each non-controlled human to 1.5 units from `final_positions[uid]`, the position it ended the previous tick at, and slides it. Dormancy (`harness/dormancy.py`) already shows the pattern for "this row does not move": `freeze` before the registry, `thaw` at the end of the tick, shifting by the origin difference when a re-base ran mid-tick.
* `h_tensor` columns 30 and 31 are reserved (29 is `H_SPACE`).

## 2. The mitigate hook (combat)

One optional hook with a registry, not a new parameter on four call sites:

```python
# systems/combat/modifiers.py  (new, ~25 lines)
COMBAT_MODIFIER = None          # or a callable; set by the model plane's installer, one at a time
# signature: (h_tensor, attacker_slot, target_slot, damage) -> (target_slot, damage)
```

In the resolver, after the range and wall checks and before `human_damage[target_slot] += ...`: if `COMBAT_MODIFIER` is set and the target is a human, call it; accept the answer only if the returned slot is a valid live human (else keep the original pair) and `0 <= damage`. The threat delta still goes to the ORIGINAL target (they were attacked); the damage goes to the returned slot (a guard that takes the hit) with the returned amount (a weapon bonus, a halving). The outcome row gains `"modified": {"target_slot": original, "damage": original}` only when the hook changed something, so flag-off outcomes are byte-identical.

Rules for the hook owner (the model plane's `GuardPosts`): pure function of the tensors and its own books, no randomness that is not seeded from the tick, no side effects on the tensors (the resolver applies damage), and no chaining (the returned slot is final; the resolver does not call the hook twice for one intent). Entity targets (creatures) are not offered to the hook in Phase 1 (Phase 2 adds `target_kind`).

Why a module registry and not an engine attribute: the resolver is called from engines and from tests without one; the registry is read at call time, `None` costs one global lookup, and the model plane sets it in its install step like a dispatch hook. Tests that set it restore it with `addCleanup`.

## 3. Restraint (`arrest_or_restrain`)

* `harness/restraint.py`, flag `EDEN_RESTRAINT` (default off, needs nothing else). New column constant `H_RESTRAINED = 30` in `genesis_config.py` (one line): **ticks remaining**, not an absolute tick (float32 is exact only below 2^24 ticks, about 9.7 real days at 20 Hz). 0 means free, which is what every existing row holds.
* `restrain(engine, slot, ticks)` and `release(engine, slot)` are the whole API; the model plane's `GuardPosts`/justice decide who and for how long. A controlled (player) human cannot be restrained in Phase 1 (`WindowManager.controlled_slots()` is the test); whether non-player residents may hold a player is a design question for the user, not for this step.
* Effect, enforced in the engine so no driver has to cooperate: (1) the row's position does not change while `H_RESTRAINED > 0`: `step()` records the positions of restrained rows next to the dormancy freeze and writes them back after the post-step hooks, with the same origin-difference shift; (2) the counter decrements by 1 per tick; (3) the resolver skips intents whose attacker is restrained (a read of column 30, 0 for everyone today). Needs, damage, ageing, infection and death all keep running; a restrained resident can starve.
* Open ordering risk, found by reading `apply_motion_limits`: it runs inside the post-step hooks and records `final_positions`; if the pin were applied after it, the next tick would start from the un-pinned position and walk back 1.5 units per tick (a jitter). The pin must run before `apply_motion_limits` (a post-step hook registered ahead of it) and update `final_positions` itself, or the hook must reset the entry. A test for it is part of the work: a restrained resident's position is bit-identical over 200 ticks with the anchor driver and the instincts trying to move it, on an authored map.
* Model plane side (latenight2): a gate like `actions/dormancy_gate.py` so a restrained slot does not plan or walk (saves work, does not decide correctness).
* Save/restore: the column is part of `h_tensor`, which the world snapshot already saves whole. Re-base: no coordinates are stored in the column. Dormancy: a dormant row is frozen bit for bit, so its counter freezes too (restraint pauses while the chunk is away; acceptable, noted).

## 4. Files and cost

`genesis_config.py` (+1 constant), `systems/combat/modifiers.py` (new), `systems/combat/resolver.py` (+about 14 lines), `harness/restraint.py` (new, about 70 lines), `map_test.py` `step()` (+about 6 lines next to the dormancy freeze/thaw), `harness/engine_hooks.py` (hook registration). Tests: hook default None byte-identical outcomes over randomized intents (old resolver kept in the test, as for the scaling work); redirect and halving cases; invalid redirect ignored; restraint pin bit-identical over 200 ticks with movers active; counter expiry; attacker restrained cannot attack; player cannot be restrained; save round trip; re-base while restrained; dormancy interaction. Gates: strict goldens x3 + window-hook + window-walk and the s1 digests unchanged (column 0 and hook None by construction). Size S to M, one commit per piece.

## 5. Decisions needed

1. Approve the hook shape (section 2) and that it lives in a new `systems/combat/modifiers.py` registry (the resolver is not mine; I need the OK to edit it, and `map_test.py` `step()` for the pin).
2. Restraint of a player's body: refused in Phase 1 (my default) or allowed. User question via c3.
3. Whether restraint should pause while dormant (my default, simplest) or tick down on wake like the needs catch-up.

## 6. As built (approved by c3 on 2026-10-09)

* `systems/combat/modifiers.py` (`COMBAT_MODIFIER`, `set_modifier`, `restraint_enabled`); `resolve_human_attack_intents` offers every human-vs-human hit to the modifier after the range and wall checks, validates the answer (live human, finite damage >= 0, a raising modifier is ignored), puts the damage on the returned slot and the threat on the original target (also when the damage is 0 or redirected), and adds `modified`, `damage_slot` and `damage` to the outcome only when the answer changed something. With no modifier and the flag off, `tests/test_combat_modifier.py` shows the result and both tensors bit-identical to the resolver of before (`tests/fixtures/combat_resolver_before_defend.py`, verbatim) over 300 randomized crowds.
* `harness/restraint.py`, flag `EDEN_RESTRAINT`, `H_RESTRAINED = 30` (ticks remaining; human column 31 is now the only free one). `restrain`, `release`, `is_restrained`; `Engine.step` calls `capture` next to the dormancy freeze and `pin` right after the id sync and before the post-step hooks, so `apply_motion_limits` records the pinned position. A restrained attacker's intents are skipped (flag on only). A player's body is refused and freed. Tests: `tests/test_harness_restraint.py` (position bit-identical for 40 ticks, counter, needs keep running, flag off inert, re-base shift, replaced row, and the real-village ordering test: 120 ticks with the anchor driver trying to walk the resident, `final_positions` equal the pinned position, the resident walks again once free).
* Not covered yet: restraint pausing while dormant is by construction (the dormancy thaw writes the whole row back, counter included) but has no test of its own; the model plane's gate (no planning for a restrained slot) is latenight2's.
