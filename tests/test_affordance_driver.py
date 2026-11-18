"""D-008, data only: while the driver mode is "roster", the engine reports the verbs a roster resident's driver would not carry out as
``roster_driven`` (options, legal, resolve and the mask alike). "agent" mode, or a resident without a roster record, is judged by the world only."""
import sys
import unittest
from pathlib import Path

from driver_pin import pin_anchor

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from harness.items import DictItemStore  # noqa: E402
from harness.world import World  # noqa: E402
from systems.affordance import AffordanceEngine, Anchor, EntityFact, REASONS, StaticServices, config, driver  # noqa: E402
from systems.decision.matrix import ACTION_INDEX  # noqa: E402

ROSTER = {"key": "gatherer", "anchors": {}}


def build(*, roster=("h_a",), mode=None, hunger=60.0, **kw):
    world = World.synthetic(seed=1, humans=12, items=DictItemStore())
    for hid, (x, y) in {"h_a": (10, 10), "h_b": (20, 10), "h_c": (14, 12)}.items():
        world.add_row("humans", hid, x=x, y=y, hp=100, hunger=hunger, stamina=100, mood=50)
    services = StaticServices(records={h: ({"roster": ROSTER} if h in roster else {}) for h in ("h_a", "h_b", "h_c")}, **kw)
    return world, AffordanceEngine(world, services, driver_mode=mode)


class DriverPolicyTests(unittest.TestCase):
    def setUp(self):
        pin_anchor(self)

    def test_the_reason_is_registered_and_the_default_mode_is_roster_until_d008_is_decided(self):
        self.assertIn("roster_driven", REASONS)
        self.assertEqual(config.DRIVER_MODE, "roster")

    def test_eat_from_the_pack_works_but_eat_at_a_site_is_demoted(self):
        site = Anchor("village:use_campfire", "food", 60.0, 10.0)
        _, with_pack = build(inventories={"h_a": {"rations": 1}}, sites={"h_a": {"food": site}})
        self.assertTrue(with_pack.legal("h_a", "eat", {"item": "rations"}).ok)
        placed = with_pack.legal("h_a", "eat", {"place": "village:use_campfire"})
        self.assertEqual((placed.ok, placed.reason), (False, "roster_driven"))
        self.assertEqual(placed.detail["place"], "village:use_campfire")
        _, no_pack = build(sites={"h_a": {"food": site}})
        self.assertEqual(no_pack.legal("h_a", "eat", {}).reason, "roster_driven")
        self.assertEqual(no_pack.options("h_a", verbs=("eat",)), [])
        self.assertEqual([o.verdict.reason for o in no_pack.options("h_a", verbs=("eat",), include_illegal=True)], ["roster_driven"])

    def test_gather_and_follow_are_demoted_for_a_roster_resident_only(self):
        tree = EntityFact("e_tree", "wood_pile", 20.0, 20.0, True, 16.0)
        _, engine = build(roster=("h_a",), entities=[tree])
        self.assertEqual(engine.legal("h_a", "gather_resource", {"source": "e_tree"}).reason, "roster_driven")
        self.assertEqual(engine.legal("h_a", "follow", {"target": "h_b"}).reason, "roster_driven")
        self.assertTrue(engine.legal("h_b", "gather_resource", {"source": "e_tree"}).ok)             # h_b has no roster record
        self.assertTrue(engine.legal("h_b", "follow", {"target": "h_a"}).ok)

    def test_agent_mode_switches_the_table_off(self):
        tree = EntityFact("e_tree", "wood_pile", 20.0, 20.0, True, 16.0)
        _, engine = build(mode="agent", entities=[tree])
        self.assertTrue(engine.legal("h_a", "gather_resource", {"source": "e_tree"}).ok)
        self.assertTrue(engine.legal("h_a", "follow", {"target": "h_b"}).ok)

    def test_the_mask_and_resolve_follow_the_same_answer(self):
        tree = EntityFact("e_tree", "wood_pile", 20.0, 20.0, True, 16.0)
        _, roster = build(entities=[tree])
        _, agent = build(mode="agent", entities=[tree])
        gather, social = ACTION_INDEX["gather"], ACTION_INDEX["socialise"]
        self.assertFalse(bool(roster.mask(["h_a"])[0, gather]))
        self.assertTrue(bool(agent.mask(["h_a"])[0, gather]))
        self.assertIsNone(roster.resolve("gather", "h_a"))
        self.assertEqual(agent.resolve("gather", "h_a").verb, "gather_resource")
        self.assertTrue(bool(roster.mask(["h_a"])[0, social]))                                # chat / greet still work for a roster resident
        self.assertEqual(roster.resolve("socialise", "h_a").verb, "chat")                    # follow is no longer the fallback

    def test_the_table_is_data(self):
        self.assertEqual(sorted(driver.ALWAYS), ["approach_node", "attack", "avoid", "drink", "explore_toward", "follow", "gather_resource", "work_shift"])
        self.assertEqual(driver.AT_SOURCE, {"eat": ("site", "entity")})


if __name__ == "__main__":
    unittest.main()
