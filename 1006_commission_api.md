# Commission API: what the client can see

Routes (POST, `X-Eden-Session` header, the `/inventory/transfer` envelope: `protocol_version`, `world_epoch`, `possession_epoch`, `controller_id`, `command_id` UUID; 202 `received`, outcome via `GET /commands/{command_id}`): `POST /commission/request` (optional `smith_id`, `recipe_id`), `POST /commission/cancel {order_id}`, `POST /commission/collect {order_id}`. Read model: `GET /commission/state?controller_id=` (404 if that controller possesses nobody).

## Two kinds of outcome
A **rejected** command (`status: "rejected"`, `reason`) means the request itself was invalid or impossible right now; nothing happened. An **applied** command means the game processed it, and a refusal by the smith is an applied result: `ok: true`, `accepted: false`, a `code` and the `line` he says.

### Applied results (`status: "applied"`)
| Command | Result fields | Codes |
| --- | --- | --- |
| request | `order_id, state, code, accepted, duplicate, line` | `accepted` (state `reserved`, `accepted: true`); `refused_no_materials`, `refused_no_forge`, `refused_cannot_afford`, `refused_busy`, `refused_distrust` (state `refused`, `accepted: false`); **`duplicate_open_order`**: the same customer already has an open sword order with this smith. It is applied, `ok: true`, `accepted: false`, `duplicate: true`, `order_id` is the existing order, `state` is that order's current state, nothing is reserved twice. The same result is returned when the identical `command_id` is replayed. |
| cancel | `order_id, state: "canceled", line` | refund is complete |
| collect | `order_id, state: "delivered", receipt, duplicate, line` | collecting twice returns the stored receipt with `duplicate: true`; no second sword |

### Rejected (`status: "rejected"`, `reason`)
- Authorization (the command is not even queued; HTTP 400): `invalid_command_envelope`, `unsupported_protocol`, `stale_world_epoch`, `stale_possession_epoch`, `human_control_required`, `outside_placed_map`, `invalid_command`, `command_id_conflict`, `command_capacity_reached`.
- Execution: `not_controlling`, `not_a_smith`, `out_of_range` (more than 16 units from the smith), `blocked` (a wall is between), `unknown_order` (not yours or no such order), `invalid_transition` (cancel after work started, cancel twice), `customer_inventory_full` (collect; the order stays `ready`), `customer_unavailable`, `not_your_order`, `delivery_failed`, `smith_unavailable`, `unknown_recipe`, `cannot_commission_yourself`.

## Order states
`reserved` (accepted; materials and payment held in escrow) -> `working` (starts as soon as the smith stands at his forge anchor; progress only counts there) -> `ready` -> `delivered`. Terminal: `refused`, `canceled`, `failed` (`forge_unavailable`, `smith_unavailable`, `no_materials`, `customer_gone`; full refund).

**Cancel while reserved is reachable but short.** If the smith is already at his forge, `reserved` becomes `working` within one tick (50 ms) and a cancel then returns `invalid_transition`; during that window it is not practically reachable. It is reachable whenever the smith has to walk to the forge first (at night, or after he was elsewhere): the order stays `reserved` for the walk (up to about 40 s) and `commission_cancel` succeeds (`tests/test_smith_loop.py::test_cancel_while_reserved_is_reachable_when_the_smith_is_away_from_the_forge`). Once `working`, cancel is not allowed (decision D6).

## The smith waits for a ready sword
While an order is `reserved` or `working` the smith stays at, or walks to, his forge anchor whatever the clock says. **A `ready` order keeps holding him there until it is delivered, for at most `ready_hold_ticks` (2400 ticks, 2 minutes)**; after that he follows his schedule again and the sword stays `ready` (collect then needs the customer to find him within 16 units and without a wall between). Reason: a time block is 600 ticks and a sword takes 900, so orders often become ready at dusk or night, when his schedule says talk or sleep; before this rule he walked to his bed (about 50 units away) and a collect from where the customer stood answered `rejected out_of_range`. After delivery the hold ends at once.
The client should still send `collect` only when the customer is within 16 units of the smith; the smith standing at the forge is now the expected place.

## Greeting and lines
`GET /commission/state` returns `line` (the latest order's outcome line) and `greeting` (or `null`). A delivered order is `delivered` for 10 s of game time, then `followup_delivered` (deterministic variant; persisted `delivered_tick`, so it survives Save/Continue). `greeting.code` is `followup_delivered` if the smith ever delivered to you, else `followup_gift` if he remembers a divine gift.

## Frame
`/frame` agent entries of roster residents carry `roster_key` (`smith`, `builder`, `gatherer`, `iven`, `elsa`); legacy frames do not have the key.
