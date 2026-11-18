# 1008 coverage map: which legacy instincts and tools the tests exercise

Measured by `at_the_beginning/harness/coverage_map.py` (a `sys.monitoring` call tracer, because `coverage.py` is not installed) over the full suite: 831 tests, 0 failures, 0 errors, 383.3 s. "Exercised" means the function was **called** at least once; it says nothing about branch coverage or whether the result was asserted. Test modules listed are those whose tests were running when the call happened (setup/teardown included).

## `instinct_*`: 25 of 46 called by some test

- called directly from a test: 1; reached through `Engine.step`: 23; never called: 21

## `tool_*`: 4 of 74 called by some test

- called directly from a test: 2; reached through `Engine.step`: 1; never called: 70

## Other top-level functions in the module (18 of 24 called)

| function | registry | calls | how reached | test modules |
| --- | --- | --- | --- | --- |
| `entity_born` |  | 6079 | via initial_map_design.py, via map_test.py | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `animal_born` |  | 0 |  |  |
| `engine_has_roster` |  | 14633 | direct from a test, via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `check_escalation` | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `animal_instinct_age` | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `animal_instinct_hunger` | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `animal_instinct_thirst` | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `animal_instinct_die` | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `animal_instinct_move` | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `animal_instinct_eat` | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `animal_instinct_drink` | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `animal_instinct_predator_attack` | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `animal_tool_reproduce` | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `geo_mutate` |  | 0 |  |  |
| `dispatch_acquired_instincts` | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `default_registry_entries` |  | 1 | via map_test.py | test_checkpoints |

## Full table: instinct_*

| function | line | registry | calls | how reached | test modules (first 4) |
| --- | --- | --- | --- | --- | --- |
| `instinct_create_object` | 354 |  | 1115 | via Engine.step, via map_test.py | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `instinct_populate_animals` | 388 |  | **0** |  |  |
| `instinct_update_objects` | 449 |  | **0** |  |  |
| `instinct_retype_objects` | 485 |  | **0** |  |  |
| `instinct_create_scattered_objects` | 514 |  | 259 | via Engine.step | test_control_protocol, test_god_mode, test_god_reset, test_god_weather_expiry |
| `instinct_create_line_objects` | 554 |  | **0** |  |  |
| `instinct_relocate_animals` | 589 |  | **0** |  |  |
| `instinct_designate_construction_site` | 621 |  | **0** |  |  |
| `instinct_gather_materials` | 655 |  | **0** |  |  |
| `instinct_build_with_humans` | 680 |  | **0** |  |  |
| `instinct_repair_with_humans` | 706 |  | **0** |  |  |
| `instinct_demolish_with_humans` | 728 |  | **0** |  |  |
| `instinct_find_buildable_site` | 791 |  | **0** |  |  |
| `instinct_proximity` | 902 |  | **0** |  |  |
| `instinct_flee` | 918 |  | **0** |  |  |
| `instinct_cooldown` | 936 | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `instinct_born` | 951 |  | 1707 | via map_test.py | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `instinct_age` | 1073 | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `instinct_hunger` | 1083 | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `instinct_thirst` | 1092 | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `instinct_stamina_tick` | 1101 | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `instinct_emotional_recovery` | 1107 | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `instinct_die` | 1111 | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `instinct_hp_death` | 1121 | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `instinct_search` | 1131 |  | **0** |  |  |
| `instinct_reproduction_strategy` | 1140 |  | **0** |  |  |
| `instinct_survival_navigation` | 1189 |  | **0** |  |  |
| `instinct_social_navigation` | 1203 |  | **0** |  |  |
| `instinct_schedule_navigation` | 1213 |  | **0** |  |  |
| `instinct_pairwise_relations` | 1236 |  | **0** |  |  |
| `instinct_eat` | 1247 |  | **0** |  |  |
| `instinct_drink` | 1255 |  | **0** |  |  |
| `instinct_heal` | 1263 | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `instinct_shelter_check` | 1267 | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `instinct_structure_occupancy` | 1272 | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `instinct_attack` | 1282 |  | 3 | direct from a test | test_map_guards |
| `instinct_incarnation_stabilize` | 1387 | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `instinct_player_control_override` | 1427 | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `instinct_move` | 1441 | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `instinct_infection_tick` | 1525 | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `instinct_nature_cycle` | 1535 | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `instinct_fire_tick` | 1580 | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `instinct_lava_tick` | 1588 | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `instinct_resource_regrow` | 1594 | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `instinct_water_cycle` | 1602 | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `instinct_frontier_expand` | 3052 | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |

## Full table: tool_*

| function | line | registry | calls | how reached | test modules (first 4) |
| --- | --- | --- | --- | --- | --- |
| `tool_reproduce` | 1919 |  | **0** |  |  |
| `tool_harvest_food` | 1950 |  | **0** |  |  |
| `tool_draw_water` | 1985 |  | **0** |  |  |
| `tool_build_house` | 2020 |  | **0** |  |  |
| `tool_build_village` | 2043 |  | **0** |  |  |
| `tool_build_farm` | 2066 |  | **0** |  |  |
| `tool_build_well` | 2100 |  | **0** |  |  |
| `tool_designate_structure_site` | 2128 |  | **0** |  |  |
| `tool_find_buildable_site` | 2150 |  | **0** |  |  |
| `tool_gather_building_materials` | 2169 |  | **0** |  |  |
| `tool_build_structure_with_humans` | 2182 |  | **0** |  |  |
| `tool_construct_house` | 2206 |  | **0** |  |  |
| `tool_construct_village` | 2219 |  | **0** |  |  |
| `tool_construct_farm` | 2232 |  | **0** |  |  |
| `tool_construct_well` | 2245 |  | **0** |  |  |
| `tool_construct_wall_with_humans` | 2258 |  | **0** |  |  |
| `tool_repair_area_with_humans` | 2284 |  | **0** |  |  |
| `tool_demolish_area_with_humans` | 2301 |  | **0** |  |  |
| `tool_build_settlement_with_humans` | 2319 |  | **0** |  |  |
| `tool_repair_structures` | 2337 |  | **0** |  |  |
| `tool_irrigate_area` | 2350 |  | **0** |  |  |
| `tool_fertilize_area` | 2371 |  | **0** |  |  |
| `tool_clear_land` | 2392 |  | **0** |  |  |
| `tool_create_lake` | 2421 |  | **0** |  |  |
| `tool_settle_area` | 2443 |  | **0** |  |  |
| `tool_area_attack` | 2460 |  | **0** |  |  |
| `tool_wildfire` | 2477 |  | **0** |  |  |
| `tool_earthquake` | 2490 |  | **0** |  |  |
| `tool_storm` | 2508 |  | **0** |  |  |
| `tool_volcanic_eruption` | 2522 |  | **0** |  |  |
| `tool_drought` | 2541 |  | **0** |  |  |
| `tool_flood` | 2554 |  | **0** |  |  |
| `tool_regrow_forest` | 2559 |  | **0** |  |  |
| `tool_seed_world` | 2575 |  | 287 | via map_test.py | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `tool_plague` | 2607 |  | **0** |  |  |
| `tool_bless` | 2613 |  | **0** |  |  |
| `tool_set_mood` | 2619 |  | 4 | direct from a test | test_harness_known_bugs, test_harness_powers |
| `tool_set_threat` | 2627 |  | **0** |  |  |
| `tool_calm_area` | 2636 |  | **0** |  |  |
| `tool_panic_area` | 2652 |  | **0** |  |  |
| `tool_bounty_area` | 2669 |  | **0** |  |  |
| `tool_scarcity_area` | 2692 |  | **0** |  |  |
| `tool_baby_boom` | 2714 |  | **0** |  |  |
| `tool_cull` | 2723 |  | **0** |  |  |
| `tool_grant_instinct` | 2732 |  | 7 | direct from a test | test_harness_known_bugs |
| `tool_revoke_instinct` | 2738 |  | **0** |  |  |
| `tool_inherit_instinct` | 2744 | yes | 14626 | via Engine.step | test_checkpoints, test_control_protocol, test_god_mode, test_god_reset |
| `tool_age_shift` | 2753 |  | **0** |  |  |
| `tool_life_exp_modify` | 2759 |  | **0** |  |  |
| `tool_set_aggression` | 2767 |  | **0** |  |  |
| `tool_smite` | 2775 |  | **0** |  |  |
| `tool_migration` | 2781 |  | **0** |  |  |
| `tool_quarantine` | 2792 |  | **0** |  |  |
| `tool_reset_cooldown` | 2801 |  | **0** |  |  |
| `tool_enlighten` | 2805 |  | **0** |  |  |
| `tool_spawn_animal_group` | 2811 |  | **0** |  |  |
| `tool_populate_area_with_animals` | 2828 |  | **0** |  |  |
| `tool_fill_land_with_animals` | 2852 |  | **0** |  |  |
| `tool_restock_lakes_with_fish` | 2882 |  | **0** |  |  |
| `tool_create_wall` | 2902 |  | **0** |  |  |
| `tool_transform_area` | 2925 |  | **0** |  |  |
| `tool_create_forest_patch` | 2942 |  | **0** |  |  |
| `tool_create_mountain_chain` | 2960 |  | **0** |  |  |
| `tool_create_feature_near_feature` | 2981 |  | **0** |  |  |
| `tool_expand_world_edge` | 3022 |  | **0** |  |  |
| `tool_upgrade_houses_to_village` | 3078 |  | **0** |  |  |
| `tool_populate_biome_with_animals` | 3101 |  | **0** |  |  |
| `tool_herd_animals_to_area` | 3132 |  | **0** |  |  |
| `tool_scatter_animals_from_area` | 3151 |  | **0** |  |  |
| `tool_feed_animals` | 3170 |  | **0** |  |  |
| `tool_heal_animals` | 3187 |  | **0** |  |  |
| `tool_make_animals_flee` | 3204 |  | **0** |  |  |
| `tool_draw_animals_to_area` | 3222 |  | **0** |  |  |
| `tool_stampede` | 3240 |  | **0** |  |  |

## Never called by any test

- **instinct** (21): `instinct_populate_animals`, `instinct_update_objects`, `instinct_retype_objects`, `instinct_create_line_objects`, `instinct_relocate_animals`, `instinct_designate_construction_site`, `instinct_gather_materials`, `instinct_build_with_humans`, `instinct_repair_with_humans`, `instinct_demolish_with_humans`, `instinct_find_buildable_site`, `instinct_proximity`, `instinct_flee`, `instinct_search`, `instinct_reproduction_strategy`, `instinct_survival_navigation`, `instinct_social_navigation`, `instinct_schedule_navigation`, `instinct_pairwise_relations`, `instinct_eat`, `instinct_drink`
- **tool** (70): `tool_reproduce`, `tool_harvest_food`, `tool_draw_water`, `tool_build_house`, `tool_build_village`, `tool_build_farm`, `tool_build_well`, `tool_designate_structure_site`, `tool_find_buildable_site`, `tool_gather_building_materials`, `tool_build_structure_with_humans`, `tool_construct_house`, `tool_construct_village`, `tool_construct_farm`, `tool_construct_well`, `tool_construct_wall_with_humans`, `tool_repair_area_with_humans`, `tool_demolish_area_with_humans`, `tool_build_settlement_with_humans`, `tool_repair_structures`, `tool_irrigate_area`, `tool_fertilize_area`, `tool_clear_land`, `tool_create_lake`, `tool_settle_area`, `tool_area_attack`, `tool_wildfire`, `tool_earthquake`, `tool_storm`, `tool_volcanic_eruption`, `tool_drought`, `tool_flood`, `tool_regrow_forest`, `tool_plague`, `tool_bless`, `tool_set_threat`, `tool_calm_area`, `tool_panic_area`, `tool_bounty_area`, `tool_scarcity_area`, `tool_baby_boom`, `tool_cull`, `tool_revoke_instinct`, `tool_age_shift`, `tool_life_exp_modify`, `tool_set_aggression`, `tool_smite`, `tool_migration`, `tool_quarantine`, `tool_reset_cooldown`, `tool_enlighten`, `tool_spawn_animal_group`, `tool_populate_area_with_animals`, `tool_fill_land_with_animals`, `tool_restock_lakes_with_fish`, `tool_create_wall`, `tool_transform_area`, `tool_create_forest_patch`, `tool_create_mountain_chain`, `tool_create_feature_near_feature`, `tool_expand_world_edge`, `tool_upgrade_houses_to_village`, `tool_populate_biome_with_animals`, `tool_herd_animals_to_area`, `tool_scatter_animals_from_area`, `tool_feed_animals`, `tool_heal_animals`, `tool_make_animals_flee`, `tool_draw_animals_to_area`, `tool_stampede`
- **other** (2): `animal_born`, `geo_mutate`
