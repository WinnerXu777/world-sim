"""Powers as plan()/apply(): the ported legacy tools (set_mood, plague), purity of plan, atomic evented apply, and equivalence with
the legacy tools on the real engine for in-range values (they differ only where legacy bug G-D0-4 leaves values out of range)."""
import hashlib
import sys
import unittest
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from authored_village import load_village_maps  # noqa: E402
from test_startup_preservation import backend  # noqa: E402,F401  (sets the isolated data root and imports map_test)
from test_map_contract import AsyncRegistryIsolation  # noqa: E402
from harness import effects as fx  # noqa: E402
from harness import powers as pw  # noqa: E402
from harness.world import FieldSpec, Table, World  # noqa: E402

COLS = {"type": 0, "x": 1, "y": 2, "hp": 3, "mood": 4, "infection": 5, "threat": 6}
ALL = {"of": "humans"}


def make_world(rows=4):
    specs = {"hp": FieldSpec(0.0, 100.0), "type": FieldSpec(0, 8, integer=True, mode="reject")}
    table = Table("humans", torch.zeros((16, 7)), COLS, type_col="type", pos_cols=("x", "y"), id_prefix="h", field_specs=specs)
    world = World(5, [table])
    ids = [world.add_row("humans", x=10 * i, y=0, hp=100, mood=50, infection=0, threat=0) for i in range(rows)]
    return world, ids


def digest(world):
    return hashlib.sha256(world.table("humans").tensor.numpy().tobytes()).hexdigest()


class SetMoodTests(unittest.TestCase):
    def test_modes_and_clamping(self):
        world, ids = make_world()
        h = world.table("humans")
        self.assertTrue(pw.call(world, "set_mood", {"targets": ALL, "value": 150, "mode": "set"}).ok)
        self.assertEqual([h.get(i, "mood") for i in ids], [100.0] * 4)          # legacy leaves 150 here (G-D0-4)
        pw.call(world, "set_mood", {"targets": ALL, "value": 0.25, "mode": "multiply"})
        self.assertEqual(h.get(ids[0], "mood"), 25.0)
        pw.call(world, "set_mood", {"targets": {"of": "humans", "ids": [ids[1]]}, "value": -60, "mode": "add"})
        self.assertEqual((h.get(ids[1], "mood"), h.get(ids[2], "mood")), (0.0, 25.0))

    def test_plan_is_pure_and_dry_run_changes_nothing(self):
        world, ids = make_world()
        before, revision = digest(world), world.revision
        the_plan = pw.plan(world, "set_mood", {"targets": ALL, "value": 10})
        self.assertTrue(the_plan.ok)
        self.assertEqual((digest(world), world.revision, len(world.events.events())), (before, revision, 0))
        self.assertEqual(sorted(the_plan.targets), sorted(ids))
        self.assertEqual(the_plan.preview["mood_after"][ids[0]], 10.0)
        result = pw.call(world, "set_mood", {"targets": ALL, "value": 10}, dry_run=True)
        self.assertEqual((result.ok, digest(world)), (True, before))

    def test_refusals_have_stable_reasons_and_change_nothing(self):
        world, ids = make_world()
        before = digest(world)
        cases = {"invalid_arguments": {"targets": ALL},                                       # value missing
                 "invalid_arguments ": {"targets": ALL, "value": 5, "mode": "explode"},
                 "invalid_targets": {"targets": {"of": "entities"}, "value": 5},
                 "invalid_selector": {"targets": {"of": "humans", "where": [{"field": "nope", "op": ">", "value": 1}]}, "value": 5},
                 "no_targets": {"targets": {"of": "humans", "where": [{"field": "hp", "op": "<", "value": -1}]}, "value": 5}}
        for reason, args in cases.items():
            result = pw.call(world, "set_mood", args)
            self.assertEqual((result.ok, result.reason), (False, reason.strip()), reason)
        self.assertEqual(pw.call(world, "no_such_power", {}).reason, "invalid_arguments")
        self.assertEqual(digest(world), before)

    def test_apply_emits_one_private_event_to_the_targets_in_the_same_atomic_run(self):
        world, ids = make_world()
        result = pw.call(world, "set_mood", {"targets": {"of": "humans", "ids": [ids[0], ids[1]]}, "value": 80})
        self.assertEqual(len(result.event_ids), 1)
        event = world.events.get(result.event_ids[0])
        self.assertEqual((event.type, event.visibility, sorted(event.witnesses)), ("mood_set", "private", sorted(ids[:2])))
        self.assertEqual(event.cause, "power:set_mood")
        self.assertEqual(result.report.revision, world.revision)

    def test_a_stale_plan_is_rebuilt_not_applied_with_old_numbers(self):
        world, ids = make_world()
        old = pw.plan(world, "set_mood", {"targets": {"of": "humans", "ids": [ids[0]]}, "value": 0.5, "mode": "multiply"})
        self.assertEqual(old.preview["mood_after"][ids[0]], 25.0)
        world.apply([fx.set_("humans", ids[0], "mood", 80)])                       # the world moves on
        result = pw.apply(world, old)
        self.assertEqual((result.ok, result.replanned), (True, True))
        self.assertEqual(world.table("humans").get(ids[0], "mood"), 40.0)         # 80 * 0.5, not the stale 25

    def test_a_resident_who_died_between_plan_and_apply_is_not_hit(self):
        world, ids = make_world()
        the_plan = pw.plan(world, "set_mood", {"targets": ALL, "value": 10})
        world.apply([fx.despawn("humans", ids[0])])
        result = pw.apply(world, the_plan)
        self.assertTrue(result.ok)
        self.assertNotIn(ids[0], result.plan.targets)
        self.assertEqual(world.table("humans").get(ids[1], "mood"), 10.0)


class PlagueTests(unittest.TestCase):
    def test_all_four_effects_stay_inside_their_ranges(self):
        world, ids = make_world(3)
        h = world.table("humans")
        world.apply([fx.set_("humans", ids[0], "infection", 90), fx.set_("humans", ids[1], "hp", 1),
                     fx.set_("humans", ids[2], "mood", 5)])
        self.assertTrue(pw.call(world, "plague", {"targets": ALL}).ok)
        self.assertEqual(h.get(ids[0], "infection"), 100.0)            # legacy: 120 (G-D0-4)
        self.assertEqual(h.get(ids[1], "hp"), 0.0)
        self.assertEqual(h.get(ids[2], "mood"), 0.0)                   # 5 - 20 floors at 0
        self.assertEqual((h.get(ids[0], "threat"), h.get(ids[0], "hp"), h.get(ids[0], "mood")), (15.0, 98.0, 30.0))

    def test_plague_is_flagged_destructive_in_the_manifest_and_validates_amounts(self):
        manifest = pw.REGISTRY.manifest()
        by_name = {p["id"]: p for p in manifest["powers"]}
        self.assertEqual((by_name["plague"]["risk"], by_name["set_mood"]["risk"]), ("destructive", "reversible"))
        self.assertEqual(by_name["plague"]["args"]["required"], ["targets"])
        world, _ = make_world(2)
        self.assertEqual(pw.call(world, "plague", {"targets": ALL, "decay_rate": -1}).reason, "invalid_amount")

    def test_event_is_local_with_the_victims_as_actors(self):
        world, ids = make_world(2)
        result = pw.call(world, "plague", {"targets": ALL})
        event = world.events.get(result.event_ids[0])
        self.assertEqual((event.type, sorted(event.actors), event.visibility), ("plague", sorted(ids), "local"))
        self.assertEqual(event.place, (5.0, 0.0))


class EngineEquivalenceTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    """On the real engine, in-range values match the legacy tools exactly."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        load_village_maps()
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="starter_village")
        from harness.adapter import EngineWorld
        self.engine = backend.engine
        self.world = EngineWorld(self.engine, seed=1008)

    def legacy_clone(self):
        return self.engine.state.h_tensor.clone()

    def live_mask(self, h):
        import genesis_config as cfg
        return (h[:, cfg.TYPE] == cfg.AGENT_TYPE_HUMAN) & (h[:, cfg.HP] > 0)

    def test_set_mood_matches_legacy_in_range(self):
        import genesis_config as cfg
        import instincts_and_tools as iat
        for mode, value in (("set", 42.0), ("add", 7.5), ("multiply", 0.5)):
            legacy = self.legacy_clone()
            mask = self.live_mask(legacy)
            iat.tool_set_mood({"h_mask": mask}, legacy, mask, value, mode=mode)
            result = pw.call(self.world, "set_mood", {"targets": ALL, "value": value, "mode": mode})
            self.assertTrue(result.ok, result.reason)
            self.assertTrue(torch.allclose(legacy[:, cfg.MOOD], self.engine.state.h_tensor[:, cfg.MOOD], atol=1e-4), mode)

    def test_plague_matches_legacy_in_range(self):
        import genesis_config as cfg
        from systems.health.effects import apply_plague_effect
        legacy = self.legacy_clone()
        mask = self.live_mask(legacy)
        apply_plague_effect(mask, legacy, decay_rate=2.0)
        result = pw.call(self.world, "plague", {"targets": ALL})
        self.assertTrue(result.ok, result.reason)
        h = self.engine.state.h_tensor
        for col in (cfg.HP, cfg.H_INFECTION, cfg.THREAT, cfg.MOOD):
            self.assertTrue(torch.allclose(legacy[:, col], h[:, col], atol=1e-4), col)
        self.assertEqual(len(result.plan.targets), 8)

    def test_the_engine_keeps_running_after_a_power(self):
        pw.call(self.world, "set_mood", {"targets": ALL, "value": 60})
        for _ in range(5):
            self.engine.step()


if __name__ == "__main__":
    unittest.main()
