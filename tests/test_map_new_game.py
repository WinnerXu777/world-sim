"""New Game creates the configured launch map (EDEN_MAP); the legacy default stays playable_village."""
import unittest
import uuid

from test_startup_preservation import backend, _test_storage
from test_map_contract import (AsyncRegistryIsolation, FIXTURES, LEGACY_PLAYABLE_VILLAGE_CONTRACT, SMITH,
                               contract_without_epoch)
from launch_config import LaunchConfig
from persistence.sessions import GameSessions
from systems.movement.map_contract import register_map_file
from systems.movement.spatial import is_standable_point, world_contract


class NewGameMapTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    def sessions(self, **kwargs):
        return GameSessions(backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime,
                            _test_storage / "new_game" / uuid.uuid4().hex, backend.create_genesis, 905, **kwargs)

    async def test_default_new_game_is_the_legacy_village(self):
        sessions = self.sessions()
        self.assertEqual(sessions.map_name, "playable_village")
        await sessions.new("Default")
        self.assertEqual(backend.engine._map_name, "playable_village")
        self.assertEqual(contract_without_epoch(backend.engine), LEGACY_PLAYABLE_VILLAGE_CONTRACT)

    async def test_new_game_uses_the_configured_authored_map(self):
        register_map_file(SMITH, base_dir=FIXTURES)
        sessions = self.sessions(map_name="example_smith")
        result = await sessions.new("Authored")
        self.assertTrue(result["ok"])
        engine = backend.engine
        self.assertEqual(engine._map_name, "example_smith")
        contract = world_contract(engine)
        self.assertEqual((contract["map_id"], contract["actor_radius"]), ("example_smith", 2.4))
        h = engine.state.h_tensor
        positions = [(float(h[s, backend.X]), float(h[s, backend.Y])) for s in range(h.shape[0]) if float(h[s, backend.TYPE]) > 0]
        self.assertEqual(len(positions), 4)
        self.assertTrue(all(is_standable_point(p, contract) for p in positions))
        # and the save round-trips through Continue with the map registered
        save_id = sessions.active_id
        engine.reset_world()
        await sessions.continue_world(save_id)
        self.assertEqual(backend.engine._map_name, "example_smith")

    async def test_the_launch_config_map_name_reaches_the_module_level_sessions(self):
        self.assertEqual(backend.game_sessions.map_name, backend.LAUNCH_CONFIG.map_name)
        self.assertEqual(LaunchConfig.from_env({"EDEN_PROFILE": "gameplay", "EDEN_MAP": "starter_village"}).map_name, "starter_village")
        self.assertEqual(LaunchConfig.from_env({"EDEN_PROFILE": "gameplay"}).map_name, "playable_village")

    async def test_an_unregistered_map_name_fails_clearly_and_the_previous_save_survives(self):
        legacy = self.sessions()
        await legacy.new("Legacy first")
        legacy_id = legacy.active_id
        broken = GameSessions(backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime, legacy.store.root,
                              backend.create_genesis, 905, map_name="starter_village_not_registered")
        broken.active_id, broken.active_name, broken.active_epoch = legacy.active_id, legacy.active_name, legacy.active_epoch
        with self.assertRaises(ValueError) as caught:
            await broken.new("Broken")
        self.assertIn("starter_village_not_registered", str(caught.exception))
        self.assertFalse(backend.engine.world_loaded)  # the failed New Game leaves no half-built world
        self.assertIn(legacy_id, [save["save_id"] for save in broken.store.list_saves()])
        await broken.continue_world(legacy_id)
        self.assertEqual(backend.engine._map_name, "playable_village")


if __name__ == "__main__":
    unittest.main()
