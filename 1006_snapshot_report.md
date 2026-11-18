# S0 local recovery snapshot report

Scope: delegated local recovery snapshot only. No push, checkout switch, reset, clean, source edits, or communication-doc edits were performed.

## Recovery refs

- Commit: `9259455f99181fd559fda754ccba63088966e8c3`
- Parent: `88e48823509c0b861f1cd49cb43dc5354f18111f`
- Branch: `codex/legacy-3d-1006`
- Annotated tag: `legacy-3d-1006`
- Tree: `4f6a0230c500ff4154ada47b42ed4c6c426f9b52`
- Tag object: `60b46a830374fd49ff7317bf1805e00182352140`
- Both refs resolve to the new commit; the tag is annotated. Both refs were created in one Git update-ref transaction with create-only semantics.
- Configured remote: `origin`, `https://github.com/calebxu777/world_simulator.git`. Remote reachability and remote ref state were not checked here. No network request or push was made.

## Timing and capture boundaries

- Plan completed: 2026-10-06 23:04:56.681 America/Toronto (UTC-04:00).
- Successful file capture started: 2026-10-06 23:05:55.211 America/Toronto (UTC-04:00).
- Successful file capture finished: 2026-10-06 23:06:14.132 America/Toronto (UTC-04:00).
- Refs published locally: 2026-10-06 23:07:17.073 America/Toronto (UTC-04:00).
- Verification finished: 2026-10-06 23:07:19.335 America/Toronto (UTC-04:00).
- This is a file-by-file recovery capture, not an atomic image of an actively edited workspace. The inventory was fixed at planning time. Each selected file was read once into memory, hashed/stored with the normal Git clean conversion for its path, and inserted into a HEAD-seeded temporary index. The actual blob IDs and capture times below identify exactly what was committed.
- Active A1 assets and coordinator documents may be incomplete or change later. Snapshot inclusion does not approve asset quality, schema, scale, or gameplay readiness.
- Specific inflight artifact: the iron-pile request/provenance sidecar is captured, but its PNG was produced after the fixed inventory and remains outside this snapshot. Recover the active asset work separately once A1 is coherent.
- A first temporary-index capture encountered a Python helper argument error after creating blobs/index but before creating any commit/ref. The helper was corrected and a fresh second temporary index was used. The first index remains only under ignored `.tmp/snapshot_s0/`; it never replaced the original index.

## Preservation and verification

- Checked-out branch remains `refs/heads/main`; HEAD remains the parent commit above.
- Original index SHA-256 before and after: `173a3c98db66c628da7ac23e56e3a8306abd3fc1a86ecd1dd6114f062067beb5`.
- Original staged-entry digest before and after: `1ee3674f7191fed996f05c2b7e05ce54fb99eb9e8c1982cde8249499ce1e07b1`.
- Original staged-diff digest before and after: `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` (the original index had no staged changes).
- Hashed 11,149 original tracked/visible untracked files to detect content changes. Snapshot operations only wrote ignored temporary metadata, Git objects/refs, and this new report. Ignored runtime/cache contents were not exhaustively inventoried.
- Verified every captured blob against the final tree, matching branch/tag commit targets, matching commit tree, and absence of every explicitly excluded candidate from the parent-to-snapshot diff.
- Main, original index bytes and staged state were exactly preserved. Concurrent changes/new files listed below prevent claiming the entire live working tree stayed byte-for-byte fixed.
- No Python/Godot behavior tests were run for this recovery-only task; these are Git integrity and preservation checks.

## Included pending paths

171 selected files; 171 changed paths relative to parent; 13,207,520 Git blob bytes across selected files (12.60 MiB, uncompressed). Complete inherited repository size is larger.
`Data_Storage/LightRAG/state_lightrag.py` is executable retrieval source and is included separately from runtime JSON/pickle data.

| Path | Blob ID | Bytes read | Captured UTC |
| --- | --- | ---: | --- |
| `.gitignore` | `5e650fcee42f9484c9590ff02bf360997fe16dac` | 1389 | 2026-10-07T03:05:55.317469+00:00 |
| `1006_2d_first_version_goal.md` | `b238d50a4ce95ae0641f07a1feb9909101cb45fa` | 4103 | 2026-10-07T03:05:55.399124+00:00 |
| `1006_communication_scratchpad.md` | `133c58e40c55f3f9885063d8e6fa9efd3c14d123` | 22613 | 2026-10-07T03:05:55.471062+00:00 |
| `1006_godot2d_port_audit.md` | `a772a346944605be0413dd0ddae6d7c253468da3` | 24126 | 2026-10-07T03:05:55.546425+00:00 |
| `1006_map_backend_integration.md` | `309df523d08151af638322ceb3a61c737c94dbc1` | 21945 | 2026-10-07T03:05:55.620002+00:00 |
| `1006megathread.md` | `fb1e4ca15820b508e3f503c63c2433fc9eb5879a` | 50192 | 2026-10-07T03:05:55.691591+00:00 |
| `1006newdesign.md` | `138add6aa748cc5649c57f64c52ccc7a6cdb373a` | 19408 | 2026-10-07T03:05:55.767055+00:00 |
| `2D1006newstart/.gitignore` | `2af8332d57e19e7bb0f120bb359e863c8c222c7f` | 38 | 2026-10-07T03:05:55.838773+00:00 |
| `2D1006newstart/PROGRESS.md` | `45a23348f948a5e88b013ea47fed3c8eeea661c8` | 12560 | 2026-10-07T03:05:55.908597+00:00 |
| `2D1006newstart/README.md` | `6da5ed2bda229bb8dc68ddf9d34c0ba2b68693d7` | 5773 | 2026-10-07T03:05:55.981809+00:00 |
| `2D1006newstart/assets.py` | `931d118c22904f546753e187082b35c8fe6366b5` | 3564 | 2026-10-07T03:05:56.051988+00:00 |
| `2D1006newstart/backend.py` | `4dfe34eacb119591ca931bc169906e7bf7e76adc` | 1702 | 2026-10-07T03:05:56.123549+00:00 |
| `2D1006newstart/generate_local.ps1` | `89eb97eefd715ba82b7ed0899f0264304a589477` | 2148 | 2026-10-07T03:05:56.195723+00:00 |
| `2D1006newstart/generate_local_batch.ps1` | `f452be5a732d1965632f50f538605f30373a6857` | 677 | 2026-10-07T03:05:56.266050+00:00 |
| `2D1006newstart/launch.ps1` | `73705a1b02bc29f27da2a6dd04e5c9c5e051d2b8` | 465 | 2026-10-07T03:05:56.340592+00:00 |
| `2D1006newstart/local_asset_jobs.json` | `d728f616eae16b7021f12c48b538a823c8616f00` | 3091 | 2026-10-07T03:05:56.412870+00:00 |
| `2D1006newstart/main.py` | `c6531fd2e7761f023a391a011d164e2379926fc0` | 18792 | 2026-10-07T03:05:56.482692+00:00 |
| `2D1006newstart/requirements.txt` | `83d0cb106df554e1b5ecb0c3e9eee37f92ed0c63` | 27 | 2026-10-07T03:05:56.552547+00:00 |
| `2D1006newstart/screenshots/coast.png` | `d0731211d5805ebc5c81b715a9c3fc0b5b4c1490` | 710747 | 2026-10-07T03:05:56.627501+00:00 |
| `2D1006newstart/screenshots/dialogue.png` | `48233bceab14e3c469a599ac5e2b94609def5543` | 505503 | 2026-10-07T03:05:56.699100+00:00 |
| `2D1006newstart/screenshots/help.png` | `b042025e542f6b1e4c6eae27202b240c3d0bce8e` | 431612 | 2026-10-07T03:05:56.771289+00:00 |
| `2D1006newstart/screenshots/opening.png` | `38f2f56818df0c734c318e1ea47e33dbc3ce9e90` | 539967 | 2026-10-07T03:05:56.843882+00:00 |
| `2D1006newstart/tests/test_backend.py` | `ef6e4c0b5cc4957277f4297de946ea0c3b6e257e` | 2168 | 2026-10-07T03:05:56.916731+00:00 |
| `2D1006newstart/tests/test_world.py` | `8221c6d2e10893ba7470e10f398401df417f7ee0` | 4777 | 2026-10-07T03:05:56.987951+00:00 |
| `2D1006newstart/verify_ui.py` | `ccb9921851e29a0aa7a4f81c13e29e5c336c8bd5` | 2224 | 2026-10-07T03:05:57.057702+00:00 |
| `2D1006newstart/world.py` | `34b0bb1ae8d5e2c9172280221996d6c2e3b8aa32` | 9362 | 2026-10-07T03:05:57.129202+00:00 |
| `CODEX_IMPLEMENTATION_GOAL.md` | `fa3ee6e1ba2f23dc27573bb0ae0a30219b58e8c4` | 13336 | 2026-10-07T03:05:57.200216+00:00 |
| `Data_Storage/LightRAG/state_lightrag.py` | `35b0e37d465a603fe9383e87244548eb92bd8d46` | 45940 | 2026-10-07T03:05:57.269731+00:00 |
| `ENGINEERING_REVIEW.md` | `eb9d39cbe418cfd74b3e524c8c98fc3cee2a34f9` | 18771 | 2026-10-07T03:05:57.338918+00:00 |
| `IMPLEMENTATION_PROGRESS.md` | `07f63e2cfc8a7b30f6691d699793a6c50f0de613` | 57236 | 2026-10-07T03:05:57.411603+00:00 |
| `at_the_beginning/api/__init__.py` | `f650c45fb5a7e4f491c701489f756d1a167fedbf` | 61 | 2026-10-07T03:05:57.480161+00:00 |
| `at_the_beginning/api/local_session.py` | `adda341e3641c08caf3a9f55784ad858af8eeb3a` | 1534 | 2026-10-07T03:05:57.548905+00:00 |
| `at_the_beginning/initial_map_design.py` | `2fab474f29280f2c97962a2875f5a2ce4a5ef461` | 20011 | 2026-10-07T03:05:57.619205+00:00 |
| `at_the_beginning/initial_test.py` | `c6916e57098a97949fae41c0b3e7df1b5ace6026` | 3698 | 2026-10-07T03:05:57.689191+00:00 |
| `at_the_beginning/launch_config.py` | `a1bc31c900e7692b0ec967605929be6fc25f321e` | 1957 | 2026-10-07T03:05:57.757708+00:00 |
| `at_the_beginning/map_test.py` | `d3ec752efbbaa5e569b7a50dcd8924dcb224af00` | 258560 | 2026-10-07T03:05:57.828124+00:00 |
| `at_the_beginning/persistence/__init__.py` | `3a87f1571263ff113b3c2cf9e5c7b2826d528230` | 62 | 2026-10-07T03:05:57.897750+00:00 |
| `at_the_beginning/persistence/checkpoints.py` | `a4349332cfda1ce4099a3750abffaee8dcb01974` | 4545 | 2026-10-07T03:05:57.967992+00:00 |
| `at_the_beginning/persistence/codec.py` | `0ea207f78717a39485cabf89d66e28cc49c094c2` | 3222 | 2026-10-07T03:05:58.038323+00:00 |
| `at_the_beginning/persistence/resident_writer.py` | `8ad35caa94064b05a2ae85eec5e369fd0350a67a` | 1208 | 2026-10-07T03:05:58.107454+00:00 |
| `at_the_beginning/persistence/sessions.py` | `4f93932b6bf7b55bc33bda209406c494b3ca3d34` | 5703 | 2026-10-07T03:05:58.175940+00:00 |
| `at_the_beginning/persistence/world_snapshot.py` | `fa2b06411dc5c118344bcb6ebf014b88f559eba4` | 6217 | 2026-10-07T03:05:58.247071+00:00 |
| `at_the_beginning/runtime/control_runtime.py` | `2f241a7b3173f0149310d79fa15ab264ae3c686c` | 49612 | 2026-10-07T03:05:58.316521+00:00 |
| `at_the_beginning/runtime/resident_store.py` | `34464a84ca8eb1648fa4f015d768f7ee503a1fe3` | 39740 | 2026-10-07T03:05:58.387237+00:00 |
| `at_the_beginning/simulation/__init__.py` | `f2631241b313581554b5aff7895cec0d2e140908` | 74 | 2026-10-07T03:05:58.458509+00:00 |
| `at_the_beginning/simulation/commands.py` | `bf1fc7fb10690b35814bbd2079d70f7f8c33bd07` | 3443 | 2026-10-07T03:05:58.529919+00:00 |
| `at_the_beginning/simulation/inventory_commands.py` | `fa11c04c665b82645d81bb0fdcdcbd49de09e9b7` | 3268 | 2026-10-07T03:05:58.598256+00:00 |
| `at_the_beginning/simulation/scheduler.py` | `3018a9eff8b2aa0a3806d847c5012194581245f5` | 3748 | 2026-10-07T03:05:58.667997+00:00 |
| `at_the_beginning/systems/combat/resolver.py` | `4add9510e52cf85d2bd0972e4d9f394ce2782809` | 7511 | 2026-10-07T03:05:58.738050+00:00 |
| `at_the_beginning/systems/memory/state_memoryrag.py` | `493c1c9083a5b6e3f8cb2974a9eb505a505850e6` | 22882 | 2026-10-07T03:05:58.807740+00:00 |
| `at_the_beginning/systems/movement/spatial.py` | `c9389c5638fc86a6688a4277d73cce806756acab` | 3410 | 2026-10-07T03:05:58.877853+00:00 |
| `game_frontend/src/game/protocol/api.ts` | `366d921f9fc69867cbd51199fe726f9f60661966` | 7915 | 2026-10-07T03:05:58.947747+00:00 |
| `godot_client/scenes/characters/generated/FemalePeasant.tscn` | `9004dec38b858ee3be3475f9114c2b8e6108d29e` | 1925191 | 2026-10-07T03:05:59.022817+00:00 |
| `godot_client/scenes/characters/generated/FemalePeasant_locomotion.res` | `9e8c184a2054eb5956bfd631cefa2850aa7ae114` | 1346442 | 2026-10-07T03:05:59.100531+00:00 |
| `godot_client/scenes/characters/generated/FemalePeasant_mixamo.res` | `e547e6a8c0de26849c23ffe6c288addfc562a780` | 1338606 | 2026-10-07T03:05:59.178363+00:00 |
| `godot_client/scenes/characters/generated/animations.json` | `0404b5b8b790a4ec08914090e5e2b0b146b2dc55` | 7713 | 2026-10-07T03:05:59.249983+00:00 |
| `godot_client/scenes/characters/generated/manifest.json` | `9445bb6f31d8b9cdba4b952ebbc6f0a08680b488` | 1303 | 2026-10-07T03:05:59.320473+00:00 |
| `godot_client/scripts/app/camera_obstruction.gd` | `4ca75b83ba90852c739415cf88846702571610b5` | 1981 | 2026-10-07T03:05:59.400572+00:00 |
| `godot_client/scripts/app/character_animation_graph.gd` | `6f849983220340021597eb0087aaf7ad2c261851` | 2301 | 2026-10-07T03:05:59.483121+00:00 |
| `godot_client/scripts/app/control_replica.gd` | `90d034739a7b3a8f29d9782e5aeddfb4e808a8b1` | 2022 | 2026-10-07T03:05:59.581044+00:00 |
| `godot_client/scripts/app/ground_player_motor.gd` | `6b3f8ac3fe60baed694e0888db8f01acf5509014` | 1671 | 2026-10-07T03:05:59.686856+00:00 |
| `godot_client/scripts/app/launch_profile.gd` | `82447bdaf437fe1d3ffaae3fff16a6812f11b6eb` | 1086 | 2026-10-07T03:05:59.787543+00:00 |
| `godot_client/scripts/app/launch_profile.gd.uid` | `53a6e205b79bb94b399b7a0a842a4288244c99cd` | 19 | 2026-10-07T03:05:59.870841+00:00 |
| `godot_client/scripts/app/movement_history.gd` | `281539fc0878fa59fc56a30f30e1cb9bacd1b1c7` | 2469 | 2026-10-07T03:05:59.953184+00:00 |
| `godot_client/scripts/app/player_presentation.gd` | `ebe829cb43a2fa9e30ab61ee7fe0c3c2c285b316` | 921 | 2026-10-07T03:06:00.038501+00:00 |
| `godot_client/scripts/app/session_menu.gd` | `523be65a9e165ea6bd0b4de5e12414053c522d83` | 5028 | 2026-10-07T03:06:00.115718+00:00 |
| `godot_client/scripts/app/spatial_contract.gd` | `cad69b2663f7a2ff2a2a36306f1a610996b2b70a` | 1494 | 2026-10-07T03:06:00.187103+00:00 |
| `godot_client/scripts/human_mode_3d.gd` | `0be7510dc340670200d64d87c4281fb176b43827` | 223719 | 2026-10-07T03:06:00.264230+00:00 |
| `godot_client/scripts/human_visual_qa.gd` | `b62efa6829886b06a16f7af1a0b75e3efeffe63e` | 8664 | 2026-10-07T03:06:00.338840+00:00 |
| `godot_client/scripts/incarnation_human.gd` | `758e7743dacbbe2a7e9e73621864c9a1100160d7` | 84199 | 2026-10-07T03:06:00.415694+00:00 |
| `godot_client/scripts/main.gd` | `6f238216cda7a9e0c780a88917dab53e9b45494a` | 40973 | 2026-10-07T03:06:00.496588+00:00 |
| `godot_client/tests/animal_scale_capture.gd` | `f145c0a07ad9aa3c6269bcac7e522e65db3cbe7f` | 1547 | 2026-10-07T03:06:00.571233+00:00 |
| `godot_client/tests/animal_scale_validation.gd` | `0996927fc427e522389deca9d92cf496d15fc3b7` | 994 | 2026-10-07T03:06:00.643484+00:00 |
| `godot_client/tests/animation_cache_validation.gd` | `9b4efdd776f223a771f1eaea6466d431d090b512` | 2438 | 2026-10-07T03:06:00.714226+00:00 |
| `godot_client/tests/animation_graph_validation.gd` | `79d6bdef2042020662124d42fd30408479eea9e7` | 2992 | 2026-10-07T03:06:00.784826+00:00 |
| `godot_client/tests/animation_playback_validation.gd` | `c8373907ed1673c489f79f7c4d46dcc709111a38` | 1376 | 2026-10-07T03:06:00.857468+00:00 |
| `godot_client/tests/bake_supported_animations.gd` | `bb3001cbf481922a16f4e4efd8901380d02f58aa` | 2103 | 2026-10-07T03:06:00.935283+00:00 |
| `godot_client/tests/build_supported_character.gd` | `402e538fc7a3acd0959d2e372c88b13b4b4b47a3` | 4554 | 2026-10-07T03:06:01.006938+00:00 |
| `godot_client/tests/camera_obstruction_validation.gd` | `437dc4cb81a19ac850a494f5ccf6e41af784cce6` | 5096 | 2026-10-07T03:06:01.079698+00:00 |
| `godot_client/tests/character_asset_audit.gd` | `9acea2d089ae3d9fdb6877bbbeb915fdfbe9b51a` | 1524 | 2026-10-07T03:06:01.149451+00:00 |
| `godot_client/tests/control_replica_validation.gd` | `5a1ca65ac3f5976b133d40a8f2e8b7207253eff5` | 1841 | 2026-10-07T03:06:01.220954+00:00 |
| `godot_client/tests/delayed_gameplay_client.gd` | `953c0d40195f64bbc94497cc399dc77031091a6a` | 813 | 2026-10-07T03:06:01.295223+00:00 |
| `godot_client/tests/gameplay_capture.gd` | `c0fab1f1adabf562fa0e36b9af1302cb284be86c` | 7618 | 2026-10-07T03:06:01.370663+00:00 |
| `godot_client/tests/ground_player_motor_validation.gd` | `3b9d046a23aecd3ae0c98c6ac56c94bd35d8628d` | 4551 | 2026-10-07T03:06:01.446974+00:00 |
| `godot_client/tests/inventory_command_smoke.gd` | `bcd95730d1434df50fcddf2567d003fedbce1c32` | 1614 | 2026-10-07T03:06:01.520147+00:00 |
| `godot_client/tests/measured_motion_routing.gd` | `440429426aa9c0a795426b12887d245f5e5bf633` | 2140 | 2026-10-07T03:06:01.593949+00:00 |
| `godot_client/tests/movement_history_validation.gd` | `fd356e51dde4dc21f85b2cd329a84f6f90c53a62` | 2828 | 2026-10-07T03:06:01.686405+00:00 |
| `godot_client/tests/player_presentation_validation.gd` | `9af864f096ed083913a3815a9f589283941af70a` | 1902 | 2026-10-07T03:06:01.776838+00:00 |
| `godot_client/tests/session_menu_smoke.gd` | `7834f25056b5d17acfff80f41469f8ff8dbabe1d` | 1550 | 2026-10-07T03:06:01.863332+00:00 |
| `godot_client/tests/spatial_parity.gd` | `5876854b79431f6cda536e4b82bbccf5bde42fa2` | 748 | 2026-10-07T03:06:01.961774+00:00 |
| `godot_client/tests/supported_character_validation.gd` | `82614eac75daa56121d7405163309abc55753559` | 1261 | 2026-10-07T03:06:02.047563+00:00 |
| `godot_client/visual_qa_controller.json` | `7a524d4983d485089c27903361165fc160b6259b` | 212 | 2026-10-07T03:06:02.122527+00:00 |
| `implementation_0905.md` | `21978fdbc9770a3983d4418d334abefdd0e1d06f` | 34483 | 2026-10-07T03:06:02.193673+00:00 |
| `implementation_1006_2d_rebaseline.md` | `5db55e6177d448797ed543ef39f41b6ee24722e2` | 7685 | 2026-10-07T03:06:02.272803+00:00 |
| `myassets/ART_BIBLE.md` | `517a0bcda22f8bb3e4134d6aa5da7347825e48a3` | 2841 | 2026-10-07T03:06:02.352297+00:00 |
| `myassets/MAP_CONTRACT_REPLY.md` | `be5cc6eb4611cb9b7aaffaa3312455fed1baff82` | 4945 | 2026-10-07T03:06:02.427925+00:00 |
| `myassets/README.md` | `addfc35b75fe719ffc98dc4521b496dded4a144b` | 3998 | 2026-10-07T03:06:02.504338+00:00 |
| `myassets/a1/generate_local.ps1` | `ce2815d4d4408283c80cd7c4e1ca1ec988afb35a` | 2229 | 2026-10-07T03:06:02.602768+00:00 |
| `myassets/a1/local_jobs.json` | `3fec6126e50da5934be3ddea0ee71664f8267341` | 5066 | 2026-10-07T03:06:02.676311+00:00 |
| `myassets/a1/raw/anvil-local-a1-v1.png` | `a28d5a04b464bfeff95775c3e442b5fe186dd250` | 196447 | 2026-10-07T03:06:02.748415+00:00 |
| `myassets/a1/raw/anvil-local-a1-v1.png.json` | `30f68b6e0b56ba6b68c3f48230483c5e17b50d51` | 2108 | 2026-10-07T03:06:02.820403+00:00 |
| `myassets/a1/raw/berry-bush-local-a1-v1.png` | `b2f2e3df445aadc27b653b6caf5439c2e254dd78` | 153531 | 2026-10-07T03:06:02.895322+00:00 |
| `myassets/a1/raw/berry-bush-local-a1-v1.png.json` | `ff0d79f4ed39463bee724a273262de715ef560ad` | 2105 | 2026-10-07T03:06:02.970447+00:00 |
| `myassets/a1/raw/forge-local-a1-v1.png` | `e9194a5bb8d647c88edeee002b5e68a78c49904c` | 301432 | 2026-10-07T03:06:03.044365+00:00 |
| `myassets/a1/raw/forge-local-a1-v1.png.json` | `7881c3ac684343ad197922bba4b6f17feef4937f` | 2194 | 2026-10-07T03:06:03.114991+00:00 |
| `myassets/a1/raw/iron-pile-local-a1-v1.png.json` | `3a864c773ac9b64720bab2f692cc38cab09de988` | 2051 | 2026-10-07T03:06:03.189492+00:00 |
| `myassets/build_catalog.py` | `d144da4427fd89bff2704e1076294115ec329835` | 7209 | 2026-10-07T03:06:03.260012+00:00 |
| `myassets/buildings/roof_blue.png` | `a7a99166c5460e0f540b8b34f12769f3840e70b2` | 879 | 2026-10-07T03:06:03.330005+00:00 |
| `myassets/buildings/roof_brown.png` | `4437fce44e65a8c9dae934bbf34a51824b585e0b` | 1523 | 2026-10-07T03:06:03.399955+00:00 |
| `myassets/buildings/wall_brick.png` | `6790f36a2320e2a370bf54d3dab8d98cdd5dc948` | 6876 | 2026-10-07T03:06:03.480829+00:00 |
| `myassets/buildings/wall_plaster.png` | `78f5ec338731dd8f6b9d75ae9bae18e114457fcb` | 4256 | 2026-10-07T03:06:03.558760+00:00 |
| `myassets/buildings/wall_stone.png` | `7497a3307409c314549ceadffc345aedf38ebdbb` | 4391 | 2026-10-07T03:06:03.632058+00:00 |
| `myassets/buildings/wall_timber.png` | `34315df246c392e523a6aab9b8f256ec76928f4d` | 2570 | 2026-10-07T03:06:03.707156+00:00 |
| `myassets/characters/cyclops_amazon.png` | `62e5e39cf101e11c3ff3ae6f79a58c9ba8b544b0` | 273235 | 2026-10-07T03:06:03.780342+00:00 |
| `myassets/characters/dungeon_stalker.png` | `f4b6db855009dd226c5f1378aff1336c60ab33e5` | 280578 | 2026-10-07T03:06:03.851111+00:00 |
| `myassets/characters/elven_adventurer.png` | `0ac1a850462aa8efcb5b6a0f4c6225a07b867f5c` | 242266 | 2026-10-07T03:06:03.922023+00:00 |
| `myassets/characters/orc_mercenary.png` | `a89af4eaa13d52f6cd008f3a84909dcae5e9f633` | 274556 | 2026-10-07T03:06:03.994602+00:00 |
| `myassets/generated/approved.json` | `703c6029a2c883be23168feb18f62365d25456ad` | 766 | 2026-10-07T03:06:04.068439+00:00 |
| `myassets/generated/generation.json` | `187cbe5d11257f8b889e17b6fd9eadb76195c37b` | 1745 | 2026-10-07T03:06:04.141739+00:00 |
| `myassets/generated/manifest.json` | `098971a094536df4067115ff37478eb180892991` | 6817 | 2026-10-07T03:06:04.215638+00:00 |
| `myassets/generated/nature_survival_atlas.png` | `511009199af2371b8a231bc4a85106f0d0ba4036` | 2066442 | 2026-10-07T03:06:04.297582+00:00 |
| `myassets/generated/sand-local-v1.png` | `04cb68410350b3bbe5df5d6a0876e4fe98e38467` | 286969 | 2026-10-07T03:06:04.369196+00:00 |
| `myassets/generated/sand-local-v1.png.json` | `c51bb7a207136d6d11825d84d313b5be65c04a6b` | 1222 | 2026-10-07T03:06:04.439626+00:00 |
| `myassets/generated/water-local-v1.png` | `7f97a4bc4b6c9bdb06cea2feaf248651f6fc850b` | 236628 | 2026-10-07T03:06:04.512157+00:00 |
| `myassets/generated/water-local-v1.png.json` | `f7860742b1138823f6751049f1ec2fcc462135af` | 1416 | 2026-10-07T03:06:04.585702+00:00 |
| `myassets/generated/water-local-v2.png` | `e42271fb85eb70ad678f8270b83b2305c2924645` | 291427 | 2026-10-07T03:06:04.662450+00:00 |
| `myassets/generated/water-local-v2.png.json` | `88d39c3cbef795e022a4733801d1383ab4886e39` | 1407 | 2026-10-07T03:06:04.767837+00:00 |
| `myassets/licenses/MedievalVillage_LICENSE.txt` | `1dbe014f4c5b636eaa1d468aade94714593a5de5` | 681 | 2026-10-07T03:06:04.853643+00:00 |
| `myassets/licenses/MedievalVillage_README.txt` | `7d6c2da215dcacca2becb3d0af5a4bd87ec5d9ba` | 1820 | 2026-10-07T03:06:04.937489+00:00 |
| `myassets/manifest.json` | `a6bf94860d59fa5a11ffa5a1ef4ea6cdc8259421` | 15190 | 2026-10-07T03:06:05.010123+00:00 |
| `myassets/previews/catalog.png` | `1fdc4b2440f6f238c9ff9da78707dc180129ef27` | 162763 | 2026-10-07T03:06:05.081187+00:00 |
| `myassets/props/barrel.png` | `73d8a23dbd9134bda3be7114967da6f7f4828057` | 2123 | 2026-10-07T03:06:05.151884+00:00 |
| `myassets/props/cart.png` | `04908aa2a39eb1b93ffbbc97f9969d8a0940b04d` | 2977 | 2026-10-07T03:06:05.223555+00:00 |
| `myassets/props/crate.png` | `1d337c458cdae5a1e3d8e81ba7fe7ec0f9acde2a` | 1700 | 2026-10-07T03:06:05.292896+00:00 |
| `myassets/props/crate_stack.png` | `bee5a212d35a11c720f750cff5c5cd0703ea4524` | 3741 | 2026-10-07T03:06:05.364095+00:00 |
| `myassets/props/door_arch.png` | `5c4797f9879a2547cb13af71dd74b227f7f97512` | 3280 | 2026-10-07T03:06:05.438396+00:00 |
| `myassets/props/door_timber.png` | `f1625ab1f56f1d7c87d8db6187b84537aca58845` | 2411 | 2026-10-07T03:06:05.510824+00:00 |
| `myassets/props/fence.png` | `6b0daf0661d235acc2811362f424251852b966b2` | 2085 | 2026-10-07T03:06:05.585635+00:00 |
| `myassets/props/gable_blue.png` | `41f70ad4695f609d00762c9a4a815edda0aad282` | 5223 | 2026-10-07T03:06:05.656047+00:00 |
| `myassets/props/gable_brown.png` | `6822e81bf34bc79a5193b4fa4fc142765f86b0cb` | 11212 | 2026-10-07T03:06:05.727349+00:00 |
| `myassets/props/plank.png` | `e6b2424a67d6596aac6fda46cc8696674aa44234` | 803 | 2026-10-07T03:06:05.800544+00:00 |
| `myassets/props/planter.png` | `82c4f0312843bb275e5a2b015243145608a07285` | 6171 | 2026-10-07T03:06:05.873408+00:00 |
| `myassets/props/tree_small.png` | `799e6e49392f2ae81fe6587c24a34249b4fdf8a9` | 3681 | 2026-10-07T03:06:05.946445+00:00 |
| `myassets/props/window_arch.png` | `582409ba280a17a5bf23c54c39f6e36a924155d7` | 2042 | 2026-10-07T03:06:06.020383+00:00 |
| `myassets/props/window_square.png` | `d72a6ce1d94a6a91ce883c8b8fe282efaf380e4d` | 750 | 2026-10-07T03:06:06.092371+00:00 |
| `myassets/terrain/grass.png` | `ce871e1724eeade548283f8cb1ce9ac6a0235f27` | 1845 | 2026-10-07T03:06:06.163209+00:00 |
| `myassets/terrain/paving_brick.png` | `0ebf177eac8290ac521575278fa37651b5265cb7` | 1559 | 2026-10-07T03:06:06.235077+00:00 |
| `myassets/terrain/paving_stone.png` | `382d3173d8cc21cbbb7976bafba83323d287ac55` | 2089 | 2026-10-07T03:06:06.305951+00:00 |
| `myassets/tilesheets/Ground.png` | `bca25d62b33f567510bdc6fc0c08ceafabbf74f7` | 22825 | 2026-10-07T03:06:06.377186+00:00 |
| `myassets/tilesheets/Props_Decor.png` | `5a81e1417063d1a157f616c00754bd488bd84df3` | 89967 | 2026-10-07T03:06:06.457864+00:00 |
| `myassets/tilesheets/Roofs.png` | `43c58d86d276c57ba5310547d27a66225915ccd7` | 2728 | 2026-10-07T03:06:06.531476+00:00 |
| `myassets/tilesheets/Sconce_Spritesheet.png` | `74a897ae670f73e2a53668fca21c0c403dc5ff0a` | 5815 | 2026-10-07T03:06:06.602613+00:00 |
| `myassets/tilesheets/Walls.png` | `b59917b7f35176bcdc3d14d5ba1f537c54b8229b` | 20824 | 2026-10-07T03:06:06.675261+00:00 |
| `tests/test_checkpoints.py` | `748450cf735ef48ca9a27a3fa57c93ee81b28906` | 8006 | 2026-10-07T03:06:06.748970+00:00 |
| `tests/test_combat_walls.py` | `daa4aeabb423928560ac6f6ad6b1df650d182ada` | 2392 | 2026-10-07T03:06:06.822268+00:00 |
| `tests/test_control_protocol.py` | `5cd40a40d82b8d59cb1a561ec28be7990da1f9c8` | 23898 | 2026-10-07T03:06:06.891741+00:00 |
| `tests/test_inventory_commands.py` | `fc1e0f7bfa14c15b457ff3b275f6e20ce872e758` | 5977 | 2026-10-07T03:06:06.967702+00:00 |
| `tests/test_launch_config.py` | `5c2a76cd96751a32b1321f4b5ba4638ee4969c25` | 1536 | 2026-10-07T03:06:07.040650+00:00 |
| `tests/test_local_session.py` | `6b22f3c2cec484a5ad6e926f039a36126392f1e1` | 4543 | 2026-10-07T03:06:07.111936+00:00 |
| `tests/test_resident_persistence.py` | `698aafa212da2aa368af36fbf76f9f8a914afe80` | 3751 | 2026-10-07T03:06:07.183359+00:00 |
| `tests/test_resident_writer.py` | `a35d6483a7ce715e758be5b3d60959314712d36d` | 4008 | 2026-10-07T03:06:07.253841+00:00 |
| `tests/test_scheduler.py` | `a53cd92ee8f827476bd27de16ce6889f277bafd0` | 3496 | 2026-10-07T03:06:07.324490+00:00 |
| `tests/test_session_lifecycle.py` | `2078ba8e17a5d816963f7a72a8757e5cea59cc67` | 5014 | 2026-10-07T03:06:07.396376+00:00 |
| `tests/test_spatial_contract.py` | `122b19dcee56ef0b69beb9011ed2fca840ef65c5` | 3723 | 2026-10-07T03:06:07.467969+00:00 |
| `tests/test_startup_preservation.py` | `e4a909acd6ff67a394819fc584e4685be1a32594` | 5765 | 2026-10-07T03:06:07.538833+00:00 |
| `tools/gameplay_development.md` | `0741af3f589141876a4d576763049f3152f67727` | 12623 | 2026-10-07T03:06:07.612012+00:00 |
| `tools/generate_spatial_cases.py` | `9b65876b92be5cb0bdd7a248e9a99628663df9d2` | 1045 | 2026-10-07T03:06:07.684308+00:00 |
| `tools/human_mode_visual_qa.md` | `14833aaa3fd2b384cf9aae000d206fc47e61dcef` | 5916 | 2026-10-07T03:06:07.754202+00:00 |
| `tools/local_control_protocol.md` | `bd48231f5de6438b2b10d85281bb8e36a1e91f00` | 4540 | 2026-10-07T03:06:07.826719+00:00 |
| `tools/measure_simulation.py` | `9d33758e05dc5902ac6fec7b5cadcd2632507a1e` | 2339 | 2026-10-07T03:06:07.895532+00:00 |
| `tools/supported_character.md` | `6de5b0464bf9d5713eb135f84a45fef03087b471` | 6230 | 2026-10-07T03:06:07.966664+00:00 |

## Explicitly excluded pending paths

The following paths were excluded from pending changes. For already-tracked paths, their parent versions remain inherited; omission of their current changes does not remove them from Git history or the snapshot tree.

| Path | Reason |
| --- | --- |
| `Data_Storage/MemoryRAG/memory_graph.pkl` | Generated, compiled or runtime data |
| `Data_Storage/ResidentAgents/h_000001.json` | Runtime data under Data_Storage |
| `Data_Storage/ResidentAgents/h_000002.json` | Runtime data under Data_Storage |
| `Data_Storage/ResidentAgents/h_000003.json` | Runtime data under Data_Storage |
| `Data_Storage/ResidentAgents/h_000004.json` | Runtime data under Data_Storage |
| `at_the_beginning/world_map/__init__.py` | Claude-owned map 0.2 work in progress; capture after coherent follow-up |
| `at_the_beginning/world_map/loader.py` | Claude-owned map 0.2 work in progress; capture after coherent follow-up |
| `at_the_beginning/world_map/parse.py` | Claude-owned map 0.2 work in progress; capture after coherent follow-up |
| `at_the_beginning/world_map/schema.py` | Claude-owned map 0.2 work in progress; capture after coherent follow-up |
| `at_the_beginning/world_map/spatial_bridge.py` | Claude-owned map 0.2 work in progress; capture after coherent follow-up |
| `at_the_beginning/world_map/validate.py` | Claude-owned map 0.2 work in progress; capture after coherent follow-up |
| `game_frontend/dist/assets/index-DRD6_zDH.js` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/assets/index-RPIoHXmD.js` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/index.html` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Bark_DeadTree.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Bark_DeadTree_Normal.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Bark_NormalTree.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Bark_NormalTree_Normal.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Bush_Common.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Bush_Common.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/CommonTree_1.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/CommonTree_1.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/CommonTree_2.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/CommonTree_2.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/CommonTree_3.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/CommonTree_3.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/DeadTree_1.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/DeadTree_1.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Fern_1.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Fern_1.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Flowers.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Grass.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Grass_Common_Short.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Grass_Common_Short.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Leaf_Pine.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Leaf_Pine_C.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Leaves.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Leaves_NormalTree_C.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Mushroom_Common.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Mushroom_Common.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Mushrooms.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/PathRocks_Diffuse.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Pebble_Round_1.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Pebble_Round_1.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Pine_1.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Pine_1.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Pine_2.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Pine_2.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Rock_Medium_1.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Rock_Medium_1.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Rock_Medium_2.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Rock_Medium_2.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Rock_Medium_3.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Rock_Medium_3.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/nature/Rocks_Diffuse.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/Anvil_Log.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/Anvil_Log.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/Barrel.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/Barrel.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/Bench.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/Bench.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/Bucket_Wooden_1.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/Bucket_Wooden_1.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/Cauldron.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/Cauldron.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/Chest_Wood.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/Chest_Wood.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/Crate_Wooden.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/Crate_Wooden.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/FarmCrate_Empty.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/FarmCrate_Empty.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/Stall_Empty.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/Stall_Empty.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/T_Trim_Cloth_BaseColor.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/T_Trim_Cloth_Normal.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/T_Trim_Cloth_ORM.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/T_Trim_Furniture_BaseColor.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/T_Trim_Furniture_Normal.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/T_Trim_Furniture_ORM.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/T_Trim_Metal_BaseColor.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/T_Trim_Metal_Normal.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/T_Trim_Metal_ORM.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/T_Trim_Props_BaseColor.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/T_Trim_Props_Normal.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/T_Trim_Props_ORM.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/Torch_Metal.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/Torch_Metal.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/Workbench.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/props/Workbench.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/Door_1_Flat.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/Door_1_Flat.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/Floor_Brick.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/Floor_Brick.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/Prop_Chimney.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/Prop_Chimney.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/Prop_Wagon.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/Prop_Wagon.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/Prop_WoodenFence_Extension1.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/Prop_WoodenFence_Extension1.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/Prop_WoodenFence_Single.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/Prop_WoodenFence_Single.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/Roof_RoundTiles_4x4.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/Roof_RoundTiles_4x4.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/Roof_RoundTiles_6x6.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/Roof_RoundTiles_6x6.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/Stairs_Exterior_Straight.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/Stairs_Exterior_Straight.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/T_Brick_BaseColor.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/T_Brick_Normal.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/T_Brick_Roughness.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/T_Plaster_BaseColor.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/T_Plaster_Normal.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/T_Plaster_ORM.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/T_RockTrim_BaseColor.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/T_RockTrim_Normal.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/T_RockTrim_ORM.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/T_RoundTiles_BaseColor.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/T_RoundTiles_Normal.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/T_RoundTiles_Roughness.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/T_UnevenBrick_BaseColor.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/T_UnevenBrick_Normal.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/T_UnevenBrick_Roughness.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/T_VineLeaf_png.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/T_WoodTrim_BaseColor.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/T_WoodTrim_Normal.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/T_WoodTrim_Roughness.png` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/Wall_Plaster_Door_Flat.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/Wall_Plaster_Door_Flat.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/Wall_Plaster_Straight.bin` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/dist/models/village/Wall_Plaster_Straight.gltf` | Cache, build output, dependency installation, log or runtime save |
| `game_frontend/tsconfig.tsbuildinfo` | Generated, compiled or runtime data |
| `godot_client/human_mode_auto_00_opening.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_00_opening.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_01_walk_forward.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_01_walk_forward.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_02_walk_diagonal.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_02_walk_diagonal.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_03_talk.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_03_talk.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_03b_talk_front.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_03b_talk_front.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_03c_talk_side.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_03c_talk_side.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_04_attack.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_04_attack.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_04b_attack_front.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_04b_attack_front.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_04c_attack_side.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_04c_attack_side.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_05_hit.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_05_hit.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_05b_hit_front.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_05b_hit_front.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_05c_hit_side.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_05c_hit_side.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_06_fall.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_06_fall.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_06b_fall_front.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_06b_fall_front.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_06c_fall_side.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_06c_fall_side.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_07_get_up.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_07_get_up.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_07b_get_up_front.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_07b_get_up_front.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_07c_get_up_side.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_auto_07c_get_up_side.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_goal_continue_real_09_shoreline_opening.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_goal_continue_real_10_far_backdrop_opening.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_goal_continue_real_11_hit_backdrop.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_goal_continue_real_12_fall_backdrop.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_goal_continue_real_13_get_up_backdrop.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_goal_continue_real_14_talk_gesture_pose.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_goal_continue_real_15_attack_gesture_pose.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_goal_continue_real_16_hit_gesture_pose.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_goal_continue_real_17_lower_camera_opening.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_goal_continue_real_18_lower_camera_pitch_opening.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_goal_continue_real_19_lower_camera_walk_2s.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_goal_continue_real_20_virtual_walk_fixed_2s.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_goal_continue_real_21_extended_envelope_opening.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_goal_continue_real_22_extended_envelope_walk_1s.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_goal_continue_real_23_backend_isolated_opening.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_goal_continue_real_24_backend_isolated_opening_retake.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_goal_continue_real_24_backend_isolated_opening_retake.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_goal_continue_real_25_scaled_qa_walk_baseline.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_goal_continue_real_25_scaled_qa_walk_baseline.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_goal_continue_real_26_scaled_qa_walk_700ms.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_goal_continue_real_26_scaled_qa_walk_700ms.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_goal_continue_real_27_scaled_qa_walk_live.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_mode_goal_continue_real_27_scaled_qa_walk_live.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_visual_qa_auto_00_overview.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_visual_qa_auto_00_overview.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_visual_qa_auto_01_upper_body_locomotion_talk.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_visual_qa_auto_01_upper_body_locomotion_talk.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_visual_qa_auto_02_reactions_attack_fall_getup.png` | Legacy visual evidence or unassigned Godot generated artifact |
| `godot_client/human_visual_qa_auto_02_reactions_attack_fall_getup.png.import` | Legacy visual evidence or unassigned Godot generated artifact |
| `tests/fixtures/maps/sprites/chest.png` | Claude-owned map 0.2 work in progress; capture after coherent follow-up |
| `tests/fixtures/maps/sprites/floor.png` | Claude-owned map 0.2 work in progress; capture after coherent follow-up |
| `tests/fixtures/maps/sprites/forge.png` | Claude-owned map 0.2 work in progress; capture after coherent follow-up |
| `tests/fixtures/maps/sprites/grass.png` | Claude-owned map 0.2 work in progress; capture after coherent follow-up |
| `tests/fixtures/maps/sprites/path.png` | Claude-owned map 0.2 work in progress; capture after coherent follow-up |
| `tests/fixtures/maps/sprites/tree.png` | Claude-owned map 0.2 work in progress; capture after coherent follow-up |
| `tests/fixtures/maps/tiny_interior.json` | Claude-owned map 0.2 work in progress; capture after coherent follow-up |
| `tests/fixtures/maps/tiny_village.json` | Claude-owned map 0.2 work in progress; capture after coherent follow-up |
| `tests/test_world_map.py` | Claude-owned map 0.2 work in progress; capture after coherent follow-up |
| `tools/validate_map.py` | Claude-owned map 0.2 work in progress; capture after coherent follow-up |

Ignored scopes were also left out without force-adding: `.tmp/`, `.runtime/`, `.venv/`, `env/`, `myenv/`, caches/bytecode, logs, private `.env` configuration, `2D1006newstart/saves/`, old Godot import caches, ignored third-party packs/Humanizer/Mixamo raw/animal assets and third-party archives. No ignored files were deleted or moved.

Explicit coordinator hold: exclude all of `at_the_beginning/world_map/`, `tests/fixtures/maps/`, `tools/validate_map.py`, `tests/test_world_map.py`, and `1006_scale_constants_audit.md`, including additions after the initial inventory. No Git changes are authorized for those paths in S0.

## Inherited parent files and recovery limits

This is a recovery commit based on HEAD, not a sanitized distribution. Existing tracked dependency/build/asset/runtime files are inherited unchanged. Runtime-data churn was excluded; already committed runtime records still exist in the parent history/tree. No runtime record contents or credentials were printed.

- `game_frontend/node_modules/`: 9,922 inherited tracked files.
- `game_frontend/dist/`: 6 inherited tracked files.
- `godot_client/assets/`: 31 inherited tracked files.

Inherited runtime/non-source paths (names only):

- `Data_Storage/ExecutionAgent/state.json`
- `Data_Storage/LightRAG/eden_graph.pkl`
- `Data_Storage/MemoryRAG/memory_graph.pkl`
- `Data_Storage/ResidentAgents/h_000001.json`
- `Data_Storage/ResidentAgents/h_000002.json`
- `Data_Storage/ResidentAgents/h_000003.json`
- `Data_Storage/ResidentAgents/h_000004.json`
- `Data_Storage/_tmp_escalation_test/h_000001.json`
- `Data_Storage/_tmp_escalation_test/h_000002.json`
- `Data_Storage/_tmp_human_batch_test/h_000001.json`
- `Data_Storage/_tmp_human_batch_test/h_000002.json`
- `Data_Storage/_tmp_resident_personality_goal_test_2/h_000002.json`
- `tmp_human_runtime_test/h_000002.json`

## Selected files changed between planning and capture

- `1006_communication_scratchpad.md`
- `myassets/a1/raw/iron-pile-local-a1-v1.png.json`

## Captured files changed after capture

- `1006_communication_scratchpad.md`

## Original visible files changed while other workers were active

- `1006_communication_scratchpad.md`
- `at_the_beginning/world_map/__init__.py`
- `at_the_beginning/world_map/parse.py`
- `at_the_beginning/world_map/schema.py`
- `at_the_beginning/world_map/spatial_bridge.py`
- `at_the_beginning/world_map/validate.py`
- `myassets/a1/raw/iron-pile-local-a1-v1.png.json`
- `tests/fixtures/maps/tiny_interior.json`
- `tests/fixtures/maps/tiny_village.json`
- `tests/test_world_map.py`
- `tools/validate_map.py`

## New visible paths after the fixed inventory (outside this snapshot)

- `1006_scale_constants_audit.md`
- `myassets/a1/raw/iron-pile-local-a1-v1.png`
- `tests/fixtures/maps/example_smith.json`
- `tests/test_world_map_v02.py`

## Handoff

S0 integrity checks passed. Coordinator must independently review this report and refs before lifting the backend hold or assigning client implementation. No backend/client work or ownership-hold release was performed here. Await the next bounded assignment.

The whole communication scratchpad was reread at finish, through C-012. The latest scale audit and accepted map contract were acknowledged without changing backend/client files or lifting the hold. The captured scratchpad blob predates its latest concurrent entries, as listed above.

Reproduce the reference checks with `git rev-parse refs/heads/codex/legacy-3d-1006^{commit}` and `git rev-parse refs/tags/legacy-3d-1006^{commit}`. Inspect exactly included changes with `git diff --name-status 88e48823509c0b861f1cd49cb43dc5354f18111f <commit-above>`. This report is a new untracked working document written after the snapshot; it is intentionally not in that commit.
