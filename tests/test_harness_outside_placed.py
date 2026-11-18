"""1008: a controlled human is never "outside the placed maps" under EDEN_WINDOW=1 (the window world has no edge and the placed rectangles do not
follow a re-base). Found by the live window smoke: /control/input answered 400 outside_placed_map the moment the player stepped past the village."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

import genesis_config as cfg  # noqa: E402
from systems.movement import map_contract  # noqa: E402


class OutsidePlacedTests(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        os.environ.pop("EDEN_WINDOW", None)
        self.engine = mock.Mock(_map_name="village")
        self.engine.state.h_tensor = torch.zeros((4, 32))
        self.engine.state.h_tensor[1, cfg.X] = 5000.0
        self.session = {"target_kind": "human", "slot": 1}
        for name, value in (("placed_group", [{"bounds": [0, 0, 100, 100]}]), ("position_in_placed_maps", False)):
            patcher = mock.patch.object(map_contract, name, **({"return_value": value} if name == "placed_group" else {"return_value": value}))
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_flag_off_outside_the_rectangles_is_outside(self):
        self.assertTrue(map_contract.outside_placed_maps(self.engine, self.session))

    def test_window_mode_is_never_outside(self):
        os.environ["EDEN_WINDOW"] = "1"
        self.assertFalse(map_contract.outside_placed_maps(self.engine, self.session))


if __name__ == "__main__":
    unittest.main()
