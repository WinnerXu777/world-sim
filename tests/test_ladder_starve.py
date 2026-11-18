"""EDEN_LADDER_STARVE: the last-resort Tier 0 ration from hunger 90 stays the default; =1 leaves food to the ladder at every level."""
import os
import sys
import types
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

import torch

import genesis_config as cfg
from systems.actions import agent_driver
from systems.actions.agent_driver import AgentDriver

ROSTER = {"needs": {"threshold": 30, "ration": 25}}


def engine_with(hunger, thirst=0.0):
    h = torch.zeros(1, 200)
    h[0, cfg.HUNGER], h[0, cfg.THIRST] = hunger, thirst
    return types.SimpleNamespace(state=types.SimpleNamespace(h_tensor=h))


class LadderOwnsFood(unittest.TestCase):
    def owns(self, hunger, thirst=0.0, trips=()):
        return AgentDriver._ladder_owns_food(engine_with(hunger, thirst), 0, "h_1", ROSTER, types.SimpleNamespace(trips={t: 1 for t in trips}))

    def setUp(self):
        patcher = unittest.mock.patch.dict(os.environ, {}, clear=False)
        patcher.start()
        os.environ.pop(agent_driver.LADDER_STARVE_ENV, None)
        self.addCleanup(patcher.stop)

    def test_default_the_ladder_owns_food_between_the_trip_threshold_and_the_ration_level(self):
        self.assertFalse(self.owns(20))
        self.assertTrue(self.owns(30))
        self.assertTrue(self.owns(89.9))
        self.assertFalse(self.owns(agent_driver.LADDER_TIER0_HUNGER))          # from here Tier 0's free ration takes over
        self.assertFalse(self.owns(95))

    def test_thirst_and_a_trip_in_progress_stay_with_tier_0(self):
        self.assertFalse(self.owns(60, thirst=40))
        self.assertFalse(self.owns(60, trips=("h_1",)))

    def test_starve_flag_removes_the_ration_level(self):
        with unittest.mock.patch.dict(os.environ, {agent_driver.LADDER_STARVE_ENV: "1"}):
            self.assertTrue(self.owns(95))
            self.assertTrue(self.owns(100))
            self.assertFalse(self.owns(20))
            self.assertFalse(self.owns(60, thirst=40))


if __name__ == "__main__":
    unittest.main()
