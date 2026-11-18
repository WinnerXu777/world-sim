# Eden

## Eden 2D (the current game)

Eden 2D is a small persistent medieval village you watch and step into. Eight named villagers live there on a daily schedule: they work, talk, eat and drink, and sleep in their houses. You are a **spirit**: you can possess any villager and walk the village as that person, or let go and act as a **god** with a few small powers. The game that exists today is one complete loop:

- **Possess a villager**, walk into the smithy (a second map, through a door) and meet Brann the smith.
- **Commission a sword**: you pay 30 coin, Brann spends his iron and forges for about 45 seconds of real time, and you collect it. He remembers you afterwards (his greeting changes), and so do you: the delivery is stored as a permanent memory and a relationship change.
- **Be a god**: heal a villager, spawn coin or iron, change the weather, pause or speed up time. Brann starts with iron for two swords; give him more and he works again. Villagers who see a gift remember it.
- **Everything persists**: save and continue (autosave every 60 s, plus *Save and quit*), the world resumes with the orders, memories and positions it had.

There is no language-model dependency in this build: villager decisions go through a rules provider (the `decision` seam is wired for other providers, none is used), and memory retrieval uses a built-in lexical (TF-IDF) embedder by default (`EDEN_EMBEDDINGS`; a local embedding model is only used if you switch it on and it is installed).

### Quick start (about 60 seconds)

You need Windows PowerShell, the repository `.venv` (create it and install `requirements.txt`, see "Quick Start" under *Legacy simulator notes*), and Godot 4.6 on `PATH` (or set `EDEN_GODOT` to the executable). Then, from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\play.ps1
```

`play.ps1` starts the backend (gameplay profile, the four authored maps, a free port, a new data root under `.runtime\play-<timestamp>`), waits until `/status` answers, opens the game window, and when you close the window it asks the backend to save the world and stops it (also on a client crash or Ctrl+C). Options, exactly as implemented:

| Option | Meaning |
| --- | --- |
| `-DataRoot .runtime\play-YYYYMMDD-HHMMSS` | continue the saves in that existing root (omit for a new world) |
| `-Port 8014` | fixed port; it refuses to start if the port is busy (default: pick a free one) |
| `-Headless`, `-GodotArgs`, `-ClientArgs` | no window and extra engine / game arguments, used by the automated tests |
| `-ReadySeconds 120` | how long to wait for the backend |

Logs are in `.runtime\play-logs`. If the backend dies while the game is open, the launcher restarts it up to three times on the same data root; choose Continue in the game afterwards (unsaved progress may be lost). In the game, **New Game** creates a world, **Continue selected world** resumes a save of the chosen data root.

### Controls

| Key | Action |
| --- | --- |
| Enter | possess the nearest villager |
| W A S D / arrow keys | walk (Shift sprints) |
| E | use a door or portal when you stand at it (within 16 units) |
| T | talk to the smith when "Press T to talk to Brann" is shown |
| I | open or close your pack |
| R | release possession |
| Esc | close the panel, then the pack, then the help card; otherwise the pause menu (Resume, Release, Save world, Save and quit, Worlds, Quit without saving) |
| H or F1 | show the controls card again |
| F2 / F3 | collision overlay / debug line (tick, frames, fps) |
| F6 | worlds menu: Save / Continue |
| + / - | integer zoom |
| G | god mode (releases possession first; free camera) |
| God mode: Tab, P, mouse | Tab cycles the placed maps, P pauses and resumes time, click a villager to inspect or pick him from the list |

### What to expect in the first five minutes

1. A title menu (New Game / Continue), then a controls card and an objective card with a yellow arrow that points toward the smithy door.
2. The villagers start together near the well and spread out to their work, talk and sleep places on a schedule: one day lasts 2 minutes (dawn, day, dusk and night are 30 seconds each). Thirsty or hungry villagers walk to the well or the campfire by themselves.
3. Press **Enter** to possess one (Iven carries 40 coin; a sword costs 30). Walk to the smith's house (the yellow arrow points to its door), press **E** at the door, walk to Brann at his forge (top left), press **T**, and choose **Commission a sword (30 coin)**. A progress bar runs while he forges (about 45 s). If you were slow, he keeps waiting at the forge for up to two minutes. Stand next to him and choose **Collect the sword**; **I** shows it in your pack.
4. Press **G** to become a god: possession is released, the camera is free, and the panels let you heal, spawn resources, set the weather (rain, storm, ...) and pause time. His iron is enough for two swords; a third order is refused for want of iron until you spawn some.
5. Close the window: the world is saved, and `play.ps1 -DataRoot <that root>` brings it back.

### How it is built

- **Authoritative simulation in Python** (`at_the_beginning/`, FastAPI): one process, a fixed 20 Hz tick, the world state in tensors plus per-resident records. The client never decides anything: it sends input and commands, the backend answers with frames and results.
- **Godot 2D client** (`godot_client_2d/`): renders interpolated server frames only (no prediction, no local collision), imports the authored maps through `GET /map_file/{id}` with a SHA-256 check, and shows the panels.
- **Authored maps and a roster**: `world_data/maps2d/*.json` (the village and three interiors: smithy, lodge, west cottage; format in `at_the_beginning/world_map/README.md`) and `world_data/rosters/starter_village.json` (who lives there, their houses, work, sleeping places and starting stock). A resident walks along the anchor mover with A* path finding and always slides along walls. The roster file is read when a world is created; a running world keeps its own rules.
- **Smith loop, god powers, memory**: commission orders hold the materials and coin in escrow and survive save and continue (`systems/commission`); god powers are typed commands with witnesses and an event ledger (`systems/god`); events become permanent resident memories and relationships (`systems/memory`).
- **Persistence**: versioned saves per data root, autosave every 60 s. A save records the revision and SHA-256 of each map; Continue is refused (with a clear error) when a registered map file changed after the save.

### Tests and how to run them

```powershell
# Python suite (about 540 tests, about 4 minutes); always use discover
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
# backend smoke tools against a real backend on port 8013 (setup in tools/smoke_common.py)
.\.venv\Scripts\python.exe tools\live_smoke_authored.py   # also: live_smoke_portal.py, live_smoke_smith.py, live_smoke_god.py
# headless soak (in-process, 36000 ticks = 30 game minutes; 108000 for 90)
.\.venv\Scripts\python.exe tools\soak_headless.py --ticks 36000
# Godot client against a real backend (needs godot on PATH or EDEN_GODOT; each test starts and stops its own backend)
.\.venv\Scripts\python.exe godot_client_2d\tools\run_live_tests.py            # or a subset: commission, persist, god, ...
.\.venv\Scripts\python.exe godot_client_2d\tools\run_recovery_tests.py        # fault injection: backend restart, lost replies
```

### Documentation index

`design_docs/README.md` lists every design, API, report and audit document with its status (current, plan or historical). The ones to read first: `BACKEND.md` (running the backend, routes, limits), `godot_client_2d/README.md` (client), `design_docs/contracts/map_wire_contract.md`, `design_docs/contracts/commission_api.md`, `design_docs/contracts/god_mode_api.md` (the contracts), `design_docs/reports/performance_report.md` and `design_docs/reports/live_smoke_report.md` (evidence).

---

## Legacy simulator notes

Everything below this line is the original README of the earlier tensor world simulator (Adam and Eve, the world agent, LightRAG, the Arcade and 3D clients). It is kept as it was. It does not describe the Eden 2D game above; the legacy `playable_village` map and the 3D/browser clients are frozen but still run.

# Eden World Simulator

Eden is a multi-agent world simulation built around a Python backend, tensor-based world state, file-backed resident sidecars, and an LLM-oriented action-planning pipeline.

At runtime, the project currently combines:

- a simulation core that advances humans, animals, and map entities each tick
- a world-agent layer that accepts "god decrees"
- a deterministic execution agent that validates and runs structured action packets
- a human-agent layer for escalated survival decisions
- file-backed resident agents that persist per-human profile and memory
- a LightRAG layer for retrieving relevant tools and instincts for world-model prompting
- a separate MemoryLightRAG path for relationship and memory retrieval

## Core Ideas

- `h_tensor` stores human state.
- `m_tensor` stores map entities, animals, and structures.
- `MAP_GEO` stores geometry and spatial lookup data.
- `genesis_config.py` is the schema and constant source of truth.
- Frontends consume semantic JSON, not raw tensors.

This repo is designed so the simulation can stay authoritative in Python while different frontends or model stacks can sit on top of it.

## Runtime Architecture

### 1. Simulation core

The backend tick loop lives in `at_the_beginning/map_test.py`.

Each tick:

1. queued world decrees are processed
2. the registered instinct/tool loop runs
3. escalated humans are handed to the human-agent layer
4. stable IDs, events, frame payloads, and map deltas are refreshed

### 2. World agent

The world agent receives either:

- a raw decree such as `"send wolves into the forest"`
- or a fully structured action packet

Free-text decrees currently use a heuristic planner unless you provide an external world model that emits structured packets.

### 3. Execution agent

The execution agent is deterministic Python code, not an LLM.

It:

- validates tool names against the local registry
- checks parameter compatibility against live Python signatures
- resolves masks/selectors and symbolic values
- executes known tools
- decides which `new_instincts` or `new_entities` still require downstream follow-up

Important: `new_instincts` and `new_entities` are treated as proposals. They are not automatic side effects by themselves.

### 4. Human agent

Humans whose `ESCALATION_FLAG` is raised are batched into the human-agent layer. This is where "survival override" decisions can be made when normal instincts are not enough.

### 5. Resident agents

Each human also has a file-backed sidecar in `Data_Storage/ResidentAgents/`. These JSON files can store identity, memory, personality, relationships, and decision history independent of the tensor row.

### 6. LightRAG

LightRAG combines:

- FAISS-style vector retrieval
- a NetworkX relationship graph
- a persisted graph snapshot in `Data_Storage/LightRAG/eden_graph.pkl`

It is meant to retrieve a compact top-k subset of tools/instincts instead of forcing the world model to read the entire registry every time.

### 7. MemoryLightRAG

MemoryLightRAG is a separate graph-retrieval system for resident memory and social context.

Its intended split is:

- resident sidecars remain the source of truth
- MemoryLightRAG is a derived graph for retrieval across relationships, events, and remembered places

The implementation lives under `at_the_beginning/systems/memory/`, while the persisted graph should live in `Data_Storage/MemoryRAG/`.

## Repository Layout

### Main simulation code

- `at_the_beginning/genesis_config.py`
  Source of truth for tensor schema, constants, timing, map/entity IDs, and thresholds.
- `at_the_beginning/instincts_and_tools.py`
  Core instincts, tools, animal logic, and low-level simulation primitives.
- `at_the_beginning/map_geo.py`
  Geometry registration, tile masks, and spatial lookup helpers.
- `at_the_beginning/initial_map_design.py`
  Map generator registry and map layouts.
- `at_the_beginning/map_test.py`
  FastAPI server, sim loop, protocol export, genesis setup, and endpoints.
- `at_the_beginning/agent_runtime.py`
  World/execution/human/resident runtime layers.

### Model and dataset tooling

- `models/tools_and_instincts_registry.py`
  Canonical world-model registry description for prompting and retrieval.
- `models/prompt_generator.py`
  Phase 1 prompt generation for SFT data.
- `models/output_generator.py`
  Phase 2 trace generation for structured world-model outputs.
- `models/pure_skill_output_generator.py`
  Registry-driven variant of structured trace generation.
- `models/generate_dataset.py`
  Older/alternate dataset generation path.

### Persistent data

- `Data_Storage/ResidentAgents/`
  Per-human resident JSON files.
- `Data_Storage/ExecutionAgent/state.json`
  Execution-agent persistent instinct-bit assignments.
- `Data_Storage/LightRAG/`
  LightRAG graph, embedder code, and retrieval state.
- `Data_Storage/MemoryRAG/`
  Separate graph persistence for resident memory and relationship retrieval.
- `Data_Storage/Metadata/`
  Metadata helpers and update scripts.

### Other

- `arcade/`
  Legacy Python viewer support.
- `design_docs/archive/implement.md`
  Backend/frontend architecture notes and serving protocol plan.

## Quick Start

### 1. Create and activate a virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

Base runtime:

```powershell
pip install -r requirements.txt
```

Optional legacy Arcade viewer support:

```powershell
pip install -r requirements-arcade.txt
```

Optional model/data generation tooling:

```powershell
pip install -r requirements-models.txt
```

Notes:

- `requirements-models.txt` includes `vllm` only on non-Windows platforms.
- `sentence-transformers` and `faiss-cpu` are already part of the base requirements for LightRAG.

### 3. Run the simulation server

```powershell
.\.venv\Scripts\python.exe .\at_the_beginning\map_test.py
```

The backend starts on:

- `http://localhost:8002`

On startup it:

- creates genesis
- selects a map generator
- seeds the world
- spawns Adam and Eve
- starts the async tick loop

## Godot Client

A minimal Godot client scaffold now lives in `godot_client/`.

It is intentionally using placeholder rendering, not external sprite sheets:

- map entities are drawn as colored circles/polygons
- humans are drawn as colored circles
- animals are drawn as colored diamonds

That means you do not need to download art just to get the first frontend pass working.

### Open the Godot client

1. Start the Python backend on port `8002`.
2. Open Godot 4.
3. Import the project from `godot_client/project.godot`.
4. Run the main scene.

The viewer polls:

- `/bootstrap`
- `/frame`
- `/map_delta`

### Sprite plan

For phase 1, use placeholders.

For phase 2, we can replace placeholders with:

- hand-made pixel art
- downloaded asset packs
- diffusion-generated sprites for dynamic entities

The current scaffold is structured so we can later swap `MapEntityView` and `AgentView` from drawn primitives to `Sprite2D`-based rendering without changing the backend protocol.

## Future Render Modes

The current backend protocol is designed first for top-down rendering, but it can be extended to support richer camera modes later.

### God view

This is the current intended mode:

- top-down
- semantic map rendering
- stable-ID actor updates from `/frame`

The existing payloads already support this well.

### 2.5D

Godot supports 2.5D well, including:

- sprite characters in a 3D world
- billboarded sprites that face the camera
- layered depth and fake elevation
- isometric or angled cameras

The current JSON protocol is partially ready for this because it already exports:

- stable IDs
- anchor positions
- semantic types
- map geometry

To support 2.5D cleanly later, the backend should add a few extra render-facing fields:

- `facing`
- `velocity`
- `elevation` or `z`
- `render_kind`
- `asset_id`
- `collision_radius`
- `focus_anchor`

### First-person or follow camera

Godot also supports switching from a high-level god view to a close follow camera or first-person style view.

The current protocol is not fully sufficient for that yet. A first-person or close-follow mode would benefit from:

- facing/heading
- velocity
- finer collision shape hints
- interaction focus points
- per-entity animation state

### Recommended approach

Build in this order:

1. top-down placeholder renderer
2. top-down sprite renderer
3. bidirectional control / possession
4. optional 2.5D renderer using the same world protocol
5. optional close-follow or first-person mode with extra render metadata

That way the backend stays authoritative and semantic, while Godot remains free to change camera style without forcing a full protocol rewrite.

## Available Maps

Defined in `at_the_beginning/initial_map_design.py`:

- `eden_island`
- `archipelago`
- `pangaea`
- `volcanic_eden`
- `divided_eden`

You can switch maps at runtime with:

```http
POST /set_map/{name}
```

## API Overview

### World state and frontend protocol

- `GET /bootstrap`
  Initial full world payload.
- `GET /frame`
  Live human/animal state.
- `GET /map_delta`
  Map/entity delta updates.
- `GET /status`
  Runtime debug/status summary.

### Agent and execution APIs

- `POST /god_decree`
  Queue a raw decree or a structured action packet.
- `POST /action_plan/validate`
  Validate a structured packet without executing it.
- `GET /agent_status`
  Inspect world/execution/human-agent status.
- `GET /resident/{human_id}`
  Inspect a resident sidecar.

### LightRAG APIs

- `POST /rag/retrieve`
  Retrieve top relevant tools/instincts for a query.
- `POST /rag/register_tool`
  Upsert a generated tool/instinct into LightRAG.

### Dynamic instinct loading

- `POST /load_instinct/{name}/{bit}`
  Load a generated instinct Python file from `at_the_beginning/`.

### Compatibility endpoints

- `GET /get_map`
- `GET /get_schema`
- `GET /get_agents`
- `GET /map_version`

## Structured World-Model Output Format

The world model is expected to emit packets shaped like:

```json
{
  "thought": "short internal explanation",
  "map_actions": [],
  "human_actions": [],
  "new_entities": [],
  "new_instincts": []
}
```

### `map_actions`

Actions targeting map entities, terrain, structures, or animals.

### `human_actions`

Actions targeting humans.

### `new_entities`

Used when the decree requires a new entity type not already in the local registry.

Each entry should include:

```json
{
  "type_id": 51,
  "label": "crater",
  "description": "scorched impact crater left by meteorite strike",
  "style_family": "disaster_entities",
  "diffusion_prompt": "top-down pixel art impact crater, scorched earth, dark ash ring, glowing edges, 32x32",
  "diffusion_negative": "3d, realistic, side view, blurry"
}
```

### `new_instincts`

Used when no existing tool/instinct can express the desired behavior.

Each entry should include:

```json
{
  "name": "instinct_hunt",
  "description": "Precise natural-language behavior spec for code generation.",
  "heritable": true,
  "mask": "TYPE==1"
}
```

### Important execution rule

`new_entities` and `new_instincts` do not instantly trigger diffusion or codegen just because they are non-empty.

The execution agent first:

- validates the packet
- checks the local registry
- runs the hardcoded Python path
- returns follow-up buckets such as:
  - `pending`
  - `skipped_existing`
  - `blocked_until_execution_ok`

This keeps the codegen/sprite pipeline deterministic and safe.

## LightRAG Notes

Implementation lives in `Data_Storage/LightRAG/state_lightrag.py`.

Current setup:

- default embed model: `BAAI/bge-small-en-v1.5`
- vector search: FAISS when available, numpy fallback otherwise
- graph layer: NetworkX
- persisted graph: `Data_Storage/LightRAG/eden_graph.pkl`

You can override the embed model with:

```powershell
$env:EDEN_LIGHTRAG_EMBED_MODEL = "BAAI/bge-small-en-v1.5"
```

## Model / Dataset Pipeline

The `models/` folder contains the SFT data-generation workflow for the world model.

Typical flow:

1. Run `models/prompt_generator.py` to generate/edit prompt seeds.
2. Review the generated `prompts.jsonl`.
3. Run `models/output_generator.py` or `models/pure_skill_output_generator.py` to generate validated structured traces.

These scripts are intended for training data generation, not for the live execution path itself.

## Current Limits and Caveats

- The live backend accepts structured packets today.
- Free-text decrees currently use a heuristic planner unless you wire in an external world model.
- The execution agent is intentionally deterministic and code-based.
- The legacy string mask DSL is only partial. Keep masks simple.
- The current mask parser supports useful cases like:
  - `TYPE==1`
  - `H_AGE==max(H_AGE)`
  - `H_AGE==second_max(H_AGE)`
  - `dist_to(M_TYPE==2)<40`
  - `rank(HP,desc)<=2`
  - `H_NAME in ['Adam','Eve']`
- More complex nested helper expressions inside string masks are still a bad idea.
- For multi-spawn human placement, prefer `spawn_points` over legacy `sample(...)` strings.
- Dynamic instinct loading still expects a generated Python file to exist locally before `/load_instinct/{name}/{bit}` is called.

## Development Notes

- If you add or change schema, start with `at_the_beginning/genesis_config.py`.
- If you add a new tool or instinct, update `models/tools_and_instincts_registry.py` too.
- If the tool should be retrievable by the world model, register or upsert it into LightRAG.
- If you add a new map, register it in `at_the_beginning/initial_map_design.py`.

## Suggested First Steps for New Contributors

1. Read `at_the_beginning/genesis_config.py`.
2. Read `at_the_beginning/map_test.py`.
3. Read `at_the_beginning/agent_runtime.py`.
4. Read `at_the_beginning/instincts_and_tools.py`.
5. Inspect `models/tools_and_instincts_registry.py`.

That path gives the fastest understanding of the actual runtime.
