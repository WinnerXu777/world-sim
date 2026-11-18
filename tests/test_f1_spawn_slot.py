"""F1 (reports/f1_spawn_slot.md): under EDEN_WINDOW the placed maps' containment slabs must not block the chunk world, and the
incarnation spawn anchors on an overworld resident without the legacy-frame clamp. Flag off and the finite window stay as they were."""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

import genesis_config as cfg  # noqa: E402
import map_test as backend  # noqa: E402
from harness.window import POCKET_ORIGINS  # noqa: E402
from harness.window_manager import WindowManager  # noqa: E402
from systems.creatures import collide  # noqa: E402
from systems.movement import spatial  # noqa: E402
from systems.movement.map_contract import MAP_CONTRACTS, clear_map_contracts, compose_group, get_map_contract, register_map_file  # noqa: E402

MAPS = Path(__file__).resolve().parents[1] / "world_data" / "maps2d"
INTERIORS = ("smith_interior", "village_lodge_interior", "west_cottage_interior")
SHIFT = (-1024.0, -256.0)                      # the probe's re-base: frame origin (4, 1)
SPAWN = (156.0, 34.401)                        # where the probe's player stood, just south of map_slab_6
CHUNK_WINDOW = {"boxes": [{"id": "void:9_9:n", "min": [2304.0, 2300.0], "max": [2560.0, 2304.0], "height": 2.4}],
                "bounds": [0.0, 0.0, 512.0, 512.0], "revision": "chunks"}
FINITE_WINDOW = {"boxes": [], "bounds": None, "revision": "finite"}


def slab_ids(boxes):
    return [b["id"] for b in boxes if str(b["id"]).startswith("map_slab_")]


class RegistryIsolation(unittest.TestCase):
    def setUp(self):
        saved = dict(MAP_CONTRACTS)
        clear_map_contracts()
        self.addCleanup(lambda: (clear_map_contracts(), MAP_CONTRACTS.update(saved)))
        collide._BOXES.clear()
        self.addCleanup(collide._BOXES.clear)
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop("EDEN_WINDOW", None)

    def pocket_world(self, window):
        """starter_village shifted by the probe's re-base, its three interiors in the pocket pool, an engine stub carrying ``window``."""
        with mock.patch.dict(os.environ, {"EDEN_WINDOW": "1"}):     # as the window loader registers them: pockets lie outside the legacy frame
            register_map_file(MAPS / "starter_village.json", "starter_village")
            for index, name in enumerate(INTERIORS):
                register_map_file(MAPS / f"{name}.json", name, origin=POCKET_ORIGINS[index], primary=False, world="starter_village")
        engine = SimpleNamespace(state=SimpleNamespace(m_tensor=torch.zeros((8, 40))), _entity_uid_by_slot=[""] * 8,
                                 _map_name="starter_village", world_epoch=1, _window_contract=window)
        WindowManager._shift_primary_contract(SimpleNamespace(engine=engine), *SHIFT)
        return engine


class ContainmentSlabTests(RegistryIsolation):
    def test_a_chunk_window_drops_the_containment_slabs_and_the_spawn_walks_north(self):
        engine = self.pocket_world(CHUNK_WINDOW)
        self.assertTrue(slab_ids(compose_group("starter_village")["boxes"]), "the pocket layout does produce slabs")
        os.environ["EDEN_WINDOW"] = "1"
        contract = spatial.world_contract(engine)
        self.assertEqual(slab_ids(contract["boxes"]), [])
        self.assertIn("void:9_9:n", [b["id"] for b in contract["boxes"]])
        self.assertTrue(any(b["id"].startswith("smith:") for b in contract["boxes"]), "the placed maps' own walls stay")
        end = spatial.slide(SPAWN, (SPAWN[0], SPAWN[1] - 20.0), contract)
        self.assertLess(end[1], SPAWN[1] - 10.0)

    def test_a_finite_window_keeps_the_slabs(self):
        engine = self.pocket_world(FINITE_WINDOW)
        os.environ["EDEN_WINDOW"] = "1"
        self.assertEqual(slab_ids(spatial.world_contract(engine)["boxes"]), slab_ids(compose_group("starter_village")["boxes"]))

    def test_flag_off_keeps_the_slabs_even_with_a_chunk_contract(self):
        engine = self.pocket_world(CHUNK_WINDOW)
        contract = spatial.world_contract(engine)
        self.assertEqual(slab_ids(contract["boxes"]), slab_ids(compose_group("starter_village")["boxes"]))
        self.assertNotIn("void:9_9:n", [b["id"] for b in contract["boxes"]])

    def test_the_creature_collider_drops_the_same_slabs(self):
        engine = self.pocket_world(CHUNK_WINDOW)
        group = compose_group("starter_village")["boxes"]
        os.environ["EDEN_WINDOW"] = "1"
        boxes, generated = collide._static_boxes(engine)
        self.assertEqual(len(boxes), len(group) - len(slab_ids(group)) + len(CHUNK_WINDOW["boxes"]))
        self.assertEqual(len(generated), len(boxes))

    def test_the_creature_collider_keeps_the_slabs_in_a_finite_window_and_flag_off(self):
        engine = self.pocket_world(FINITE_WINDOW)
        group = compose_group("starter_village")["boxes"]
        os.environ["EDEN_WINDOW"] = "1"
        self.assertEqual(len(collide._static_boxes(engine)[0]), len(group))
        collide._BOXES.clear()
        os.environ.pop("EDEN_WINDOW")
        engine._window_contract = CHUNK_WINDOW
        self.assertEqual(len(collide._static_boxes(engine)[0]), len(group) + len(CHUNK_WINDOW["boxes"]))


def human_rows(*rows):
    """h_tensor with one live human per (x, y, space) row; free rows after them."""
    h = torch.zeros((6, cfg.H_RESTRAINED + 8))
    for slot, (x, y, space) in enumerate(rows):
        h[slot, cfg.TYPE] = float(cfg.AGENT_TYPE_HUMAN)
        h[slot, cfg.X], h[slot, cfg.Y], h[slot, cfg.H_SPACE] = x, y, space
    return SimpleNamespace(state=SimpleNamespace(h_tensor=h), tick=0, _map_name="starter_village")


def spawn_point(engine):
    return backend.Engine._player_incarnation_spawn_point(engine, "local_player")


class SpawnAnchorTests(RegistryIsolation):
    SMITH_IN_POCKET = (1817.0, -2010.7, 1.0)
    VILLAGER = (-900.0, -100.0, 0.0)

    def test_window_anchors_on_the_first_overworld_human_without_the_legacy_clamp(self):
        engine = human_rows(self.SMITH_IN_POCKET, self.VILLAGER)
        os.environ["EDEN_WINDOW"] = "1"
        x, y = spawn_point(engine)
        self.assertTrue(-900.0 + 18.0 - 12.0 <= x <= -900.0 + 18.0 + 12.0, x)
        self.assertTrue(-100.0 + 12.0 - 10.0 <= y <= -100.0 + 12.0 + 10.0, y)

    def test_window_without_an_overworld_human_uses_the_primary_map_centre(self):
        engine = self.pocket_world(FINITE_WINDOW)
        engine.state, engine.tick = human_rows(self.SMITH_IN_POCKET).state, 0
        b = get_map_contract("starter_village")["bounds"]
        os.environ["EDEN_WINDOW"] = "1"
        x, y = spawn_point(engine)
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        self.assertTrue(abs(x - cx) <= 12.0 and abs(y - cy) <= 10.0, (x, y, cx, cy))

    def test_flag_off_keeps_the_first_human_and_the_legacy_clamp(self):
        engine = human_rows(self.SMITH_IN_POCKET, self.VILLAGER)
        self.assertEqual(spawn_point(engine), (cfg.MAP_WIDTH - 20.0, 20.0))
        inside = human_rows((300.0, 200.0, 0.0))
        x, y = spawn_point(inside)
        self.assertTrue(306.0 <= x <= 330.0 and 202.0 <= y <= 222.0, (x, y))


if __name__ == "__main__":
    unittest.main()
