# S-1 family_farm authoring report

Created on branch 1008implementation. Format 0.2-draft, revision 1 throughout.
Only four new files were created:

- world_data/maps2d/family_farm.json
- world_data/maps2d/family_home_interior.json
- world_data/maps2d/neighbour_home_interior.json
- 1008_family_farm_report.md

Exterior: 40 x 30 tiles, 8 units/tile, 48 px/tile, actor radius 2.4.
Interiors: 12 x 10 tiles, copied cottage perimeter/10-unit door channel style.
Total: 21 interactive entities, 40 anchors, 4 paired portals, 5 single-capacity beds,
3 storage containers plus the optional counter. The family pantry is a porch crate
with 2 rations; its interior storage starts unseeded. Neighbour pantry is inside
the neighbour interior with 14 rations and 6 crop bundles. No duplicate stock.

## Distances and access

Family door entity and portal anchor: [48,80]; neighbour door: [133,80].
Exact Euclidean distances in backend units (checked to 1e-9 tolerance):

| From | To | Units |
| --- | --- | --- |
| Family door | Family plot [48,105] | 25 |
| Family door | Well [13,80] | 35 |
| Family door | Neighbour door | 85 |
| Family door | Bushes [198,80], [223,80], [248,80] | 150, 175, 200 |
| Third bush | Hostile marker/spawn [248,110] | 30 |
| Either door | Counter [90.5,94.79019945774904] | 45 |

The counter is on the perpendicular bisector, 14.79019945774904 units south of
the segment midpoint. This resolves section 5's incompatible literal midpoint
and 45-unit distances while preserving both specified distances.
All anchors pass standability and flood-fill reachability. Every interactive
entity has a reachable work/talk anchor within interact_radius; bush work anchors
are also within the resource circle (5 units away, radius 6). Plot and bush work
anchors use for_role gatherer. Beds each have sleep and work anchors. Both families
have exterior spawn anchors. IDs are unique across all seven authored maps.

## Existing sprites and stand-ins

- Three farm_plot entities use a2/sprites/planter-a2-v1.png, the existing village
  farm-bed sprite. Semantic kind farm_plot and resource crops follow section 7.
- Optional market counter uses storage and a2/sprites/crate-a2-v1.png.
- Hostile area marker uses noninteractive tree and a1/sprites/pine-a1-v1.png,
  with a separate spawn anchor family:hostile_spawn. It marks the area only.
- No fish_spot is required by section 5, so none was authored and no fish stand-in
  was needed.
- Homes, bushes, well, wood, beds and interior wall art reuse shipped map sprites.
  All sprite paths were checked against myassets; no sprite files were invented.

## Validation

Exact command from repository root (PYTHONDONTWRITEBYTECODE=1 was set):

```powershell
.venv\Scripts\python.exe tools\validate_map.py world_data\maps2d\family_farm.json world_data\maps2d\family_home_interior.json world_data\maps2d\neighbour_home_interior.json --base-dir myassets
```

Output:

```text
world_data\maps2d\family_farm.json: map_id=family_farm revision=1 size_tiles=[40, 30] units_per_tile=8.0 actor_radius=2.4 walls=12 anchors=18 entities=15 portals=2
world_data\maps2d\family_home_interior.json: map_id=family_home_interior revision=1 size_tiles=[12, 10] units_per_tile=8.0 actor_radius=2.4 walls=10 anchors=12 entities=11 portals=1
world_data\maps2d\neighbour_home_interior.json: map_id=neighbour_home_interior revision=1 size_tiles=[12, 10] units_per_tile=8.0 actor_radius=2.4 walls=9 anchors=10 entities=10 portals=1
OK (0 error(s))
```

Exit code 0; zero errors and zero warnings. Cross-map portal targets were checked.
Additional light assertions checked the exact distances, interactive entity
work/talk proximity and globally unique IDs.

## Entity table

### family_farm

| Entity id | Kind | Resource keys (flat) |
| --- | --- | --- |
| `family:home` | `building` | None |
| `family:door_home` | `door` | None |
| `neighbour:home` | `building` | None |
| `neighbour:door` | `door` | None |
| `family:pantry` | `storage` | `{"stock":{"rations":2}}` |
| `family:plot_1` | `farm_plot` | `{"resource":"crops","amount":0,"cap":40,"water":30,"regrow":0.1,"radius":10}` |
| `neighbour:plot_1` | `farm_plot` | `{"resource":"crops","amount":30,"cap":40,"water":60,"regrow":0.1,"radius":10}` |
| `neighbour:plot_2` | `farm_plot` | `{"resource":"crops","amount":30,"cap":40,"water":60,"regrow":0.1,"radius":10}` |
| `family:well` | `well` | `{"resource":"water","amount":80,"cap":100,"regrow":0.08,"radius":10}` |
| `family:bush_far_1` | `berry_bush` | `{"resource":"berries","amount":24,"cap":40,"regrow":0.02,"radius":6}` |
| `family:bush_far_2` | `berry_bush` | `{"resource":"berries","amount":24,"cap":40,"regrow":0.02,"radius":6}` |
| `family:bush_far_3` | `berry_bush` | `{"resource":"berries","amount":24,"cap":40,"regrow":0.02,"radius":6}` |
| `family:wood_pile` | `wood_pile` | `{"resource":"wood","amount":20,"cap":20,"regrow":0,"radius":10}` |
| `family:market_stall` | `storage` | `{"stock":{"wood_bundle":3}}` |
| `family:hostile_marker` | `tree` | None |

### family_home_interior

| Entity id | Kind | Resource keys (flat) |
| --- | --- | --- |
| `family_interior:wall_art_north` | `decoration` | None |
| `family_interior:wall_art_west` | `decoration` | None |
| `family_interior:wall_art_east` | `decoration` | None |
| `family_interior:wall_art_south` | `decoration` | None |
| `family_interior:wall_art_door_left` | `decoration` | None |
| `family_interior:wall_art_door_right` | `decoration` | None |
| `family_interior:bed_1` | `bed` | `{"capacity":1}` |
| `family_interior:bed_2` | `bed` | `{"capacity":1}` |
| `family_interior:bed_3` | `bed` | `{"capacity":1}` |
| `family_interior:storage` | `storage` | None |
| `family_interior:exit_door` | `door` | None |

### neighbour_home_interior

| Entity id | Kind | Resource keys (flat) |
| --- | --- | --- |
| `neighbour_interior:wall_art_north` | `decoration` | None |
| `neighbour_interior:wall_art_west` | `decoration` | None |
| `neighbour_interior:wall_art_east` | `decoration` | None |
| `neighbour_interior:wall_art_south` | `decoration` | None |
| `neighbour_interior:wall_art_door_left` | `decoration` | None |
| `neighbour_interior:wall_art_door_right` | `decoration` | None |
| `neighbour_interior:bed_1` | `bed` | `{"capacity":1}` |
| `neighbour_interior:bed_2` | `bed` | `{"capacity":1}` |
| `neighbour:pantry` | `storage` | `{"stock":{"rations":14,"crop_bundle":6}}` |
| `neighbour_interior:exit_door` | `door` | None |

## Scope limits and orchestrator decisions

No runtime scenario, residents, inventories, relationships, scarcity power call,
wolf creature configuration, launch/roster config or resource engine changes
were authored. The map validator proves data/access validity; gameplay was not
launched and the full test suite was not run.

Orchestrator: register these three new maps, place family_farm at the design's
origin [420,0], and choose nonoverlapping interior origins. Bind the five residents
to the supplied spawn/sleep/work anchors, configure the hostile area's creature
spawn separately, and enable the existing resource feature flag when running S-1.
Keep the documented planter/crate/tree stand-ins until dedicated art is available.
The counter geometry and porch pantry are explicit authoring choices above.

Verification: tracked git diff remained byte-identical to the initial baseline,
and SHA-256 hashes of all four existing authored maps and initial dirty files
were unchanged. Pre-existing game_frontend/dist and godot_client changes remain
untouched. No existing file was edited; only the four files listed above were
added. No git add, commit, push, stash or .gitignore change was performed.

Final status note: the three new map paths appeared in the Git index during final verification, although this task issued no Git mutation commands. This indicates concurrent external Git activity; the report remains untracked. Existing-file verification above compares the worktree content, not ownership of external index changes.
