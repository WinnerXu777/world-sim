# Backend: running the authored-map game

Python backend in `at_the_beginning/` (FastAPI, one process, 20 Hz fixed tick). It serves the 2D client and the legacy 3D/browser clients. Everything below is what the code does today; details live in the linked notes.

## Run it
From the repo root, Windows PowerShell, with a **fresh data root** (the world autosaves into it):

```powershell
$env:EDEN_PROFILE   = 'gameplay'
$env:EDEN_PORT      = '8013'
$env:EDEN_DATA_ROOT = Join-Path (Get-Location) ('.runtime/play-' + [guid]::NewGuid().ToString('N'))
$env:EDEN_MAP       = 'starter_village'
$env:EDEN_MAP_FILES = 'world_data/maps2d/starter_village.json;world_data/maps2d/smith_interior.json;world_data/maps2d/village_lodge_interior.json;world_data/maps2d/west_cottage_interior.json'
$env:EDEN_MAP_ORIGINS = '{"smith_interior": [620, 0], "village_lodge_interior": [620, 400], "west_cottage_interior": [960, 160]}'
.\.venv\Scripts\python.exe at_the_beginning/map_test.py
```
Connecting does not create a world: the client calls `POST /session/new` (or `/session/continue`). Tests: `.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py'` (always `discover`).

| Variable | Meaning |
| --- | --- |
| `EDEN_PROFILE` | `gameplay` (default), `render_fixture`, `animation_qa` |
| `EDEN_PORT` | default 8002 (gameplay), 8012 otherwise; loopback only |
| `EDEN_DATA_ROOT` | saves, resident sidecars, `decisions/` log. Must not be inside `Data_Storage`. Default `.runtime/<profile>` |
| `EDEN_MAP` | map New Game creates. Default `playable_village` (legacy generator). An authored name (`starter_village`) must be registered through `EDEN_MAP_FILES`, otherwise startup exits with an error |
| `EDEN_MAP_FILES` | `;`-separated authored map JSON paths (first = primary, registered under its `map_id`). Unset = legacy maps only |
| `EDEN_MAP_ORIGINS` | JSON object (or path to one) `{map_id: [x, y]}` placing every non-primary map; maps must fit 1200x900 units, not overlap, and be more than 220 units apart |
| `EDEN_ROSTER_DIR` | where `<map_id>.json` rosters live (default `world_data/rosters/`) |
| `EDEN_SEED` | default 905 |

## Authored maps and the roster
Map format `0.2-draft`: `at_the_beginning/world_map/README.md`; validate with `.venv/Scripts/python.exe tools/validate_map.py A.json B.json --base-dir myassets`. A roster (`world_data/rosters/starter_village.json`) names the residents (role, personality, anchors, stock, `needs_scale`). It applies only when the map is registered and every anchor it names is placed (the current roster needs all four maps above; with fewer maps registered the world starts with the legacy villagers, so check the startup log). Whether a *running* world is a roster world is decided by its own residents, not by re-reading the roster file: editing or breaking `world_data/rosters/*.json` while the server runs changes nothing until the next New Game. On a roster map: residents live on anchors and move only through the anchor mover (walk 1.0 u/tick, max 1.5 u/tick, always slid through walls); construction/trade/occupation tasks, NPC attacks, mating and the random disaster cycle are off; hunger/thirst run at the roster's `needs_scale` (0.015) and aging at `age_scale` (0.05: a 30-game-minute run is about 3 game years, not 60). Residents on a different placed map than their goal anchor walk to the portal and are moved through it (same teleport bookkeeping as the player's portal command). **Food/water loop** (`needs` block of the roster file, `systems/roster/needs.py`): at hunger/thirst 30 a resident walks to `village:use_campfire` / `village:use_well` (the smith crosses the portal), stands there 60/40 ticks, the need resets to 0 and the routine resumes; a trip pre-empts the schedule and an open commission (order progress is kept in the order and only counts at the forge, so the order pauses and resumes). No site, no path or a trip longer than 2400 ticks: a free ration (need -25). A possessed resident needs nothing: the engine pins his hunger and thirst at 0 and his HP at 100 while a player controls him.

## Save / Continue
`POST /session/new {name}` creates the launch map (`EDEN_MAP`) and saves it; autosave every 60 s and on clean shutdown; `POST /session/save`, `POST /session/continue {save_id}`. **A save of an authored map can only be continued while that map is registered** (`EDEN_MAP_FILES` set to the same files, placement unchanged): otherwise Continue is refused with an error naming the map and nothing changes. Orders, escrow, the god-event ledger and resident memory are in the save; pause, `teleport_seq`, plans and the decision service are not. Each save records the revision, sha256 and origin of every placed map (`inventory_state["map_manifest"]`); in the gameplay profile Continue is **refused** (HTTP 400, naming old and new revision/sha256) when a registered map differs from the save, so saves made before a map revision are refused on purpose. Dev override: `EDEN_ALLOW_MAP_MISMATCH=1` or a non-gameplay profile. Saves without a manifest (legacy maps, older saves) load unchanged. The memory graph (`MemoryRAG/memory_graph.pkl`, a derived index) is written by a worker thread at most every 15 s, queued on every session save, and written synchronously on clean shutdown.

## Routes
Reads (GET): `/bootstrap` (contract, `maps[]`, session capability) · `/map_file/{map_id}` (exact file bytes, ETag = sha256) · `/session` · `/frame` (agents incl. `roster_key`, `teleport_seq`; `nature.weather`) · `/map_delta` · `/status` (timing, `decision`, `god`) · `/commands/{id}` (result of a queued command) · `/control/state` · `/talk/state` · `/inventory/focus|owner/..|container/..` · `/commission/state?controller_id=` · `/god/inspect/{resident_id}` · `/resident/{id}`.
Writes (POST, need header `X-Eden-Session` from `/bootstrap`): `/session/new|continue|save` · `/control/claim|release|input|event|portal` · `/commission/request|cancel|collect` · `/god/heal|spawn_resource|weather|time` · `/inventory/transfer|equip_main_hand|spend|spawn_storage_case`. Queued commands (portal, commission, god, inventory transfer/equip) use one envelope: `protocol_version: 1`, `world_epoch`, `possession_epoch` (not for god commands), `controller_id`, `command_id` (UUID); answer 202 `received`, outcome at `/commands/{id}`; idempotent by `command_id`.
Legacy/dev routes (`/god_decree`, `/set_map`, `/testing/...`, RAG/memory) exist; `/testing/*` needs a non-gameplay profile.
Client notes: `design_docs/contracts/map_wire_contract.md`, `design_docs/contracts/commission_api.md`, `design_docs/contracts/god_mode_api.md`.

## Smoke and soak tools (real backend on port 8013, fresh data root)
`tools/live_smoke_authored.py` (maps block, files, residents, walls) · `live_smoke_portal.py` (every interior in and out) · `live_smoke_smith.py` (the sword loop, ~45 s; `--night --lag 8` requests so the sword is ready at night and collects 8 s late) · `live_smoke_god.py` (iron gift loop, ~4 min) · `soak_http.py` (5 min client-like load) · `tools/restart_probe.py` (cold restart + Continue timing in two fresh interpreters, no sockets) · `tools/thread_probe.py` (tick times under CPU contention). They share `tools/smoke_common.py` (four maps, the possessed resident is picked by position and coin, the walk goes through portals from wherever the player is). In-process: `tools/soak_headless.py` (36000 ticks). Results: `design_docs/reports/live_smoke_report.md`, `design_docs/reports/performance_report.md`.

## Known limitations
- Roster residents have no wander; their only survival behaviour is the food/water loop above (drinking resets thirst to 0 without consuming the well's water or any inventory item).
- Weather is cosmetic apart from the nature growth modifiers; no irreversible god effect exists. A god-set weather ends at its `duration_ticks` on a roster map too (`systems/god/expiry.py`, end tick saved with the world); the random disaster cycle stays off there.
- God pause and time scale belong to the running process, not to a save: `Engine.reset_world` (New Game, Continue) resets them to running at 1x.
- The orders in `inventory_state["work_orders"]` and the events in `inventory_state["god"]` are never pruned (about 1 KB per order; 22 KB after 90 game minutes with 4 orders).
- Possession is released after 5 s without input (wall-clock), also while paused. Command receipts are in memory: after Continue, re-read state instead of retrying old command ids.
- The legacy `playable_village` and the 3D/browser clients are frozen; the 2D client has not been exercised against `/god/*`.
- Map placement is validated at startup only. A map file changed while the server runs is not noticed until the next Continue or restart.
