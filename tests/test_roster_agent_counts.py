"""Agent-aware variants of the three roster-count tests (D-008): the originals count ``anchor_driven_slots``; with every resident bound to the agent
driver that count is 0 and the same residents are ``roster_slots(engine, "agent")``. The originals are unchanged (they pin the default)."""
import json
import os
import unittest
import uuid
from pathlib import Path
from unittest import mock

from authored_village import load_village_maps
from test_startup_preservation import backend, _test_storage
from test_map_contract import AsyncRegistryIsolation
import genesis_config as cfg
from instincts_and_tools import engine_has_roster
from systems.actions.agent_driver import AgentDriver, RulesTier1
from systems.roster.apply import clear_roster_cache, world_has_roster
from systems.roster.driver import anchor_driven_slots, needs_scale_vector, roster_of, roster_slots, runtime

ROOT = Path(__file__).resolve().parents[1]


async def agent_world():
    load_village_maps()
    backend.engine.reset_world()
    await backend.create_genesis(backend.engine, map_name="starter_village")
    engine = backend.engine
    for human_id in [u for u in engine._human_uid_by_slot if u]:
        engine.resident_store.get(human_id)["roster"]["driver"] = "agent"
    engine.__dict__["_agent_driver"] = AgentDriver(RulesTier1())
    return engine


class AgentWorldRulesTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    def roster_dir(self):
        directory = _test_storage / "rd" / uuid.uuid4().hex[:8]
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    async def assert_agent_world_unchanged(self, engine, note):
        self.assertTrue(world_has_roster(engine), note)
        self.assertTrue(engine_has_roster(engine), note)
        self.assertEqual(len(anchor_driven_slots(engine)), 0, note)             # nobody is anchor-driven ...
        self.assertEqual(len(roster_slots(engine, "agent")), 8, note)           # ... all eight are agent-driven
        self.assertEqual(len(roster_slots(engine, None)), 8, note)
        self.assertIsNotNone(needs_scale_vector(engine, engine.state.h_tensor), note)       # the roster needs scale still applies to agent residents
        for _ in range(30):
            engine.step()
        self.assertTrue(bool((engine.state.h_tensor[:8, cfg.HP] >= 99.9).all()), note)
        self.assertGreater(engine.__dict__["_agent_driver"].ticks_driven, 0, note)

    async def test_a_missing_roster_file_does_not_change_the_running_agent_world(self):
        engine = await agent_world()
        engine.step()
        with mock.patch.dict(os.environ, {"EDEN_ROSTER_DIR": str(self.roster_dir())}):
            clear_roster_cache()
            await self.assert_agent_world_unchanged(engine, "missing file")

    async def test_a_new_roster_naming_anchors_the_world_never_placed_does_not_change_the_running_agent_world(self):
        engine = await agent_world()
        engine.step()
        data = json.loads((ROOT / "world_data" / "rosters" / "starter_village.json").read_text(encoding="utf-8"))
        extra = json.loads(json.dumps(data["residents"][1]))
        extra.update(key="newcomer", name="Newcomer")
        extra["anchors"] = {"spawn": "village:spawn", "work": "lodge:not_placed_in_this_world"}
        data["residents"].append(extra)
        directory = self.roster_dir()
        (directory / "starter_village.json").write_text(json.dumps(data), encoding="utf-8")
        with mock.patch.dict(os.environ, {"EDEN_ROSTER_DIR": str(directory)}):
            clear_roster_cache()
            await self.assert_agent_world_unchanged(engine, "roster with unplaced anchors")

    async def test_a_possessed_agent_resident_is_not_sent_anywhere_and_is_driven_again_afterwards(self):
        engine = await agent_world()
        slot, uid = next((s, u) for s, u in enumerate(engine._human_uid_by_slot) if u and roster_of(engine, u)[0]["key"] == "iven")
        engine.player_control.claim_target(engine, controller_id="p", target_kind="human", target_id=uid)
        engine.player_control.clock = lambda: 0.0
        h = engine.state.h_tensor
        self.assertNotIn(slot, roster_slots(engine, "agent"))
        h[slot, cfg.THIRST] = 45.0
        start = (float(h[slot, cfg.X]), float(h[slot, cfg.Y]))
        for _ in range(60):
            engine.step()
        self.assertEqual((float(h[slot, cfg.X]), float(h[slot, cfg.Y])), start)
        self.assertNotIn(uid, runtime(engine).trips)
        engine.player_control.release_target(engine, controller_id="p")
        engine.step()
        self.assertEqual(roster_slots(engine, "agent").count(slot), 1)
        self.assertEqual(anchor_driven_slots(engine).count(slot), 0)


if __name__ == "__main__":
    unittest.main()
