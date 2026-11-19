"""F1b (owner ruling 1118 after R0.5 run 6): under a chunk window the exterior placed maps' own edge walls (``<prefix>:boundary_*`` of a
``map_kind == "exterior"`` map: starter_village's four) are dropped like F1's containment slabs, for the player and the creatures, so an
incarnated player can walk out of the village. Interior maps keep their boundary walls (they hold the room inside its pocket); houses and props
stay; flag off and the finite window keep every box."""
import json
import os
import unittest
from pathlib import Path

from test_f1_spawn_slot import CHUNK_WINDOW, FINITE_WINDOW, MAPS, SHIFT, RegistryIsolation, slab_ids
from systems.creatures import collide
from systems.movement import spatial
from systems.movement.map_contract import compose_group

VILLAGE_EDGE = {"village:boundary_north", "village:boundary_south", "village:boundary_west", "village:boundary_east"}
CORNER = (377.6 + SHIFT[0], 281.6 + SHIFT[1])          # R0.5 run 6: the walker's stop, the village's SE inner corner (absolute -> shifted)


def ids(boxes):
    return {str(b["id"]) for b in boxes}


class VillageEdgeTests(RegistryIsolation):
    def test_a_chunk_window_drops_the_village_edge_and_the_walker_leaves_east(self):
        engine = self.pocket_world(CHUNK_WINDOW)
        self.assertTrue(VILLAGE_EDGE <= ids(compose_group("starter_village")["boxes"]))
        os.environ["EDEN_WINDOW"] = "1"
        contract = spatial.world_contract(engine)
        have = ids(contract["boxes"])
        self.assertFalse(VILLAGE_EDGE & have, "the village edge walls are gone over chunks")
        self.assertIn("village:wall_house_smith", have, "houses stay")
        for room in ("smith", "lodge", "west"):
            self.assertIn(f"{room}:boundary_north", have, f"the {room} interior keeps its walls")
        end = spatial.slide(CORNER, (CORNER[0] + 20.0, CORNER[1]), contract)
        self.assertGreater(end[0], CORNER[0] + 10.0, "the walker crosses the old east edge")

    def test_a_finite_window_keeps_the_village_edge(self):
        engine = self.pocket_world(FINITE_WINDOW)
        os.environ["EDEN_WINDOW"] = "1"
        self.assertTrue(VILLAGE_EDGE <= ids(spatial.world_contract(engine)["boxes"]))

    def test_flag_off_keeps_the_village_edge(self):
        engine = self.pocket_world(CHUNK_WINDOW)
        contract = spatial.world_contract(engine)
        self.assertTrue(VILLAGE_EDGE <= ids(contract["boxes"]))
        end = spatial.slide(CORNER, (CORNER[0] + 20.0, CORNER[1]), contract)
        self.assertLess(end[0], CORNER[0] + 1.0)

    def test_the_creature_collider_drops_the_same_edge_and_keeps_it_otherwise(self):
        engine = self.pocket_world(CHUNK_WINDOW)
        group = compose_group("starter_village")["boxes"]
        os.environ["EDEN_WINDOW"] = "1"
        boxes, _ = collide._static_boxes(engine)
        self.assertEqual(len(boxes), len(group) - len(slab_ids(group)) - len(VILLAGE_EDGE) + len(CHUNK_WINDOW["boxes"]))
        collide._BOXES.clear()
        engine._window_contract = FINITE_WINDOW
        self.assertEqual(len(collide._static_boxes(engine)[0]), len(group))
        collide._BOXES.clear()
        os.environ.pop("EDEN_WINDOW")
        engine._window_contract = CHUNK_WINDOW
        self.assertEqual(len(collide._static_boxes(engine)[0]), len(group) + len(CHUNK_WINDOW["boxes"]))

    def test_only_starter_village_is_an_exterior_map_with_edge_walls(self):
        exterior, interior = set(), {}
        for path in sorted(Path(MAPS).glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            edge = {w["id"] for w in data.get("walls", []) if str(w["id"]).split(":", 1)[-1].startswith("boundary_")}
            if data.get("map_kind") == "exterior":
                exterior |= edge
            elif edge:
                interior[data["map_id"]] = edge
        self.assertEqual(exterior, VILLAGE_EDGE)
        self.assertTrue(interior and all(len(e) >= 4 for e in interior.values()), interior)


if __name__ == "__main__":
    unittest.main()
