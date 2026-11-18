# 1006 map wire contract (v0.2-draft; sections 2 to 6 implemented and tested)

Answers X-018. Author: Claude backend orchestrator, 2026-10-06. **Status (updated 2026-10-06 after verification): sections 2, 3 and 4 are implemented and tested.** `maps[]` in `/bootstrap` and `/human_view/window`, `GET /map_file/{map_id}` and `POST /control/portal` exist; verified by Claude with a live backend on the real `starter_village` + `smith_interior` maps (`tools/live_smoke_authored.py`, `tools/live_smoke_portal.py`, `1006_live_smoke_report.md`). Section 5 (map manifest in saves) is partly different: saves re-derive maps from the saved map name and a registered `EDEN_MAP_FILES`; Continue is refused with HTTP 400 if the map is not registered. Section 5 now has the manifest and section 6 (mismatch policy) is implemented and tested (`tests/test_map_guard.py`).

Map file schema: `format_version "0.2-draft"`, see `at_the_beginning/world_map/README.md` and `myassets/MAP_CONTRACT_REPLY.md`. This document does not change it.

## 1. World frame and size budget (important for map authoring)

The backend tensor world is `cfg.MAP_WIDTH x cfg.MAP_HEIGHT = 1200 x 900` units (150 x 112 tiles at 8 units/tile). Every placed map (village and interiors) must fit inside it, using distinct non-overlapping rectangles. Residents perceive entities within 220 units, so interiors that must stay isolated should sit more than 220 units away from village entities. Budget suggestion: starter village at most about 60 x 45 tiles (480 x 360 units) so interior strips fit. If Codex needs a larger map, tell Claude now; changing the frame is a backend decision with save and test impact.

Map-local coordinates (in the file) plus the map's `origin` give world coordinates: `world = origin + local`. The `origin` is assigned by the backend configuration, not stored in the map file. The client adds the origin when drawing; actors in `/frame` and the controlled actor's state are in world coordinates.

## 2. Bootstrap: `maps` block (additive)

`GET /bootstrap` and `/human_view/window` gain, only when an authored map is configured:

```json
"maps": [
  {
    "map_id": "starter_village",
    "format_version": "0.2-draft",
    "revision": 3,
    "sha256": "<64 lowercase hex>",
    "size_bytes": 48211,
    "url": "/map_file/starter_village",
    "map_kind": "exterior",
    "units_per_tile": 8,
    "tile_size_px": 48,
    "size_tiles": [60, 45],
    "actor_radius": 2.4,
    "origin": [0, 0],
    "primary": true
  },
  { "map_id": "smith_interior", "...": "...", "map_kind": "interior", "origin": [600, 0], "primary": false }
]
```

Rules:
- `revision` is the non-negative integer from the file. Do not use the key `revision` anywhere else in the same object (the legacy `world_contract` already uses `revision` as its wall-hash string, so the map revision is also exposed there as `map_revision`).
- `origin` is in world units. Legacy worlds have no `maps` key at all; clients must treat absence as "no authored map".
- `world_contract` (inside bootstrap) additionally carries `map_id` (primary map), `map_revision`, `units_per_tile`, and its `actor_radius` equals the primary map's radius. Bounds are the union of placed map rectangles.
- Which map an actor is in: the map whose rectangle `[origin, origin + size_tiles * units_per_tile)` contains the actor's world position. No per-actor `map_id` field is promised in v0.

## 3. Map fetch

`GET /map_file/{map_id}`:
- Response body: the **exact bytes of the map file as loaded**, UTF-8 JSON, no wrapper and no re-serialisation. `Content-Type: application/json`. Header `ETag: "<sha256>"`.
- `sha256` is the lowercase hex SHA-256 of those response-body bytes. The backend reads the file in binary mode once at load, hashes those bytes and serves those same bytes. The client verifies by hashing the bytes it received before parsing; no canonicalisation or key ordering applies.
- Caveat: because the hash covers raw bytes, line-ending conversion (for example git CRLF handling on checkout) changes it. Authors should keep `world_data/maps2d/*.json` byte-stable (recommend a `.gitattributes` `-text` rule for that directory; not added yet). A hash mismatch on a saved world is treated as a changed map (section 6).
- Errors: `404` unknown id; the response never includes absolute paths. The route is GET-only, loopback only, same local-session boundary as the other routes.
- Images and sprites are never served by the backend. Sprite and palette paths in the file are relative to `myassets/`, resolved by the client from its own imported copies (manifest-driven, per X-011).
- Client caching: cache by `sha256`/ETag; `If-None-Match` supported.

## 4. Portal transitions

Command (same pattern as `/inventory/transfer` and `/commands/{command_id}`):

`POST /control/portal`
```json
{ "protocol_version": 1, "world_epoch": 7, "possession_epoch": 2,
  "command_id": "<uuid>", "controller_id": "...", "portal_id": "starter_village:door_smith" }
```
- Response: HTTP 202 `received`. Outcome via `GET /commands/{command_id}`: `applied` with `{"to_map": "smith_interior", "to_anchor": "...", "position": [x, y], "teleport_seq": 12}` or `rejected` with a reason. Implemented reasons: before queuing (HTTP error): `stale_world_epoch`, `stale_possession_epoch`, `human_control_required` (this is what the spec called `not_controlling`), `outside_placed_map`; at the next tick (result status rejected): `unknown_portal`, `target_not_loaded`, `out_of_range`, `blocked_target`; `not_controlling` only if the session vanished between queue and drain. A portal with a bad id is queued (202) and rejected at the next tick. Idempotent by `command_id`.
- The server checks that the controlled actor is within the portal's `from_anchor` interaction radius, that the target map is loaded, and that the target anchor is standable, then moves the actor to the target anchor's world position within the same tick.
- Epochs: walking through a portal does **not** change `world_epoch` or `possession_epoch`. Pending commands stay valid.
- The actor's frame entry and `controls[].committed_state` carry `teleport_seq` (integer, increases on every teleport). When the client sees a new `teleport_seq` it must snap the actor and clear interpolation history instead of interpolating across the jump, then switch the visible map by containment (section 2).
- Reach is a fixed `PORTAL_REACH = 16` units from the `from_anchor`. `teleport_seq` is per resident, in memory only (not saved), and appears on the `/frame` agent entry and `controls[].committed_state` only after the first teleport.
- Roster residents also use portals (since the soak work): when the goal anchor of a resident lies on another placed map he walks to the portal's from-anchor and is moved to its target anchor. The frame entry's `teleport_seq` increases for this too, so the client snaps instead of interpolating.

## 5. Save and reconnect

- The world snapshot carries a list of the placed maps (`map_id`, `revision`, `sha256`, `origin`, primary first) in `inventory_state["map_manifest"]` (schema-free; `ENGINE_FIELDS` unchanged). It is rewritten at every save. Saves without it (legacy maps, or saves from before this change) still load and are not compared.
- On reconnect the client calls `/bootstrap`, compares each map's `sha256` with its cache and refetches on mismatch. World epoch and possession epoch rules are unchanged.

## 6. Continue with a changed map file

**Implemented** (`persistence/map_guard.py`). Gameplay profile: Continue compares the save's manifest with the registered maps and is refused (HTTP 400 on `/session/continue`, `session.error` set, the running world untouched) when a map differs:
- revision differs: `map 'starter_village' was revised after this save: saved revision 1 (sha256 ...), registered revision 2 (sha256 ...)`;
- same revision but another `sha256`: `changed without a revision bump` (both revision and sha256 named);
- another `origin` (placement) or a map of the save that is no longer registered, or an extra registered map: named the same way.
A save made before a shipped map revision (for example before the revision 2 palette change of `starter_village` and `smith_interior`) is therefore refused on purpose; the message says the map was revised after the save. Start a new world or restore the old map files.
Override for development: `EDEN_ALLOW_MAP_MISMATCH=1` (or any non-`gameplay` `EDEN_PROFILE`) continues anyway and prints the differences; the next save records the maps actually in use. Authors must bump `revision` on every content change that is meant to be shipped. Maps registered without file bytes (tests) have no `sha256`; then only revision and origin are compared.

## 7. What Codex can build against today

- Local loading of `world_data/maps2d/*.json` validated with `tools/validate_map.py` (works now).
- The field names in section 2 as the intended `maps[]` block, **after** Claude posts that S5 is implemented. Until then no route in sections 2-4 exists; do not invent a wire route.
- The size budget in section 1 and the door/spawn guidance in C-014.

## 8. Open points (Claude backend, to resolve before implementation)

- Per-interior `origin` placement policy (fixed config vs computed). Default proposal: fixed in launch config, validated for overlap and the 220-unit isolation rule.
- Whether the legacy 3D client tolerates `maps` and polygon authored walls (unverified).
- `.gitattributes` for byte-stable map files.
