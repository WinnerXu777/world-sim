# Memory System Design

## Purpose

`systems/memory` is the home for persistent personal memory, relationship memory,
and graph-based retrieval for escalated human decisions.

This is intentionally separate from the existing tool/instinct LightRAG.

## Separation Of Concerns

### Resident sidecars remain the source of truth

Per-human truth stays in:

- `Data_Storage/ResidentAgents/*.json`
- managed by [resident_store.py](C:/Users/Rita/Desktop/world_simulator/at_the_beginning/runtime/resident_store.py)

These files are best for:

- profile
- personality
- current status
- recent event lists
- local remembered resources
- direct relationship values

### MemoryLightRAG is the derived retrieval layer

`MemoryLightRAG` lives in:

- [state_memoryrag.py](C:/Users/Rita/Desktop/world_simulator/at_the_beginning/systems/memory/state_memoryrag.py)

Its persisted graph should live under:

- `Data_Storage/MemoryRAG/memory_graph.pkl`

This graph is best for:

- family/ally/rival connection lookup
- conflict chains
- place memory lookup
- top-k retrieval for the human decision agent
- relation-aware prompt context

## Why Separate It From Tool LightRAG

The current tool LightRAG answers:

- "what tools and instincts should the world model use?"

MemoryLightRAG answers:

- "what personal/social context matters for this human right now?"

Mixing these two graphs would muddy retrieval and make prompts less focused.

## System Placement

Yes, it is better to put the domain code in `systems/memory`.

Reason:

- memory is a simulation domain, not just a storage folder
- human-agent escalation will depend on it directly
- it belongs beside `social`, `health`, `perception`, and `combat`

The persistence artifact still lives in `Data_Storage/MemoryRAG/`.

## Node Types

- `resident`
- `relationship`
- `event`
- `place`

Future node types:

- `tribe`
- `concept`
- `settlement`
- `lineage`

## Edge Types

- `has_relationship`
- `remembers`
- `knows_place`
- `fears`
- relation kinds such as `family`, `friend`, `rival`, `mate`

Future edges:

- `parent_of`
- `child_of`
- `helped`
- `attacked`
- `belongs_to_tribe`
- `visited`

## Read Path

Escalated decision flow should eventually be:

1. build the resident case from the sidecar and live tensors
2. derive a memory query from the case
3. retrieve top-k relation/event/place nodes from MemoryLightRAG
4. pass both:
   - resident JSON
   - memory graph retrieval bundle
   into the human decision agent

## Write Path

Recommended pattern:

1. sim updates resident sidecar
2. `systems/memory/ops.py` syncs that resident into MemoryLightRAG
3. graph retrieval stays derived and rebuildable

This keeps the graph replaceable and prevents graph drift from becoming the only truth.

## Retention Policy

Memory should not grow without bound.

Use a 3-tier policy:

- `permanent`
  - family links
  - parent/child lineage
  - mate bonds
  - death / killed-by / major birth events
- `decay`
  - conflicts
  - disaster memories
  - threat sightings
  - known food/water locations
  - routine decisions
- `dead-resident compacted`
  - keep the resident node
  - keep permanent relationship structure
  - keep only a small high-salience event core
  - drop routine place and threat memory

Resident sidecars should hold:

- `memory_class`
- `salience`
- `created_tick`
- `last_reinforced_tick`
- `expires_tick`
- `permanent`
- `archived`

`MemoryLightRAG` should only sync active, non-archived entries, so the graph stays
derived and trim-friendly over long runs.

## Reusability Rule

Generated instincts or tools should not write graph edges directly as their main storage.

Prefer:

1. update resident memory/relationship through stable ops
2. sync resident -> MemoryLightRAG
3. retrieve through MemoryLightRAG later

That keeps the pipeline more reliable for smaller open-source models.
