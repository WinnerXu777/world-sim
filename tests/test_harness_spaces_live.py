"""1008 WS-D P3b: the space columns kept current in a live engine (flag EDEN_SPACES=1 with EDEN_PERCEPTION_BOUNDED=1): rows created from a
map carry the map's space, a portal use writes H_SPACE in the same tick, the post-step refresh equals a recomputation from positions,
and with the flag off nothing is written."""
import os
import random
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_startup_preservation import backend  # noqa: E402,F401  (sets the isolated data root and imports map_test)
from test_map_contract import AsyncRegistryIsolation  # noqa: E402
from test_map_portals import PORTAL, claim, position, real_world, submit  # noqa: E402
import genesis_config as cfg  # noqa: E402
from harness import engine_hooks as eh, spaces  # noqa: E402
from simulation.dispatch import DISPATCH, Dispatcher  # noqa: E402
from systems.movement.map_contract import find_portal, placed_group  # noqa: E402

ON = {"EDEN_SPACES": "1", "EDEN_PERCEPTION_BOUNDED": "1"}


def env(on=True):
    patcher = mock.patch.dict(os.environ, ON if on else {}, clear=False)
    patcher.start()
    if not on:
        os.environ.pop("EDEN_SPACES", None)
    return patcher


class InstallTests(unittest.TestCase):
    def test_spaces_flag_installs_the_refresh_without_the_harness_flag(self):
        patcher = env(True)
        try:
            os.environ.pop(eh.FLAG, None)
            d = Dispatcher()
            self.assertTrue(eh.install(d))
            self.assertTrue(eh.install(d))                                             # idempotent
            self.assertEqual([n for n, _ in d.post_step_hooks], ["harness_spaces"])
            self.assertEqual([n for n, _ in d.genesis_hooks], ["harness_spaces_genesis"])
            self.assertNotIn(eh.EXECUTOR, d.executors)
            eh.uninstall(d)
            self.assertEqual((d.post_step_hooks, d.genesis_hooks), ([], []))
        finally:
            patcher.stop()

    def test_boot_refuses_without_bounded_perception_naming_the_flag(self):
        with mock.patch.dict(os.environ, {"EDEN_SPACES": "1"}, clear=False):
            os.environ.pop("EDEN_PERCEPTION_BOUNDED", None)
            with self.assertRaises(spaces.SpaceConfigError) as caught:
                eh.install(Dispatcher())
            self.assertIn("EDEN_PERCEPTION_BOUNDED=1", str(caught.exception))

    def test_flag_off_installs_nothing(self):
        patcher = env(False)
        try:
            os.environ.pop(eh.FLAG, None)
            d = Dispatcher()
            self.assertFalse(eh.install(d))
            self.assertEqual((d.step_hooks, d.post_step_hooks, d.genesis_hooks, d.executors), ([], [], [], {}))
        finally:
            patcher.stop()


class LiveColumnTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        DISPATCH.clear()

    async def asyncTearDown(self):
        eh.uninstall(DISPATCH)
        DISPATCH.clear()
        await super().asyncTearDown()

    async def world(self, on=True):
        patcher = env(on)
        self.addCleanup(patcher.stop)
        if on:
            eh.install(DISPATCH)
        engine = await real_world()
        return engine

    async def test_authored_rows_carry_the_space_of_their_map_and_the_rest_are_overworld(self):
        engine = await self.world(True)
        m = engine.state.m_tensor
        slot_of = {uid: slot for slot, uid in enumerate(engine._entity_uid_by_slot) if uid}
        seen = set()
        for index, entry in enumerate(placed_group("starter_village")):
            for entity in entry["entities"]:
                if entity["id"] in slot_of:
                    seen.add(index)
                    self.assertEqual(int(m[slot_of[entity["id"]], cfg.M_SPACE]), index, entity["id"])
        self.assertTrue({1, 2, 3} <= seen, "interior maps declare interactive entities")
        authored_slots = {slot_of[e["id"]] for entry in placed_group("starter_village")[1:] for e in entry["entities"] if e["id"] in slot_of}
        live = (m[:, cfg.M_TYPE] > 0).nonzero().flatten().tolist()
        self.assertTrue(all(int(m[i, cfg.M_SPACE]) == 0 for i in live if i not in authored_slots))
        h = engine.state.h_tensor
        for i in range(h.shape[0]):                              # residents: the smith starts in the smith interior, the others outside
            self.assertEqual(int(h[i, cfg.H_SPACE]), spaces.space_at(engine, float(h[i, cfg.X]), float(h[i, cfg.Y])), i)
        self.assertEqual(int(h[0, cfg.H_SPACE]), spaces.space_of_map(engine, "smith_interior"), "the first resident is the smith, inside")

    async def test_portal_round_trip_sets_h_space_in_the_same_tick(self):
        engine = await self.world(True)
        h = engine.state.h_tensor
        envelope = claim(engine, 128.0, 110.0)                 # a direct write of the position, as the portal tests do
        spaces.refresh(engine)
        self.assertEqual(int(h[0, cfg.H_SPACE]), 0)
        payload, _ = submit(engine, envelope)
        engine.step()
        self.assertEqual(engine.command_inbox.result(payload["command_id"])["status"], "applied")
        self.assertEqual(int(h[0, cfg.H_SPACE]), spaces.space_of_map(engine, "smith_interior"))
        back = find_portal("starter_village", "smith:portal_village")
        h[0, cfg.X], h[0, cfg.Y] = back["from"][0], back["from"][1] + 6.0
        payload, _ = submit(engine, envelope, portal_id="smith:portal_village")
        engine.step()
        self.assertEqual(engine.command_inbox.result(payload["command_id"])["status"], "applied")
        self.assertEqual(int(h[0, cfg.H_SPACE]), 0)

    async def test_post_step_hook_catches_a_move_done_by_any_other_path(self):
        engine = await self.world(True)
        h = engine.state.h_tensor
        self.assertIn("harness_spaces", [name for name, _ in DISPATCH.post_step_hooks])
        self.assertIn("harness_spaces_genesis", [name for name, _ in DISPATCH.genesis_hooks])
        target = find_portal("starter_village", PORTAL)["to"]
        h[1, cfg.X], h[1, cfg.Y] = target[0], target[1]                      # what a teleport power or a god command does
        self.assertEqual(int(h[1, cfg.H_SPACE]), 0)
        hook = dict(DISPATCH.post_step_hooks)["harness_spaces"]               # alone: the roster's motion-limit hook would pull the move back
        hook(engine)
        self.assertEqual(int(h[1, cfg.H_SPACE]), spaces.space_of_map(engine, "smith_interior"))
        h[1, cfg.X], h[1, cfg.Y] = 100.0, 100.0
        hook(engine)
        self.assertEqual(int(h[1, cfg.H_SPACE]), 0)
        self.assertEqual(DISPATCH.errors, [] if isinstance(DISPATCH.errors, list) else DISPATCH.errors)

    async def test_the_hook_runs_inside_a_real_tick(self):
        engine = await self.world(True)
        h = engine.state.h_tensor
        h[1, cfg.H_SPACE] = 3.0                                               # stale value; the resident stands in the village
        engine.step()
        self.assertEqual(int(h[1, cfg.H_SPACE]), spaces.space_at(engine, float(h[1, cfg.X]), float(h[1, cfg.Y])))

    async def test_refresh_equals_a_recomputation_from_positions_on_random_states(self):
        engine = await self.world(True)
        rects = spaces.rectangles(engine)
        rng = random.Random(1008)
        corners = [c for _, x0, y0, x1, y1 in rects for c in ((x0, y0), (x1, y1), (x0, y1), (x1, y0), (x0 - 0.5, y0), (x1 + 0.5, y1))]
        h, m = engine.state.h_tensor, engine.state.m_tensor
        for round_ in range(5):
            for tensor, (xc, yc, sc) in ((h, (cfg.X, cfg.Y, cfg.H_SPACE)), (m, (cfg.CX, cfg.CY, cfg.M_SPACE))):
                n = tensor.shape[0]
                points = corners + [(rng.uniform(-100, 1400), rng.uniform(-100, 900)) for _ in range(n)]
                for i in range(n):
                    tensor[i, xc], tensor[i, yc] = points[i]
                    tensor[i, sc] = float(rng.randint(0, 3))                     # junk to overwrite
            spaces.refresh(engine)
            for tensor, (xc, yc, sc) in ((h, (cfg.X, cfg.Y, cfg.H_SPACE)), (m, (cfg.CX, cfg.CY, cfg.M_SPACE))):
                for i in range(tensor.shape[0]):
                    self.assertEqual(int(tensor[i, sc]), spaces.space_at(engine, float(tensor[i, xc]), float(tensor[i, yc])), (round_, i))
            self.assertEqual(spaces.refresh(engine), 0, "a second refresh changes nothing")

    async def test_a_power_applied_through_the_executor_refreshes_before_the_next_tick(self):
        engine = await self.world(True)
        h = engine.state.h_tensor
        target = find_portal("starter_village", PORTAL)["to"]
        h[1, cfg.X], h[1, cfg.Y] = target[0], target[1]
        with mock.patch.dict(os.environ, {eh.FLAG: "1"}):
            with mock.patch("harness.powers.call") as call:
                plan = mock.Mock(errors=[], risk="", targets=[], preview={}, effects=[])
                call.return_value = mock.Mock(ok=True, reason="", plan=plan, event_ids=[], replanned=False)
                result = eh.execute_power(engine, "harness_power", {"power": "noop", "args": {}})
        self.assertTrue(result["ok"])
        self.assertEqual(int(h[1, cfg.H_SPACE]), spaces.space_of_map(engine, "smith_interior"))


    async def test_gated_refresh_skips_the_entity_column_until_the_entity_set_changes_or_every_20_ticks(self):
        engine = await self.world(True)
        h, m = engine.state.h_tensor, engine.state.m_tensor
        smith = spaces.space_of_map(engine, "smith_interior")
        row = next(i for i in range(m.shape[0]) if int(m[i, cfg.M_TYPE]) > 0 and int(m[i, cfg.M_SPACE]) == 0)
        target = find_portal("starter_village", PORTAL)["to"]
        engine.tick = 1
        spaces.refresh(engine, gated=True)                                    # records the signature
        m[row, cfg.CX], m[row, cfg.CY] = target[0], target[1]                 # a row moved into the interior, no event
        h[1, cfg.X], h[1, cfg.Y] = target[0], target[1]
        engine.tick = 2
        spaces.refresh(engine, gated=True)
        self.assertEqual(int(h[1, cfg.H_SPACE]), smith, "the human column is refreshed on every gated call")
        self.assertEqual(int(m[row, cfg.M_SPACE]), 0, "the entity column is skipped while the entity set is unchanged")
        engine.tick = 40                                                      # safety net
        spaces.refresh(engine, gated=True)
        self.assertEqual(int(m[row, cfg.M_SPACE]), smith)
        m[row, cfg.CX], m[row, cfg.CY] = 100.0, 100.0
        engine.tick = 41
        spaces.refresh(engine, gated=True)
        self.assertEqual(int(m[row, cfg.M_SPACE]), smith)                     # skipped again
        engine._force_map_refresh = True                                      # an event the engine itself raises
        spaces.refresh(engine, gated=True)
        self.assertEqual(int(m[row, cfg.M_SPACE]), 0)
        engine._force_map_refresh = False
        m[row, cfg.CX], m[row, cfg.CY] = target[0], target[1]
        engine.tick = 42
        spaces.refresh(engine, gated=True)                                    # signature changed back: refreshed
        self.assertEqual(int(m[row, cfg.M_SPACE]), smith)
        m[row, cfg.CX], m[row, cfg.CY] = 100.0, 100.0
        engine.tick = 43
        spaces.refresh(engine)                                                # ungated refresh always does both columns
        self.assertEqual(int(m[row, cfg.M_SPACE]), 0)

    async def test_the_registered_post_step_hook_is_the_gated_one(self):
        engine = await self.world(True)
        with mock.patch.object(spaces, "refresh") as refresh:
            dict(DISPATCH.post_step_hooks)["harness_spaces"](engine)
        refresh.assert_called_once_with(engine, gated=True)
        self.assertEqual(spaces.FULL_REFRESH_EVERY, 20)

    async def test_flag_off_writes_no_space_column(self):
        engine = await self.world(False)
        h, m = engine.state.h_tensor, engine.state.m_tensor
        self.assertEqual(float(h[:, cfg.H_SPACE].abs().sum()), 0.0)
        self.assertEqual(float(m[:, cfg.M_SPACE].abs().sum()), 0.0)
        envelope = claim(engine, 128.0, 110.0)
        submit(engine, envelope)
        engine.step()
        self.assertGreater(position(engine)[0], 500.0)                              # it really moved into the interior
        self.assertEqual(int(h[0, cfg.H_SPACE]), 0)
        self.assertEqual(spaces.refresh(engine), 0)


if __name__ == "__main__":
    unittest.main()
