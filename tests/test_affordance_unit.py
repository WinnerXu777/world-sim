"""Affordance engine on synthetic worlds (no legacy engine): legality, reasons, reachability with detours, perception bounds, the mask,
and the commission rule branches. The real-engine parity test is ``test_affordance_engine.py``."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from harness.items import DictItemStore  # noqa: E402
from harness.world import World  # noqa: E402
from systems.affordance import (AffordanceEngine, Anchor, EntityFact, Reach, StaticServices, VERBS, commission, config)  # noqa: E402
from systems.affordance.engine import MACRO_VERBS  # noqa: E402
from systems.decision.matrix import ACTION_INDEX, MENU  # noqa: E402


def box(name, x0, y0, x1, y1):
    return {"id": name, "min": [x0, y0], "max": [x1, y1], "height": 2.4}


def contract(*boxes, bounds=(0.0, 0.0, 300.0, 100.0)):
    return {"actor_radius": 2.4, "bounds": list(bounds), "boxes": list(boxes)}


def make(*, capacity=None, services=None, humans=None, **kw):
    world = World.synthetic(seed=1, humans=12, items=DictItemStore(capacity_per_owner=capacity))
    humans = humans or {"h_a": (10, 10), "h_b": (20, 10)}
    for hid, (x, y) in humans.items():
        world.add_row("humans", hid, x=x, y=y, hp=100, hunger=0, stamina=100, mood=50)
    services = services or StaticServices(**kw)
    return world, services, AffordanceEngine(world, services)


def verbs_of(options):
    return sorted({o.verb for o in options})


class LegalityTests(unittest.TestCase):
    def test_eat_from_pack_needs_hunger_and_an_edible(self):
        world, services, engine = make(inventories={"h_a": {"rations": 2}})
        self.assertEqual(engine.legal("h_a", "eat", {"item": "rations"}).reason, "not_needed")     # hunger 0
        world.table("humans").tensor[world.table("humans").slot_of("h_a"), world.table("humans").col("hunger")] = 60.0
        self.assertTrue(engine.legal("h_a", "eat", {}).ok)
        self.assertEqual(engine.legal("h_a", "eat", {}).detail["item"], "rations")
        self.assertEqual(engine.legal("h_a", "eat", {"item": "iron_ingot"}).reason, "invalid_params")      # not an edible kind
        self.assertEqual(engine.legal("h_a", "eat", {"item": "fish_catch"}).reason, "no_item")             # edible but not held
        self.assertEqual({"item": "rations"}, engine.options("h_a", verbs=("eat",))[0].params)

    def test_no_food_anywhere_is_refused_with_no_edible(self):
        world, services, engine = make()
        world.table("humans").tensor[world.table("humans").slot_of("h_a"), world.table("humans").col("hunger")] = 80.0
        self.assertEqual(engine.legal("h_a", "eat", {}).reason, "no_edible")
        self.assertEqual(engine.options("h_a", verbs=("eat",)), [])

    def test_food_site_is_offered_when_reachable_and_not_when_walled_in(self):
        site = Anchor("village:use_campfire", "food", 200.0, 10.0)
        world, services, engine = make(sites={"h_a": {"food": site}})
        h = world.table("humans")
        h.tensor[h.slot_of("h_a"), h.col("hunger")] = 80.0
        verdict = engine.legal("h_a", "eat", {})
        self.assertTrue(verdict.ok)
        self.assertEqual(verdict.detail, {"source": "site", "place": "village:use_campfire"})
        walled = StaticServices(sites={"h_a": {"food": site}}, contract=contract(box("w1", 80, 0, 100, 100)))   # a wall across the whole map
        world2, _, engine2 = make(services=walled)
        h2 = world2.table("humans")
        h2.tensor[h2.slot_of("h_a"), h2.col("hunger")] = 80.0
        self.assertEqual(engine2.legal("h_a", "eat", {}).reason, "unreachable")

    def test_dead_resident_has_no_options_and_an_empty_mask_row(self):
        world, services, engine = make(inventories={"h_a": {"rations": 2}}, anchors={"h_a": {"sleep": Anchor("bed", "sleep", 12, 10)}})
        h = world.table("humans")
        h.tensor[h.slot_of("h_a"), h.col("hp")] = 0.0
        self.assertEqual(engine.options("h_a"), [])
        for name in VERBS:
            self.assertEqual(engine.legal("h_a", name, {}).reason, "dead", name)
        self.assertEqual(engine.legal("h_a", "eat", {}).reason, "dead")
        self.assertFalse(bool(engine.mask(["h_a"]).any()))

    def test_unknown_verb_extra_and_malformed_arguments(self):
        world, services, engine = make(inventories={"h_a": {"rations": 2}})
        self.assertEqual(engine.legal("h_a", "teleport", {}).reason, "unknown_verb")
        self.assertEqual(engine.legal("h_a", "give_item", {"target": "h_b", "item": "rations", "qty": 1, "bogus": 1}).reason, "invalid_params")
        for bad in (0, -1, True, 1.5, "2"):
            self.assertEqual(engine.legal("h_a", "give_item", {"target": "h_b", "item": "rations", "qty": bad}).reason, "invalid_params", bad)
        self.assertEqual(engine.legal("h_a", "give_item", {"target": 7, "item": "rations"}).reason, "invalid_params")
        self.assertEqual(engine.legal("h_a", "give_item", {"item": "rations"}).reason, "invalid_params")     # target missing

    def test_give_item_rules(self):
        world, services, engine = make(capacity=2, inventories={"h_a": {"rations": 2}, "h_b": {"stone_chunk": 2}})
        world.items.add("h_a", "rations", 2)
        world.items.add("h_b", "stone_chunk", 2)                                    # recipient pack is full (capacity 2)
        full = engine.legal("h_a", "give_item", {"target": "h_b", "item": "rations", "qty": 1})
        self.assertEqual((full.ok, full.reason), (False, "no_room"))
        self.assertEqual(engine.legal("h_a", "give_item", {"target": "h_a", "item": "rations"}).reason, "self_target")
        self.assertEqual(engine.legal("h_a", "give_item", {"target": "h_zzz", "item": "rations"}).reason, "no_target")
        self.assertEqual(engine.legal("h_a", "give_item", {"target": "h_b", "item": "rations", "qty": 3}).reason, "no_item")
        world2, services2, engine2 = make(inventories={"h_a": {"rations": 2}})
        ok = engine2.legal("h_a", "give_item", {"target": "h_b", "item": "rations", "qty": 2})
        self.assertTrue(ok.ok)
        self.assertAlmostEqual(ok.distance, 10.0)

    def test_range_wall_and_target_state(self):
        world, services, engine = make(humans={"h_a": (10, 10), "h_b": (40, 10), "h_c": (14, 10)}, inventories={"h_a": {"rations": 1}},
                                       contract=contract(box("wall", 11.5, 0, 12.5, 100)))
        self.assertEqual(engine.legal("h_a", "give_item", {"target": "h_b", "item": "rations"}).reason, "out_of_range")   # 30 > 16
        self.assertEqual(engine.legal("h_a", "give_item", {"target": "h_c", "item": "rations"}).reason, "blocked")        # in range, wall between
        h = world.table("humans")
        h.tensor[h.slot_of("h_b"), h.col("hp")] = 0.0
        self.assertEqual(engine.legal("h_a", "chat", {"target": "h_b"}).reason, "target_dead")

    def test_perception_is_bounded(self):
        world, services, engine = make(humans={"h_a": (10, 10), "h_near": (40, 10), "h_far": (290, 10)}, inventories={"h_a": {"rations": 1}})
        talk = {o.params["target"] for o in engine.options("h_a", verbs=("chat",))}
        self.assertEqual(talk, {"h_near"})
        self.assertEqual(engine.legal("h_a", "chat", {"target": "h_far"}).reason, "no_target")   # exists, not perceived: rejected
        self.assertEqual(engine.situation("h_a").obs.neighbours[0].id, "h_near")

    def test_crafting_reasons_and_station(self):
        forge = EntityFact("smith:forge", "forge", 30.0, 10.0, True, 16.0)
        records = {"h_a": {"occupation": {"kind": "smith"}}}
        inv = {"iron_ingot": 2, "wood_bundle": 1, "hammer": 1}
        world, services, engine = make(records=records, inventories={"h_a": dict(inv)}, entities=[forge])
        self.assertEqual(engine.legal("h_a", "craft", {"recipe": "sword"}).reason, "no_station")          # 20 units from the forge, radius 16
        world.table("humans").tensor[world.table("humans").slot_of("h_a"), world.table("humans").col("x")] = 25.0
        self.assertTrue(engine.legal("h_a", "craft", {"recipe": "sword"}).ok)
        self.assertEqual(engine.legal("h_a", "craft", {"recipe": "nonsense"}).reason, "no_recipe")
        self.assertEqual(engine.legal("h_a", "craft", {"recipe": "club"}).reason, "wrong_occupation")
        self.assertEqual(engine.legal("h_a", "craft", {"recipe": "sword", "qty": 2}).reason, "missing_ingredients")
        no_iron = make(records=records, inventories={"h_a": {"wood_bundle": 1, "hammer": 1}}, entities=[forge])
        no_iron[0].table("humans").tensor[0, no_iron[0].table("humans").col("x")] = 25.0
        verdict = no_iron[2].legal("h_a", "craft", {"recipe": "sword"})
        self.assertEqual((verdict.reason, verdict.detail["missing"][0]["item"]), ("missing_ingredients", "iron_ingot"))
        no_hammer = make(records=records, inventories={"h_a": {"iron_ingot": 2, "wood_bundle": 1}}, entities=[forge])
        no_hammer[0].table("humans").tensor[0, no_hammer[0].table("humans").col("x")] = 25.0
        self.assertEqual(no_hammer[2].legal("h_a", "craft", {"recipe": "sword"}).reason, "missing_tool")
        broken = EntityFact("smith:forge", "forge", 30.0, 10.0, False, 16.0, 0.0)
        wrecked = make(records=records, inventories={"h_a": dict(inv)}, entities=[broken])
        wrecked[0].table("humans").tensor[0, wrecked[0].table("humans").col("x")] = 25.0
        self.assertEqual(wrecked[2].legal("h_a", "craft", {"recipe": "sword"}).reason, "no_station")

    def test_craft_output_room(self):
        forge = EntityFact("smith:forge", "forge", 12.0, 10.0, True, 16.0)
        world, services, engine = make(capacity=3, records={"h_a": {"occupation": {"kind": "smith"}}}, entities=[forge],
                                       inventories={"h_a": {"iron_ingot": 2, "wood_bundle": 1, "hammer": 1}})
        for kind, q in {"iron_ingot": 2, "wood_bundle": 1}.items():
            world.items.add("h_a", kind, q)
        self.assertEqual(engine.legal("h_a", "craft", {"recipe": "sword"}).reason, "no_room")        # the pack holds 3 of 3

    def test_cognitive_and_stub_verbs(self):
        world, services, engine = make(records={"h_a": {"plans": [], "goals": [], "relationships": {}}})
        self.assertTrue(engine.legal("h_a", "USE_BRAIN").ok)
        self.assertEqual(engine.legal("h_a", "REPLAN").reason, "no_plan")
        self.assertEqual(engine.legal("h_a", "continue_plan_step").reason, "no_plan")
        self.assertEqual(engine.legal("h_a", "PLOT").reason, "no_motive")
        self.assertEqual(engine.legal("h_a", "repair", {"target": "x"}).reason, "system_missing")
        self.assertEqual(engine.legal("h_a", "build_structure").reason, "no_site")
        rich = make(records={"h_a": {"plans": [{"status": "active"}], "goals": [{"kind": "retaliate", "status": "active"}],
                                     "relationships": {}, "construction_needs": [{"x": 1}], "planning_state": {}}})[2]
        for name in ("REPLAN", "continue_plan_step", "PLOT", "build_structure"):
            self.assertTrue(rich.legal("h_a", name).ok, name)


class ReachTests(unittest.TestCase):
    def walled(self, *boxes, **kw):
        return make(services=StaticServices(contract=contract(*boxes), **kw), humans={"h_a": (50, 50), "h_b": (140, 50)})

    def test_detour_through_a_gap_is_reachable_but_straight_line_would_say_blocked(self):
        # a wall across x=100 from y=0 to y=80 leaves a gap at y 80..100
        world, services, engine = self.walled(box("w", 93, 0, 97, 80))
        from systems.movement.spatial import segment_blocked
        self.assertTrue(segment_blocked((50, 50), (150, 50), services.contract()["boxes"]))       # the naive answer: no
        verdict = engine.legal("h_a", "chat", {"target": "h_b"})
        self.assertTrue(verdict.ok, verdict)
        self.assertEqual(verdict.reachability, "exact")
        self.assertGreater(verdict.distance, 100.0)                    # straight is 90; the way round through the gap at y >= 80 is longer
        self.assertEqual(engine.reach.stats["path_searches"], 1)

    def test_walled_in_actor_is_unreachable_exactly_when_the_search_can_finish(self):
        cage = [box("n", 40, 40, 70, 42), box("s", 40, 60, 70, 62), box("w", 40, 40, 42, 62), box("e", 68, 40, 70, 62)]
        world, services, engine = self.walled(*cage)
        verdict = engine.legal("h_a", "chat", {"target": "h_b"})
        self.assertEqual((verdict.ok, verdict.reason, verdict.reachability), (False, "unreachable", "exact"))
        self.assertEqual(engine.options("h_a", verbs=("chat", "follow", "attack")), [])

    def test_a_large_closed_region_exhausts_the_budget_and_is_marked_approx(self):
        world, services, engine = self.walled(box("w", 93, 0, 97, 100))                    # the wall closes the gap: ~7000 nodes to flood
        verdict = engine.legal("h_a", "chat", {"target": "h_b"})
        self.assertEqual((verdict.ok, verdict.reason, verdict.reachability), (False, "unreachable", "approx"))

    def test_search_cap_falls_back_to_the_straight_line_and_says_approx(self):
        world, services, _ = self.walled(box("w", 93, 0, 97, 80))
        engine = AffordanceEngine(world, services, Reach(services, max_expansions=3))
        verdict = engine.legal("h_a", "chat", {"target": "h_b"})
        self.assertEqual((verdict.ok, verdict.reason, verdict.reachability), (False, "unreachable", "approx"))
        self.assertEqual(engine.reach.stats["capped"], 1)

    def test_cache_hits_on_repeat_and_on_the_same_cell(self):
        world, services, engine = self.walled(box("w", 93, 0, 97, 80))
        engine.legal("h_a", "chat", {"target": "h_b"})
        engine.legal("h_a", "chat", {"target": "h_b"})
        self.assertEqual((engine.reach.stats["path_searches"], engine.reach.stats["hits"]), (1, 1))

    def test_entity_inside_its_own_footprint_is_reached_from_outside(self):
        # a well whose footprint box would swallow its centre; the goal snaps to the nearest standable point
        site = EntityFact("well", "well", 100.0, 50.0, True, 16.0)
        world, services, engine = make(services=StaticServices(contract=contract(box("well_wall", 94, 44, 106, 56)),
                                                               entities=[site], sites={"h_a": {}}), humans={"h_a": (50, 50)})
        reach = engine.reach.check((50, 50), (100, 50), goal_entity="well")
        self.assertTrue(reach.ok, reach)

    def test_portal_two_step_route(self):
        # the actor is inside a closed room (x < 40) whose only way out is a portal; the goal is outside
        room = [box("n", 0, 0, 40, 2), box("s", 0, 98, 40, 100), box("w", 0, 0, 2, 100), box("e", 40, 0, 42, 100)]
        portal = {"here": lambda p: p[0] < 40, "from": (20.0, 50.0), "to": (60.0, 50.0)}
        services = StaticServices(contract=contract(*room), portals=[portal])
        world, _, engine = make(services=services, humans={"h_a": (10, 50), "h_b": (90, 50)})
        verdict = engine.legal("h_a", "chat", {"target": "h_b"})
        self.assertTrue(verdict.ok, verdict)
        no_portal = make(services=StaticServices(contract=contract(*room)), humans={"h_a": (10, 50), "h_b": (90, 50)})[2]
        self.assertEqual(no_portal.legal("h_a", "chat", {"target": "h_b"}).reason, "unreachable")


class MaskAndResolveTests(unittest.TestCase):
    def test_mask_shape_and_macro_columns(self):
        world, services, engine = make(inventories={"h_a": {"rations": 1}}, humans={"h_a": (10, 10), "h_b": (20, 10)})
        h = world.table("humans")
        h.tensor[h.slot_of("h_a"), h.col("hunger")] = 70.0
        mask = engine.mask(["h_a", "h_b"])
        self.assertEqual(tuple(mask.shape), (2, len(MENU)))
        self.assertTrue(bool(mask[0, ACTION_INDEX["eat"]]))
        self.assertFalse(bool(mask[1, ACTION_INDEX["eat"]]))                  # no pack, no site, not hungry
        self.assertFalse(bool(mask[0, ACTION_INDEX["repair"]]))              # no repair task: false, not a placeholder
        self.assertTrue(bool(mask[0, ACTION_INDEX["idle"]]))
        self.assertFalse(bool(mask[0, ACTION_INDEX["accept_commission"]]))   # no offered order

    def test_every_macro_verb_is_a_known_verb_and_every_macro_a_menu_entry(self):
        for macro, names in MACRO_VERBS.items():
            self.assertIn(macro, ACTION_INDEX)
            for name in names:
                self.assertIn(name, VERBS, f"{macro} -> {name}")

    def test_resolve_picks_the_nearest_legal_target(self):
        world, services, engine = make(humans={"h_a": (10, 10), "h_far": (80, 10), "h_close": (30, 10)})
        call = engine.resolve("socialise", "h_a")
        self.assertEqual((call.verb, call.params["target"], call.macro), ("chat", "h_close", "socialise"))
        self.assertIsNone(engine.resolve("repair", "h_a"))
        self.assertEqual(engine.resolve("idle", "h_a").verb, "idle")

    def test_help_needs_a_neighbour_in_need(self):
        world, services, engine = make(inventories={"h_a": {"rations": 1}}, humans={"h_a": (10, 10), "h_b": (18, 10)})
        h = world.table("humans")
        self.assertFalse(bool(engine.mask(["h_a"])[0, ACTION_INDEX["help"]]))
        h.tensor[h.slot_of("h_b"), h.col("hunger")] = 80.0
        self.assertTrue(bool(engine.mask(["h_a"])[0, ACTION_INDEX["help"]]))
        self.assertEqual(engine.resolve("help", "h_a").verb, "give_item")


class CommissionRuleTests(unittest.TestCase):
    CONFIG = {"prices": {"sword": 30}, "capacity_open_orders": 2, "distrust_closeness": -0.2}

    def setup(self, *, iron=2, wood=1, coin=100, forge_alive=True, orders=(), closeness=0.0, rival=False, occupation="smith", smith_hp=100):
        relation = {"closeness": closeness, "tags": ["rival"] if rival else []}
        forge = EntityFact("smith:forge", "forge", 30.0, 10.0, forge_alive, 16.0)
        services = StaticServices(records={"h_a": {"occupation": {"kind": occupation}, "relationships": {"h_b": relation}}},
                                  inventories={"h_a": {"iron_ingot": iron, "wood_bundle": wood, "hammer": 1}, "h_b": {"coin": coin}},
                                  entities=[forge], anchors={"h_a": {"work": Anchor("w", "work", 28, 10)}}, orders={"h_a": list(orders)},
                                  config=self.CONFIG)
        world, _, engine = make(services=services)
        world.table("humans").tensor[world.table("humans").slot_of("h_a"), world.table("humans").col("hp")] = smith_hp
        return engine

    def test_every_branch(self):
        cases = {
            "all fine": ({}, ["accept_commission"]),
            "no iron": ({"iron": 0}, ["refuse_no_materials"]),
            "short of wood": ({"wood": 0}, ["refuse_no_materials"]),
            "wrong trade": ({"occupation": "baker"}, ["refuse_no_materials"]),
            "no forge": ({"forge_alive": False}, ["refuse_no_forge"]),
            "customer too poor": ({"coin": 10}, ["refuse_cannot_afford"]),
            "busy": ({"orders": [{"order_id": "o1"}, {"order_id": "o2"}]}, ["refuse_busy"]),
            "distrust alongside accept": ({"closeness": -0.5}, ["accept_commission", "refuse_distrust"]),
            "rival": ({"rival": True}, ["accept_commission", "refuse_distrust"]),
            "several reasons, in Stage 1 order": ({"iron": 0, "forge_alive": False, "coin": 0}, ["refuse_no_forge", "refuse_no_materials", "refuse_cannot_afford"]),
            "dead smith": ({"smith_hp": 0}, ["refuse_busy"]),
        }
        for name, (kwargs, expected) in cases.items():
            self.assertEqual(self.setup(**kwargs).commission_options("h_a", "h_b", "sword"), expected, name)

    def test_excluding_the_order_being_decided(self):
        engine = self.setup(orders=[{"order_id": "o1"}, {"order_id": "o2"}])
        self.assertEqual(engine.commission_options("h_a", "h_b", "sword", exclude_order="o2"), ["accept_commission"])

    def test_outcomes_follow_the_oldest_offered_order_and_feed_the_mask(self):
        offered = [{"order_id": "o7", "state": "offered", "customer_id": "h_b", "recipe_id": "sword"},
                   {"order_id": "o3", "state": "offered", "customer_id": "h_b", "recipe_id": "sword"},
                   {"order_id": "o1", "state": "working", "customer_id": "h_b", "recipe_id": "sword"}]
        engine = self.setup(orders=offered)
        # the oldest offered order is o3; the two others (o7 offered, o1 working) already fill the capacity of 2
        self.assertEqual(engine.commission_outcomes("h_a"), ["refuse_busy"])
        mask = engine.mask(["h_a"])
        self.assertEqual([bool(mask[0, ACTION_INDEX[n]]) for n in ("accept_commission", "refuse_busy")], [False, True])

    def test_no_offered_order_means_no_commission_columns(self):
        engine = self.setup()
        self.assertEqual(engine.commission_outcomes("h_a"), [])


class DriftTests(unittest.TestCase):
    def test_constants_mirror_the_stage_one_sources(self):
        from systems.commission.access import DEFAULT_INTERACT_RADIUS
        from systems.commission.engine import AT_WORK_TOLERANCE
        from systems.inventory.schema import DEFAULT_CURRENCY_KIND
        from systems.tasks.families.survival import EDIBLE_ITEM_KINDS
        import genesis_config as cfg
        self.assertEqual(config.RADIUS["interact"], DEFAULT_INTERACT_RADIUS)
        self.assertEqual(config.AT_WORK_TOLERANCE, AT_WORK_TOLERANCE)
        self.assertEqual(commission.CURRENCY, DEFAULT_CURRENCY_KIND)
        self.assertEqual(config.EDIBLE_ITEMS, tuple(EDIBLE_ITEM_KINDS))
        self.assertEqual(config.THREAT_BLOCKS_SLEEP, float(cfg.SHELTER_SEEK_THREAT))


if __name__ == "__main__":
    unittest.main()
