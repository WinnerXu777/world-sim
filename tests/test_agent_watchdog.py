"""The task watchdog (``AgentDriver._watchdog``) runs for every agent-driven resident, with the ladder and the action layer off: a stuck ``talk_to_target`` is released.

Real booted engine (starter_village); the stuck task is queued directly and the engine tick is advanced by assignment (no physics are needed to age a task).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
import random
import unittest
import unittest.mock

import torch

from test_startup_preservation import backend, _test_storage  # noqa: F401
from test_map_contract import AsyncRegistryIsolation
from authored_village import load_village_maps
import genesis_config as cfg
from driver_pin import pin_anchor
from systems.actions.agent_driver import AgentDriver, RulesTier1, TASK_CRITICAL_NEED, TASK_PATIENCE, _owns_movement_task
from systems.tasks.ops import queue_resident_task


class Watchdog(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        pin_anchor(self)
        patcher = unittest.mock.patch.dict("os.environ", {"EDEN_AGENT_ACTIONS": "", "EDEN_AGENT_LADDER": "", "EDEN_REPUTATION": "", "EDEN_MARKET": ""})
        patcher.start()
        self.addCleanup(patcher.stop)
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        self.engine = backend.engine
        self.engine.__dict__.pop("_roster_runtime", None)
        humans = [u for u in self.engine._human_uid_by_slot if u]
        for human_id in humans:
            self.engine.resident_store.get(human_id)["roster"]["driver"] = "agent"
        self.driver = self.engine.__dict__["_agent_driver"] = AgentDriver(RulesTier1())
        random.seed(1008)
        torch.manual_seed(1008)
        self.human, self.other = humans[0], humans[1]
        self.record = self.engine.resident_store.get(self.human)
        self.engine.state.h_tensor[:, cfg.HUNGER] = 0.0
        self.engine.state.h_tensor[:, cfg.THIRST] = 0.0

    def stuck_talk(self, tick):
        queue_resident_task(self.record, "talk_to_target", tick=tick, priority=0.4, source="action", summary=f"talk {self.other}", target_kind="human",
                            target_id=self.other)
        self.assertTrue(_owns_movement_task(self.record))

    def at(self, tick):
        self.engine.tick = tick
        self.driver.step(self.engine)

    async def test_a_task_that_never_finishes_is_cleared_after_the_patience_for_a_flag_off_driver(self):
        self.stuck_talk(100)
        self.at(100)                                              # first sight: the clock starts
        self.at(100 + TASK_PATIENCE - 1)
        self.assertTrue(_owns_movement_task(self.record))
        self.at(100 + TASK_PATIENCE)
        self.assertFalse(_owns_movement_task(self.record))
        self.assertEqual(self.driver.routed["watchdog:cleared_patience"], 1)

    async def test_a_critical_need_releases_it_at_once(self):
        self.stuck_talk(100)
        self.engine.state.h_tensor[self.engine._human_slot_for_id(self.human), cfg.THIRST] = TASK_CRITICAL_NEED
        self.at(101)
        self.assertFalse(_owns_movement_task(self.record))
        self.assertEqual(self.driver.routed["watchdog:cleared_critical"], 1)

    async def test_a_resident_without_a_task_is_untouched(self):
        self.at(500)
        self.at(500 + TASK_PATIENCE * 3)
        self.assertFalse(any(k.startswith("watchdog") for k in self.driver.routed))


if __name__ == "__main__":
    unittest.main()
