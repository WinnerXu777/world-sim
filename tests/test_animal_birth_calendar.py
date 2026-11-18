"""R0.3 breeding fix: under EDEN_CALENDAR a mature female animal gives at most one birth per calendar year (8 game days), not one per life-year
(one game day, USER-DEC-4). Flag off: the legacy one-year recovery is unchanged (the legacy life-year and year are both 600 ticks)."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "at_the_beginning"))

import genesis_config as cfg  # noqa: E402
from harness import calendar as cal  # noqa: E402

ROWS = 64


def pair(species=cfg.M_SHEEP):
    """A small m_tensor with a mature male (slot 1) and a mature female (slot 2) of ``species`` two units apart."""
    m = torch.zeros(ROWS, 32)
    for slot, x, sex in ((1, 10.0, 0.0), (2, 12.0, 1.0)):
        m[slot, cfg.M_TYPE], m[slot, cfg.CX], m[slot, cfg.CY] = float(species), x, 10.0
        m[slot, cfg.M_HP], m[slot, cfg.SCALE] = 100.0, 4.0
        m[slot, cfg.A_AGE], m[slot, cfg.A_SEX], m[slot, cfg.A_COOLDOWN] = cfg.ANIMAL_MATURE_TICKS + 1.0, sex, 0.0
    return m


def calendar_flag(on):
    patcher = mock.patch.dict(os.environ, {"EDEN_CALENDAR": "1"} if on else {}, clear=False)
    patcher.start()
    if not on:
        os.environ.pop("EDEN_CALENDAR", None)
    return patcher


class BirthRecoveryTests(unittest.TestCase):
    def setUp(self):
        import instincts_and_tools as iat
        self.iat = iat

    def births(self, m, calls, species=cfg.M_SHEEP):
        count = [3]
        mask = lambda: m[:, cfg.M_TYPE] == float(species)
        for _ in range(calls):
            self.iat.animal_tool_reproduce({"a_mask": mask()}, m, count, "cpu")
            m[3:, :] = 0.0                       # newborns leave: only the original pair can breed again
            count[0] = 3
        return m

    def run_once(self, on):
        patcher = calendar_flag(on)
        self.addCleanup(patcher.stop)
        m = pair()
        count = [3]
        self.iat.animal_tool_reproduce({"a_mask": m[:, cfg.M_TYPE] == float(cfg.M_SHEEP)}, m, count, "cpu")
        return m, count[0] - 3

    def test_flag_off_the_recovery_is_one_legacy_year(self):
        m, born = self.run_once(False)
        self.assertEqual(born, 1)
        expected = torch.tensor(1.0) - torch.tensor(cal.cooldown_decay_rate())
        self.assertEqual(float(m[2, cfg.A_COOLDOWN]), float(expected))
        self.assertEqual(cal.cooldown_decay_rate(), 1.0 / cal.LEGACY_YEAR_TICKS)

    def test_flag_on_the_recovery_is_one_calendar_year(self):
        m, born = self.run_once(True)
        self.assertEqual(born, 1)
        recovery = float(m[2, cfg.A_COOLDOWN]) + cal.cooldown_decay_rate()      # the decay of the birth call itself
        self.assertAlmostEqual(recovery, cal.USER_DAYS_PER_YEAR * cal.USER_DAY_TICKS / cal.active().life_year_ticks, places=4)
        self.assertAlmostEqual(recovery / cal.cooldown_decay_rate(), cal.USER_DAY_TICKS * cal.USER_DAYS_PER_YEAR, delta=2.0)

    def test_flag_on_a_pair_breeds_once_in_two_game_days(self):
        patcher = calendar_flag(True)
        self.addCleanup(patcher.stop)
        m = pair()
        counted = [0]
        original = self.iat.animal_born

        def spy(*args, **kw):
            counted[0] += 1
            return original(*args, **kw)
        with mock.patch.object(self.iat, "animal_born", spy):
            self.births(m, 2 * cal.USER_DAY_TICKS)
        self.assertEqual(counted[0], 1, "one birth per calendar year, not one per game day")

    def test_flag_on_the_life_year_decay_is_unchanged(self):
        patcher = calendar_flag(True)
        self.addCleanup(patcher.stop)
        self.assertEqual(cal.cooldown_decay_rate(), 1.0 / (cal.USER_DAY_TICKS / cal.CALENDAR_LIFE_YEARS_PER_DAY))
        self.assertEqual(cal.age_step(), cal.cooldown_decay_rate())


if __name__ == "__main__":
    unittest.main()
