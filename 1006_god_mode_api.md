# God mode API (P5, backend)

Status: implemented and tested (`tests/test_god_mode.py`, live `tools/live_smoke_god.py` 31/31 on the four-map world). All POST routes need the `X-Eden-Session` capability header like every other POST. Code: `at_the_beginning/systems/god/`.

## Envelope and the possession state machine
God powers are typed commands, queued like `/inventory/transfer`: `POST` returns **202** `{"status": "received", "command_id", ...}`; the outcome is `GET /commands/{command_id}` (`applied` or `rejected`, `reason`). Idempotent by `command_id` (same id and payload returns the stored receipt; same id with another payload is `command_id_conflict`). Rejected early with HTTP 400 when authorization fails.

```json
{ "protocol_version": 1, "world_epoch": "<current>", "controller_id": "<id>", "command_id": "<uuid>", ...power fields }
```
- There is **no `possession_epoch`**: god mode is a controller that possesses nobody.
- An embodied controller is refused with `release_possession_first`. Flow: `POST /control/release` -> god commands -> `POST /control/claim` (new `possession_epoch`; input with the old one is `stale_possession_epoch`).
- After release the resident is autonomous again at once (roster driver, schedule).
- `stale_world_epoch` after New Game / Continue: re-read `/bootstrap` for the new epoch.
- Every outcome carries `god_event_id` (`g_NNNNNN`, persisted counter, never reused) when something happened; `event_id` in the result is the command's own id and is unrelated.

## Powers
| Route | Body fields | Notes |
| --- | --- | --- |
| `POST /god/heal` | `target_id` (human id), `amount` 1..100 (default 100), `dry_run` | Living residents only. HP never exceeds 100. A dead resident is `dead_resident` (no resurrection); unknown id `unknown_resident`. Full health: applied, `healed: 0`, `god_event_id: null`, nothing remembered. |
| `POST /god/spawn_resource` | `resource` in `iron_ingot, wood, food, water, coin`; `quantity` 1..20 (coin 1..200); `target_kind` `resident` or `container`; `target_id` (human id, or a container entity id such as `smith:output_chest`, `village:supply_crate`); `dry_run` | Not range limited. All or nothing: `no_room` when it does not fit. Rejections: `resource_not_allowed`, `invalid_quantity`, `invalid_target_kind`, `unknown_resident`, `dead_resident`, `unknown_container`, `not_a_container`. |
| `POST /god/weather` | `weather` in `clear, rain, humid, storm, wind, heat, dry, cold` (the nature system's kinds), `duration_ticks` (default 600), `dry_run` | Sets `engine._nature_state.weather` (already persisted and already in `/frame` as `nature.weather`). The random disaster cycle stays off on roster maps. `dry_run` returns `affected_residents`, `affected_area`, `effects`, `reversible`. Same weather again: `changed: false`. **On a roster map the weather ends by itself**: after `duration_ticks` (default 600 ticks, 30 s) of game time a post-step hook (`systems/god/expiry.py`) sets it back to `clear` and records one `weather_changed` event (`weather: "clear"`, `expired: true`); the end tick is kept in the saved god ledger (`inventory_state["god"]["weather"]`), so Continue mid-weather still ends it; paused time delays the end; a later `/god/weather` (including `clear`) replaces or cancels the pending end. The disaster cycle stays off. |
| `POST /god/time` | `action` `pause` / `resume` / `scale` (+ `scale` 0.5, 1, 2) | Result `{paused, time_scale, tick}`. |

### Pause
Paused = no simulation tick (tick, positions, hunger, schedules, commission work all frozen). Transport and commands keep working: queued commands (god powers, commissions, inventory) drain at each paused step (about 20 Hz), so edits apply at that boundary and the frame is rebuilt. Player movement input has no effect. Pause is **not saved**: Continue starts running. `GET /status` -> `god: {paused, time_scale, tick, weather}`.

## Consequences (Gate G)
`divine_gift`, `divine_heal`, `weather_changed` are recorded in resident memory (gift permanent, heal long TTL, weather short) only for **witnesses**: living residents in the same placed map within 80 units of the event (the target always); weather: everyone outdoors (exterior maps). Each event has one causal id; a resident is affected once per id (ledger in `inventory_state["god"]`, saved with the world). Frame events carry the same kinds.

The smith's `GET /commission/state` has `greeting: {code, text} | null`: `followup_delivered` (a delivered sword for this customer) outranks `followup_gift` (he remembers a divine gift).

## Inspect
`GET /god/inspect/{resident_id}` (404 `unknown_resident`): `{name, role, alive, controlled, position, map_id, needs{hp,hunger,thirst,stamina}, routine, goal_anchor, at_anchor, anchors, relationships[], recent_events[], commission_orders[], explanation}`; `explanation` is a short deterministic sentence list (where they are, which anchor and why, open orders, remembered gift).

## Not in v1
No irreversible effect exists, so no checkpoint-before-effect and no confirmation flow beyond `dry_run`. Weather has no gameplay effect beyond the nature growth modifiers. Pause does not freeze the wall-clock possession timeout (5 s without input releases possession, as always).
