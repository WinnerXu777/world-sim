# Map fixture sprites (placeholders)

The fixture maps in `tests/fixtures/maps/*.json` (and a few tests that build maps inline) reference these files. The map validator only checks that each file **exists** inside the base directory (`at_the_beginning/world_map/validate.py`, `_sprite_problem`: `is_file()` plus a path containment check). No test reads their size or pixels, so plain placeholder tiles are enough.

All six are 48x48 RGBA, one plain opaque fill colour each, made with PIL on 2026-11-18 (R0.1 / T1 follow-up S1):

| File | Fill | Referenced by |
|---|---|---|
| `grass.png` | #567d3a | tiny_village, example_smith layer palettes; test_world_map_v02 |
| `path.png` | #b09466 | tiny_village layer palette |
| `floor.png` | #7a5634 | tiny_village, tiny_interior, example_smith_interior layer palettes |
| `forge.png` | #46464a | tiny_village, example_smith entity sprite |
| `chest.png` | #8c5e30 | tiny_village entity sprite; test_harness_map_resources inline entities |
| `tree.png` | #2c5a28 | tiny_village entity sprite |

`myassets/terrain/grass.png` (48x48) also exists, but it was deliberately **not** copied here: `myassets/` images stay out of git and their licence is unverified. Other near-matches in `myassets/` (`terrain/plank_floor.png`, `a1/sprites/forge-local-a1-v1.png`, `props/tree_small.png`) were left out for the same reason.

Note: the repository's `.gitignore` ignores `*.png`, so these files are committed with `git add -f`.
