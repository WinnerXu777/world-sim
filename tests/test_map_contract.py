"""Per-map movement contract: legacy golden baseline, registry, world_contract override, combat walls, saves,
and real-scale (8 units/tile, radius 2.4) passage behaviour of spatial.slide versus the map validator."""
import os
import unittest
import uuid

from test_startup_preservation import backend, _test_storage
from test_world_map import FIXTURES
from persistence import codec, world_snapshot
from persistence.sessions import GameSessions
from systems.combat.intents import CombatIntent
from systems.combat.resolver import resolve_human_attack_intents
from systems.movement import map_contract
from systems.movement.map_contract import (MAP_CONTRACTS, clear_map_contracts, get_map_contract, load_from_environment,
                                           register_map_contract, register_map_file, register_world_map, unregister_map_contract)
from systems.movement.spatial import RADIUS, map_wall_boxes, slide, world_contract
from world_map import load_map, parse_map, to_movement_contract, validate_map

# Captured from the unmodified backend (playable_village; geometry is seed-independent). If this changes, every
# legacy map's contract changed: that is a regression unless the change is deliberate and reviewed.
LEGACY_PLAYABLE_VILLAGE_CONTRACT = {
    "actor_radius": 0.35,
    "bounds": [0.0, 0.0, 1200.0, 900.0],
    "boxes": [
        {"height": 2.4, "id": "e_000006", "max": [586.0, 472.6], "min": [578.0, 471.4]},
        {"height": 2.4, "id": "e_000007", "max": [622.0, 472.6], "min": [614.0, 471.4]},
    ],
    "height": 0.0,
    "revision": "a02ca09f557efffe",
    "sprint_multiplier": 1.5,
    "surface_id": "ground",
    "units_per_meter": 1.0,
    "version": 1,
    "walk_speed": 20.0,
}
LEGACY_KEY_ORDER = ["version", "revision", "world_epoch", "units_per_meter", "surface_id", "height",
                    "actor_radius", "bounds", "walk_speed", "sprint_multiplier", "boxes"]
SMITH = FIXTURES / "example_smith.json"


def contract_without_epoch(engine):
    return {key: value for key, value in world_contract(engine).items() if key != "world_epoch"}


class RegistryIsolation:
    """Each test starts and ends with an empty registry, so nothing leaks into legacy-map tests."""

    def setUp(self):
        self._saved = dict(MAP_CONTRACTS)
        clear_map_contracts()
        super().setUp()

    def tearDown(self):
        clear_map_contracts()
        MAP_CONTRACTS.update(self._saved)
        super().tearDown()


class AsyncRegistryIsolation:
    async def asyncSetUp(self):
        self._saved = dict(MAP_CONTRACTS)
        clear_map_contracts()
        backend.engine.reset_world()

    async def asyncTearDown(self):
        clear_map_contracts()
        MAP_CONTRACTS.update(self._saved)


async def make_authored_world(name="example_smith", path=SMITH):
    """A live world whose map name has a registered authored contract (full authored creation is a later step)."""
    register_map_file(path, name=name, base_dir=FIXTURES)
    backend.engine.reset_world()
    await backend.create_genesis(backend.engine, map_name="playable_village")
    backend.engine._map_name = name
    return backend.engine


class LegacyGoldenContractTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def test_playable_village_contract_is_byte_identical_to_the_baseline(self):
        await backend.create_genesis(backend.engine, map_name="playable_village")
        self.assertEqual(contract_without_epoch(backend.engine), LEGACY_PLAYABLE_VILLAGE_CONTRACT)
        self.assertEqual(list(world_contract(backend.engine)), LEGACY_KEY_ORDER)  # JSON key order is part of "byte-identical"
        self.assertIsNone(map_wall_boxes(backend.engine))

    async def test_registering_other_maps_does_not_change_the_legacy_contract(self):
        register_world_map(load_map(SMITH, base_dir=FIXTURES))
        register_map_contract("some_other_map", 3.0, [0, 0, 10, 10], [])
        await backend.create_genesis(backend.engine, map_name="playable_village")
        self.assertEqual(contract_without_epoch(backend.engine), LEGACY_PLAYABLE_VILLAGE_CONTRACT)

    async def test_render_test_village_is_also_unaffected(self):
        await backend.create_genesis(backend.engine, map_name="render_test_village")
        contract = contract_without_epoch(backend.engine)
        self.assertEqual((contract["actor_radius"], contract["bounds"]), (0.35, [0.0, 0.0, 1200.0, 900.0]))
        self.assertIsNone(map_wall_boxes(backend.engine))


class RegistryTests(RegistryIsolation, unittest.TestCase):
    def test_empty_by_default_and_unknown_names_are_legacy(self):
        self.assertEqual(MAP_CONTRACTS, {})
        for name in ("playable_village", "nope", None, 5):
            self.assertIsNone(get_map_contract(name))

    def test_register_unregister_and_replace(self):
        register_map_contract("a", 1.0, [0, 0, 10, 10], [{"id": "w", "min": [1, 1], "max": [2, 2]}])
        self.assertEqual(get_map_contract("a")["actor_radius"], 1.0)
        self.assertEqual(get_map_contract("a")["boxes"][0]["height"], 2.4)
        register_map_contract("a", 2.0, [0, 0, 10, 10], [])
        self.assertEqual((get_map_contract("a")["actor_radius"], get_map_contract("a")["boxes"]), (2.0, []))
        unregister_map_contract("a")
        unregister_map_contract("a")  # idempotent
        self.assertIsNone(get_map_contract("a"))

    def test_inputs_are_validated_and_copied(self):
        box = {"id": "w", "min": [1, 1], "max": [2, 2]}
        for args in (("", 1, [0, 0, 1, 1], []), ("a", 0, [0, 0, 1, 1], []), ("a", float("nan"), [0, 0, 1, 1], []),
                     ("a", True, [0, 0, 1, 1], []), ("a", 1, [0, 0, 1], []), ("a", 1, [0, 0, 0, 1], []),
                     ("a", 1, [0, 0, float("inf"), 1], []), ("a", 1, [0, 0, 1, 1], [{"id": "w", "min": [1], "max": [2, 2]}]),
                     ("a", 1, [0, 0, 1, 1], [{"id": 3, "min": [1, 1], "max": [2, 2]}])):
            with self.subTest(args=args):
                with self.assertRaises((ValueError, KeyError, TypeError)):
                    register_map_contract(*args)
        self.assertEqual(MAP_CONTRACTS, {})
        register_map_contract("a", 1, [0, 0, 10, 10], [box])
        box["min"][0] = 99
        self.assertEqual(get_map_contract("a")["boxes"][0]["min"], [1.0, 1.0])

    def test_register_world_map_uses_the_file_radius_and_bounds(self):
        register_world_map(load_map(SMITH, base_dir=FIXTURES))
        entry = get_map_contract("example_smith")
        self.assertEqual((entry["actor_radius"], entry["bounds"]), (2.4, [0.0, 0.0, 48.0, 48.0]))
        self.assertEqual(entry["boxes"][0]["id"], "example_smith:wall_forge")
        register_world_map(load_map(SMITH, base_dir=FIXTURES), name="alias", actor_radius=1.1)
        self.assertEqual(get_map_contract("alias")["actor_radius"], 1.1)

    def test_environment_loading(self):
        self.assertEqual(load_from_environment({}), [])
        self.assertEqual(load_from_environment({"EDEN_MAP_FILES": ""}), [])
        self.assertEqual(MAP_CONTRACTS, {})
        self.assertEqual(load_from_environment({"EDEN_MAP_FILES": str(SMITH)}), ["example_smith"])
        self.assertEqual(sorted(MAP_CONTRACTS), ["example_smith"])
        self.assertEqual(get_map_contract("example_smith")["actor_radius"], 2.4)

    def test_a_second_file_needs_an_origin_and_a_failed_load_registers_nothing(self):
        paths = os.pathsep.join([str(SMITH), str(FIXTURES / "tiny_village.json")])
        with self.assertRaises(ValueError):
            load_from_environment({"EDEN_MAP_FILES": paths})
        self.assertEqual(MAP_CONTRACTS, {})

    def test_environment_loading_rejects_missing_or_invalid_files(self):
        clear_map_contracts()
        with self.assertRaises(Exception):
            load_from_environment({"EDEN_MAP_FILES": str(FIXTURES / "does_not_exist.json")})
        self.assertEqual(MAP_CONTRACTS, {})


class WorldContractOverrideTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def test_override_merges_into_the_contract_without_replacing_it(self):
        engine = await make_authored_world()
        legacy_walls = LEGACY_PLAYABLE_VILLAGE_CONTRACT["boxes"]
        contract = world_contract(engine)
        self.assertEqual(list(contract), LEGACY_KEY_ORDER + ["map_id", "map_revision", "units_per_tile"])  # appended, authored only
        self.assertEqual((contract["map_id"], contract["map_revision"], contract["units_per_tile"]), ("example_smith", 0, 8.0))
        self.assertNotEqual(contract["revision"], contract["map_revision"])  # "revision" stays the wall-hash string
        self.assertEqual((contract["version"], contract["walk_speed"], contract["sprint_multiplier"], contract["units_per_meter"],
                          contract["surface_id"], contract["height"], contract["world_epoch"]),
                         (1, 20.0, 1.5, 1.0, "ground", 0.0, engine.world_epoch))
        self.assertEqual((contract["actor_radius"], contract["bounds"]), (2.4, [0.0, 0.0, 48.0, 48.0]))
        self.assertEqual(contract["boxes"][0], {"id": "example_smith:wall_forge", "min": [16.0, 8.0], "max": [32.0, 16.0], "height": 2.4})
        self.assertEqual(contract["boxes"][1:], legacy_walls)  # live tensor walls (e.g. player-built) are kept
        self.assertEqual(map_wall_boxes(engine), contract["boxes"])

    async def test_returned_boxes_are_copies_of_the_registry(self):
        engine = await make_authored_world()
        world_contract(engine)["boxes"][0]["min"][0] = 999
        self.assertEqual(world_contract(engine)["boxes"][0]["min"][0], 16.0)

    async def test_revision_hash_changes_only_with_radius_bounds_or_boxes(self):
        # Same radius and bounds as legacy and no extra boxes: identical to the legacy revision.
        register_map_contract("playable_village", RADIUS, [0, 0, 1200, 900], [])
        await backend.create_genesis(backend.engine, map_name="playable_village")
        self.assertEqual(contract_without_epoch(backend.engine), LEGACY_PLAYABLE_VILLAGE_CONTRACT)
        revisions = {}
        for label, radius, bounds in (("radius", 2.4, [0, 0, 1200, 900]), ("bounds", RADIUS, [0, 0, 600, 900]),
                                      ("both", 2.4, [0, 0, 600, 900])):
            register_map_contract("playable_village", radius, bounds, [])
            revisions[label] = world_contract(backend.engine)["revision"]
        self.assertEqual(len({*revisions.values(), LEGACY_PLAYABLE_VILLAGE_CONTRACT["revision"]}), 4)
        register_map_contract("playable_village", 2.4, [0, 0, 1200, 900], [])
        self.assertEqual(world_contract(backend.engine)["revision"], revisions["radius"])  # deterministic
        register_map_contract("playable_village", RADIUS, [0, 0, 1200, 900], [{"id": "w", "min": [1, 1], "max": [2, 2]}])
        self.assertNotEqual(world_contract(backend.engine)["revision"], LEGACY_PLAYABLE_VILLAGE_CONTRACT["revision"])

    async def test_unregistering_restores_the_legacy_contract(self):
        engine = await make_authored_world("playable_village")
        self.assertEqual(world_contract(engine)["actor_radius"], 2.4)
        unregister_map_contract("playable_village")
        self.assertEqual(contract_without_epoch(engine), LEGACY_PLAYABLE_VILLAGE_CONTRACT)

    async def test_slide_stops_at_the_authored_wall_minus_the_map_radius_and_slides_tangentially(self):
        contract = world_contract(await make_authored_world())
        self.assertAlmostEqual(slide((24, 21), (24, 0), contract)[1], 18.4)  # 16 + 2.4
        self.assertAlmostEqual(slide((24, 5), (24, 40), contract)[1], 5.6)  # 8 - 2.4
        self.assertEqual(slide((24, 18.4), (30, 18.4), contract), (30, 18.4))  # tangent move along the wall face
        self.assertEqual(slide((10, 10), (-50, -50), contract), (2.4, 2.4))  # map bounds, not 1200x900

    async def test_real_tick_cannot_move_a_possessed_resident_through_the_authored_wall(self):
        engine = await make_authored_world()
        engine.state.h_tensor[0, backend.X], engine.state.h_tensor[0, backend.Y] = 24, 21
        claim = engine.player_control.claim_target(engine, controller_id="map_wall", target_kind="human",
                                                   target_id=engine._human_uid_by_slot[0])
        for seq in range(1, 11):
            payload = {key: claim[key] for key in ("protocol_version", "world_epoch", "possession_epoch", "target_kind", "target_id")}
            payload.update(seq=seq, move={"x": 0, "y": -1}, buttons={"sprint": True})
            self.assertTrue(engine.player_control.submit_input(engine, "map_wall", payload)["ok"])
            engine.step()
        self.assertAlmostEqual(float(engine.state.h_tensor[0, backend.Y]), 18.4, places=3)
        self.assertAlmostEqual(float(engine.state.h_tensor[0, backend.X]), 24.0, places=3)

    async def test_destroying_a_live_tensor_wall_still_changes_the_revision(self):
        engine = await make_authored_world()
        before = world_contract(engine)
        slot = engine._entity_uid_by_slot.index(before["boxes"][1]["id"])
        engine.state.m_tensor[slot, backend.M_HP] = 0
        after = world_contract(engine)
        self.assertNotEqual(after["revision"], before["revision"])
        self.assertEqual(len(after["boxes"]), len(before["boxes"]) - 1)


class CombatWallsTests(unittest.TestCase):
    def setUp(self):
        self.h = backend.engine.state.h_tensor.clone().zero_()
        self.m = backend.engine.state.m_tensor.clone().zero_()
        self.h[:2, backend.TYPE] = backend.AGENT_TYPE_HUMAN
        self.h[:2, backend.HP] = 100
        self.h[:2, backend.H_STAMINA] = 100
        self.h[:2, backend.X] = 100
        self.h[0, backend.Y], self.h[1, backend.Y] = 99, 101
        self.intent = CombatIntent(source="manual", action="attack", attacker_kind="human", attacker_slot=0,
                                   target_kind="human", target_slot=1, target_id="victim")

    def attack(self, **kwargs):
        self.h[:2, backend.HP] = 100
        self.h[:2, backend.H_STAMINA] = 100
        return resolve_human_attack_intents([self.intent], self.h, self.m, str(self.h.device), **kwargs)

    def test_default_behaviour_is_unchanged(self):
        self.assertEqual(self.attack()["resolved"], 1)
        self.assertEqual(self.attack(walls=None)["resolved"], 1)
        self.m[0, backend.M_TYPE], self.m[0, backend.M_HP] = backend.M_WALL, 100
        self.m[0, backend.CX], self.m[0, backend.CY] = 100, 100
        self.assertEqual(self.attack()["rejections"][0]["reason"], "blocked")
        self.assertEqual(self.attack(walls=None)["rejections"][0]["reason"], "blocked")

    def test_an_authored_wall_box_blocks_an_attack(self):
        wall = {"id": "authored", "min": [97.0, 99.5], "max": [103.0, 100.5], "height": 2.4}
        result = self.attack(walls=[wall])
        self.assertEqual((result["resolved"], result["rejections"][0]["reason"]), (0, "blocked"))
        side = {"id": "authored", "min": [110.0, 99.5], "max": [120.0, 100.5], "height": 2.4}
        self.assertEqual(self.attack(walls=[side])["resolved"], 1)

    def test_walls_argument_replaces_the_tensor_derived_boxes(self):
        self.m[0, backend.M_TYPE], self.m[0, backend.M_HP] = backend.M_WALL, 100
        self.m[0, backend.CX], self.m[0, backend.CY] = 100, 100
        self.assertEqual(self.attack(walls=[])["resolved"], 1)  # explicit list wins; the engine passes the merged list

    def test_engine_passes_the_merged_boxes_only_for_registered_maps(self):
        clear_map_contracts()
        backend.engine.reset_world()
        self.assertIsNone(map_wall_boxes(backend.engine))


class SaveRestoreTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.sessions = GameSessions(backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime,
                                     _test_storage / "map_contract" / uuid.uuid4().hex, backend.create_genesis, 905)

    def round_trip(self):
        payload = codec.loads(world_snapshot.capture(backend.engine, backend.map_geo))
        world_snapshot.validate(payload, backend.engine)
        backend.engine.reset_world()
        world_snapshot.restore(payload, backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime)

    def test_snapshot_engine_fields_have_no_contract_state(self):
        self.assertIn("_map_name", world_snapshot.ENGINE_FIELDS)
        for name in world_snapshot.ENGINE_FIELDS:
            self.assertNotIn("contract", name)
            self.assertNotIn("radius", name)

    async def test_legacy_session_saves_and_loads_with_the_golden_contract(self):
        await self.sessions.new("Legacy map")
        save_id = self.sessions.active_id
        self.assertEqual(contract_without_epoch(backend.engine), LEGACY_PLAYABLE_VILLAGE_CONTRACT)
        backend.engine.reset_world()
        await self.sessions.continue_world(save_id)
        self.assertEqual(contract_without_epoch(backend.engine), LEGACY_PLAYABLE_VILLAGE_CONTRACT)
        self.assertEqual(backend.engine._map_name, "playable_village")

    async def test_authored_map_session_restores_with_the_same_contract(self):
        await self.sessions.new("Authored map")
        engine = await make_authored_world()
        self.sessions.active_epoch = engine.world_epoch  # the session now owns this world
        await self.sessions.save()
        before = contract_without_epoch(engine)
        self.assertEqual(before["actor_radius"], 2.4)
        engine.reset_world()
        self.assertNotEqual(contract_without_epoch(engine).get("actor_radius"), 2.4)  # unregistered "unknown" map: legacy
        await self.sessions.continue_world(self.sessions.active_id)
        self.assertEqual(engine._map_name, "example_smith")
        self.assertEqual(contract_without_epoch(engine), before)

    async def test_direct_snapshot_round_trip_keeps_the_authored_contract(self):
        engine = await make_authored_world()
        before = contract_without_epoch(engine)
        self.round_trip()
        self.assertEqual(contract_without_epoch(engine), before)

    async def test_restoring_without_the_map_registered_is_refused_not_silently_legacy(self):
        engine = await make_authored_world()
        payload = codec.loads(world_snapshot.capture(engine, backend.map_geo))
        engine.reset_world()
        clear_map_contracts()
        with self.assertRaises(ValueError) as caught:
            world_snapshot.restore(payload, engine, backend.map_geo, backend.ar.PlayerControlRuntime)
        self.assertIn("example_smith", str(caught.exception))
        self.assertFalse(engine.world_loaded)  # nothing was applied



def gap_map(gap, radius=2.4, upt=8):
    """80x48-unit map (10x6 tiles at 8 u/tile): a vertical wall at x 40..42 with a centred gap of ``gap`` units."""
    half = gap / 2
    return parse_map({
        "format_version": "0.2-draft", "map_id": "gap_test", "revision": 0, "tile_size_px": 48, "units_per_tile": upt,
        "actor_radius": radius, "size_tiles": [10, 6],
        "walls": [{"id": "wall_top", "min": [40, 0], "max": [42, 24 - half]},
                  {"id": "wall_bottom", "min": [40, 24 + half], "max": [42, 48]}],
        "anchors": [{"id": "west", "kind": "spawn", "position": [20, 24]}, {"id": "east", "kind": "work", "position": [62, 24]}],
        "entities": [], "portals": []})[0]


def walks_through(world_map, lateral=0.0, step=1.0):
    """Walk east in straight steps at y = 24 + lateral using the real spatial.slide; True if it gets past the wall."""
    contract = to_movement_contract(world_map)
    pos = (20.0, 24.0 + lateral)
    for _ in range(80):
        pos = slide(pos, (pos[0] + step, pos[1]), contract)
    return pos[0] > 45


def validator_says_unreachable(world_map):
    return any("unreachable" in str(i) for i in validate_map(world_map) if i.severity == "error")


class RealScaleGapTests(unittest.TestCase):
    """8 units/tile, radius 2.4: the passable band through a gap g is g - 4.8, centred on the gap."""

    def test_gap_sizes_slide_and_validator_agree(self):
        for gap, passable in ((8.0, True), (5.8, True), (5.0, True), (4.79, False), (4.0, False)):
            with self.subTest(gap=gap):
                world_map = gap_map(gap)
                self.assertEqual(walks_through(world_map), passable)
                self.assertEqual(validator_says_unreachable(world_map), not passable)

    def test_one_tile_door_has_a_3_2_unit_band(self):
        world_map = gap_map(8.0)
        for lateral in (0.0, 1.0, 1.5, -1.5):
            self.assertTrue(walks_through(world_map, lateral), lateral)
        for lateral in (1.7, 2.0, 3.2, -2.0):
            self.assertFalse(walks_through(world_map, lateral), lateral)

    def test_ten_unit_door_tolerates_larger_lateral_offsets(self):
        world_map = gap_map(10.0)  # band 5.2: +-2.6
        for lateral in (0.0, 2.0, 2.5, -2.5):
            self.assertTrue(walks_through(world_map, lateral), lateral)
        for lateral in (2.7, 3.2, 4.0, -3.2):
            self.assertFalse(walks_through(world_map, lateral), lateral)

    def test_sprint_steps_do_not_tunnel(self):
        self.assertTrue(walks_through(gap_map(8.0), 0.0, step=1.5))
        self.assertFalse(walks_through(gap_map(4.79), 0.0, step=1.5))
        self.assertFalse(walks_through(gap_map(8.0), 2.0, step=1.5))

    def test_a_blocked_dead_centre_walk_stops_flush_at_the_inflated_wall(self):
        contract = to_movement_contract(gap_map(4.79))
        pos = (20.0, 24.0)
        for _ in range(80):
            pos = slide(pos, (pos[0] + 1.0, pos[1]), contract)
        self.assertAlmostEqual(pos[0], 40 - 2.4)

    def test_validator_uses_the_exact_band_not_a_grid(self):
        world_map = gap_map(5.0)  # band is only 0.2 wide, narrower than any tile-aligned cell
        self.assertFalse(validator_says_unreachable(world_map))
        self.assertTrue(walks_through(world_map, 0.0))
        self.assertFalse(walks_through(world_map, 0.5))


if __name__ == "__main__":
    unittest.main()
