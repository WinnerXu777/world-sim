# Local control protocol

The gameplay backend accepts loopback Host names and loopback HTTP(S) browser origins only. Obtain `session_capability` from `GET /bootstrap` and send it as `X-Eden-Session` on every POST (including read-like POST routes). The capability changes on backend restart. Both Godot clients and the browser transport obtain it automatically; a 401 clears their cache without automatically replaying a mutation. This trusts local applications and is not remote authentication. Debug reset remains disabled in gameplay even with a valid capability.

For manual requests against your selected isolated test backend:

```powershell
$edenBootstrap = Invoke-RestMethod http://127.0.0.1:8012/bootstrap
$edenHeaders = @{ 'X-Eden-Session' = $edenBootstrap.session_capability }
Invoke-RestMethod -Method Post http://127.0.0.1:8012/session/save -Headers $edenHeaders -ContentType 'application/json' -Body '{}'
```

Control input/event envelopes still require protocol version 1, world epoch, possession epoch and integer sequence. A capability does not replace those identity checks.

## Identified discrete events

Send a UUID `event_id` on `/control/event`. Godot generates one for each new request before the bootstrap await. If retrying an uncertain request, retain its ID, original epochs and arguments; never assign a fresh ID to a retry. The transport currently does not retry automatically.

An identified event is independent of movement sequencing. A newer movement sequence cannot invalidate a delayed event. Distinct events are consumed in arrival order in the same bounded ingress as movement; this does not reconstruct the player's original chronological order across reordered discrete events. An identified attack stops that session's ingress drain for the tick so combat can consume it before following commands overwrite its pending-action slot. Following inputs remain queued and keep their original timeout. Clients without event IDs retain the legacy shared-sequence behavior during migration.

An identical ID and arguments returns its existing receipt even if the retry sequence differs. Reusing the ID with changed arguments returns `event_id_conflict`. Epoch checks happen before receipt lookup. Receipts are retained for the possession lifetime, capped at 4096 without eviction; new events then return `event_receipts_full`. Release/reclaim establishes a new possession epoch. Ingress remains capped at 64. Receipt fingerprints accept at most 16 KiB of serialized event content.

Receipt states:

- `received`: enqueued, no simulation effect yet.
- `consumed`: dispatched into semantic command state at `consumed_tick`; this is not proof of a successful attack, completed dialogue or item award.
- `expired`: ingress aged past the input timeout before dispatch; retry cannot revive it.
- `applied` / `rejected`: identified attacks finish at `resolved_tick` after the manual combat phase, with `hit`, `range`, `stamina`, `blocked` or `target_invalid` reason. Retrying retrieves this final receipt without another effect. The top-level `ok` still describes acceptance of the original request; inspect `status` for its outcome.

Movement snapshots keep their separate last-applied input acknowledgment. The legacy `last_consumed_command_seq` is a nondecreasing diagnostic maximum, not a receipt for every event beneath it. Applied outcomes for other domain actions, combat timing/cooldowns, client receipt presentation and reconnect UI remain additional work.

`GET /control/event_result` takes `controller_id`, `event_id`, `world_epoch` and `possession_epoch`. It returns a detached receipt without resubmitting the action; invalid identity/epoch/ID or missing receipt returns an error. The 3D Godot attack path now reads this endpoint after reception, with at most 12 polls and eight concurrent attack requests. Only the latest click in the same world/possession may update its result message. A transport failure or an unresolved receipt reports unavailable; it never claims a hit or retries the mutation. New world/possession clears the message. Full reconnect recovery and final receipts for other actions remain open.

Run the Python control/session tests with the full isolated suite. For a Godot HTTP integration check, append `--test-event-retry` to the documented gameplay capture command using a fresh isolated backend and `--create-test-world`. It verifies ID generation and receipt reuse through the normal 3D transport. Secondary browser world/possession envelope migration remains unverified.
