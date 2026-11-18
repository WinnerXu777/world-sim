"""Model-plane consumers of the creature table: the hostile set behind ``EngineServices.hostile_count`` (legacy pair with the flag off, the table's rows with it)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
import os
import unittest
import unittest.mock

import torch

import genesis_config as cfg
from systems.affordance.services import EngineServices
from systems.creatures import table


class FakeEngine:
    def __init__(self, rows):
        self.state = type("S", (), {})()
        m = torch.zeros((len(rows), cfg.M_TENSOR_WIDTH if hasattr(cfg, "M_TENSOR_WIDTH") else 40), dtype=torch.float32)
        for i, (mtype, x, y, hp) in enumerate(rows):
            m[i, cfg.M_TYPE], m[i, cfg.CX], m[i, cfg.CY], m[i, cfg.M_HP] = mtype, x, y, hp
        self.state.m_tensor = m


class HostileCount(unittest.TestCase):
    def count(self, flag, rows, radius=100.0):
        env = {"EDEN_CREATURES": flag} if flag else {}
        with unittest.mock.patch.dict(os.environ, env, clear=False):
            if not flag:
                os.environ.pop("EDEN_CREATURES", None)
            return EngineServices(FakeEngine(rows)).hostile_count(0.0, 0.0, radius)

    def rows(self):
        boar = table.id_of("boar")
        return [(cfg.M_TIGER, 10, 0, 100), (cfg.M_WOLF, 20, 0, 100), (cfg.M_SHEEP, 5, 0, 100), (boar, 15, 0, 80), (cfg.M_WOLF, 30, 0, 0), (cfg.M_TIGER, 900, 0, 100)]

    def test_flag_off_counts_tigers_and_wolves_only_alive_and_in_range(self):
        self.assertEqual(self.count("", self.rows()), 2)

    def test_flag_on_counts_the_tables_hostile_rows(self):
        self.assertEqual(self.count("1", self.rows()), 3)                # the boar is hostile in the table

    def test_no_animals_is_zero(self):
        self.assertEqual(self.count("", [(cfg.M_SHEEP, 1, 1, 100)]), 0)


if __name__ == "__main__":
    unittest.main()
