"""F3: under EDEN_CALENDAR a mature female still gives birth at most once per calendar year (R0.3), but sheep and boar bear a litter (table key
``litter``: sheep 2, boar 2, everything else 1; boar 4 -> 1 in F3-5, 2 in F3-6, once the breeding hold became calendar-aware), so the long calendar no
longer leaves them below replacement (reports/f3_decline.md: R0 0.67 and 0.86 with one young per year). Flag off (legacy calendar): one young per birth and the one-year recovery, unchanged."""
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
from systems.creatures import table  # noqa: E402

ROWS = 64
BOAR = table.CREATURES["boar"]["id"]


def pair(species):
    """A small m_tensor with a mature male (slot 1) and a mature female (slot 2) of ``species`` two units apart."""
    m = torch.zeros(ROWS, 32)
    for slot, x, sex in ((1, 10.0, 0.0), (2, 12.0, 1.0)):
        m[slot, cfg.M_TYPE], m[slot, cfg.CX], m[slot, cfg.CY] = float(species), x, 10.0
        m[slot, cfg.M_HP], m[slot, cfg.SCALE] = 100.0, 4.0
        m[slot, cfg.A_AGE], m[slot, cfg.A_SEX], m[slot, cfg.A_COOLDOWN] = cfg.ANIMAL_MATURE_TICKS + 1.0, sex, 0.0
    return m


class LitterTests(unittest.TestCase):
    def setUp(self):
        import instincts_and_tools as iat
        self.iat = iat

    def calendar(self, on):
        patcher = mock.patch.dict(os.environ, {"EDEN_CALENDAR": "1"} if on else {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        if not on:
            os.environ.pop("EDEN_CALENDAR", None)
        self.assertIs(cal.active(), cal.USER if on else cal.LEGACY)

    def breed(self, species):
        m = pair(species)
        count = [3]
        self.iat.animal_tool_reproduce({"a_mask": m[:, cfg.M_TYPE] == float(species)}, m, count, "cpu")
        born = count[0] - 3
        rows = (m[:, cfg.M_TYPE] == float(species)).nonzero().flatten().tolist()
        newborn = [r for r in rows if r not in (1, 2)]                          # entity_born picks free rows; only the pair was there before
        self.assertEqual(len(newborn), born)
        self.assertTrue(all(float(m[r, cfg.A_AGE]) == 0.0 for r in newborn))
        return m, born

    def recovery(self, m):
        return float(m[2, cfg.A_COOLDOWN]) + cal.cooldown_decay_rate()          # add back the decay of the birth call itself

    def test_table_litters(self):
        self.assertEqual(table.CREATURES["sheep"]["litter"], 2)
        self.assertEqual(table.CREATURES["boar"]["litter"], 2)   # F3-6: with the 600-tick hold, litter 4 made 5 boar 40 in 10 days and litter 1 made them 3
        for name in ("deer", "wolf", "tiger", "fox"):
            self.assertEqual(table.CREATURES[name]["litter"], 1, name)
        self.assertTrue(all(row["litter"] == 1 for name, row in table.CREATURES.items() if name not in ("sheep", "boar")))
        self.assertEqual(table.validate(), [])

    def test_validate_rejects_bad_litter(self):
        for value in (0, 9, 1.5, "2", True):
            bad = {name: dict(row) for name, row in table.CREATURES.items()}
            bad["sheep"]["litter"] = value
            self.assertTrue(any(p.startswith("sheep: litter") for p in table.validate(bad)), value)

    def test_export_has_no_litter(self):
        self.assertFalse(any("litter" in s for s in table.export()["species"]))

    def test_user_calendar_litters(self):
        self.calendar(True)
        for species, young in ((cfg.M_SHEEP, 2), (BOAR, 2), (cfg.M_WOLF, 1), (table.CREATURES["deer"]["id"], 1)):
            m, born = self.breed(species)
            self.assertEqual(born, young, species)
            self.assertAlmostEqual(self.recovery(m), cal.active().year_ticks / cal.active().life_year_ticks, places=4)   # still one birth per calendar year

    def test_legacy_calendar_one_young(self):
        self.calendar(False)
        for species in (cfg.M_SHEEP, BOAR, cfg.M_WOLF):
            m, born = self.breed(species)
            self.assertEqual(born, 1, species)
            expected = torch.tensor(1.0) - torch.tensor(cal.cooldown_decay_rate())
            self.assertEqual(float(m[2, cfg.A_COOLDOWN]), float(expected))

    def test_legacy_calendar_never_reads_the_litter(self):
        self.calendar(False)
        with mock.patch.dict(table.CREATURES["sheep"], {"litter": 4}):
            _, born = self.breed(cfg.M_SHEEP)
        self.assertEqual(born, 1)


if __name__ == "__main__":
    unittest.main()
