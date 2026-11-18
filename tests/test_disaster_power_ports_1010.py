"""Unit test suite for the eight P1 disaster god power ports (1008expandtools_instincts.md 2.C1).

Covers all 8 powers:
- wildfire
- earthquake
- storm
- volcanic_eruption
- drought
- flood
- area_attack
- smite

Tests verify:
1. Registration under EDEN_GOD_POWER_PORTS=1, default-off registry unchanged (10 original powers).
2. Pure dry-run (plan() and call(dry_run=True)): global RNG, world revision, events, geometry, tensors untouched.
3. Actual atomic apply and witnessed events.
4. Parameter validation and refusals (finite/bool/int/selector/missing column/no targets).
5. Parity with production legacy oracle functions on real-layout fixtures.
6. Space isolation under multi-space configurations.
7. Stale plan detection, automatic replanning, and slot recycling safety.
8. FieldSpec reject atomic rollback (no partial changes, no event).
9. Deterministic world-keyed randomness parity.
"""
from __future__ import annotations

import hashlib
import math
import os
import random
import sys
import unittest
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

import genesis_config as cfg  # noqa: E402
import map_geo  # noqa: E402
from harness import adapter  # noqa: E402
from harness import effects as fx  # noqa: E402
from harness import spaces as harness_spaces  # noqa: E402
from harness import powers as pw  # noqa: E402
from harness import target_selectors as sel  # noqa: E402
from harness.world import FieldSpec, Table, World  # noqa: E402
from instincts_and_tools import instinct_flee, tool_drought, tool_smite  # noqa: E402
from systems.movement.map_contract import MAP_CONTRACTS, clear_map_contracts, register_map_file  # noqa: E402
from systems.health.effects import apply_area_attack_effect, kill_humans  # noqa: E402
from systems.nature.disasters import (  # noqa: E402
    apply_earthquake as nature_apply_earthquake,
    apply_flood as nature_apply_flood,
    apply_storm as nature_apply_storm,
    apply_volcanic_eruption as nature_apply_volcanic_eruption,
    ignite_wildfire as nature_ignite_wildfire,
)

MAP_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "maps"

H_COLS = {
    "type": 0, "x": 1, "y": 2, "hp": 3, "mood": 4, "threat": 5,
    "shelter": 6, "space": 7, "cooldown": 8, "strength": 9,
}
E_COLS = {
    "type": 0, "x": 1, "y": 2, "hp": 3, "food": 4, "water": 5,
    "fertility": 6, "burning": 7, "flooded": 8, "space": 9, "lava_cooling": 10,
}


def make_disaster_world(num_humans: int = 6, num_entities: int = 12, seed: int = 1010) -> tuple[World, list[str], list[str]]:
    specs_h = {
        "hp": FieldSpec(0.0, 100.0),
        "mood": FieldSpec(0.0, 100.0),
        "threat": FieldSpec(0.0, 100.0),
        "type": FieldSpec(0, 8, integer=True, mode="reject"),
    }
    specs_e = {
        "hp": FieldSpec(0.0, 100.0),
        "food": FieldSpec(0.0, 1000.0),
        "water": FieldSpec(0.0, 1000.0),
        "fertility": FieldSpec(0.0, 100.0),
        "burning": FieldSpec(0.0, 100.0),
        "flooded": FieldSpec(0.0, 1.0),
        "type": FieldSpec(0, 100, integer=True, mode="reject"),
    }
    t_h = Table("humans", torch.zeros((32, 10)), H_COLS, type_col="type", pos_cols=("x", "y"),
                space_col="space", id_prefix="h", field_specs=specs_h, indexed=True)
    t_e = Table("entities", torch.zeros((32, 11)), E_COLS, type_col="type", pos_cols=("x", "y"),
                space_col="space", id_prefix="e", field_specs=specs_e, indexed=True)
    world = World(seed, [t_h, t_e])
    h_ids = []
    for i in range(num_humans):
        hid = world.add_row("humans", x=100.0 + 10.0 * i, y=100.0, hp=100.0, mood=60.0, threat=10.0,
                            shelter=0.0 if i % 2 == 0 else 1.0, space=0.0)
        h_ids.append(hid)
    e_ids = []
    for j in range(num_entities):
        eid = world.add_row("entities", x=100.0 + 15.0 * j, y=100.0, hp=100.0, food=50.0, water=50.0,
                            fertility=40.0, burning=0.0, flooded=0.0, space=0.0)
        e_ids.append(eid)
    return world, h_ids, e_ids


# The engine's real tensor layout: the column maps EngineWorld puts over cfg.HUMAN_TENSOR_COLS / MAP_TENSOR_COLS. The legacy
# oracles index genesis_config columns directly, so parity runs both sides on clones of tensors in this layout.
P_H_COLS = {name: getattr(cfg, const) for name, const in adapter.HUMAN_COLUMNS.items()}
P_E_COLS = {name: getattr(cfg, const) for name, const in adapter.ENTITY_COLUMNS.items()}


def make_production_layout_world(num_humans: int = 2, num_entities: int = 4, seed: int = 1010) -> tuple[World, list[str], list[str]]:
    """The residents and tiles of make_disaster_world (same positions and values), on the production layout."""
    t_h = Table("humans", torch.zeros((32, cfg.HUMAN_TENSOR_COLS)), P_H_COLS, type_col="type", pos_cols=("x", "y"),
                id_prefix="h", field_specs=dict(adapter.HUMAN_SPECS), indexed=True)
    t_e = Table("entities", torch.zeros((32, cfg.MAP_TENSOR_COLS)), P_E_COLS, type_col="type", pos_cols=("x", "y"),
                id_prefix="e", indexed=True)
    world = World(seed, [t_h, t_e])
    h_ids = [world.add_row("humans", x=100.0 + 10.0 * i, y=100.0, hp=100.0, mood=60.0, threat=10.0,
                           shelter=0.0 if i % 2 == 0 else 1.0) for i in range(num_humans)]
    e_ids = [world.add_row("entities", x=100.0 + 15.0 * j, y=100.0, hp=100.0, food=50.0, water=50.0,
                           fertility=40.0, burning=0.0, flooded=0.0) for j in range(num_entities)]
    return world, h_ids, e_ids


def assert_same_tensor(case: unittest.TestCase, harness_tensor: torch.Tensor, legacy_tensor: torch.Tensor) -> None:
    """Every column of every row: whatever either side wrote must agree (float32 tensors; harness amounts are float64)."""
    diff = (harness_tensor - legacy_tensor).abs()
    case.assertTrue(torch.allclose(harness_tensor, legacy_tensor, atol=1e-4),
                    f"harness and legacy differ at (row, col) {(diff > 1e-4).nonzero().tolist()}")


def world_digest(world: World) -> tuple[str, str]:
    dh = hashlib.sha256(world.table("humans").tensor.numpy().tobytes()).hexdigest()
    de = hashlib.sha256(world.table("entities").tensor.numpy().tobytes()).hexdigest()
    return dh, de


class BaseDisasterTestCase(unittest.TestCase):
    def setUp(self):
        self._orig_env = dict(os.environ)
        os.environ["EDEN_GOD_POWER_PORTS"] = "1"
        self.reg = pw.build_registry()
        self._orig_map_geo = dict(getattr(map_geo, "MAP_GEO", {}))
        self._orig_tile_to_entity = dict(getattr(map_geo, "TILE_TO_ENTITY", {}))
        self._orig_geo_version = getattr(map_geo, "geo_version", 0)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._orig_env)
        if hasattr(map_geo, "MAP_GEO"):
            map_geo.MAP_GEO.clear()
            map_geo.MAP_GEO.update(self._orig_map_geo)
        if hasattr(map_geo, "TILE_TO_ENTITY"):
            map_geo.TILE_TO_ENTITY.clear()
            map_geo.TILE_TO_ENTITY.update(self._orig_tile_to_entity)
        if hasattr(map_geo, "geo_version"):
            map_geo.geo_version = self._orig_geo_version


class RegistrationAndFlagTests(unittest.TestCase):
    def test_default_registry_off_names_unchanged(self):
        old_env = os.environ.get("EDEN_GOD_POWER_PORTS")
        try:
            if "EDEN_GOD_POWER_PORTS" in os.environ:
                del os.environ["EDEN_GOD_POWER_PORTS"]
            default_reg = pw.build_registry()
            expected_ten = {
                "set_mood", "plague", "bless", "calm_area", "panic_area",
                "baby_boom", "cull", "enlighten", "bounty_area", "scarcity_area",
            }
            self.assertEqual(set(default_reg.powers.keys()), expected_ten)
        finally:
            if old_env is not None:
                os.environ["EDEN_GOD_POWER_PORTS"] = old_env

    def test_flag_registers_all_eight_disaster_powers(self):
        old_env = os.environ.get("EDEN_GOD_POWER_PORTS")
        try:
            os.environ["EDEN_GOD_POWER_PORTS"] = "1"
            ported_reg = pw.build_registry()
            eight_disasters = {
                "wildfire", "earthquake", "storm", "volcanic_eruption",
                "drought", "flood", "area_attack", "smite",
            }
            for name in eight_disasters:
                self.assertIn(name, ported_reg.powers)
                spec = ported_reg.powers[name]
                self.assertEqual(spec.extra.get("risk"), "destructive")
                self.assertEqual(spec.audience, "god")
                self.assertTrue(spec.doc)
            # Three mind/body ports also preserved
            self.assertIn("set_threat", ported_reg.powers)
            self.assertIn("set_aggression", ported_reg.powers)
            self.assertIn("reset_cooldown", ported_reg.powers)
            self.assertEqual(len(ported_reg.powers), 21)
        finally:
            if old_env is not None:
                os.environ["EDEN_GOD_POWER_PORTS"] = old_env
            else:
                os.environ.pop("EDEN_GOD_POWER_PORTS", None)


class WildfireTests(BaseDisasterTestCase):
    def test_pure_dry_run(self):
        world, _, e_ids = make_disaster_world()
        world.table("entities").tensor[world.table("entities").slot_of(e_ids[0]), E_COLS["type"]] = float(cfg.M_FOREST)
        before = world_digest(world)
        rev = world.revision

        plan = pw.plan(world, "wildfire", {"center": [100.0, 100.0], "radius": 50.0}, registry=self.reg)
        self.assertTrue(plan.ok)
        self.assertEqual(world_digest(world), before)
        self.assertEqual(world.revision, rev)
        self.assertEqual(len(world.events.events()), 0)
        self.assertEqual(plan.targets, (e_ids[0],))
        self.assertEqual(plan.preview["ignited"], 1)

        call_dry = pw.call(world, "wildfire", {"center": [100.0, 100.0], "radius": 50.0}, dry_run=True, registry=self.reg)
        self.assertTrue(call_dry.ok)
        self.assertEqual(world_digest(world), before)

    def test_actual_apply_and_witnessed_event(self):
        world, _, e_ids = make_disaster_world()
        t_e = world.table("entities")
        t_e.tensor[t_e.slot_of(e_ids[0]), E_COLS["type"]] = float(cfg.M_FOREST)
        t_e.tensor[t_e.slot_of(e_ids[1]), E_COLS["type"]] = float(cfg.M_FOREST)
        t_e.tensor[t_e.slot_of(e_ids[2]), E_COLS["type"]] = float(cfg.M_GRASS)

        res = pw.call(world, "wildfire", {"center": [100.0, 100.0], "radius": 30.0}, registry=self.reg)
        self.assertTrue(res.ok)
        self.assertEqual(t_e.get(e_ids[0], "burning"), 1.0)
        self.assertEqual(t_e.get(e_ids[0], "food"), 0.0)
        self.assertEqual(t_e.get(e_ids[1], "burning"), 1.0)
        self.assertEqual(t_e.get(e_ids[1], "food"), 0.0)
        # Non-forest entity untouched
        self.assertEqual(t_e.get(e_ids[2], "burning"), 0.0)
        self.assertEqual(t_e.get(e_ids[2], "food"), 50.0)

        self.assertEqual(len(res.event_ids), 1)
        ev = world.events.get(res.event_ids[0])
        self.assertEqual(ev.type, "wildfire")
        self.assertEqual(ev.visibility, "local")
        self.assertEqual(ev.payload["ignited"], 2)

    def test_oracle_parity(self):
        # Production layout: the legacy function reads M_TYPE and writes M_BURNING / M_RESOURCE_FOOD by cfg index.
        world, _, e_ids = make_production_layout_world(num_entities=4)
        t_e = world.table("entities")
        for eid in e_ids[:3]:
            t_e.tensor[t_e.slot_of(eid), P_E_COLS["type"]] = float(cfg.M_FOREST)
        t_e.tensor[t_e.slot_of(e_ids[3]), P_E_COLS["type"]] = float(cfg.M_FOREST)   # 45 units out: outside radius 40

        legacy_m = t_e.tensor.clone()
        nature_ignite_wildfire(legacy_m, 100.0, 100.0, 40.0, entity_radial_ids_fn=lambda m, cx, cy, r: torch.tensor([0, 1, 2]))

        res = pw.call(world, "wildfire", {"center": [100.0, 100.0], "radius": 40.0}, registry=self.reg)
        self.assertTrue(res.ok)
        self.assertEqual(t_e.get(e_ids[0], "burning"), 1.0)
        self.assertEqual(t_e.get(e_ids[3], "burning"), 0.0)
        assert_same_tensor(self, t_e.tensor, legacy_m)

    def test_refusals(self):
        world, _, _ = make_disaster_world()
        self.assertEqual(pw.call(world, "wildfire", {"center": [100.0, 100.0], "radius": -5.0}, registry=self.reg).reason, "invalid_amount")
        self.assertEqual(pw.call(world, "wildfire", {"center": [100.0, float("nan")], "radius": 10.0}, registry=self.reg).reason, "invalid_center")
        self.assertEqual(pw.call(world, "wildfire", {"center": [100.0], "radius": 10.0}, registry=self.reg).reason, "invalid_center")
        # No forest in area
        self.assertEqual(pw.call(world, "wildfire", {"center": [100.0, 100.0], "radius": 50.0}, registry=self.reg).reason, "no_targets")


class EarthquakeTests(BaseDisasterTestCase):
    def test_pure_dry_run(self):
        world, h_ids, e_ids = make_disaster_world()
        before = world_digest(world)
        rev = world.revision

        plan = pw.plan(world, "earthquake", {"center": [100.0, 100.0], "radius": 50.0}, registry=self.reg)
        self.assertTrue(plan.ok)
        self.assertEqual(world_digest(world), before)
        self.assertEqual(world.revision, rev)
        self.assertEqual(len(world.events.events()), 0)

    def test_controlled_rubble_draws_and_damage(self):
        world, h_ids, e_ids = make_disaster_world()
        t_e = world.table("entities")
        t_h = world.table("humans")
        t_e.tensor[t_e.slot_of(e_ids[0]), E_COLS["type"]] = float(cfg.M_GRASS)
        t_e.tensor[t_e.slot_of(e_ids[1]), E_COLS["type"]] = float(cfg.M_FOREST)

        # Draw 0: 0.1 (< 0.4 -> rubble), Draw 1: 0.9 (>= 0.4 -> no rubble)
        res = pw.call(world, "earthquake", {
            "center": [100.0, 100.0], "radius": 25.0,
            "rubble_draws": [0.1, 0.9],
        }, registry=self.reg)
        self.assertTrue(res.ok)

        # Entity 0 converted to barren, food cleared, hp damaged by 60
        self.assertEqual(t_e.get(e_ids[0], "type"), float(cfg.M_BARREN))
        self.assertEqual(t_e.get(e_ids[0], "food"), 0.0)
        self.assertEqual(t_e.get(e_ids[0], "hp"), 40.0)

        # Entity 1 kept type, hp damaged by 60
        self.assertEqual(t_e.get(e_ids[1], "type"), float(cfg.M_FOREST))
        self.assertEqual(t_e.get(e_ids[1], "hp"), 40.0)

        # Humans in radius: hp damaged by 30, threat=100
        for hid in h_ids[:2]:
            self.assertEqual(t_h.get(hid, "hp"), 70.0)
            self.assertEqual(t_h.get(hid, "threat"), 100.0)
        # Flee is a push away from the centre: h_ids[0] stands exactly on it, so its direction is zero and it stays put (legacy
        # instinct_flee divides by norm.clamp(1e-6) the same way); h_ids[1] at x 110 is pushed outward.
        self.assertEqual(t_h.get(h_ids[0], "x"), 100.0)
        self.assertGreater(t_h.get(h_ids[1], "x"), 110.0)

        ev = world.events.get(res.event_ids[0])
        self.assertEqual(ev.type, "earthquake")
        self.assertEqual(ev.payload["rubble"], 1)

    def test_oracle_parity(self):
        # Production layout; the legacy flee is the one tool_earthquake passes (instinct_flee), so positions are compared too.
        world, h_ids, e_ids = make_production_layout_world(num_humans=2, num_entities=2)
        t_e = world.table("entities")
        t_h = world.table("humans")
        for slot in t_e.live_slots():
            t_e.tensor[slot, P_E_COLS["type"]] = float(cfg.M_GRASS)
        t_h.tensor[t_h.slot_of(h_ids[0]), P_H_COLS["y"]] = 104.0   # off-centre, so both residents are pushed

        legacy_h = t_h.tensor.clone()
        legacy_m = t_e.tensor.clone()

        random.seed(3)   # draws 0.238, 0.544: entity 0 turns to rubble, entity 1 does not
        nature_apply_earthquake(
            {"h_mask": legacy_h[:, cfg.TYPE] > 0},
            legacy_h, legacy_m,
            center_x=100.0, center_y=100.0, radius=50.0,
            entity_radial_ids_fn=lambda m, cx, cy, r: torch.tensor([0, 1]),
            agent_radial_mask_fn=lambda h, m, cx, cy, r, dev: torch.tensor([True, True] + [False] * (legacy_h.shape[0] - 2)),
            flee_fn=instinct_flee,
        )

        random.seed(3)
        draws = [random.random() for _ in range(2)]
        res = pw.call(world, "earthquake", {"center": [100.0, 100.0], "radius": 50.0, "rubble_draws": draws}, registry=self.reg)
        self.assertTrue(res.ok)
        self.assertEqual(res.plan.preview["rubble_entities"], [e_ids[0]])
        assert_same_tensor(self, t_e.tensor, legacy_m)
        assert_same_tensor(self, t_h.tensor, legacy_h)


class StormTests(BaseDisasterTestCase):
    def test_sheltered_vs_unsheltered_damage_and_mood_threat(self):
        world, h_ids, _ = make_disaster_world(num_humans=2)
        t_h = world.table("humans")
        # h_ids[0] has shelter=0.0 (unsheltered), h_ids[1] has shelter=1.0 (sheltered)
        t_h.tensor[t_h.slot_of(h_ids[0]), H_COLS["shelter"]] = 0.0
        t_h.tensor[t_h.slot_of(h_ids[1]), H_COLS["shelter"]] = 1.0

        res = pw.call(world, "storm", {
            "center": [100.0, 100.0], "radius": 50.0,
            "displacement_draws": [[0.5, 0.5], [0.5, 0.5]],  # 0 net displacement
        }, registry=self.reg)
        self.assertTrue(res.ok)

        # Unsheltered takes 8.0 damage; sheltered takes 0 damage
        self.assertEqual(t_h.get(h_ids[0], "hp"), 92.0)
        self.assertEqual(t_h.get(h_ids[1], "hp"), 100.0)

        # Both suffer mood penalty (-25 from 60 -> 35) and threat increase (+30 from 10 -> 40)
        self.assertEqual(t_h.get(h_ids[0], "mood"), 35.0)
        self.assertEqual(t_h.get(h_ids[1], "mood"), 35.0)
        self.assertEqual(t_h.get(h_ids[0], "threat"), 40.0)
        self.assertEqual(t_h.get(h_ids[1], "threat"), 40.0)

    def test_oracle_parity(self):
        # Production layout. Legacy draws its displacement from torch.rand((n, 2)); the harness takes the same draws as
        # displacement_draws, so the two runs see identical randomness and every column can be compared.
        world, h_ids, _ = make_production_layout_world(num_humans=2)
        t_h = world.table("humans")
        self.assertEqual(t_h.get(h_ids[0], "shelter"), 0.0)
        self.assertEqual(t_h.get(h_ids[1], "shelter"), 1.0)

        legacy_h = t_h.tensor.clone()
        torch.manual_seed(1010)
        draws = torch.rand((2, 2)).tolist()
        torch.manual_seed(1010)
        nature_apply_storm(
            {"h_mask": legacy_h[:, cfg.TYPE] > 0},
            legacy_h,
            center_x=100.0, center_y=100.0, radius=50.0,
            agent_radial_mask_fn=lambda h, m, cx, cy, r, dev: torch.tensor([True, True] + [False] * (legacy_h.shape[0] - 2)),
        )

        res = pw.call(world, "storm", {"center": [100.0, 100.0], "radius": 50.0, "displacement_draws": draws}, registry=self.reg)
        self.assertTrue(res.ok)
        self.assertEqual(t_h.get(h_ids[0], "hp"), 92.0)    # unsheltered
        self.assertEqual(t_h.get(h_ids[1], "hp"), 100.0)   # sheltered
        assert_same_tensor(self, t_h.tensor, legacy_h)


class VolcanicEruptionTests(BaseDisasterTestCase):
    def test_inner_and_outer_zones(self):
        world, h_ids, e_ids = make_disaster_world(num_humans=4, num_entities=4)
        t_h = world.table("humans")
        t_e = world.table("entities")

        # Position entities: e[0] at distance 20 (inner), e[1] at distance 100 (outer, forest), e[2] at distance 200 (outside)
        t_e.tensor[t_e.slot_of(e_ids[0]), [E_COLS["x"], E_COLS["y"]]] = torch.tensor([120.0, 100.0])
        t_e.tensor[t_e.slot_of(e_ids[0]), E_COLS["type"]] = float(cfg.M_GRASS)

        t_e.tensor[t_e.slot_of(e_ids[1]), [E_COLS["x"], E_COLS["y"]]] = torch.tensor([200.0, 100.0])
        t_e.tensor[t_e.slot_of(e_ids[1]), E_COLS["type"]] = float(cfg.M_FOREST)

        t_e.tensor[t_e.slot_of(e_ids[2]), [E_COLS["x"], E_COLS["y"]]] = torch.tensor([400.0, 100.0])
        t_e.tensor[t_e.slot_of(e_ids[2]), E_COLS["type"]] = float(cfg.M_FOREST)

        # Position humans: h[0] inner (x=110), h[1] outer (x=180), h[2] outside (x=400)
        t_h.tensor[t_h.slot_of(h_ids[0]), [H_COLS["x"], H_COLS["y"]]] = torch.tensor([110.0, 100.0])
        t_h.tensor[t_h.slot_of(h_ids[1]), [H_COLS["x"], H_COLS["y"]]] = torch.tensor([180.0, 100.0])
        t_h.tensor[t_h.slot_of(h_ids[2]), [H_COLS["x"], H_COLS["y"]]] = torch.tensor([400.0, 100.0])

        res = pw.call(world, "volcanic_eruption", {"center": [100.0, 100.0]}, registry=self.reg)
        self.assertTrue(res.ok)

        # Inner entity converted to lava with cooling
        self.assertEqual(t_e.get(e_ids[0], "type"), float(cfg.M_LAVA))
        self.assertEqual(t_e.get(e_ids[0], "food"), 0.0)
        self.assertEqual(t_e.get(e_ids[0], "lava_cooling"), float(cfg.VOLCANO_LAVA_COOLING))

        # Outer forest ignited
        self.assertEqual(t_e.get(e_ids[1], "burning"), 1.0)
        # Outside forest untouched
        self.assertEqual(t_e.get(e_ids[2], "burning"), 0.0)

        # Inner human despawned
        self.assertNotIn(h_ids[0], [t_h.ids[s] for s in t_h.live_slots()])

        # Outer human threat=100 and fled outward
        self.assertEqual(t_h.get(h_ids[1], "threat"), 100.0)
        self.assertGreater(t_h.get(h_ids[1], "x"), 180.0)

        # Outside human untouched
        self.assertEqual(t_h.get(h_ids[2], "threat"), 10.0)
        self.assertEqual(t_h.get(h_ids[2], "x"), 400.0)


class DroughtTests(BaseDisasterTestCase):
    def test_lake_depletion(self):
        world, _, e_ids = make_disaster_world(num_entities=3)
        t_e = world.table("entities")
        t_e.tensor[t_e.slot_of(e_ids[0]), E_COLS["type"]] = float(cfg.M_LAKE)
        t_e.tensor[t_e.slot_of(e_ids[1]), E_COLS["type"]] = float(cfg.M_FOREST)

        res = pw.call(world, "drought", {}, registry=self.reg)
        self.assertTrue(res.ok)

        # Lake food, water, fertility wiped to 0
        self.assertEqual(t_e.get(e_ids[0], "food"), 0.0)
        self.assertEqual(t_e.get(e_ids[0], "water"), 0.0)
        self.assertEqual(t_e.get(e_ids[0], "fertility"), 0.0)

        # Forest untouched
        self.assertEqual(t_e.get(e_ids[1], "food"), 50.0)
        self.assertEqual(t_e.get(e_ids[1], "water"), 50.0)

    def test_oracle_parity(self):
        # Production layout: tool_drought writes M_RESOURCE_FOOD / M_RESOURCE_WATER / M_FERTILITY by cfg index.
        world, _, e_ids = make_production_layout_world(num_entities=2)
        t_e = world.table("entities")
        t_e.tensor[t_e.slot_of(e_ids[0]), P_E_COLS["type"]] = float(cfg.M_LAKE)
        t_e.tensor[t_e.slot_of(e_ids[1]), P_E_COLS["type"]] = float(cfg.M_FOREST)

        legacy_m = t_e.tensor.clone()
        tool_drought({}, legacy_m)

        res = pw.call(world, "drought", {}, registry=self.reg)
        self.assertTrue(res.ok)
        self.assertEqual(t_e.get(e_ids[0], "water"), 0.0)
        self.assertEqual(t_e.get(e_ids[1], "water"), 50.0)
        assert_same_tensor(self, t_e.tensor, legacy_m)


class FloodTests(BaseDisasterTestCase):
    def test_flood_expansion_and_human_damage(self):
        world, h_ids, e_ids = make_disaster_world(num_humans=2, num_entities=3)
        t_e = world.table("entities")
        t_h = world.table("humans")

        # Entity 0 is water (M_LAKE) at (100, 100)
        t_e.tensor[t_e.slot_of(e_ids[0]), E_COLS["type"]] = float(cfg.M_LAKE)
        t_e.tensor[t_e.slot_of(e_ids[0]), [E_COLS["x"], E_COLS["y"]]] = torch.tensor([100.0, 100.0])

        # Entity 1 is expandable (M_GRASS) at (130, 100) (dist = 30 < 100)
        t_e.tensor[t_e.slot_of(e_ids[1]), E_COLS["type"]] = float(cfg.M_GRASS)
        t_e.tensor[t_e.slot_of(e_ids[1]), [E_COLS["x"], E_COLS["y"]]] = torch.tensor([130.0, 100.0])

        # Entity 2 is mountain (M_MOUNTAIN) at (120, 100) - not expandable
        t_e.tensor[t_e.slot_of(e_ids[2]), E_COLS["type"]] = float(cfg.M_MOUNTAIN)
        t_e.tensor[t_e.slot_of(e_ids[2]), [E_COLS["x"], E_COLS["y"]]] = torch.tensor([120.0, 100.0])

        res = pw.call(world, "flood", {"expand_radius": 50.0}, registry=self.reg)
        self.assertTrue(res.ok)

        # Entity 1 converted to sea, food=0, flooded=1
        self.assertEqual(t_e.get(e_ids[1], "type"), float(cfg.M_SEA))
        self.assertEqual(t_e.get(e_ids[1], "food"), 0.0)
        self.assertEqual(t_e.get(e_ids[1], "flooded"), 1.0)

        # Mountain not converted
        self.assertEqual(t_e.get(e_ids[2], "type"), float(cfg.M_MOUNTAIN))


class AreaAttackTests(BaseDisasterTestCase):
    def test_blast_kill_and_flee_survivors(self):
        world, h_ids, _ = make_disaster_world(num_humans=3)
        t_h = world.table("humans")
        # h[0] in blast (< 30): at (110, 100), dist=10
        t_h.tensor[t_h.slot_of(h_ids[0]), [H_COLS["x"], H_COLS["y"]]] = torch.tensor([110.0, 100.0])
        # h[1] in flee ring (30 <= dist < 75): at (140, 100), dist=40
        t_h.tensor[t_h.slot_of(h_ids[1]), [H_COLS["x"], H_COLS["y"]]] = torch.tensor([140.0, 100.0])
        # h[2] outside (dist >= 75): at (200, 100), dist=100
        t_h.tensor[t_h.slot_of(h_ids[2]), [H_COLS["x"], H_COLS["y"]]] = torch.tensor([200.0, 100.0])

        res = pw.call(world, "area_attack", {"center": [100.0, 100.0], "radius": 30.0, "flee_radius_multiplier": 2.5}, registry=self.reg)
        self.assertTrue(res.ok)

        # h[0] killed (despawned)
        self.assertNotIn(h_ids[0], [t_h.ids[s] for s in t_h.live_slots()])

        # h[1] fled outward
        self.assertGreater(t_h.get(h_ids[1], "x"), 140.0)

        # h[2] untouched
        self.assertEqual(t_h.get(h_ids[2], "x"), 200.0)

    def test_oracle_parity(self):
        world, h_ids, _ = make_disaster_world(num_humans=2)
        t_h = world.table("humans")
        t_h.tensor[t_h.slot_of(h_ids[0]), [H_COLS["x"], H_COLS["y"]]] = torch.tensor([110.0, 100.0])
        t_h.tensor[t_h.slot_of(h_ids[1]), [H_COLS["x"], H_COLS["y"]]] = torch.tensor([150.0, 100.0])

        legacy_h = t_h.tensor.clone()
        pop_ref = [2]
        apply_area_attack_effect(
            {"h_mask": legacy_h[:, cfg.TYPE] > 0},
            legacy_h, pop_ref,
            center_x=100.0, center_y=100.0, radius=30.0, device="cpu",
            agent_radial_mask_fn=lambda h, m, cx, cy, r, dev: torch.tensor([r == 30.0, r > 30.0] + [False] * (legacy_h.shape[0] - 2)),
            flee_fn=lambda ctx, h, tpos, flee_mask, device: h[flee_mask, :2].add_(10.0),
        )

        pw.call(world, "area_attack", {"center": [100.0, 100.0], "radius": 30.0}, registry=self.reg)
        # h[0] is dead in both
        self.assertEqual(legacy_h[0, cfg.TYPE].item(), 0.0)
        self.assertNotIn(h_ids[0], [t_h.ids[s] for s in t_h.live_slots()])


class SmiteTests(BaseDisasterTestCase):
    def test_targeted_smite(self):
        world, h_ids, _ = make_disaster_world(num_humans=3)
        t_h = world.table("humans")

        res = pw.call(world, "smite", {"targets": {"of": "humans", "ids": [h_ids[1]]}}, registry=self.reg)
        self.assertTrue(res.ok)

        # Only h_ids[1] is despawned
        live = [t_h.ids[s] for s in t_h.live_slots()]
        self.assertIn(h_ids[0], live)
        self.assertNotIn(h_ids[1], live)
        self.assertIn(h_ids[2], live)

    def test_oracle_parity(self):
        world, h_ids, _ = make_disaster_world(num_humans=2)
        t_h = world.table("humans")

        legacy_h = t_h.tensor.clone()
        pop_ref = [2]
        mask = torch.tensor([False, True] + [False] * (legacy_h.shape[0] - 2))
        kill_humans(mask, legacy_h, pop_ref)

        pw.call(world, "smite", {"targets": {"of": "humans", "ids": [h_ids[1]]}}, registry=self.reg)
        self.assertEqual(legacy_h[1, cfg.TYPE].item(), 0.0)
        self.assertNotIn(h_ids[1], [t_h.ids[s] for s in t_h.live_slots()])


class ContractAndLifecycleTests(BaseDisasterTestCase):
    def test_spaces_isolation(self):
        # harness.spaces.point_space returns None (= do not filter) unless EDEN_SPACES is on AND an authored world with an
        # interior is registered, so the fixture registers one: the example smith map (0..48) with its interior placed at
        # x 300..396, y 0..80 (the placement tests' origin). The centre (250, 40) is overworld (space 0); entity 1 stands
        # inside the interior (space 1), 70 units away, within the radius.
        world, h_ids, e_ids = make_disaster_world(num_humans=2, num_entities=2)
        t_e = world.table("entities")
        t_e.tensor[t_e.slot_of(e_ids[0]), [E_COLS["x"], E_COLS["y"]]] = torch.tensor([250.0, 40.0])
        t_e.tensor[t_e.slot_of(e_ids[0]), E_COLS["space"]] = 0.0
        t_e.tensor[t_e.slot_of(e_ids[0]), E_COLS["type"]] = float(cfg.M_FOREST)
        t_e.tensor[t_e.slot_of(e_ids[1]), [E_COLS["x"], E_COLS["y"]]] = torch.tensor([320.0, 40.0])
        t_e.tensor[t_e.slot_of(e_ids[1]), E_COLS["space"]] = 1.0
        t_e.tensor[t_e.slot_of(e_ids[1]), E_COLS["type"]] = float(cfg.M_FOREST)

        saved_contracts = dict(MAP_CONTRACTS)
        saved_bound = harness_spaces._bound_name
        clear_map_contracts()
        harness_spaces._bound_name = None
        try:
            register_map_file(MAP_FIXTURES / "example_smith.json", base_dir=MAP_FIXTURES)
            register_map_file(MAP_FIXTURES / "example_smith_interior.json", origin=[300.0, 0.0], base_dir=MAP_FIXTURES,
                              primary=False, world="example_smith")
            os.environ["EDEN_SPACES"] = "1"
            self.assertEqual(harness_spaces.point_space(250.0, 40.0), 0)
            self.assertEqual(harness_spaces.point_space(320.0, 40.0), 1)

            res = pw.call(world, "wildfire", {"center": [250.0, 40.0], "radius": 100.0}, registry=self.reg)
            self.assertTrue(res.ok)
            self.assertEqual(res.plan.targets, (e_ids[0],))
            self.assertEqual(t_e.get(e_ids[0], "burning"), 1.0)
            self.assertEqual(t_e.get(e_ids[1], "burning"), 0.0)

            # Control: with spaces off the same query reaches both (the isolation above is the space filter, not distance).
            os.environ.pop("EDEN_SPACES", None)
            plan = pw.plan(world, "wildfire", {"center": [250.0, 40.0], "radius": 100.0}, registry=self.reg)
            self.assertEqual(set(plan.targets), {e_ids[0], e_ids[1]})
        finally:
            os.environ.pop("EDEN_SPACES", None)
            clear_map_contracts()
            MAP_CONTRACTS.update(saved_contracts)
            harness_spaces._bound_name = saved_bound

    def test_stale_plan_and_slot_recycling(self):
        world, h_ids, _ = make_disaster_world(num_humans=3)
        t_h = world.table("humans")

        # Plan smite on h_ids[0]
        plan = pw.plan(world, "smite", {"targets": {"of": "humans", "ids": [h_ids[0]]}}, registry=self.reg)
        self.assertTrue(plan.ok)

        # World changes before apply: h_ids[0] dies, slot is freed
        world.apply([fx.despawn("humans", [h_ids[0]])])
        self.assertNotEqual(plan.revision, world.revision)

        # Replan at apply time safely drops the dead resident
        res = pw.apply(world, plan, registry=self.reg)
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "no_targets")
        self.assertTrue(res.replanned)

    def test_field_spec_reject_atomic_rollback(self):
        # Table with FieldSpec mode="reject" on type column
        world, h_ids, e_ids = make_disaster_world(num_humans=2, num_entities=2)
        before = world_digest(world)

        # An effect that would put out-of-bounds on type (e.g. type 999 when max is 8)
        # Verify that atomic apply rolls back completely
        report = world.apply([
            fx.set_("humans", [h_ids[0]], "hp", 50.0),
            fx.set_("humans", [h_ids[0]], "type", 999.0),  # rejected
        ], atomic=True)
        self.assertFalse(report.ok)
        self.assertTrue(report.rolled_back)
        self.assertEqual(world_digest(world), before)
        self.assertEqual(len(world.events.events()), 0)

    def test_deterministic_random_result_parity(self):
        world1, _, _ = make_disaster_world(seed=777)
        world2, _, _ = make_disaster_world(seed=777)

        plan1 = pw.plan(world1, "earthquake", {"center": [100.0, 100.0], "radius": 50.0}, registry=self.reg)
        plan2 = pw.plan(world2, "earthquake", {"center": [100.0, 100.0], "radius": 50.0}, registry=self.reg)

        self.assertEqual(plan1.preview, plan2.preview)
        self.assertEqual(len(plan1.effects), len(plan2.effects))


if __name__ == "__main__":
    unittest.main()
