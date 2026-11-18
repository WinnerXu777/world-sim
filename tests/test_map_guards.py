"""Map safety guards: restore refuses unknown maps (G1), NPC combat honours authored walls (G2),
standable spawns on authored maps (G4)."""
import unittest
import uuid

import torch

from test_startup_preservation import backend, _test_storage
from test_map_contract import (AsyncRegistryIsolation, LEGACY_PLAYABLE_VILLAGE_CONTRACT, SMITH, FIXTURES,
                               contract_without_epoch, make_authored_world)
from persistence import codec, world_snapshot
from persistence.sessions import GameSessions
from systems.movement.map_contract import clear_map_contracts, register_world_map
from world_map import load_map
import instincts_and_tools as iat
from systems.combat.ops import resolve_attack_intents
from systems.combat.intents import CombatIntent


class RestoreRefusesUnknownMapTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.sessions = GameSessions(backend.engine, backend.map_geo, backend.ar.PlayerControlRuntime,
                                     _test_storage / "map_guards" / uuid.uuid4().hex, backend.create_genesis, 905)

    async def save_authored(self):
        await self.sessions.new("Authored map")
        engine = await make_authored_world()
        self.sessions.active_epoch = engine.world_epoch
        await self.sessions.save()
        return self.sessions.active_id

    async def test_authored_save_without_its_map_registered_is_refused_naming_the_map(self):
        save_id = await self.save_authored()
        backend.engine.reset_world()
        clear_map_contracts()
        with self.assertRaises(ValueError) as caught:
            await self.sessions.continue_world(save_id)
        self.assertIn("example_smith", str(caught.exception))
        self.assertIn("EDEN_MAP_FILES", str(caught.exception))
        self.assertFalse(backend.engine.world_loaded)

    async def test_refusal_leaves_the_running_world_and_session_untouched(self):
        save_id = await self.save_authored()
        clear_map_contracts()
        await self.sessions.new("Legacy map")  # the world we are playing now
        engine = backend.engine
        for _ in range(3):
            engine.step()
        snapshot = lambda: (engine.world_epoch, engine.tick, engine._map_name, engine.world_loaded,
                            engine.state.m_tensor.clone(), engine.state.h_tensor.clone(),
                            list(engine._entity_uid_by_slot), list(engine._human_uid_by_slot),
                            self.sessions.active_id, self.sessions.active_name, self.sessions.active_epoch,
                            self.sessions.last_saved_tick, dict(engine.resident_store._cache))
        before = snapshot()
        saves_before = self.sessions.store.list_saves()
        with self.assertRaises(ValueError) as caught:
            await self.sessions.continue_world(save_id)
        self.assertIn("example_smith", str(caught.exception))
        after = snapshot()
        for index, (old, new) in enumerate(zip(before, after)):
            if hasattr(old, "shape"):
                self.assertTrue(bool((old == new).all()), f"tensor {index} changed")
            else:
                self.assertEqual(old, new, f"state field {index} changed")
        self.assertEqual(self.sessions.store.list_saves(), saves_before)  # nothing was written either
        self.assertEqual(contract_without_epoch(engine), LEGACY_PLAYABLE_VILLAGE_CONTRACT)
        self.assertEqual(self.sessions.status()["error"], str(caught.exception))  # surfaced to the client

    async def test_registered_authored_map_loads(self):
        save_id = await self.save_authored()
        before = contract_without_epoch(backend.engine)
        backend.engine.reset_world()
        register_world_map(load_map(SMITH, base_dir=FIXTURES))
        await self.sessions.continue_world(save_id)
        self.assertEqual(backend.engine._map_name, "example_smith")
        self.assertEqual(contract_without_epoch(backend.engine), before)

    async def test_legacy_save_still_loads_without_any_registration(self):
        await self.sessions.new("Legacy map")
        save_id = self.sessions.active_id
        backend.engine.reset_world()
        await self.sessions.continue_world(save_id)
        self.assertEqual(contract_without_epoch(backend.engine), LEGACY_PLAYABLE_VILLAGE_CONTRACT)

    async def test_every_builtin_generator_name_is_accepted(self):
        from initial_map_design import MAP_REGISTRY
        payload = codec.loads(world_snapshot.capture(backend.engine, backend.map_geo))
        for name in MAP_REGISTRY:
            payload["engine"]["_map_name"] = name
            world_snapshot.validate(payload, backend.engine)  # must not raise

    async def test_unknown_or_non_string_names_are_refused(self):
        payload = codec.loads(world_snapshot.capture(backend.engine, backend.map_geo))
        for name in ("no_such_map", "", None, 5):
            payload["engine"]["_map_name"] = name
            with self.assertRaises(ValueError, msg=repr(name)):
                world_snapshot.validate(payload, backend.engine)


class NpcCombatWallsTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    """Autonomous (NPC) combat goes through instinct_attack; the authored wall at [16,8]-[32,16] must block it."""

    def npc_attack(self, engine, attacker_y, target_y):
        h = engine.state.h_tensor
        for slot, y in ((0, attacker_y), (1, target_y)):
            h[slot, backend.X], h[slot, backend.Y] = 24.0, y
            h[slot, backend.HP], h[slot, backend.H_STAMINA] = 100.0, 100.0
        hp_before = float(h[1, backend.HP])
        mask = torch.zeros(h.shape[0], dtype=torch.bool)
        mask[:2] = True
        pairwise = {"live_idx": torch.tensor([0, 1]), "dists": torch.full((2, 2), 12.0),
                    "within_attack": torch.tensor([[False, True], [True, False]]),
                    "aggressive": torch.tensor([True, False]), "peaceful": torch.tensor([False, True])}
        ctx = {"h_mask": mask, "pairwise_pre": pairwise, "manual_control": None, "engine": engine}
        outcome = iat.instinct_attack(ctx, h, engine.state.m_tensor, [2], str(h.device), engine=engine)
        return float(h[1, backend.HP]) < hp_before, outcome

    async def test_an_npc_cannot_attack_through_an_authored_wall(self):
        engine = await make_authored_world()
        hit, _ = self.npc_attack(engine, attacker_y=6.0, target_y=18.0)  # wall spans y 8..16 between them
        self.assertFalse(hit)

    async def test_the_same_attack_lands_when_nothing_is_between(self):
        engine = await make_authored_world()
        hit, _ = self.npc_attack(engine, attacker_y=18.0, target_y=28.0)  # both south of the wall
        self.assertTrue(hit)

    async def test_legacy_world_is_unchanged_by_the_walls_argument(self):
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="playable_village")
        self.assertIsNone(backend.map_wall_boxes(backend.engine))
        hit, _ = self.npc_attack(backend.engine, attacker_y=6.0, target_y=18.0)  # no authored wall in a legacy world
        self.assertTrue(hit)

    def test_ops_resolve_attack_intents_accepts_walls_and_defaults_to_none(self):
        h = backend.engine.state.h_tensor.clone().zero_()
        m = backend.engine.state.m_tensor.clone().zero_()
        h[:2, backend.TYPE] = backend.AGENT_TYPE_HUMAN
        h[:2, backend.HP] = 100
        h[:2, backend.H_STAMINA] = 100
        h[:2, backend.X] = 100
        h[0, backend.Y], h[1, backend.Y] = 99, 101
        intent = CombatIntent(source="sim", action="attack", attacker_kind="human", attacker_slot=0,
                              target_kind="human", target_slot=1, target_id="victim")
        wall = {"id": "w", "min": [97.0, 99.5], "max": [103.0, 100.5], "height": 2.4}
        self.assertEqual(resolve_attack_intents([intent], h, m, device=str(h.device), walls=[wall])["resolved"], 0)
        h[:2, backend.H_STAMINA] = 100
        self.assertEqual(resolve_attack_intents([intent], h, m, device=str(h.device))["resolved"], 1)


if __name__ == "__main__":
    unittest.main()
