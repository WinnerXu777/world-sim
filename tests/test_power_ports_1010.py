"""Three opt-in mind/body ports: registry, atomic effects and legacy tensor parity."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
from harness import effects as fx, powers as pw
from harness.world import FieldSpec, Table, World
import genesis_config as cfg

ALL = {"of": "humans"}
PORTS = {"set_threat", "set_aggression", "reset_cooldown"}
# harness/powers.py docstring: the same flag also exposes the eight disaster ports (harness/disaster_powers.py).
DISASTERS = {"wildfire", "earthquake", "storm", "volcanic_eruption", "drought", "flood", "area_attack", "smite"}
BASE = {"set_mood", "plague", "bless", "calm_area", "panic_area", "baby_boom",
        "cull", "enlighten", "bounty_area", "scarcity_area"}


def fixture():
    cols = {"type": cfg.TYPE, "x": cfg.X, "y": cfg.Y, "hp": cfg.HP,
            "mood": cfg.MOOD, "threat": cfg.THREAT, "aggression": cfg.H_AGGRESSION,
            "cooldown": cfg.H_COOLDOWN, "stamina": cfg.H_STAMINA}
    table = Table("humans", torch.zeros(6, cfg.HUMAN_TENSOR_COLS), cols, type_col="type",
                  pos_cols=("x", "y"), field_specs={"hp": FieldSpec(0, 100)})
    world = World(1008, [table])
    ids = [world.add_row("humans", x=i * 10, y=0, hp=100, mood=50, threat=20 + i * 10,
                         aggression=0.2 + i * 0.1, cooldown=3 + i, stamina=75) for i in range(3)]
    return world, ids


class PowerPortsTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"EDEN_GOD_POWER_PORTS": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.reg = pw.build_registry()
        self.world, self.ids = fixture()

    def call(self, name, args, **kw):
        return pw.call(self.world, name, args, registry=self.reg, **kw)

    def test_flag_off_registry_and_existing_output_unchanged(self):
        with patch.dict(os.environ, {"EDEN_GOD_POWER_PORTS": "0"}):
            off = pw.build_registry()
        with patch.dict(os.environ, {}, clear=True):
            missing = pw.build_registry()
        self.assertEqual(set(off.powers), BASE)
        self.assertEqual(off.manifest(), missing.manifest())
        self.assertEqual(set(self.reg.powers), BASE | PORTS | DISASTERS)
        for name in PORTS:
            result = pw.call(self.world, name, {"targets": ALL, "value": 5}, registry=off)
            self.assertEqual((result.ok, result.reason), (False, "invalid_arguments"))
        other, _ = fixture()
        a = pw.call(self.world, "set_mood", {"targets": ALL, "value": 60}, registry=off)
        b = pw.call(other, "set_mood", {"targets": ALL, "value": 60}, registry=self.reg)
        self.assertEqual(a.plan, b.plan)
        self.assertTrue(torch.equal(self.world.table("humans").tensor, other.table("humans").tensor))

    def test_flag_on_default_registry_dispatch(self):
        with patch.object(pw, "REGISTRY", self.reg):
            result = pw.call(self.world, "set_aggression", {"targets": ALL})
        self.assertTrue(result.ok)
        self.assertEqual([self.world.table("humans").get(i, "aggression") for i in self.ids], [1.0] * 3)

    def test_selected_rows_only_and_exact_cooldown_fields(self):
        table = self.world.table("humans")
        for name, column, args in (("set_threat", "threat", {"value": 70}),
                                   ("set_aggression", "aggression", {"value": 0.8}),
                                   ("reset_cooldown", "cooldown", {})):
            before = table.tensor.clone()
            result = self.call(name, {"targets": {"of": "humans", "ids": [self.ids[1]]}, **args})
            self.assertTrue(result.ok, result.reason)
            expected = before.clone()
            expected[1, table.col(column)] = args.get("value", 0)
            self.assertTrue(torch.equal(table.tensor, expected), name)
            self.assertEqual(result.plan.targets, (self.ids[1],))
            self.assertEqual(result.report.revision, self.world.revision)
            self.assertEqual(len(result.event_ids), 1)
            event = self.world.events.get(result.event_ids[0])
            self.assertEqual((event.actors, event.witnesses), ((self.ids[1],), (self.ids[1],)))
            self.assertEqual(event.cause, f"power:{name}")
            self.assertEqual(event.visibility, "private")

    def test_dry_run_reports_changes_without_mutation_or_events(self):
        table = self.world.table("humans")
        before, revision = table.tensor.clone(), self.world.revision
        for name, field, args in (("set_threat", "threat", {"value": 90}),
                                  ("set_aggression", "aggression", {"value": 1}),
                                  ("reset_cooldown", "cooldown", {})):
            result = self.call(name, {"targets": ALL, **args}, dry_run=True)
            self.assertTrue(result.ok)
            self.assertEqual(result.plan.preview["affected"], self.ids)
            self.assertIn(f"{field}_after", result.plan.preview)
            self.assertEqual(len(result.plan.effects), 2)
        self.assertTrue(torch.equal(before, table.tensor))
        self.assertEqual(self.world.revision, revision)
        self.assertEqual(self.world.events.events(), [])

    def test_modes_bounds_and_defaults(self):
        table = self.world.table("humans")
        for name, column, cap in (("set_threat", "threat", 100), ("set_aggression", "aggression", 1)):
            for mode, value, expected in (("set", cap * 2, cap), ("add", -cap * 3, 0),
                                           ("set", cap / 2, cap / 2), ("multiply", 0.5, cap / 4)):
                self.assertTrue(self.call(name, {"targets": ALL, "value": value, "mode": mode}).ok)
                self.assertEqual([table.get(i, column) for i in self.ids], [expected] * 3)
        self.assertTrue(self.call("reset_cooldown", {}).ok)
        self.assertEqual([table.get(i, "cooldown") for i in self.ids], [0] * 3)

    def test_invalid_arguments_targets_and_nonfinite_are_pure(self):
        table = self.world.table("humans")
        before = table.tensor.clone()
        for name in PORTS:
            cases = [{"targets": {"of": "entities"}}, {"targets": {"of": "humans", "ids": ["missing"]}},
                     {"targets": {"of": "humans", "where": [{"field": "missing", "op": ">", "value": 0}]}},
                     {"targets": ALL, "extra": 4}]
            if name != "reset_cooldown":
                cases = [{**a, "value": 1} for a in cases]
                cases += [{"targets": ALL, "value": v} for v in
                          (float("nan"), float("inf"), -float("inf"), True, 10 ** 400)]
                cases += [{"targets": ALL, "value": 1, "mode": "unknown"}]
            for args in cases:
                self.assertFalse(self.call(name, args).ok, (name, args))
        self.assertTrue(torch.equal(table.tensor, before))
        self.assertEqual(self.world.events.events(), [])

    def test_missing_columns_refuse_without_events(self):
        table = self.world.table("humans")
        for name, column in (("set_threat", "threat"), ("set_aggression", "aggression"), ("reset_cooldown", "cooldown")):
            with patch.dict(table.columns):
                del table.columns[column]
                args = {"targets": ALL, **({} if name == "reset_cooldown" else {"value": 1})}
                self.assertEqual(self.call(name, args).reason, "no_column")
        self.assertEqual(self.world.events.events(), [])

    def test_nonfinite_state_and_overflow_refuse_before_apply(self):
        table = self.world.table("humans")
        for name, column in (("set_threat", "threat"), ("set_aggression", "aggression")):
            slot = table.slot_of(self.ids[0])
            table.tensor[slot, table.col(column)] = float("nan")
            self.assertEqual(self.call(name, {"targets": ALL, "value": 1}).reason, "invalid_state")
            table.tensor[slot, table.col(column)] = 2
            self.assertEqual(self.call(name, {"targets": ALL, "value": 1e308, "mode": "multiply"}).reason,
                             "invalid_amount")
        self.assertEqual(self.world.events.events(), [])

    def test_stale_plan_recomputes_and_recycled_id_is_safe(self):
        table = self.world.table("humans")
        for name, column in (("set_threat", "threat"), ("set_aggression", "aggression")):
            args = {"targets": {"of": "humans", "ids": [self.ids[0]]}, "value": 0.5, "mode": "multiply"}
            old = pw.plan(self.world, name, args, self.reg)
            self.world.apply([fx.set_("humans", self.ids[0], column, 0.8)])
            result = pw.apply(self.world, old, self.reg)
            self.assertTrue(result.ok and result.replanned)
            self.assertAlmostEqual(table.get(self.ids[0], column), 0.4)
        old = pw.plan(self.world, "reset_cooldown", {"targets": {"of": "humans", "ids": [self.ids[0]]}}, self.reg)
        self.world.apply([fx.despawn("humans", self.ids[0])])
        replacement = self.world.add_row("humans", hp=100, cooldown=7)
        result = pw.apply(self.world, old, self.reg)
        self.assertFalse(result.ok)
        self.assertTrue(result.replanned)
        self.assertEqual(table.get(replacement, "cooldown"), 7)

    def test_field_spec_rejection_is_atomic_with_no_event(self):
        table = self.world.table("humans")
        table.field_specs["threat"] = FieldSpec(0, 30, mode="reject")
        before = table.tensor.clone()
        result = self.call("set_threat", {"targets": ALL, "value": 70})
        self.assertEqual((result.ok, result.reason), (False, "apply_failed"))
        self.assertTrue(torch.equal(table.tensor, before))
        self.assertEqual(self.world.events.events(), [])

    def test_valid_input_legacy_equivalence_all_modes_and_masked_reset(self):
        import instincts_and_tools as legacy
        table = self.world.table("humans")
        mask = torch.tensor([True, False, True, True, False, False])
        live = table.live_mask()
        selected = {"of": "humans", "ids": [self.ids[0], self.ids[2]]}
        for name, fn, values in (("set_threat", legacy.tool_set_threat, (42, 7, 0.5)),
                                 ("set_aggression", legacy.tool_set_aggression, (0.4, 0.1, 0.5))):
            for mode, value in zip(("set", "add", "multiply"), values):
                clone = table.tensor.clone()
                fn({"h_mask": live}, clone, mask, value=value, mode=mode)
                self.assertTrue(self.call(name, {"targets": selected, "value": value, "mode": mode}).ok)
                self.assertTrue(torch.equal(clone, table.tensor), (name, mode))
        clone = table.tensor.clone()
        legacy.tool_reset_cooldown({"h_mask": live}, clone, mask)
        self.assertTrue(self.call("reset_cooldown", {"targets": selected}).ok)
        self.assertTrue(torch.equal(clone, table.tensor))
        clone = table.tensor.clone()
        legacy.tool_reset_cooldown({"h_mask": live}, clone)
        self.assertTrue(self.call("reset_cooldown", {}).ok)
        self.assertTrue(torch.equal(clone, table.tensor))


if __name__ == "__main__":
    unittest.main()
