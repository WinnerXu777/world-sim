"""1008 Part 2.A1 (1008_instincts_wiring_gap.md step 1): EDEN_STEERING registers the six steering instincts the default registry never had.

The registration (order, priorities, once, only with the flag), the keys the entries put in the tick context when run the way ``Engine.step`` runs them, and a hungry human whose
survival bias points at food. The invisibility in a roster world is the strict-golden gate, not a unit test."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_harness_window_manager import WindowFixture  # noqa: E402
import genesis_config as cfg  # noqa: E402
import map_geo  # noqa: E402
from harness import engine_hooks, steering  # noqa: E402


class SteeringFixture(WindowFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        patcher = mock.patch.dict(os.environ, {"EDEN_STEERING": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.registry = self.engine._registry
        self.saved = list(self.registry)
        self.addCleanup(lambda: self.registry.__setitem__(slice(None), self.saved))


class RegistrationTests(SteeringFixture):
    def names(self):
        return [e["fn"].__name__ for e in self.registry]

    async def test_the_genesis_hook_registers_the_six_between_occupancy_and_move_only_with_the_flag(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_STEERING")
            engine_hooks.steering_genesis_hook(self.engine)
            self.assertFalse(any(n in self.names() for n, _ in steering.ENTRIES))
        engine_hooks.steering_genesis_hook(self.engine)
        engine_hooks.steering_genesis_hook(self.engine)
        names = self.names()
        for name, priority in steering.ENTRIES:
            self.assertEqual(names.count(name), 1, name)
            self.assertEqual(next(e for e in self.registry if e["fn"].__name__ == name)["priority"], priority)
        order = [n for n in names if n in {name for name, _ in steering.ENTRIES}]
        self.assertEqual(order, [name for name, _ in steering.ENTRIES])
        self.assertLess(names.index("instinct_structure_occupancy"), names.index("instinct_pairwise_relations"))
        self.assertLess(names.index("instinct_schedule_navigation"), names.index("instinct_move"))

    async def test_the_boot_installs_the_genesis_hook_only_with_the_flag(self):
        from simulation.dispatch import DISPATCH
        self.addCleanup(engine_hooks.uninstall, DISPATCH)
        with mock.patch.dict(os.environ):
            os.environ.pop("EDEN_STEERING")
            engine_hooks.uninstall(DISPATCH)
            engine_hooks.install(DISPATCH)
            self.assertNotIn("harness_steering_genesis", {n for n, _ in DISPATCH.genesis_hooks})
        engine_hooks.uninstall(DISPATCH)
        engine_hooks.install(DISPATCH)
        self.assertIn("harness_steering_genesis", {n for n, _ in DISPATCH.genesis_hooks})


class ContextTests(SteeringFixture):
    def run_entries(self, h_mask):
        """The registered steering entries, run in registry order the way ``Engine.step`` runs them."""
        ctx = {"h_mask": h_mask, "a_mask": torch.zeros_like(h_mask), "engine": self.engine}
        kwargs = self.engine._build_kwargs()
        wanted = {name for name, _ in steering.ENTRIES}
        for entry in self.registry:
            if entry["fn"].__name__ in wanted:
                result = entry["fn"](ctx, **{**kwargs, **entry["kwargs"]})
                if result is not None:
                    ctx.update(result)
        return ctx

    async def test_a_hungry_human_is_pulled_toward_food_and_a_fed_one_is_not(self):
        engine_hooks.steering_genesis_hook(self.engine)
        self.place_human(0, 500.0, 500.0)
        self.place_human(1, 500.0, 700.0)
        h = self.engine.state.h_tensor
        for slot, hunger in ((0, 90.0), (1, 5.0)):
            h[slot, cfg.HP], h[slot, cfg.HUNGER], h[slot, cfg.H_STAMINA], h[slot, cfg.THIRST] = 100.0, hunger, 100.0, 5.0
        (food,) = self.manager.allocator.allocate(["food:1"], [cfg.M_GRASS], [620.0], [500.0], {cfg.M_HP: [100.0], cfg.SCALE: [10.0], cfg.M_RESOURCE_FOOD: [100.0]})
        self.addCleanup(self.manager.allocator.release, [food])
        map_geo.register_entity(food, "circle", 620.0, 500.0, 10.0)
        mask = torch.zeros(h.shape[0], dtype=torch.bool)
        mask[[0, 1]] = True
        ctx = self.run_entries(mask)
        bias = ctx.get("nav_survival_bias")
        self.assertIsNotNone(bias, "the survival entry ran and produced its bias")
        self.assertGreater(float(bias[0, 0]), 0.0, "food is at +x: the hungry one leans that way")
        self.assertGreater(float(bias[0].norm()), float(bias[1].norm()))
        self.assertIn("pairwise_pre", ctx, "the pairwise entry filled its context key")
        self.assertIn("seek_mask", ctx)

    async def test_without_the_flag_none_of_the_keys_appear(self):
        ctx = self.run_entries(torch.zeros(self.engine.state.h_tensor.shape[0], dtype=torch.bool))
        self.assertNotIn("nav_survival_bias", ctx)


if __name__ == "__main__":
    unittest.main()
