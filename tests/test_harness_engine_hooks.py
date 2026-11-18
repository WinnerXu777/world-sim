"""Scheduler integration stages S0, S1, S2 and S4: the harness installed into the live Engine through DISPATCH, behind EDEN_HARNESS."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from authored_village import load_village_maps  # noqa: E402
from test_startup_preservation import backend  # noqa: E402,F401  (sets the isolated data root and imports map_test)
from test_map_contract import AsyncRegistryIsolation  # noqa: E402
from harness import engine_hooks as eh  # noqa: E402
from simulation.dispatch import DISPATCH, Dispatcher  # noqa: E402


class InstallTests(unittest.TestCase):
    def test_flag_off_installs_nothing(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(eh.FLAG, None)
            d = Dispatcher()
            self.assertFalse(eh.install(d))
            self.assertEqual((d.step_hooks, d.post_step_hooks, d.genesis_hooks, d.executors), ([], [], [], {}))

    def test_flag_on_installs_once_as_builtin_and_uninstalls_cleanly(self):
        with mock.patch.dict(os.environ, {eh.FLAG: "1"}):
            d = Dispatcher()
            self.assertTrue(eh.install(d))
            self.assertTrue(eh.install(d))                                          # idempotent
            self.assertEqual([n for n, _ in d.genesis_hooks], ["harness_world"])
            self.assertEqual([n for n, _ in d.post_step_hooks], ["harness_events", "harness_parity"])
            self.assertIn(eh.EXECUTOR, d.executors)
            d.clear()                                                                # test isolation keeps builtin hooks
            self.assertEqual(len(d.post_step_hooks), 2)
            eh.uninstall(d)
            self.assertEqual((d.post_step_hooks, d.genesis_hooks, d.builtin_names), ([], [], set()))
            self.assertNotIn(eh.EXECUTOR, d.executors)


class EngineStageTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        load_village_maps()
        self.env = mock.patch.dict(os.environ, {eh.FLAG: "1"})
        self.env.start()
        eh.install(DISPATCH)
        self.engine = backend.engine
        self.engine.reset_world()
        await backend.create_genesis(self.engine, map_name="starter_village")
        DISPATCH.errors.clear()

    async def asyncTearDown(self):
        eh.uninstall(DISPATCH)
        self.env.stop()
        if hasattr(self.engine, "harness"):
            del self.engine.harness
        await super().asyncTearDown()

    # S0 -------------------------------------------------------------------------------------------------------------
    def test_s0_world_is_built_at_genesis_tracks_the_engine_and_is_replaced_on_a_new_world(self):
        rt = self.engine.harness
        self.assertEqual(rt.epoch, self.engine.world_epoch)
        self.assertEqual(rt.world.tick, self.engine.tick)
        self.engine.step()
        self.engine.step()
        self.assertEqual(rt.world.tick, self.engine.tick)
        self.assertIs(eh.runtime(self.engine), rt)

    async def test_s0_a_new_world_gets_a_new_runtime(self):
        old = self.engine.harness
        self.engine.reset_world()
        await backend.create_genesis(self.engine, map_name="starter_village")
        self.assertIsNot(self.engine.harness, old)
        self.assertEqual(self.engine.harness.epoch, self.engine.world_epoch)

    def test_hooks_never_raise_into_the_tick_and_record_nothing_on_a_healthy_world(self):
        for _ in range(20):
            self.engine.step()
        self.assertEqual(list(DISPATCH.errors), [])
        self.assertEqual(self.engine.harness.errors, [])

    # S1 -------------------------------------------------------------------------------------------------------------
    def test_s1_god_events_are_mirrored_once_with_their_witnesses_and_new_witnesses_are_added(self):
        from systems.god.events import commit_event
        ids = [i for i in self.engine._human_uid_by_slot if i][:3]
        entry = commit_event(self.engine, "divine_heal", point=(10.0, 20.0), target_id=ids[0], witnesses=ids[:2])
        self.engine.step()
        ledger = self.engine.harness.world.events
        event = ledger.get(f"god:{entry['id']}")
        self.assertIsNotNone(event)
        self.assertEqual((event.type, sorted(event.witnesses), event.place), ("divine_heal", sorted(ids[:2]), (10.0, 20.0)))
        self.engine.step()
        self.assertEqual(len(ledger.events(type="divine_heal")), 1)                       # not duplicated
        commit_event(self.engine, "divine_heal", point=(10.0, 20.0), target_id=ids[0], witnesses=[ids[2]], extra={"event_id": entry["id"]})
        self.engine.step()
        self.assertEqual(sorted(ledger.get(f"god:{entry['id']}").witnesses), sorted(ids[:3]))
        self.assertEqual(len(ledger.events(type="divine_heal")), 1)

    def test_s1_with_no_god_events_the_mirror_does_nothing_and_creates_no_legacy_state(self):
        self.engine.inventory_state.pop("god", None)
        self.engine.step()
        self.assertNotIn("god", self.engine.inventory_state)
        self.assertEqual(self.engine.harness.world.events.events(), [])

    # S2 -------------------------------------------------------------------------------------------------------------
    def test_s2_the_harness_schedule_equals_the_legacy_registry_order(self):
        rt = self.engine.harness
        self.assertIsNone(rt.parity())
        scheduled = [spec.name.split(":", 1)[1] for spec in rt.legacy.schedule()]
        self.assertEqual(scheduled, [e["fn"].__name__ for e in self.engine._registry])
        self.assertGreater(len(scheduled), 5)

    def test_s2_a_registry_change_is_reported_once_and_then_re_recorded(self):
        def extra_system(ctx, **kwargs):
            return None
        self.engine.register(extra_system, priority=1)
        self.engine.step()
        self.assertEqual(len(self.engine.harness.errors), 1)
        self.assertIn("engine._registry changed", self.engine.harness.errors[0][2])
        self.engine.step()
        self.engine.step()
        self.assertEqual(len(self.engine.harness.errors), 1)
        self.assertIsNone(self.engine.harness.parity())
        self.engine.unregister(extra_system)

    # S4 -------------------------------------------------------------------------------------------------------------
    def test_s4_a_power_command_applies_atomically_and_a_dry_run_changes_nothing(self):
        import genesis_config as cfg
        h = self.engine.state.h_tensor
        before = h.clone()
        dry = DISPATCH.execute(self.engine, "harness_power", {"power": "set_mood", "args": {"targets": {"of": "humans"}, "value": 33.0}, "dry_run": True})
        self.assertTrue(dry["ok"], dry)
        self.assertTrue(dry["dry_run"] and len(dry["targets"]) >= 1)
        self.assertTrue((h == before).all())
        done = DISPATCH.execute(self.engine, "harness_power", {"power": "set_mood", "args": {"targets": {"of": "humans"}, "value": 33.0}})
        self.assertTrue(done["ok"], done)
        live = h[:, cfg.TYPE] > 0
        self.assertTrue((h[live, cfg.MOOD] == 33.0).all())
        self.assertEqual(len(done["event_ids"]), 1)
        self.assertTrue(self.engine._force_frame_refresh)
        self.engine.step()
        self.assertEqual(list(DISPATCH.errors), [])

    def test_s4_refusals_have_stable_reasons_and_do_not_raise(self):
        run = lambda payload: DISPATCH.execute(self.engine, "harness_power", payload)                     # noqa: E731
        self.assertEqual(run({})["reason"], "invalid_arguments")
        self.assertEqual(run({"power": "no_such_power"})["reason"], "invalid_arguments")
        self.assertEqual(run({"power": "set_mood", "args": {"targets": {"of": "humans"}}})["reason"], "invalid_arguments")
        self.assertEqual(run({"power": "cull", "args": {"target_population": 10 ** 6}})["reason"], "no_targets")
        self.assertEqual(run("not a dict")["reason"], "invalid_arguments")

    def test_s4_cull_through_the_command_keeps_the_engine_population_counter_in_step(self):
        target = self.engine.pop_count - 2
        out = DISPATCH.execute(self.engine, "harness_power", {"power": "cull", "args": {"target_population": target}})
        self.assertTrue(out["ok"], out)
        self.assertEqual(self.engine.pop_count, target)
        self.engine.step()


if __name__ == "__main__":
    unittest.main()
