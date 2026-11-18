"""Connected-component labelling per contract revision (R3-M1 step 5): the labels, the cheap "can it get there" answer in ``Reach`` and the mask, and
that the cheap answer never disagrees with the exact one."""
from authored_village import load_village_maps
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

import genesis_config as cfg  # noqa: E402
from test_affordance_engine import RealEngineCase  # noqa: E402
from harness.items import DictItemStore  # noqa: E402
from harness.world import World  # noqa: E402
from systems.affordance import AffordanceEngine, Anchor, EntityFact, Reach, StaticServices  # noqa: E402
from systems.affordance import components as comp  # noqa: E402
from systems.movement.spatial import is_standable_point  # noqa: E402


def box(name, x0, y0, x1, y1):
    return {"id": name, "min": [x0, y0], "max": [x1, y1], "height": 2.4}


def two_rooms():
    """A wall at x 100-104 with a door at y 40-52, and a sealed 40 x 40 pocket (a closed ring of four walls) on the right."""
    boxes = [box("w_lo", 100, 0, 104, 40), box("w_hi", 100, 52, 104, 100),
             box("p_top", 200, 60, 240, 64), box("p_bot", 200, 16, 240, 20), box("p_l", 196, 16, 200, 64), box("p_r", 240, 16, 244, 64)]
    return {"actor_radius": 2.4, "bounds": [0.0, 0.0, 300.0, 100.0], "boxes": boxes}


class RevisionServices(StaticServices):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.revision = "r1"

    def contract_revision(self):
        return self.revision


class ComponentLabelTests(unittest.TestCase):
    def setUp(self):
        self.contract = two_rooms()
        self.labels = comp.Components(self.contract)

    def test_rooms_joined_by_the_door_share_a_label_and_the_pocket_does_not(self):
        left, right, pocket = self.labels.label((20, 20)), self.labels.label((180, 20)), self.labels.label((220, 40))
        self.assertIsNotNone(left)
        self.assertEqual(left, right)
        self.assertIsNotNone(pocket)
        self.assertNotEqual(left, pocket)
        self.assertEqual(self.labels.count, 2)
        self.assertTrue(self.labels.connected((20, 20), (180, 90)))
        self.assertFalse(self.labels.connected((20, 20), (220, 40)))

    def test_a_point_inside_a_wall_has_no_label(self):
        self.assertIsNone(self.labels.label((102, 10)))
        self.assertFalse(self.labels.connected((102, 10), (20, 20)))

    def test_closing_the_door_splits_the_map(self):
        closed = two_rooms()
        closed["boxes"].append(box("door", 100, 40, 104, 52))
        labels = comp.Components(closed)
        self.assertFalse(labels.connected((20, 20), (180, 20)))
        self.assertEqual(labels.count, 3)

    def test_a_door_narrower_than_the_actor_is_closed(self):
        narrow = two_rooms()
        narrow["boxes"][1] = box("w_hi", 100, 44, 104, 100)          # a 4-unit gap: less than the actor's 4.8 diameter
        self.assertFalse(comp.Components(narrow).connected((20, 20), (180, 20)))

    def test_no_walls_is_one_component(self):
        labels = comp.Components({"actor_radius": 2.4, "bounds": [0.0, 0.0, 300.0, 100.0], "boxes": []})
        self.assertEqual(labels.count, 1)


class ReachShortcutTests(unittest.TestCase):
    def setUp(self):
        self.services = RevisionServices(contract=two_rooms())
        self.reach = Reach(self.services)

    def test_connected_points_are_answered_without_a_search(self):
        quick = self.reach.check((20, 20), (180, 20), need_length=False)
        self.assertEqual((quick.ok, quick.mode), (True, "component"))
        self.assertAlmostEqual(quick.length, 160.0)                      # straight-line lower bound
        self.assertEqual((self.reach.stats["component_hits"], self.reach.stats["path_searches"]), (1, 0))
        exact = self.reach.check((20, 20), (180, 20))                     # an exact question is not answered by the quick cache entry
        self.assertEqual((exact.ok, exact.mode), (True, "exact"))
        self.assertGreater(exact.length, 160.0)                           # round the door
        self.assertEqual(self.reach.stats["path_searches"], 1)
        again = self.reach.check((20, 20), (180, 20), need_length=False)  # now the exact entry serves both kinds
        self.assertEqual(again.mode, "exact")

    def test_a_straight_clear_line_never_needs_the_labels(self):
        self.assertEqual(self.reach.check((20, 20), (60, 30), need_length=False).mode, "exact")
        self.assertEqual(self.reach.stats["components_built"], 0)

    def test_a_different_label_is_not_trusted_the_search_decides(self):
        verdict = self.reach.check((20, 20), (220, 40), need_length=False)
        self.assertEqual((verdict.ok, verdict.mode, verdict.reason), (False, "exact", "unreachable"))
        self.assertEqual(self.reach.stats["component_hits"], 0)

    def test_labels_are_built_once_per_contract_revision(self):
        self.reach.check((20, 20), (180, 20), need_length=False)
        self.reach.check((20, 30), (180, 30), need_length=False)
        self.assertEqual(self.reach.stats["components_built"], 1)
        self.services._contract = {**two_rooms(), "boxes": two_rooms()["boxes"] + [box("door", 100, 40, 104, 52)]}
        self.services.revision = "r2"
        self.reach.clear()
        verdict = self.reach.check((20, 20), (180, 20), need_length=False)
        self.assertEqual(self.reach.stats["components_built"], 2)
        self.assertFalse(verdict.ok)

    def test_without_the_planner_internals_the_search_answers(self):
        saved = comp._contract
        comp._contract = None
        try:
            verdict = Reach(self.services).check((20, 20), (180, 20), need_length=False)
        finally:
            comp._contract = saved
        self.assertEqual((verdict.ok, verdict.mode), (True, "exact"))

    def test_portal_legs_use_the_shortcut_too(self):
        services = RevisionServices(contract=two_rooms(), portals=[{"here": lambda p: p[0] < 150, "from": (20.0, 20.0), "to": (180.0, 90.0)}])
        verdict = Reach(services).check((10, 10), (250, 90), need_length=False)
        self.assertTrue(verdict.ok)
        self.assertIn(verdict.mode, ("component", "exact"))

    def test_the_quick_answer_never_disagrees_with_the_exact_one(self):
        rng = random.Random(1008)
        contract = two_rooms()
        points = []
        while len(points) < 80:
            p = (rng.uniform(3, 297), rng.uniform(3, 97))
            if is_standable_point(p, contract):
                points.append(p)
        quick, exact = Reach(self.services), Reach(self.services)
        checked = same = 0
        for a in points[:40]:
            for b in points[40:]:
                q, e = quick.check(a, b, need_length=False), exact.check(a, b)
                if e.mode == "approx":
                    continue
                checked += 1
                same += int(q.ok == e.ok)
                self.assertEqual(q.ok, e.ok, (a, b, q, e))
        self.assertEqual(checked, same)
        self.assertGreater(quick.stats["component_hits"], 100)
        self.assertLess(quick.stats["path_searches"], exact.stats["path_searches"])


class MaskEquivalenceTests(unittest.TestCase):
    def test_mask_is_the_same_with_and_without_exact_lengths_on_a_walled_world(self):
        world = World.synthetic(seed=1, humans=12, items=DictItemStore())
        for hid, (x, y) in {"h_a": (20, 20), "h_b": (60, 50), "h_c": (150, 50)}.items():
            world.add_row("humans", hid, x=x, y=y, hp=100, hunger=70, stamina=30, mood=50)
        services = StaticServices(contract=two_rooms(), inventories={"h_a": {}},
                                  anchors={"h_a": {"sleep": Anchor("bed", "sleep", 180.0, 90.0), "work": Anchor("work", "work", 160.0, 20.0)}},
                                  sites={"h_a": {"food": Anchor("fire", "food", 170.0, 50.0), "water": Anchor("well", "water", 220.0, 40.0)}},
                                  entities=[EntityFact("e_tree", "wood_pile", 130.0, 30.0, True, 16.0)])
        aff = AffordanceEngine(world, services)
        actors = ["h_a", "h_b", "h_c"]
        exact, quick = aff.mask(actors, exact=True), aff.mask(actors)
        self.assertTrue(bool((exact == quick).all()))
        self.assertTrue(bool(quick[0].any()))
        well = aff.legal("h_a", "drink", {"place": "well"})                 # the pocket is sealed: the exact answer is "no", and the mask agrees
        self.assertFalse(well.ok)


class RealMapTests(RealEngineCase):
    def test_labels_of_the_starter_village(self):
        reach = Reach(self.services)
        labels = reach.components_for(self.services.contract())
        self.assertIsNotNone(labels)
        self.assertGreaterEqual(labels.count, 1)
        for human in self.residents:
            self.assertIsNotNone(labels.label(self.aff.observation(human).pos), human)

    def test_the_real_mask_is_identical_with_and_without_exact_lengths(self):
        rng = random.Random(7)
        contract = self.services.contract()
        for round_ in range(6):
            if round_:
                for human in self.residents:                                    # scatter the residents over standable points of the map
                    while True:
                        p = (rng.uniform(5, 1050), rng.uniform(5, 470))
                        if is_standable_point(p, contract):
                            break
                    self.put(human, *p)
                    self.engine.state.h_tensor[self.slot(human), cfg.HUNGER] = rng.uniform(0, 100)
                    self.engine.state.h_tensor[self.slot(human), cfg.THIRST] = rng.uniform(0, 100)
            aff_exact, aff_quick = AffordanceEngine(self.world, self.services), AffordanceEngine(self.world, self.services)
            exact, quick = aff_exact.mask(self.residents, exact=True), aff_quick.mask(self.residents)
            self.assertTrue(bool((exact == quick).all()), (round_, (exact != quick).nonzero().tolist()))
        self.assertGreater(aff_quick.reach.stats["component_hits"], 0)


if __name__ == "__main__":
    unittest.main()
