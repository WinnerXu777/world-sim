# Performance and soak report (H3)

Date: 2026-10-07. Machine: Windows 11, CPU torch, an unrelated CPU-hungry process (`2D1006newstart\main.py`) was running the whole time, so every number below is a pessimistic one. World: the real two-map roster world (`starter_village` + `smith_interior` at origin 620,0), five roster residents, profile `gameplay`, seed 905, fresh temp data roots under `.runtime/` (never `Data_Storage`).

## Commands
```powershell
# (a) in-process, headless, 36000 ticks = 30 game minutes at 20 Hz. ~6.5 min wall.
.\.venv\Scripts\python.exe tools/soak_headless.py --ticks 36000 --out .runtime/soak-result.json

# (b) real-time HTTP, 5 minutes. Backend first (fresh data root, port 8013, both maps):
$env:EDEN_PROFILE='gameplay'; $env:EDEN_PORT='8013'; $env:EDEN_DATA_ROOT=(Join-Path (Get-Location) '.runtime/play-http-soak')
$env:EDEN_MAP='starter_village'; $env:EDEN_MAP_FILES='world_data/maps2d/starter_village.json;world_data/maps2d/smith_interior.json'
$env:EDEN_MAP_ORIGINS='{"smith_interior": [620, 0]}'
.\.venv\Scripts\python.exe at_the_beginning/map_test.py
# then, in a second shell:
.\.venv\Scripts\python.exe tools/soak_http.py --seconds 300 --out .runtime/soak-http-timing.json
```

## (a) Headless 36000-tick soak (final run, after the fixes below)
The scripted player (`Bot` in `tools/soak_headless.py`): claim Iven, portal into the smithy, commission a sword and collect it (x2, with god coin top-ups), a commission refused for lack of materials, release, god iron gift (witnessed by 2), god pause for 100 steps then resume, a third commission and collect, then idle for the rest of the run with a god weather change every 3000 ticks. All four orders ended as expected (3 delivered, 1 `refused_no_materials`).

| Metric | Result |
| --- | --- |
| Per-tick work (`Engine.step`) | mean 10.9 ms, **p50 9.7, p95 19.1, p99 27.9, max 65.8 ms** |
| Ticks over the 50 ms budget | **7 of 36000** (0.02%); over 25 ms: 595 (1.7%) |
| Paused steps (god pause) | 101, p99 0.005 ms (the guard does no work) |
| RSS | 245.4 MB at start, 256.2 MB at end (+10.8 MB, flat after warm-up) |
| Wall time | 393.9 s for 1800 s of game time (4.6x real time) |
| Exceptions | dispatch errors 0, logged errors 0 |
| Decision log | 6073 bytes after 36000 ticks (4 requests; rules provider) |
| Event/log growth | memory events 36, `inventory_state` 13.3 KB, command records 23, talk lines 7, pending events 0, frame 9.7 KB; none grows with ticks |

### Resident survival (36000 ticks)
No resident died; HP stayed at 100 for all five throughout; no hp loss.

| Resident | hunger max | thirst max | embedded samples | max consecutive stalled ticks | direction reversals |
| --- | --- | --- | --- | --- | --- |
| Brann (smith) | 27.0 | 37.8 | 0 | 0 | 124 |
| Mara | 27.0 | 37.8 | 0 | 0 | 55 |
| Toma | 27.0 | 37.8 | 0 | 0 | 74 |
| Iven | 24.7 | 34.6 | 0 | 0 | 57 |
| Elsa | 27.0 | 37.8 | 0 | 0 | 176 |

Needs rise linearly (0.015 x the legacy rate, so the 36000-tick end values are the maxima above); thirst is below the 50 mark, where legacy survival behaviour would start. (Superseded by the food/water loop, see "Update after H6, H7, H8".)

### Drift
`max_step` is 1.5 u/tick (the motion cap) for everyone except Iven's 540 u: that single sample is the portal teleport into the smithy (a jump, recorded by `teleport_seq`, not a speed violation) and Elsa 1.1. AnchorMover over the whole run: 514 plan calls, 514 replanned steps, **0 blocked results** (no `no_path`, `stuck` or `goal_not_standable`). Direction reversals are the normal turn-at-waypoint count (no door oscillation: nobody stalls).

## What the first run found, and what was fixed
The first full soak (before this task's fixes) was not clean:

| Finding | Before | Fix | After |
| --- | --- | --- | --- |
| All five residents died of old age at ticks 22812 to 33010 | aging runs at 600 ticks per game year (1 game year = 30 s), so 30 game minutes is 60 years | new roster key `age_scale` (default 1.0, range 0..1, validated), applied per resident in `instinct_age` through `age_scale_vector` (roster maps only; legacy aging is byte-for-byte the same and has a test). `starter_village.json` sets `age_scale: 0.05` (about 3 years in 30 minutes) | no deaths |
| Iven stuck in the smithy for the rest of the run after the player released him (`blocked: no_path` on 28810 steps, 771 consecutive stalled ticks, replan every tick) | residents could not use portals; the goal was on the other map, the planner had no route | roster driver now detects "goal on another placed map" (`map_id_at`, `portal_toward`), walks the resident to the portal's from-anchor and moves him through it (`use_portal`: same bookkeeping as the player's portal command, `teleport_seq`, `_tick_teleports`, `final_positions` so the motion limiter does not clamp the jump). Test: `test_a_resident_left_on_another_map_walks_to_the_portal_and_goes_home` | 0 blocked, 0 stalled ticks, 514 plan calls instead of 29176 replanned steps |
| thirst reached about 46 at 36000 ticks (needs_scale 0.02) | too close to the threshold | roster `needs_scale` 0.02 -> **0.015** (this is the roster fix, no food/water loop was added). Tests that asserted 0.02 now assert 0.015 | thirst max 37.8 |
| 293 ticks over 50 ms, max 97 ms | mostly the replan storm above plus a noisy machine | (the storm fix) | 7 ticks over 50 ms, max 65.8 ms |

## (b) Real-time HTTP soak, 5 minutes
Load: `GET /frame` at 20 Hz (6001 calls), `POST /control/input` at 5 Hz (1500, a possessed Iven walking a square), `GET /commission/state` and `GET /status` once a second (300 each), through a fresh `/session/new`.

| Client-side latency (ms) | n | p50 | p95 | p99 | max |
| --- | --- | --- | --- | --- | --- |
| `/frame` | 6001 | 1.12 | 1.74 | 2.45 | 44.3 |
| `/control/input` | 1500 | 1.04 | 1.68 | 2.69 | 22.8 |
| `/commission/state` | 300 | 1.05 | 1.77 | 2.27 | 13.2 |
| `/status` | 300 | 2.16 | 3.22 | 17.7 | 34.5 |

Errors: 0 of 8101 requests. Server `/status` `timing` at the end (1200-sample window): `work_ms` p50 10.0 / p95 14.1 / p99 17.5 / max 30.8; `lateness_ms` p50 7.7 / p95 15.1 / max 16.3; `overruns` 1, `dropped_deadlines` 0; 6072 steps in 300 s (20.2 Hz, no drift: ticks 1 to 6001). Persistence: no errors, autosave at tick 5932. The 8 to 16 ms lateness is the Windows timer granularity (about 15.6 ms), present with an idle backend as well (see the start sample).

## Left as is (reported, not fixed)
- **`portal_uses` and the loop counters** (`trips_done`, `rations`, `trip_timeouts`, `trip_blocked`) live on the roster runtime (diagnostic only, not saved).
- **Possessed residents** are not driven and need no feeding: `instinct_incarnation_stabilize` pins a controlled human's HP at 100 and hunger/thirst at 0 every tick (checked by `tests/test_roster_needs.py`: 1500 ticks at needs_scale 1.0, more than 60 game minutes of needs, with the needs staying at 0). An earlier version of this report said such a player would starve; that was wrong.
- Soak timings were taken on a machine shared with other heavy processes; a quiet machine should be somewhat better, not worse.

## Update after H6, H7, H8
Changes since the first report: a food/water loop (H6), the memory graph write moved to a worker thread (H7), a map revision/sha guard on Continue (H8). Full suite after the changes: 529 tests OK.

### Food/water loop (H6)
At hunger or thirst 30 a resident walks to `village:use_campfire` / `village:use_well` (the smith crosses the portal and comes back), stands there 60 / 40 ticks, the need resets to 0, the routine resumes. A trip pre-empts the schedule and an open commission; order progress is stored in the order and only counts at the forge, so the order pauses (`smith_away`) and resumes, nothing is lost (test). No site, no path, or a trip over 2400 ticks: a free ration (need -25). `needs_scale` stays 0.015.

### Spike analysis (H7): what it was and was not
| Hypothesis | Evidence | Result |
| --- | --- | --- |
| memory graph save on the tick path | moved to a worker thread (debounced, at most every 15 s; 18 to 19 background writes per 36000 ticks, 0 errors) | **not the cause**: the next soak still had 7 ticks over 50 ms, 5 of them at tick = 1 mod 20 |
| map delta build | 0.4 ms mean, 1.5 ms max (200 calls) | not the cause |
| resident JSON files written with fsync on the tick thread (`sync_live_population` -> `resident_store.flush_dirty` -> `write_resident_batch`, every 20 ticks) | per-phase probe: the step at tick = 0 mod 20 averages 26 ms vs 12 ms for the other ticks; cProfile of only those steps puts `_atomic_write_json` / `nt.fsync` at the top | **the cause, in the development-style harness**. The gameplay server sets `resident_store.background_writes = True` and `ResidentWriter` writes them off the loop, so the server never pays this on the tick |
`tools/soak_headless.py` now mirrors the server (`--resident-writes background`, the default; capture runs between ticks, 0.77 ms p50 / 1.36 ms p99 / 5.1 ms max). `--resident-writes inline` reproduces the old numbers.

### 36000 ticks, three configurations (same bot, same world)
| Run | work p50 | p95 | p99 | max | ticks > 50 ms | > 25 ms |
| --- | --- | --- | --- | --- | --- | --- |
| first report (before any fix, residents died) | 9.0 | 17.4 | 29.4 | 97.2 | 293 | n/a |
| after the fixes of the first report (inline resident writes) | 9.7 | 19.1 | 27.9 | 65.8 | 7 | 595 |
| H6-H8 (inline resident writes, dev-style harness) | 9.6 | 21.7 | 29.3 | 65.2 | 7 | 1073 |
| **H6-H8, production-like background resident writes** | **10.4** | **15.9** | **20.4** | **56.5** | **1** | **108** |
Last row, details: no deaths, HP 100 for all five, hunger max 27.0, thirst max 29.6, embedded 0, stalled ticks 0, 506 plan calls and 0 blocked results, 0 exceptions, RSS 245.3 to 258.2 MB, decision log 6074 bytes, graph writer 18 writes / 0 errors, loop counters: 5 trips done, 0 rations, 0 timeouts, 0 blocked, 3 portal uses. The single tick over 50 ms (2723, 56.5 ms) is not on the 1-per-second phase. Command: `.venv/Scripts/python.exe tools/soak_headless.py --ticks 36000 --resident-writes background --out .runtime/soak-result-bg.json`. (The inline rows are slower at p95/p99 than before because the machine was busier, the extra resident writes are the same.)

### The roster changed under the soak: 8 residents on 4 maps
While the first 90-minute run was in progress the roster and map files were extended (Rhea, Orrin, Nessa; `village_lodge_interior`, `west_cottage_interior`). That run **ended in three deaths (Mara and Iven at tick 78782, Elsa at 78876) with needs at most 30 and HP 100 at the last sample**. Cause, found by reading the code and the timestamps (the roster file was rewritten at 08:56:29, tick ~78800): `has_roster()` re-read the roster file on every tick (cache keyed by the file's mtime) and required every anchor the *current file* names to be placed in the *running* world. The new file named anchors the running world had not placed, so the check turned False and the live world fell back to legacy NPC rules (attacks, random disasters, legacy needs).
**Fixed** (not a soak artefact): the rules of a running world no longer depend on the roster file. `world_has_roster(engine)` (`systems/roster/apply.py`) decides from the world's own residents (`roster` bindings; True is remembered per world epoch), and `engine_has_roster` (instincts) and the mating check use it. The file is read only when a world is created (New Game), as before. Regression tests: `tests/test_roster_world_rules.py` (missing file, broken JSON, a new roster with unplaced anchors: the running world keeps its rules, 8 residents still driven, no exception, HP 100; a new world reads the file again; legacy unaffected).
The soak harness registers all four maps now (`tools/soak_headless.py`); BACKEND.md has the four-map run command. The 5-minute HTTP soak above was taken on the earlier two-map, 5-resident world and was not repeated.

### Headless soaks on the current world (8 residents, 4 maps, production-like resident writes)
| Run | work p50 | p95 | p99 | max | ticks > 50 ms | > 25 ms | RSS start to end | wall |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 36000 ticks (30 game minutes) | 15.4 | 23.0 | 27.6 | 52.7 | 2 | 815 | 245.3 to 256.2 MB | 602 s |
| **108000 ticks (90 game minutes)** | **14.3** | **21.3** | **23.9** | **40.2** | **0** | 589 | 245.1 to 263.9 MB | 1656 s |
Eight residents on four maps cost about 5 ms more per tick than five on two (median 14.3 to 15.4 ms against 10.4 ms); the budget is 50 ms.
Commands: `.venv/Scripts/python.exe tools/soak_headless.py --ticks 36000 --resident-writes background --out .runtime/soak-result-bg2.json` and `.venv/Scripts/python.exe tools/soak_headless.py --ticks 108000 --sample-every 1800 --resident-writes background --out .runtime/soak-result-90min2.json` (about 10 and 28 minutes wall).

**90 game minutes, results:**
- Survival: **0 deaths**, HP 100 for all eight in every sample; highest hunger or thirst in any of the 60 samples **30.23** (target: nobody above 60). Per resident max: hunger 29.7 to 30.1, thirst 28.4 to 30.2.
- Food/water loop: 40 trips done, 0 rations, 0 trip timeouts, 0 blocked trips (every resident drinks and eats at the real anchors; the smith goes through the portal).
- Movement: 2929 plan calls, **0 blocked results** (no `no_path`, `stuck`), **0 stalled ticks, 0 embedded samples** for everybody; 642 portal uses (the residents commute between the interiors and the village); `max_step` 1.5 u/tick for walkers, the 460 to 963 u values are portal jumps.
- Exceptions: dispatch errors 0, logged errors 0. Decision log 6075 bytes. Graph writer 56 writes, 0 errors.
- Memory: RSS 245.1 MB to 263.9 MB over 108000 ticks (+0.17 MB per 1000 ticks, mostly the first 40000 ticks; 252 MB at 1800, 256 MB at 55800, 260 MB at 91800). `inventory_state` 21.9 KB, memory events 38, command records 47, nothing grows with the tick count except these slow counters.
- Resident file capture between ticks (production path): p50 1.10 ms, p99 1.67 ms, max 3.5 ms.
- The harness now records a 60-tick ring of every resident's full tensor row and freezes it into `death_forensics` on a death (empty here).

## Restart and Continue: the first minute (investigation, 2026-10-07)
Evidence from the Gate H recording (attempt 2): after the planned backend restart (process killed, new process on the same port and data root, Continue) the new backend's overruns went from 1 to 15 and dropped deadlines from 0 to 9 within about 30 s (work p95 35 ms, max 73.9 ms), then stayed flat; the client lost its connection once later. Tools: `tools/restart_probe.py` (two cold Python processes, the real app lifespan and an ASGI client in one event loop, no sockets; `make` / `restore` / `--profile` / `--routes`) and `tools/thread_probe.py`.

| Question | Measured (the real Gate H world, 34609 ticks, 1.1 MB save, 459 KB memory graph, 8 residents, 4 maps) |
| --- | --- |
| Does `POST /session/continue` block the event loop? | No. It takes 24 to 29 ms (read 3, decode 8, validate 0.2, reset 1.4, restore 4); with the warm-up below 64 to 67 ms. A concurrent `GET /status` hammered in a tight loop waited at most 25 to 29 ms. Autosave (`world_snapshot.capture`) blocks the loop for about 10 ms. `POST /session/new` takes 96 to 127 ms with a longest concurrent wait of 93 ms. **No single event-loop blocking call exceeds 100 ms**, so nothing here can make an HTTP request time out. |
| Is any route expensive on its first call in a fresh process? | No: `/bootstrap` 20 ms the first time and 1.5 ms after, every other route the client uses (`/frame`, `/status`, `/session`, `/control/*`, `/commission/state`, `/god/inspect`, `/map_delta`, the four `/map_file/*`) 0.3 to 1.7 ms. |
| Is the first minute after a cold start slow? | Not in process: 1500 ticks timed after a cold restore: first 1200 ticks p50 16.5 / p95 23.8 / p99 29.2 / max 45.4 ms, no tick over 50 ms, server `overruns` 0 and `dropped_deadlines` 0. The 3000-tick world gave the same. |
| What is the one cold-start cost? | The first tick after Continue: 45 to 58 ms in `flush_memory_graph_queue -> ensure_memory_rag`: `import faiss` 29 ms, loading the memory graph, syncing the restored residents into it. **Fixed** (below). |
| Does torch's thread pool matter? | No. 10 threads (default on this 16-core machine) against 1: p50 15.8 against 16.5 ms. |
| Does a busy machine matter? | Yes, a lot. The same restored world stepped while 12 busy-loop processes ran on the 16 logical cores: **p50 16 -> 28 ms, p95 28 -> 58 ms, ticks over 50 ms 1 -> 110 to 163 per 1000**. The tick is single-threaded Python and competes with Godot, the recorder and the new process starting up. |

**Conclusion.** The slow first minute is not a backend phase that the in-process reproduction can show. What the data supports: the restart window is the busiest moment of the whole recording (the new interpreter importing torch, Godot reconnecting and re-reading four maps, the recorder), the tick is very sensitive to CPU contention (above), and the new process added one 45 ms first tick. I could not reproduce overruns or dropped deadlines without artificial CPU load and I could not find the cause of the single lost connection (no backend call blocks for more than 100 ms; the keep-alive and socket behaviour of uvicorn is not covered by an in-process test).
**Fix (safe, small).** `Engine.warm_up_world` (load the memory graph and sync every resident into it) now runs inside `POST /session/new` and `POST /session/continue` (`GameSessions._warm_up`, never fails the request), and `Engine.warm_up_process` imports the index library once in the server lifespan before the tick loop starts. Measured on the same cold restore: first-minute worst tick 45 to 49 ms -> 37 to 39 ms, Continue 28 ms -> 65 ms, longest `/status` wait during Continue 29 ms. Tests: `tests/test_warm_up.py` (4).
**Recommendation for the recording.** Keep the machine quiet during a restart (no extra Godot instances, no second recorder), or accept a short burst of overruns at that moment; do not run the restart while another heavy process runs.

## Tests
`tests/test_checkpoints.py` (H4): the two MAX_PATH errors are fixed by shorter temp directory names. New or changed tests: roster `age_scale` aging and legacy aging unchanged, portal return for a stranded resident, needs_scale 0.015 assertions. Full suite after H6 to H8 and the roster-file fix: **535 tests, OK** (it was 499 before; new files `test_roster_needs.py` 11, `test_memory_graph_background.py` 9, `test_map_guard.py` 10, `test_roster_world_rules.py` 5, plus the aging, portal and needs-scale tests) (`.venv/Scripts/python.exe -m unittest discover -s tests -p 'test_*.py'`).
