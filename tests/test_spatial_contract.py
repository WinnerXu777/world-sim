import unittest
from test_startup_preservation import backend
from systems.movement.spatial import slide, world_contract


class SpatialContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_controlled_tick_moves_once_at_contract_speed(self):
        for profile in ("full", "render_test"):
            backend.engine.reset_world()
            await backend.create_genesis(backend.engine, map_name="playable_village")
            engine = backend.engine
            engine._runtime_profile = profile
            engine.state.h_tensor[0, backend.X] = 100
            engine.state.h_tensor[0, backend.Y] = 100
            claim = engine.player_control.claim_target(engine, controller_id="speed_test", target_kind="human", target_id=engine._human_uid_by_slot[0])
            contract = world_contract(engine)
            for seq, (x, y, sprint) in enumerate(((1, 0, False), (.6, .8, False), (0, 1, True), (0, 0, False)), 1):
                with self.subTest(profile=profile, seq=seq):
                    before = engine.state.h_tensor[0, :2].clone()
                    payload = {key: claim[key] for key in ("protocol_version", "world_epoch", "possession_epoch", "target_kind", "target_id")}
                    payload.update(seq=seq, move={"x": x, "y": y}, buttons={"sprint": sprint})
                    self.assertTrue(engine.player_control.submit_input(engine, "speed_test", payload)["ok"])
                    engine.step()
                    distance = contract["walk_speed"] / backend.TICK_RATE_HZ * (contract["sprint_multiplier"] if sprint else 1)
                    self.assertAlmostEqual(float(engine.state.h_tensor[0, backend.X] - before[0]), x * distance, places=4)
                    self.assertAlmostEqual(float(engine.state.h_tensor[0, backend.Y] - before[1]), y * distance, places=4)

    def test_sweep_blocks_tunnelling_and_allows_tangent_motion(self):
        contract = {"actor_radius": .35, "bounds": [0, 0, 100, 100],
                    "boxes": [{"min": [40, 20], "max": [60, 21]}]}
        self.assertEqual(slide((50, 10), (50, 90), contract), (50, 19.65))
        self.assertEqual(slide((50, 30), (50, 0), contract), (50, 21.35))
        self.assertEqual(slide((50, 19.65), (55, 19.65), contract), (55, 19.65))
        self.assertEqual(slide((10, 10), (-50, -50), contract), (.35, .35))

    async def test_real_tick_cannot_move_possessed_resident_through_live_wall(self):
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="playable_village")
        engine = backend.engine
        contract = world_contract(engine)
        wall = contract["boxes"][0]
        x = (wall["min"][0] + wall["max"][0]) / 2
        engine.state.h_tensor[0, backend.X] = x
        engine.state.h_tensor[0, backend.Y] = wall["min"][1] - 1
        claim = engine.player_control.claim_target(engine, controller_id="wall_test", target_kind="human", target_id=engine._human_uid_by_slot[0])
        for seq in range(1, 21):
            payload = {key: claim[key] for key in ("protocol_version", "world_epoch", "possession_epoch", "target_kind", "target_id")}
            payload.update(seq=seq, move={"x": 0, "y": 1}, buttons={"sprint": True})
            self.assertTrue(engine.player_control.submit_input(engine, "wall_test", payload)["ok"])
            engine.step()
        self.assertLessEqual(float(engine.state.h_tensor[0, backend.Y]), wall["min"][1]-.35+.0001)
        self.assertGreater(float(engine.state.h_tensor[0, backend.Y]), wall["min"][1]-.5)
        slot = engine._entity_uid_by_slot.index(wall["id"])
        engine.state.m_tensor[slot, backend.M_HP] = 0
        self.assertNotEqual(world_contract(engine)["revision"], contract["revision"])
