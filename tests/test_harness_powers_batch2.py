"""Second batch of ported god powers (evidence: the god-decree keyword path in runtime/world_runtime.py): bless, calm_area,
panic_area, baby_boom, cull, bounty_area, scarcity_area. Synthetic-world behaviour tests, plus equivalence with the legacy tools
on the real engine for in-range values."""
import hashlib
import sys
import unittest
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from authored_village import load_village_maps  # noqa: E402
from test_startup_preservation import backend  # noqa: E402,F401  (sets the isolated data root and imports map_test)
from test_map_contract import AsyncRegistryIsolation  # noqa: E402
from harness import powers as pw  # noqa: E402
from harness.frame import SpaceFrame  # noqa: E402
from harness.world import FieldSpec, Table, World  # noqa: E402

H_COLS = {"type": 0, "x": 1, "y": 2, "hp": 3, "mood": 4, "threat": 5, "cooldown": 6, "sex": 7, "fertility": 8}
E_COLS = {"type": 0, "x": 1, "y": 2, "food": 3, "water": 4, "fertility": 5}
RESOURCE = {"natural_types": [1, 2], "other_types": [22], "max_food": 100.0, "max_water": 100.0, "max_fertility": 100.0}


def make_world():
    humans = Table("humans", torch.zeros((16, 9)), H_COLS, type_col="type", pos_cols=("x", "y"), id_prefix="h",
                   field_specs={"hp": FieldSpec(0.0, 100.0), "type": FieldSpec(0, 8, integer=True, mode="reject")})
    entities = Table("entities", torch.zeros((16, 6)), E_COLS, type_col="type", pos_cols=("x", "y"), id_prefix="e")
    world = World(7, [humans, entities], frame=SpaceFrame(bounds=(0.0, 0.0, 200.0, 100.0)))
    world.config["resource_model"] = dict(RESOURCE)
    return world


def add_humans(world, rows):
    return [world.add_row("humans", **row) for row in rows]


def digest(world):
    return hashlib.sha256(b"".join(t.tensor.numpy().tobytes() for t in world.tables.values())).hexdigest()


def get(world, table, ident, field):
    return world.table(table).get(ident, field)


class BlessTests(unittest.TestCase):
    def test_full_heal_mood_90_and_cooldown_cleared_for_everyone_by_default(self):
        w = make_world()
        a, b = add_humans(w, [dict(x=1, y=1, hp=30, mood=10, cooldown=5), dict(x=2, y=2, hp=-5, mood=100, cooldown=2)])
        result = pw.call(w, "bless", {})
        self.assertTrue(result.ok, result.reason)
        self.assertEqual([(get(w, "humans", i, "hp"), get(w, "humans", i, "mood"), get(w, "humans", i, "cooldown")) for i in (a, b)],
                         [(100.0, 90.0, 0.0), (95.0, 90.0, 0.0)])               # -5 + 100 = 95, as the legacy clamp(hp + 100, max=100)
        self.assertEqual(w.events.get(result.event_ids[0]).type, "blessing")

    def test_selector_limits_the_targets_and_dry_run_changes_nothing(self):
        w = make_world()
        a, b = add_humans(w, [dict(x=1, y=1, hp=30, mood=10), dict(x=2, y=2, hp=30, mood=10)])
        before = digest(w)
        self.assertTrue(pw.call(w, "bless", {"targets": {"of": "humans", "ids": [a]}}, dry_run=True).ok)
        self.assertEqual(digest(w), before)
        pw.call(w, "bless", {"targets": {"of": "humans", "ids": [a]}})
        self.assertEqual((get(w, "humans", a, "hp"), get(w, "humans", b, "hp")), (100.0, 30.0))


class AreaTests(unittest.TestCase):
    def setUp(self):
        self.w = make_world()
        self.a, self.b, self.far = add_humans(self.w, [dict(x=100, y=50, hp=80, mood=95, threat=10),
                                                       dict(x=130, y=50, hp=80, mood=40, threat=90),
                                                       dict(x=180, y=50, hp=80, mood=40, threat=90)])

    def test_calm_area_clamps_and_uses_a_strict_radius(self):
        pw.call(self.w, "calm_area", {"center": [100, 50], "radius": 30})              # b is at exactly 30: excluded (legacy '<')
        self.assertEqual((get(self.w, "humans", self.a, "mood"), get(self.w, "humans", self.a, "threat")), (100.0, 0.0))
        self.assertEqual((get(self.w, "humans", self.b, "mood"), get(self.w, "humans", self.b, "threat")), (40.0, 90.0))
        pw.call(self.w, "calm_area", {"center": [100, 50], "radius": 31})
        self.assertEqual((get(self.w, "humans", self.b, "mood"), get(self.w, "humans", self.b, "threat")), (60.0, 65.0))
        self.assertEqual(get(self.w, "humans", self.far, "mood"), 40.0)

    def test_panic_area_raises_threat_to_at_most_100_lowers_mood_to_at_least_0_and_pushes_away(self):
        pw.call(self.w, "panic_area", {"center": [100, 50], "radius": 50, "mood_drop": 60})
        self.assertEqual((get(self.w, "humans", self.b, "threat"), get(self.w, "humans", self.b, "mood")), (100.0, 0.0))
        self.assertEqual(get(self.w, "humans", self.b, "x"), 133.0)                    # pushed 3 units away from the centre
        self.assertEqual(get(self.w, "humans", self.far, "x"), 180.0)
        self.assertEqual((get(self.w, "humans", self.a, "x"), get(self.w, "humans", self.a, "y")), (100.0, 50.0))   # a resident exactly at the centre has a zero direction: it does not move

    def test_panic_push_is_clamped_to_the_frame_bounds(self):
        edge, = add_humans(self.w, [dict(x=199, y=99, hp=10)])
        pw.call(self.w, "panic_area", {"center": [195, 95], "radius": 20})
        self.assertLessEqual(get(self.w, "humans", edge, "x"), 200.0)
        self.assertLessEqual(get(self.w, "humans", edge, "y"), 100.0)

    def test_refusals(self):
        before = digest(self.w)
        cases = {"no_targets": {"center": [0, 0], "radius": 1}, "invalid_center": {"center": [1]},
                 "invalid_amount": {"center": [100, 50], "radius": -1}}
        for reason, args in cases.items():
            self.assertEqual(pw.call(self.w, "calm_area", args).reason, reason, reason)
        self.assertEqual(pw.call(self.w, "calm_area", {"center": [100, 50], "mood_gain": -3}).reason, "invalid_amount")
        self.assertEqual(pw.call(self.w, "calm_area", {"radius": 5}).reason, "invalid_arguments")
        self.assertEqual(digest(self.w), before)


class BabyBoomTests(unittest.TestCase):
    def test_only_females_get_fertility_and_cooldown_everyone_gets_mood(self):
        w = make_world()
        f, m = add_humans(w, [dict(x=1, y=1, sex=1, fertility=1.8, cooldown=4, mood=10), dict(x=2, y=2, sex=0, fertility=1.0, cooldown=4, mood=10)])
        self.assertTrue(pw.call(w, "baby_boom", {}).ok)
        self.assertEqual([get(w, "humans", f, c) for c in ("fertility", "cooldown", "mood")], [2.0, 0.0, 90.0])   # capped at 2
        self.assertEqual([get(w, "humans", m, c) for c in ("fertility", "cooldown", "mood")], [1.0, 4.0, 90.0])


class CullTests(unittest.TestCase):
    def test_weakest_first_lowest_slot_on_ties_until_the_target_is_met(self):
        w = make_world()
        ids = add_humans(w, [dict(x=i, y=1, hp=hp) for i, hp in enumerate([50, 20, 20, 90, 10])])
        result = pw.call(w, "cull", {"target_population": 2})
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(sorted(result.plan.targets), sorted([ids[4], ids[1], ids[2]]))
        self.assertEqual(sorted(w.table("humans").live_slots()), [0, 3])
        self.assertEqual(w.events.get(result.event_ids[0]).type, "cull")

    def test_nothing_to_cull_and_bad_target_are_refusals_and_cull_is_destructive(self):
        w = make_world()
        add_humans(w, [dict(x=1, y=1, hp=10)])
        self.assertEqual(pw.call(w, "cull", {"target_population": 5}).reason, "no_targets")
        self.assertEqual(pw.call(w, "cull", {"target_population": -1}).reason, "invalid_amount")
        risks = {p["id"]: p["risk"] for p in pw.REGISTRY.manifest()["powers"]}
        self.assertEqual((risks["cull"], risks["panic_area"], risks["scarcity_area"], risks["bless"]),
                         ("destructive", "destructive", "destructive", "reversible"))


class ResourceTests(unittest.TestCase):
    def setUp(self):
        self.w = make_world()
        self.tree = self.w.add_row("entities", x=50, y=50, type=1, food=90, water=10, fertility=95)
        self.farm = self.w.add_row("entities", x=55, y=50, type=22, food=5, water=5, fertility=50)
        self.rock = self.w.add_row("entities", x=52, y=50, type=9, food=5, water=5, fertility=50)
        self.far = self.w.add_row("entities", x=150, y=50, type=1, food=5, water=5, fertility=5)

    def values(self, ident):
        return tuple(get(self.w, "entities", ident, c) for c in ("food", "water", "fertility"))

    def test_bounty_adds_and_caps_only_for_natural_and_listed_entities(self):
        pw.call(self.w, "bounty_area", {"center": [50, 50], "radius": 20})
        self.assertEqual(self.values(self.tree), (100.0, 30.0, 100.0))
        self.assertEqual(self.values(self.farm), (25.0, 25.0, 50.0))               # farms get food/water, not fertility
        self.assertEqual(self.values(self.rock), (5.0, 5.0, 50.0))                 # type 9 is not listed here
        self.assertEqual(self.values(self.far), (5.0, 5.0, 5.0))

    def test_scarcity_subtracts_and_floors_at_zero(self):
        pw.call(self.w, "scarcity_area", {"center": [50, 50], "radius": 20, "food_loss": 50, "fertility_loss": 99})
        self.assertEqual(self.values(self.tree), (40.0, 0.0, 0.0))
        self.assertEqual(self.values(self.farm), (0.0, 0.0, 50.0))

    def test_a_world_without_a_resource_model_refuses(self):
        self.w.config.clear()
        self.assertEqual(pw.call(self.w, "bounty_area", {"center": [50, 50]}).reason, "no_resource_model")

    def test_nothing_in_range_is_a_refusal_that_changes_nothing(self):
        before = digest(self.w)
        self.assertEqual(pw.call(self.w, "scarcity_area", {"center": [120, 10], "radius": 5}).reason, "no_targets")
        self.assertEqual(digest(self.w), before)


class EnlightenTests(unittest.TestCase):
    """Eighth power (evidence: runtime/execution_validation.py:294 lists tool_enlighten with the other instinct-bit tools)."""

    def world(self):
        cols = {"type": 0, "x": 1, "y": 2, "hp": 3, "acquired_instinct_mask": 4, "acquired_instinct_mask_1": 5, "acquired_instinct_mask_2": 6}
        humans = Table("humans", torch.zeros((8, 7)), cols, type_col="type", pos_cols=("x", "y"), id_prefix="h",
                       field_specs={"type": FieldSpec(0, 8, integer=True, mode="reject")})
        w = World(7, [humans])
        ids = [w.add_row("humans", x=i, y=0, hp=10) for i in range(3)]
        return w, ids

    def bits(self, w, ident):
        from harness import instinct_bits as ib
        t = w.table("humans")
        mask = int(t.get(ident, "acquired_instinct_mask")) | (int(t.get(ident, "acquired_instinct_mask_1")) << 24)             | (int(t.get(ident, "acquired_instinct_mask_2")) << 48)
        return ib.bits_of(mask)

    def test_every_boundary_bit_is_granted_to_the_right_word_without_disturbing_the_others(self):
        w, ids = self.world()
        for bit in (0, 23, 24, 47, 48, 63):
            result = pw.call(w, "enlighten", {"bit": bit, "targets": {"of": "humans", "ids": [ids[0]]}})
            self.assertTrue(result.ok, (bit, result.reason))
        self.assertEqual(self.bits(w, ids[0]), [0, 23, 24, 47, 48, 63])
        self.assertEqual(self.bits(w, ids[1]), [])
        self.assertEqual(w.table("humans").get(ids[0], "acquired_instinct_mask_2"), float((1 << 0) | (1 << 15)))

    def test_default_targets_everyone_it_is_idempotent_and_refusals_are_stable(self):
        w, ids = self.world()
        pw.call(w, "enlighten", {"bit": 30})
        pw.call(w, "enlighten", {"bit": 30})
        self.assertEqual([self.bits(w, i) for i in ids], [[30]] * 3)
        for bad in (-1, 64, 3.5):
            self.assertIn(pw.call(w, "enlighten", {"bit": bad}).reason, ("invalid_bit", "invalid_arguments"), bad)
        self.assertEqual(pw.call(w, "enlighten", {}).reason, "invalid_arguments")
        self.assertEqual(pw.call(w, "enlighten", {"bit": 5}, dry_run=True).ok, True)
        self.assertEqual(self.bits(w, ids[0]), [30])

    def test_a_world_without_the_word_columns_refuses_high_bits_only(self):
        w = make_world()
        add_humans(w, [dict(x=1, y=1, hp=5)])
        self.assertEqual(pw.call(w, "enlighten", {"bit": 40}).reason, "no_mask_column")


class EngineEquivalenceTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    """On the real engine every new power matches its legacy tool, bit for bit, for in-range values."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        from harness.adapter import EngineWorld
        self.engine = backend.engine
        for _ in range(3):
            self.engine.step()
        self.world = EngineWorld(self.engine, seed=1008)
        import genesis_config as cfg
        self.cfg = cfg
        h = self.engine.state.h_tensor
        live = (h[:, cfg.TYPE] > 0).nonzero().flatten().tolist()
        self.centre = (float(h[live[0], cfg.X]), float(h[live[0], cfg.Y]))
        self.live = live

    def legacy_ctx(self, h):
        return {"h_mask": h[:, self.cfg.TYPE] > 0}

    def assert_same(self, legacy, actual, what):
        self.assertTrue(torch.equal(legacy, actual) or torch.allclose(legacy, actual, atol=1e-5), what)

    def test_bless(self):
        import instincts_and_tools as iat
        legacy = self.engine.state.h_tensor.clone()
        iat.tool_bless(self.legacy_ctx(legacy), legacy)
        self.assertTrue(pw.call(self.world, "bless", {}).ok)
        self.assert_same(legacy, self.engine.state.h_tensor, "bless")

    def test_calm_and_panic_area(self):
        import instincts_and_tools as iat
        for name, tool, extra in (("calm_area", iat.tool_calm_area, {}), ("panic_area", iat.tool_panic_area, {})):
            legacy = self.engine.state.h_tensor.clone()
            tool(self.legacy_ctx(legacy), legacy, center_x=self.centre[0], center_y=self.centre[1], radius=150.0, device="cpu")
            result = pw.call(self.world, name, {"center": list(self.centre), "radius": 150.0})
            self.assertTrue(result.ok, result.reason)
            self.assertGreaterEqual(len(result.plan.targets), 1)
            self.assert_same(legacy, self.engine.state.h_tensor, name)

    def test_baby_boom(self):
        import instincts_and_tools as iat
        legacy = self.engine.state.h_tensor.clone()
        iat.tool_baby_boom(self.legacy_ctx(legacy), legacy, [self.engine.pop_count])
        self.assertTrue(pw.call(self.world, "baby_boom", {}).ok)
        self.assert_same(legacy, self.engine.state.h_tensor, "baby_boom")

    def test_cull_matches_rows_and_keeps_the_engine_population_counter_in_step(self):
        import instincts_and_tools as iat
        legacy = self.engine.state.h_tensor.clone()
        pop = [self.engine.pop_count]
        target = pop[0] - 3
        iat.tool_cull(self.legacy_ctx(legacy), legacy, pop, target)
        result = pw.call(self.world, "cull", {"target_population": target})
        self.assertTrue(result.ok, result.reason)
        self.assert_same(legacy, self.engine.state.h_tensor, "cull")
        self.assertEqual((self.engine.pop_count, pop[0]), (target, target))

    def test_bounty_and_scarcity_area(self):
        import instincts_and_tools as iat
        m = self.engine.state.m_tensor
        # D-005 froze the legacy frontier, which used to put natural entities into this village: the test brings its own carriers
        free = (m[:, self.cfg.M_TYPE] == 0).nonzero(as_tuple=False).flatten().tolist()[:4]
        for i, (slot, kind) in enumerate(zip(free, (self.cfg.M_GRASS, self.cfg.M_FARM, self.cfg.M_WELL, self.cfg.M_RESOURCE_NODE))):
            m[slot] = 0.0
            m[slot, self.cfg.M_TYPE], m[slot, self.cfg.CX], m[slot, self.cfg.CY], m[slot, self.cfg.SCALE] = float(kind), 100.0 + 20 * i, 100.0, 6.0
            m[slot, self.cfg.M_FERTILITY], m[slot, self.cfg.M_RESOURCE_FOOD], m[slot, self.cfg.M_RESOURCE_WATER] = 40.0, 30.0 + i, 20.0 + i
            self.engine._entity_uid_by_slot[slot] = f"carrier_{i}"
        self.engine._entity_count_ref[0] = max(self.engine._entity_count_ref[0], max(free) + 1)
        carriers = sorted(set(self.cfg.NATURAL_TYPES) | {self.cfg.M_FARM, self.cfg.M_WELL, self.cfg.M_RESOURCE_NODE})
        carrying = torch.isin(m[:, self.cfg.M_TYPE].long(), torch.tensor(carriers))
        self.assertTrue(bool(carrying.any()), "the starter village has no food/water carrying entity")
        first = int(carrying.nonzero()[0])
        cx, cy = float(m[first, self.cfg.CX]), float(m[first, self.cfg.CY])
        for name, tool in (("bounty_area", iat.tool_bounty_area), ("scarcity_area", iat.tool_scarcity_area)):
            legacy = self.engine.state.m_tensor.clone()
            tool({}, legacy, center_x=cx, center_y=cy, radius=120.0)
            result = pw.call(self.world, name, {"center": [cx, cy], "radius": 120.0})
            self.assertTrue(result.ok, result.reason)
            self.assert_same(legacy, self.engine.state.m_tensor, name)

    def test_enlighten_matches_the_legacy_tool_for_low_bits_and_is_exact_for_high_ones(self):
        import instincts_and_tools as iat
        from harness import instinct_bits as ib
        legacy = self.engine.state.h_tensor.clone()
        iat.tool_enlighten(self.legacy_ctx(legacy), legacy, 7)
        self.assertTrue(pw.call(self.world, "enlighten", {"bit": 7}).ok)
        self.assert_same(legacy, self.engine.state.h_tensor, "enlighten low bit")
        legacy = self.engine.state.h_tensor.clone()
        iat.tool_enlighten(self.legacy_ctx(legacy), legacy, 55)
        self.assertTrue(pw.call(self.world, "enlighten", {"bit": 55}).ok)
        self.assert_same(legacy, self.engine.state.h_tensor, "enlighten high bit")
        rows = (self.engine.state.h_tensor[:, self.cfg.TYPE] > 0).nonzero().flatten().tolist()
        self.assertTrue(all(ib.bits_of(int(ib.read_mask(self.engine.state.h_tensor, r))) == [7, 55] for r in rows))

    def test_the_engine_keeps_running_after_the_powers(self):
        pw.call(self.world, "bless", {})
        pw.call(self.world, "baby_boom", {})
        for _ in range(5):
            self.engine.step()


if __name__ == "__main__":
    unittest.main()
