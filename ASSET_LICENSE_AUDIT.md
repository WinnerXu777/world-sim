# Asset license audit (what the 2D client actually uses)

Audited 2026-10-07 from `godot_client_2d/data/import_lock.json` (33 imported assets) and the `myassets` manifests. This is a provenance audit, not legal advice. "Unverified" means the repository does not contain proof, not that the asset is unlicensed.

## Summary

| Group | Used | Status | Release risk |
| --- | --- | --- | --- |
| Hypnobius "Medieval Village Exterior RPG Tileset" (grass, houses, walls, barrel, cart, crate, planter) | 12 | Licence file in repo (`myassets/licenses/MedievalVillage_LICENSE.txt`): commercial and personal use allowed, modification allowed, credit optional. Not allowed: reselling or redistributing the pack (modified or not), including tiles in other downloadable packs, NFTs/blockchain, AI training datasets | Low for a game, but the game must not ship the raw pack as a standalone asset pack; credit the artist |
| Eden procedural terrain (`cobble_tileable`, `flagstone_slate`, `plank_floor`) | 3 | Original work from `tools/generate_tileable_terrain.py` | None known |
| Character sheets `cyclops_amazon`, `dungeon_stalker`, `elven_adventurer`, `orc_mercenary` (`adventurer_pack_2`) | 4 | **Licence not supplied in the repository** | **High: must be resolved or replaced before any release** |
| Recoloured variants `stalker_smith`, `stalker_iven`, `elven_elsa` | 3 | Derived from the above, so same status | **High**, same as above |
| Generated props, cloud-model batch (`boulders`, `campfire`, `oak`, `pine`, `well`) | 5 | "Generated output terms not independently verified" | Medium: check the generating service's terms |
| Generated props, local-model batch (`anvil`, `berry-bush`, `forge`, `iron-pile`, `cot`, `wood-pile`) | 6 | "Local model/GGUF and generated-output distribution terms not verified" | Medium: check the model licence (Qwen-Image 2.1 GGUF) and output terms |

## What must happen before a public release

1. **Characters (7 sheets in use):** find the original source and licence for `adventurer_pack_2` (the folder `Adventurer_Pack_2_RPG_Maker` next to the repo suggests an RPG Maker pack; the licence is not in `myassets/licenses/`), or replace the sheets with original or properly licensed art. The recoloured variants cannot be cleaner than their source.
2. **Generated props (11):** read and record the terms of the local model and weights actually used (see `myassets/generated/*.json` and `a1/manifest.json`), and of any cloud generator used for the first five. Add the result to the manifest `license_status` fields.
3. **Medieval Village:** keep the licence text with any distribution, credit Hypnobius in the game's credits, and do not publish `game_frontend/assets/MedievalVillageExteriorv1.0` or the zip as part of the repository if the repository becomes public (the licence forbids redistributing the pack).
4. Remove the legacy 3D assets and add-ons from any public repository (not audited here; the large Godot add-ons and Mixamo animations have their own terms).

## Not used by the 2D client but present in the repository

`godot_client/` (3D) assets and add-ons (Humanizer, Mixamo retargeter, Fantasy Props MegaKit), `game_frontend/` assets, `third_party_archives/`, `2D1006newstart/` prototype assets. They are excluded from this audit and are covered by `.gitignore` in part; check them separately if the repository is ever made public.

## How to re-run this audit

`godot_client_2d/data/import_lock.json` lists every asset the client imports with its manifest metadata; group the entries by `metadata.pack` and `metadata.license_status`.
