# Eden 2D — 1006 new start

A native desktop 2D/2.5D prototype in Python and Arcade. It uses the existing
`../myassets` collection and a new generated transparent nature/survival atlas.
No Godot or web project files are modified.

The shared October 6 rebaseline arrived after this exploratory prototype was
built. Production direction is Godot 2D; preserve this Arcade prototype as art and
gameplay reference. It is not the production client or a shared authored-map
implementation. See `PROGRESS.md` for unit/schema proposals and remaining work.

## Play

From the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\2D1006newstart\launch.ps1
```

The existing repository `.venv` already has Arcade and Pillow. For a fresh Python
environment, install `requirements.txt` and run `python main.py` from this folder.
Keep this folder alongside `myassets`; paths are resolved relative to the code,
so the launcher works regardless of the shell's current folder.

Walk around the village, speak to Mira beside the campfire, gather 3 wood from
trees and 2 stone from rocks, then interact with the fire to finish the first task.
Gather berries and eat them, use the well, or open the supply crate.

| Input | Action |
| --- | --- |
| WASD / arrows | Walk |
| Shift | Run |
| E | Interact / close dialogue |
| B | Eat a berry |
| F5 / F9 | Save / load local prototype world |
| Mouse wheel / +/- | Zoom |
| Escape | Pause / resume |
| H | Help |
| F12 | Save screenshot |

The local save is `saves/world.json`. It stores position, inventory, depletion,
quest progress, hunger, and time. It does not touch Eden's backend save files.
Closing the window does not autosave: press F5 to keep progress.

## Implemented starting slice

- Deterministic village, woods, roads, and coast.
- Transparent generated oak, pine, rock, berry, campfire, and well sprites.
- Locally generated water and sand tiles, selected after visual review.
- Houses assembled from the existing tile art.
- Four-direction walking animation, camera follow, zoom, foot depth sorting.
- Collision against buildings, resource objects, and water.
- Gathering, limited stocks, crate loot, inventory, dialogue, eating, and a task.
- Health/hunger indicators, minimap, pause/help, screenshots, atomic local saves.

This is a small local gameplay prototype. It does not yet execute Eden's full
resident AI, combat, planning, construction, or memory systems. Hunger decreases
slowly; starvation damage and full survival balancing are not implemented.

## Observe the existing Eden simulation

When an Eden backend is already running:

```powershell
.\2D1006newstart\launch.ps1 -Backend http://127.0.0.1:8002
```

This mode reads `/bootstrap` and `/frame` on a background thread, projects map
entities and actors into the 2D view, and lets WASD pan the camera. It sends no
POST requests. Gathering, local saves, and local interactions are disabled.
It is a first transport integration, not backend possession/control. Its ground
is the prototype ground, not Eden's authoritative terrain; entity coordinates
are normalized into the prototype world bounds. Animals temporarily share the
human marker. Bootstrap map data refreshes every five seconds. These are next
integration tasks alongside action animations and biome art.

## Verify

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s .\2D1006newstart\tests -v
.\.venv\Scripts\python.exe .\2D1006newstart\main.py --capture .\2D1006newstart\screenshots\opening.png
```

The capture is rendered through the actual Arcade/OpenGL game, not a mockup.

`verify_ui.py` also exercises the real window callbacks for movement, pause,
save/load, dialogue, help, zoom, and resizing. Its saves are isolated in the test
scratch folder. Run it with the repository Python interpreter.

## Local image generation

Future bulk art generation should use the user's local Qwen-Image setup at
`C:/Users/Rita/Desktop/caleb/voiceimage/qwen-image-2.1`. The local CLI and model
files are reused without modifying that folder. Candidate images and their exact
prompts are saved under `../myassets/generated`.

```powershell
.\2D1006newstart\generate_local.ps1 -Job sand
```

`local_asset_jobs.json` holds the prompts, seeds, and settings. Existing candidate
files are never overwritten: add a new versioned job to iterate. The example job
will refuse to run if its output already exists. Each 512px/32-step generation
took roughly 45 seconds on this RTX 4060 during the initial check. This is a local
compute route with no OpenAI image API call; Codex prompt work and visual reviews
still use Codex. Generation is sequential to fit the GPU memory budget.

Review every candidate for unwanted borders, repetition, palette, silhouettes,
transparency, and scale before importing. A candidate is not automatically a
production asset. The first water candidate was rejected for an edge frame.
The revised water tile and first sand tile are accepted in
`../myassets/generated/approved.json`; only accepted terrain is loaded by the game.
`generate_local_batch.ps1` runs selected jobs sequentially and skips existing
outputs. It never automatically approves candidates. Add as many versioned jobs
as needed to `local_asset_jobs.json`, then review their outputs before approval.

## Art provenance

Existing environment art is by Hypnobius; its terms remain in `../myassets/licenses`.
Existing character sheets have no accompanying license in the repository; verify
distribution permissions before shipping them. The new nature atlas was generated
with the built-in imagegen tool. Its exact prompt and import details are in
`../myassets/generated/generation.json`. The original alpha is preserved, and
sprites are extracted from its 3 x 2 layout during game import.
