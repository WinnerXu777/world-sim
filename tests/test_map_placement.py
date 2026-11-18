"""Multi-map placement (G5): origins, validation, union bounds, containment slabs, command guards."""
import hashlib
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path

import httpx

from test_startup_preservation import backend
from test_map_contract import AsyncRegistryIsolation, FIXTURES, LEGACY_PLAYABLE_VILLAGE_CONTRACT, SMITH, contract_without_epoch
from systems.movement import map_contract
from systems.movement.map_contract import (MAP_CONTRACTS, clear_map_contracts, compose_group, containment_slabs, get_map_contract,
                                           load_from_environment, maps_block, outside_placed_maps, placed_group,
                                           position_in_placed_maps, register_map_file, validate_placement)
from systems.movement.spatial import is_standable_point, slide, world_contract
from authored_village import MAP_NAMES, load_village_maps

INTERIOR = FIXTURES / "example_smith_interior.json"
ROOT = Path(__file__).resolve().parents[1]
REAL_VILLAGE = ROOT / "world_data" / "maps2d" / "starter_village.json"
REAL_SMITH = ROOT / "world_data" / "maps2d" / "smith_interior.json"
ORIGIN = [300.0, 0.0]  # interior at x 300..396, y 0..80: 252 units from the 48x48 smith map


def place_both(origin=ORIGIN):
    register_map_file(SMITH, base_dir=FIXTURES)
    register_map_file(INTERIOR, origin=origin, base_dir=FIXTURES, primary=False, world="example_smith")


class PlacementRegistryTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def test_group_and_union_bounds(self):
        place_both()
        group = compose_group("example_smith")
        self.assertEqual([e["info"]["map_id"] for e in group["entries"]], ["example_smith", "example_smith_interior"])
        self.assertEqual(group["bounds"], [0.0, 0.0, 396.0, 80.0])
        self.assertEqual(group["actor_radius"], 2.4)
        self.assertEqual(len(placed_group("example_smith_interior")), 1)  # a secondary on its own is just itself
        self.assertEqual(placed_group("nope"), [])

    async def test_boxes_are_both_maps_walls_shifted_by_origin_then_slabs(self):
        place_both()
        boxes = compose_group("example_smith")["boxes"]
        ids = [b["id"] for b in boxes]
        self.assertEqual(ids[:5], ["example_smith:wall_forge", "example_smith_interior:wall_n", "example_smith_interior:wall_s",
                                   "example_smith_interior:wall_w", "example_smith_interior:wall_e"])
        north = next(b for b in boxes if b["id"] == "example_smith_interior:wall_n")
        self.assertEqual((north["min"], north["max"]), ([300.0, 0.0], [396.0, 4.0]))
        self.assertEqual([b for b in boxes if b["id"].startswith("map_slab_")],
                         [{"id": "map_slab_0", "min": [48.0, 0.0], "max": [300.0, 48.0], "height": 2.4},
                          {"id": "map_slab_1", "min": [0.0, 48.0], "max": [300.0, 80.0], "height": 2.4}])

    async def test_slabs_cover_exactly_the_space_outside_every_map(self):
        slabs = containment_slabs([(0, 0, 48, 48), (300, 0, 396, 80), (0, 200, 40, 260)])
        covered = lambda x, y: any(s["min"][0] < x < s["max"][0] and s["min"][1] < y < s["max"][1] for s in slabs)
        inside = lambda x, y: any(r[0] < x < r[2] and r[1] < y < r[3] for r in [(0, 0, 48, 48), (300, 0, 396, 80), (0, 200, 40, 260)])
        for x in range(1, 396, 7):
            for y in range(1, 260, 7):
                with self.subTest(x=x, y=y):
                    self.assertNotEqual(covered(x, y), inside(x, y))
        self.assertEqual(containment_slabs([(0, 0, 10, 10)]), [])

    async def test_contract_merges_both_maps_and_changes_the_wall_revision(self):
        register_map_file(SMITH, base_dir=FIXTURES)
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="example_smith")
        single = world_contract(backend.engine)
        register_map_file(INTERIOR, origin=ORIGIN, base_dir=FIXTURES, primary=False, world="example_smith")
        both = world_contract(backend.engine)
        self.assertEqual(single["bounds"], [0.0, 0.0, 48.0, 48.0])
        self.assertEqual(both["bounds"], [0.0, 0.0, 396.0, 80.0])
        self.assertNotEqual(single["revision"], both["revision"])
        self.assertEqual((both["map_id"], both["actor_radius"], both["version"], both["walk_speed"]), ("example_smith", 2.4, 1, 20.0))
        self.assertEqual(list(both)[:11], list(single)[:11])

    async def test_legacy_golden_contract_is_untouched_by_placed_maps(self):
        place_both()
        await backend.create_genesis(backend.engine, map_name="playable_village")
        self.assertEqual(contract_without_epoch(backend.engine), LEGACY_PLAYABLE_VILLAGE_CONTRACT)


class PlacementValidationTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    def assert_rejected(self, origin, text, path=INTERIOR, **kwargs):
        register_map_file(SMITH, base_dir=FIXTURES)
        before = dict(MAP_CONTRACTS)
        with self.assertRaises(ValueError) as caught:
            register_map_file(path, origin=origin, base_dir=FIXTURES, primary=False, world="example_smith", **kwargs)
        self.assertIn(text, str(caught.exception))
        self.assertEqual(sorted(MAP_CONTRACTS), sorted(before))  # rolled back

    async def test_overlap_is_rejected(self):
        self.assert_rejected([20.0, 0.0], "overlap")

    async def test_closer_than_the_isolation_distance_is_rejected(self):
        self.assert_rejected([260.0, 0.0], "more than 220")  # 212 units apart
        self.assert_rejected([268.0, 0.0], "more than 220")  # exactly 220 is not enough

    async def test_just_beyond_the_isolation_distance_is_accepted(self):
        register_map_file(SMITH, base_dir=FIXTURES)
        register_map_file(INTERIOR, origin=[268.5, 0.0], base_dir=FIXTURES, primary=False, world="example_smith")
        self.assertEqual(len(placed_group("example_smith")), 2)

    async def test_diagonal_gaps_use_the_euclidean_distance(self):
        self.assert_rejected([240.0, 150.0], "more than 220")  # dx 192, dy 102 -> 217
        register_map_file(INTERIOR, origin=[260.0, 160.0], base_dir=FIXTURES, primary=False, world="example_smith")  # 212, 112 -> 240

    async def test_must_fit_inside_the_world(self):
        self.assert_rejected([1150.0, 0.0], "does not fit")
        self.assert_rejected([300.0, 850.0], "does not fit")
        self.assert_rejected([-5.0, 0.0], "does not fit")

    async def test_placed_maps_must_share_one_actor_radius(self):
        self.assert_rejected(ORIGIN, "must share one radius", path=FIXTURES / "tiny_interior.json")

    async def test_ids_must_not_collide_across_maps(self):
        register_map_file(SMITH, base_dir=FIXTURES)
        before = dict(MAP_CONTRACTS)
        with self.assertRaises(ValueError) as caught:
            register_map_file(SMITH, name="smith_copy", origin=ORIGIN, base_dir=FIXTURES, primary=False, world="example_smith")
        self.assertIn("is defined by both", str(caught.exception))
        self.assertEqual(sorted(MAP_CONTRACTS), sorted(before))

    async def test_a_secondary_needs_a_registered_primary(self):
        with self.assertRaises(ValueError):
            register_map_file(INTERIOR, origin=ORIGIN, base_dir=FIXTURES, primary=False, world="example_smith")
        with self.assertRaises(ValueError):
            register_map_file(INTERIOR, origin=ORIGIN, base_dir=FIXTURES, primary=False)
        self.assertEqual(MAP_CONTRACTS, {})

    async def test_validate_placement_accepts_a_good_layout_and_a_single_map(self):
        place_both()
        validate_placement(placed_group("example_smith"))
        validate_placement(placed_group("example_smith")[:1])


class PlacementMovementTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def contract(self):
        place_both()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="example_smith")
        return world_contract(backend.engine)

    async def test_an_actor_cannot_leave_its_map_into_the_gap(self):
        contract = await self.contract()
        self.assertAlmostEqual(slide((24, 40), (100, 40), contract)[0], 45.6)  # east edge of the smith map
        self.assertAlmostEqual(slide((24, 40), (24, 70), contract)[1], 45.6)  # south edge
        self.assertAlmostEqual(slide((310, 40), (200, 40), contract)[0], 306.4)  # interior's west wall (300..304) + radius
        self.assertAlmostEqual(slide((24, 40), (1000, 40), contract)[0], 45.6)  # a huge step cannot tunnel through the gap
        self.assertAlmostEqual(slide((24, 40), (700, 60), contract)[0], 45.6)

    async def test_movement_inside_a_map_is_unchanged_and_still_slides_along_walls(self):
        contract = await self.contract()
        self.assertEqual(slide((8, 32), (8, 30), contract), (8, 30))
        self.assertAlmostEqual(slide((24, 21), (24, 0), contract)[1], 18.4)  # forge wall in the smith map
        self.assertEqual(slide((24, 18.4), (30, 18.4), contract), (30, 18.4))
        inside = slide((350, 40), (320, 40), contract)  # open floor of the interior
        self.assertEqual(inside, (320, 40))
        self.assertAlmostEqual(slide((350, 40), (350, 200), contract)[1], 80 - 4 - 2.4)  # interior's south wall

    async def test_interior_bounds_are_enforced_by_the_union_clamp_and_walls(self):
        contract = await self.contract()
        self.assertEqual(slide((350, 40), (500, 40), contract)[0], 396 - 4 - 2.4)  # east wall
        self.assertEqual(slide((350, 40), (350, -50), contract)[1], 4 + 2.4)  # north wall

    async def test_spawn_in_the_gap_is_snapped_back_into_a_map(self):
        await self.contract()
        engine = backend.engine
        before = engine.pop_count
        self.assertTrue(engine.spawn(150.0, 30.0, 0.0, 70.0, age=20.0, preferred_name="Gapper"))
        h = engine.state.h_tensor
        positions = [(float(h[s, backend.X]), float(h[s, backend.Y])) for s in range(h.shape[0]) if float(h[s, backend.TYPE]) > 0]
        self.assertEqual(len(positions), before + 1)
        for position in positions:
            self.assertTrue(position_in_placed_maps("example_smith", *position), position)
            self.assertTrue(is_standable_point(position, world_contract(engine)), position)

    async def test_position_helpers(self):
        place_both()
        self.assertTrue(position_in_placed_maps("example_smith", 10, 10))
        self.assertTrue(position_in_placed_maps("example_smith", 350, 70))
        self.assertFalse(position_in_placed_maps("example_smith", 150, 30))
        self.assertFalse(position_in_placed_maps("example_smith", 10, 60))
        self.assertTrue(position_in_placed_maps("playable_village", 150, 30))  # legacy: no placement, nothing to enforce


class PlacementCommandGuardTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def claimed_outside(self, x, y):
        place_both()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="example_smith")
        engine = backend.engine
        engine.state.h_tensor[0, backend.X], engine.state.h_tensor[0, backend.Y] = x, y
        claim = engine.player_control.claim_target(engine, controller_id="guard", target_kind="human", target_id=engine._human_uid_by_slot[0])
        envelope = {key: claim[key] for key in ("protocol_version", "world_epoch", "possession_epoch", "target_kind", "target_id")}
        return engine, envelope

    async def test_input_and_events_are_rejected_for_an_actor_outside_every_map(self):
        engine, env = await self.claimed_outside(150.0, 30.0)  # in the gap
        session = engine.player_control.sessions_by_controller["guard"]
        self.assertTrue(outside_placed_maps(engine, session))
        move = engine.player_control.submit_input(engine, "guard", {**env, "seq": 1, "move": {"x": 1, "y": 0}, "buttons": {}})
        self.assertEqual((move["ok"], move["reason"]), (False, "outside_placed_map"))
        event = engine.player_control.submit_event(engine, "guard", {**env, "seq": 2, "type": "attack"})
        self.assertEqual((event["ok"], event["reason"]), (False, "outside_placed_map"))

    async def test_inventory_commands_are_rejected_for_an_actor_outside_every_map(self):
        engine, env = await self.claimed_outside(150.0, 30.0)
        payload = {**env, "controller_id": "guard", "command_id": str(uuid.uuid4()), "item_id": "x"}
        result = engine.command_inbox.submit(engine, "equip", payload)
        self.assertEqual((result["ok"], result["status"], result["reason"]), (False, "rejected", "outside_placed_map"))

    async def test_an_actor_inside_a_map_is_not_affected(self):
        engine, env = await self.claimed_outside(24.0, 21.0)
        session = engine.player_control.sessions_by_controller["guard"]
        self.assertFalse(outside_placed_maps(engine, session))
        move = engine.player_control.submit_input(engine, "guard", {**env, "seq": 1, "move": {"x": 0, "y": -1}, "buttons": {}})
        self.assertTrue(move["ok"])
        payload = {**env, "controller_id": "guard", "command_id": str(uuid.uuid4()), "item_id": "x"}
        self.assertNotEqual(engine.command_inbox.submit(engine, "equip", payload).get("reason"), "outside_placed_map")

    async def test_the_interior_counts_as_inside(self):
        engine, env = await self.claimed_outside(350.0, 40.0)
        self.assertFalse(outside_placed_maps(engine, engine.player_control.sessions_by_controller["guard"]))

    async def test_legacy_worlds_are_never_rejected(self):
        await backend.create_genesis(backend.engine, map_name="playable_village")
        engine = backend.engine
        engine.state.h_tensor[0, backend.X], engine.state.h_tensor[0, backend.Y] = 5.0, 5.0
        claim = engine.player_control.claim_target(engine, controller_id="legacy", target_kind="human", target_id=engine._human_uid_by_slot[0])
        env = {key: claim[key] for key in ("protocol_version", "world_epoch", "possession_epoch", "target_kind", "target_id")}
        result = engine.player_control.submit_input(engine, "legacy", {**env, "seq": 1, "move": {"x": 1, "y": 0}, "buttons": {}})
        self.assertTrue(result["ok"])
        self.assertFalse(outside_placed_maps(engine, engine.player_control.sessions_by_controller["legacy"]))


class PlacementConfigTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    def env(self, files, origins=None):
        env = {"EDEN_MAP_FILES": os.pathsep.join(str(f) for f in files)}
        if origins is not None:
            env["EDEN_MAP_ORIGINS"] = origins if isinstance(origins, str) else json.dumps(origins)
        return env

    async def test_inline_json_origins(self):
        names = load_from_environment(self.env([SMITH, INTERIOR], {"example_smith_interior": ORIGIN}))
        self.assertEqual(names, ["example_smith", "example_smith_interior"])
        self.assertEqual([e["info"]["origin"] for e in placed_group("example_smith")], [[0.0, 0.0], ORIGIN])
        self.assertEqual([e["info"]["primary"] for e in placed_group("example_smith")], [True, False])

    async def test_origins_from_a_json_file_and_an_explicit_primary_origin(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "origins.json"
            path.write_text(json.dumps({"example_smith": [10, 10], "example_smith_interior": [400, 20]}), encoding="utf-8")
            load_from_environment(self.env([SMITH, INTERIOR], str(path)))
        group = placed_group("example_smith")
        self.assertEqual(group[0]["bounds"], [10.0, 10.0, 58.0, 58.0])
        self.assertEqual(group[1]["bounds"], [400.0, 20.0, 496.0, 100.0])

    async def test_a_missing_origin_or_bad_origins_register_nothing(self):
        for origins in (None, {}, {"example_smith_interior": [1]}, {"example_smith_interior": "x"}, "[1, 2]", "{not json"):
            with self.subTest(origins=origins):
                with self.assertRaises((ValueError, KeyError, TypeError, json.JSONDecodeError)):
                    load_from_environment(self.env([SMITH, INTERIOR], origins))
                self.assertEqual(MAP_CONTRACTS, {})

    async def test_an_invalid_layout_registers_nothing(self):
        with self.assertRaises(ValueError):
            load_from_environment(self.env([SMITH, INTERIOR], {"example_smith_interior": [30, 0]}))
        self.assertEqual(MAP_CONTRACTS, {})

    async def test_all_four_real_maps_can_be_placed(self):
        names = load_village_maps()
        self.assertEqual(names, list(MAP_NAMES))
        group = compose_group("starter_village")
        self.assertEqual(group["bounds"], [0.0, 0.0, 1056.0, 480.0])
        self.assertEqual(group["actor_radius"], 2.4)
        self.assertTrue(any(b["id"].startswith("map_slab_") for b in group["boxes"]))
        issues = [b["id"] for b in group["boxes"]]
        self.assertEqual(len(issues), len(set(issues)))


class PlacementWireTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    def client(self):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=backend.app), base_url="http://127.0.0.1")

    async def test_both_maps_are_listed_primary_first_and_both_are_served(self):
        place_both()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="example_smith")
        async with self.client() as client:
            body = (await client.get("/bootstrap")).json()
            blocks = body["maps"]
            self.assertEqual([(b["map_id"], b["primary"], b["origin"]) for b in blocks],
                             [("example_smith", True, [0.0, 0.0]), ("example_smith_interior", False, [300.0, 0.0])])
            self.assertEqual(body["spatial"]["bounds"], [0.0, 0.0, 396.0, 80.0])
            self.assertEqual(body["spatial"]["map_id"], "example_smith")
            for block, path in zip(blocks, (SMITH, INTERIOR)):
                response = await client.get(block["url"])
                self.assertEqual(response.content, path.read_bytes())
                self.assertEqual(hashlib.sha256(response.content).hexdigest(), block["sha256"])
                self.assertEqual(response.headers["etag"], f'"{block["sha256"]}"')
                self.assertEqual(blocks.index(block) == 0, block["primary"])

    async def test_the_block_set_is_per_world(self):
        place_both()
        register_map_file(FIXTURES / "tiny_village.json", name="tiny_village", base_dir=FIXTURES)
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="tiny_village")
        self.assertEqual([b["map_id"] for b in maps_block(backend.engine)], ["tiny_village"])


if __name__ == "__main__":
    unittest.main()
