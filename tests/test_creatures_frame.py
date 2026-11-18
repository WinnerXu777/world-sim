"""1008 Phase 2 step 5: the additive ``creature`` key of a frame animal (EDEN_CREATURES=1 only)."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_creatures_kernel import HOME, KernelFixture  # noqa: E402
import genesis_config as cfg  # noqa: E402
from systems.creatures import frame, table  # noqa: E402


class FrameKeyTests(KernelFixture):
    async def test_flag_off_the_frame_animal_has_no_creature_key(self):
        slot = self.spawn("boar", *HOME)
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_CREATURES")
            self.assertNotIn("creature", self.engine._export_animal(slot))

    async def test_flag_on_a_table_species_carries_species_sprite_footprint_state_variant(self):
        slot = self.spawn("goblin", *HOME)
        m = self.engine.state.m_tensor
        m[slot, table.C_STATE] = float(table.STATES["chase"])
        m[slot, table.C_VARIANT] = 2.0
        exported = self.engine._export_animal(slot)
        self.assertEqual(exported["creature"], {"species": "goblin", "sprite": None, "footprint": table.CREATURES["goblin"]["footprint"], "state": "chase",
                                               "variant": table.CREATURES["goblin"]["variants"][1]})
        self.assertIn("state", exported, "the existing schema state dict is untouched")
        self.assertEqual(exported["type_id"], table.id_of("goblin"))
        self.assertEqual(exported["type_label"], "goblin")

    async def test_a_legacy_brain_species_has_no_state_and_a_sprite_when_art_exists(self):
        slot = self.spawn("sheep", *HOME)
        creature = self.engine._export_animal(slot)["creature"]
        self.assertIsNone(creature["state"])
        self.assertEqual(creature["sprite"], "a4/static/static-sheep-a4-v1.png")
        self.assertIsNone(creature["variant"])

    async def test_a_row_that_is_no_creature_has_no_keys(self):
        row = self.engine.state.m_tensor[0].clone()
        row[cfg.M_TYPE] = float(cfg.M_FOREST)
        self.assertIsNone(frame.keys(row))


if __name__ == "__main__":
    unittest.main()
