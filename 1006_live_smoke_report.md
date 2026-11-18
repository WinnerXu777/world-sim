# Live smoke report: authored map `starter_village` on the real backend (2026-10-06)

Author: session 1006implementation. No mocks: a real `map_test.py` subprocess, real HTTP, real files in `world_data/maps2d/`. The backend was started with an isolated data root `.runtime/smoke-a6a8cbab20c24e39be5af994401d67b6` (logs next to it: `...log`, `...-r1.log`, `...-r2.log`). Nothing outside that data root was written; the process was stopped afterwards (port 8013 verified free). The script is saved as `tools/live_smoke_authored.py`.

## What was run

```
EDEN_PROFILE=gameplay EDEN_PORT=8013 EDEN_MAP=starter_village \
EDEN_MAP_FILES=world_data/maps2d/starter_village.json \
EDEN_DATA_ROOT=.runtime/smoke-<guid> .venv/Scripts/python.exe at_the_beginning/map_test.py   # background
.venv/Scripts/python.exe tools/live_smoke_authored.py                                          # 21 checks
```
Then two restarts on the same data root: (r1) with the map file registered, `POST /session/continue`; (r2) without `EDEN_MAP_FILES`, `POST /session/continue`; then (r3) `EDEN_MAP=starter_village` with no map file.

Prerequisite change made first: `persistence/sessions.py` hard-coded `map_name="playable_village"` for New Game. `GameSessions` now takes `map_name` (default `"playable_village"`), `map_test.py` passes `LAUNCH_CONFIG.map_name`, and startup refuses (`SystemExit`) an `EDEN_MAP` that is neither built in nor registered. Tests: `tests/test_map_new_game.py` (4).

## Result 1: main smoke (21/21 checks passed on the second run)

The first run had 18/21 passing; both failures were in my script, not the backend, and are recorded here for honesty:
1. `/control/input` returned `400 session_not_found controller_id=local_player` because my payload omitted `controller_id` (the route defaults to `local_player`). Fixed in the script.
2. The strict "first villager exactly on the anchor" check failed with a 0.9-unit offset: residents already wander for roughly a second between New Game and my first `/frame` read. The exact placement is covered by `tests/test_map_spawn.py`; the smoke check now accepts a 6-unit tolerance.

Output of the passing run (trimmed to the checks):
```
PASS New Game ok
PASS bootstrap has maps block
PASS maps[0] has exactly the 13 spec keys in order
PASS revision is an int [1]
PASS map_name is starter_village
PASS spatial carries map_id/map_revision/units_per_tile
PASS spatial actor_radius 2.4 and bounds are the map rectangle [[0.0, 0.0, 384.0, 288.0]]
PASS map_file bytes equal the file on disk
PASS sha256(body) equals block sha256
PASS ETag equals quoted block sha256
PASS size_bytes matches
PASS If-None-Match gives 304 with empty body [304]
PASS unknown map is 404
PASS four starter villagers [4]
PASS every villager spawned standable under the live contract [[True, True, True, True]]
PASS villagers start at the real spawn anchor (184, 160) ... [nearest offset 0.90]
PASS villagers are within 2 rings of the anchor
PASS claim ok
PASS player stopped at the contract boundary y = 142.4 (well wall 140 + radius 2.4) [(184.9, 142.4)]
PASS player did not enter the wall
PASS tangential movement along the boundary works (x grew, y stayed at the boundary) [(219.9, 142.4)]
21/21 checks passed
```
Selected live values:
- `maps[0]`: `{"map_id": "starter_village", "format_version": "0.2-draft", "revision": 1, "sha256": "26864396ae2444bf76e8ef5096300fc0831077fd2b2094e08e17fa2a4729f35b", "size_bytes": 36196, "url": "/map_file/starter_village", "map_kind": "exterior", "units_per_tile": 8.0, "tile_size_px": 48, "size_tiles": [48, 36], "actor_radius": 2.4, "origin": [0.0, 0.0], "primary": true}`
- `spatial` (no boxes): `version 1, actor_radius 2.4, bounds [0,0,384,288], walk_speed 20.0, sprint_multiplier 1.5, map_id starter_village, map_revision 1, units_per_tile 8.0`, 24 boxes (the map's 24 walls; no live tensor walls, no slabs for a single map).
- Before New Game `/bootstrap` has no `maps` key and `world.map_name == "unknown"` (legacy shape).
- Villagers (Mara, Iven, Toma, Elsa) at `(184.9,160.4) (189.1,160.5) (184.5,165.2) (178.3,160.6)`, all standable; the real spawn anchor is `village:spawn` at `(184, 160)`.
- Possessed Mara walking north with `move.y = -1` for 4 s stopped exactly at `y = 142.4`, the well wall `village:wall_well` (`[180,132]-[196,140]`) plus radius 2.4; walking east afterwards slid along the boundary to `x = 219.9` with `y` unchanged.
- `/frame` keys: `agents animals cap controls despawned events frame_id inventory map_name nature pop protocol talk tick year`; `/frame` carries no spatial data (as specified).

## Result 2: restart with the map registered (Continue)
```
saves on disk: [('smoke-test','22c0b31a',0), ('smoke-test','993487b1',327)]
POST /session/continue: 200 {"ok": true, ... "world_loaded": true ...}
map_name: starter_village | maps block: ['starter_village'] | actor_radius: 2.4 | bounds: [0.0, 0.0, 384.0, 288.0]
residents: Mara (184.9,160.4) Iven (189.1,160.5) Toma (184.5,165.2) Elsa (178.3,160.6)
RESULT PASS
```

## Result 3: restart WITHOUT `EDEN_MAP_FILES` (default map): Continue is refused
```
POST /session/continue: 400 {"detail": "Saved world uses map 'starter_village', which is not a built-in map and has no registered authored map contract; register its map file (EDEN_MAP_FILES) and try again"}
world still empty/untouched: False   (world_loaded stayed false)
RESULT PASS
```

## Result 4: misconfigured launch fails fast
`EDEN_MAP=starter_village` with no `EDEN_MAP_FILES` exits with code 1 and `EDEN_MAP='starter_village' is neither a built-in map nor a registered authored map (EDEN_MAP_FILES)`, instead of starting a server that cannot create a world.

## Not covered / observations
- Only the primary map was loaded. `smith_interior` placement, portals and multi-map containment are G5/G7 and were not exercised live.
- The sprite files were not checked (`--base-dir` was not given to the backend; the validator command `tools/validate_map.py world_data/maps2d/*.json --base-dir myassets` passes with 0 errors).
- The two saves in the data root come from two New Games in one server run (one reached tick 327 in the first run; Continue picked the newest, tick 0). Position persistence across a hard kill was not tested; the backend was force-stopped each time (so no shutdown checkpoint), and Continue used the New Game checkpoint.
- No `/map_file` request was made from a non-loopback host in the live run (covered by `tests/test_map_wire.py`).
- Residents wander and run tasks immediately after New Game (for example `construction:designate_build_site`); that is existing behaviour. I did not examine whether NPC task movement respects walls live: the smith-loop design note says `_move_human_toward_point` writes X/Y without sliding (not tested here).

## Addendum H2: starter storage case on authored maps
`Engine._spawn_starter_storage_case` used to place a seeded storage case at `first resident + (26, 18)` (circle, scale 14). In the live run that was about `(210.9, 178.4)` on `starter_village`: not inside any wall box, but not at any authored object either (an invented chest in the town square), and for other maps or spawn positions the same formula can land inside a wall or off the map. For authored maps (a registered contract) the case is now placed at a standable point at the map's first interactive entity of kind `storage`/`chest`/`storage_case`/`crate`, or skipped when the map has none. Legacy maps are unchanged. Tests: `tests/test_map_storage_case.py` (6). Not re-run live after this change.

## Addendum: flaky boundary check fixed
Another session reproduced one failure (20/21): the check "player stopped at the contract boundary" compared the final x with the resident's x read BEFORE the claim, but residents wander before they are claimed, so the stale x was off by a few tenths while `y` was exactly 142.4 and the player never entered the wall. `tools/live_smoke_authored.py` now takes the baseline AFTER the claim succeeds (a possessed resident no longer wanders) and compares against that. The port is now configurable with `EDEN_SMOKE_PORT` (default 8013). Re-run three times against a fresh backend (same data root, `EDEN_MAP=starter_village`): 21/21, 21/21, 21/21 (baselines (184.9, 160.4), (184.0, 160.0), (184.9, 160.4); final y = 142.4 each time). Backend stopped afterwards; port 8013 free.

## Addendum G5-G7: live portal smoke (both real maps, `tools/live_smoke_portal.py`)
Backend: `EDEN_MAP=starter_village`, `EDEN_MAP_FILES=world_data/maps2d/starter_village.json;world_data/maps2d/smith_interior.json`, `EDEN_MAP_ORIGINS={"smith_interior": [620, 0]}` (620 is a test placement, not a decision), fresh data root `.runtime/smoke-<guid>`, port 8013. 13/13 checks passed on the first run:
```
maps: [('starter_village', True, [0.0, 0.0]), ('smith_interior', False, [620.0, 0.0])]
PASS both maps are listed, primary first / union bounds cover both maps / both /map_file bodies hash to their block sha256
arrived at (130.2, 112.0)   # walked there on foot from the spawn, claimed resident h_000001
POST /control/portal: 202 {'status': 'received', ... 'received_tick': 78}
result: {"status": "applied", "to_map": "smith_interior", "to_anchor": "smith:entry", "position": [668.0, 60.0], "teleport_seq": 1, "applied_tick": 78, ...}
frame entry: h_000001 (668.0, 60.0) teleport_seq 1   # other residents have no teleport_seq key
committed_state: {... 'completed_tick': 90, 'position': {'x': 668.0, 'y': 60.0}, 'teleport_seq': 1}
world_epoch unchanged, possession_epoch unchanged
walking west inside the interior stopped at x = 626.4 (never entered the gap)
13/13 checks passed
```
Observations: an unknown portal id gets `202 received` and is rejected at the next tick (`GET /commands/{id}` then shows `rejected`/`unknown_portal`), like every other queued command. The backend was force-stopped afterwards (port 8013 free).

## Addendum B: live smith loop (`tools/live_smoke_smith.py`, 11/11)
Backend as in the portal smoke (both real maps, interior at `[620, 0]`), fresh data root, port 8013. Five roster residents appeared (Brann, Mara, Toma, Iven, Elsa). The script claimed Iven, walked to the smith's door (128, 110), used the portal (`smith_interior`), walked up to Brann (645.0, 37.3, at the forge anchor), saw `request_commission` enabled, requested a sword (accepted, state `reserved`, line "A blade? Aye, I have the iron..."), kept sending input while waiting, saw the order `ready` after **45.1 s** (900 ticks of work), collected it once (`delivered`), and a second collect returned the stored receipt with `duplicate: true`. A first run failed only because the script stopped sending input while waiting and possession was released after 5 s (existing behaviour); the script now sends neutral input at 4 Hz like a client would. Backend stopped, port 8013 free.

## Addendum P5: live god mode (`tools/live_smoke_god.py`, 29/29)
Both real maps, fresh data root. The embodied player was refused god powers (`release_possession_first`); two real orders (coin topped up by the god between them) used the smith's 4 iron; the third request was refused `refused_no_materials` ("Not without iron. My stock is empty."); after release the god spawned 2 iron into Brann (2 witnesses, `g_000003`), `/god/inspect` showed he remembers the gift, the re-claimed player's next request was accepted; heal at full health was a no-op; weather `rain` showed in `/status` and `/frame`; pause froze the tick for 1.5 s while a god command still applied; resume restarted it; after New Game and Continue of the first save the smith still remembered the gift. A first run failed 5 checks only because the script's player could not afford a second sword (40 coin); the script now has the god top up the purse. Backend stopped, port 8013 free.

## Addendum: the four-map world, ready-order hold (2026-10-07)
Backend: `EDEN_MAP_FILES` with all four maps and origins `smith_interior [620,0]`, `village_lodge_interior [620,400]`, `west_cottage_interior [960,160]`, the 8-resident roster, port 8013, a fresh `EDEN_DATA_ROOT`. The four tools were rewritten on `tools/smoke_common.py` (nothing assumes Iven or the village; the player is chosen by position and coin, walks through portals from wherever he stands).
- Finding: with the order ready at night the smith's schedule says sleep and he walked to his bed (696, 62), 47.9 units from the customer, and `collect` answered `rejected out_of_range` (`live_smoke_smith.py --night --lag 8`, tick 2006 ready, tick 2169 collect). Cause confirmed live and in `tests/test_smith_ready_hold.py` (57.6 units away within 300 ticks). Fix: a ready order holds the smith at his forge (up to 2400 ticks). After the fix the same run: routine `sleep` but goal anchor `work`, collect applied from where the player stood, the smith goes to bed right after delivery.
- Results on the fixed backend: `live_smoke_authored.py` 26/26, `live_smoke_portal.py` 26/26 (all three interiors in and out), `live_smoke_smith.py` 11/11 (also `--night --lag 8`: 11/11), `live_smoke_god.py` 31/31 (including Continue: the third order `o_000004` is still known).
- A resident with less than 30 coin (Rhea has 25) is refused with `refused_cannot_afford`: that is correct, pick a funded player (Iven, Elsa, Orrin, Mara, Toma 35 to 60, Nessa exactly 30).
