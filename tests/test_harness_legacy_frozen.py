"""D-005: the legacy frontier expansion is frozen. Not deleted, not registered, not offered (registry loader, prompt builder, manifest,
NL parser) and refused by name with reason ``legacy_frozen``; ``genesis_config.FREEZE_LEGACY_FRONTIER = False`` brings it all back."""
import sys
import unittest
from pathlib import Path
from unittest import mock

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from authored_village import load_village_maps  # noqa: E402
from test_startup_preservation import backend  # noqa: E402,F401  (sets the isolated data root and imports map_test)
from test_map_contract import AsyncRegistryIsolation  # noqa: E402
import genesis_config as cfg  # noqa: E402
import instincts_and_tools as iat  # noqa: E402
from harness import legacy_manifest as lm  # noqa: E402
from harness.registry import Registry  # noqa: E402
from runtime import execution_support  # noqa: E402
from systems.actions.catalog import FROZEN_LEGACY as ACTIONS_FROZEN  # noqa: E402
from models import tools_and_instincts_registry as models_registry  # noqa: E402

NAMES = {"instinct_frontier_expand", "tool_expand_world_edge"}


def unfrozen():
    return mock.patch.object(cfg, "FREEZE_LEGACY_FRONTIER", False)


class SwitchTests(unittest.TestCase):
    def test_one_list_of_names_everywhere_and_the_default_is_frozen(self):
        self.assertTrue(cfg.FREEZE_LEGACY_FRONTIER)
        self.assertEqual(set(cfg.FROZEN_FRONTIER_TOOLS), NAMES)
        self.assertEqual(set(lm.FROZEN_LEGACY), NAMES)
        self.assertEqual(set(ACTIONS_FROZEN), NAMES)              # the Model plane's own list agrees

    def test_the_code_is_kept_not_deleted(self):
        for name in NAMES:
            self.assertTrue(callable(getattr(iat, name)), name)

    def test_the_instinct_is_not_registered_while_frozen_and_is_again_when_unfrozen(self):
        self.assertNotIn(iat.instinct_frontier_expand, [fn for fn, _, _ in iat.default_registry_entries()])
        with unfrozen():
            self.assertIn(iat.instinct_frontier_expand, [fn for fn, _, _ in iat.default_registry_entries()])

    def test_the_tool_refuses_by_name_and_touches_nothing(self):
        h, m = torch.zeros((4, cfg.HUMAN_TENSOR_COLS)), torch.zeros((8, 16))
        before = (h.clone(), m.clone())
        refs = [0]
        result = iat.tool_expand_world_edge({"h_mask": h[:, 0] > 0}, h, m, refs, edge="east")
        self.assertEqual((result["ok"], result["reason"]), (False, "legacy_frozen"))
        self.assertTrue(torch.equal(h, before[0]) and torch.equal(m, before[1]))
        self.assertEqual(refs, [0])
        self.assertEqual(iat.instinct_frontier_expand({"h_mask": h[:, 0] > 0}, h, m, refs, engine=None), {})


class ListingTests(unittest.TestCase):
    def test_the_tool_registry_loader_and_prompt_builder_leave_them_out(self):
        self.assertNotIn("tool_expand_world_edge", execution_support.load_registry_entries())
        self.assertNotIn("tool_expand_world_edge", models_registry.build_registry_string())
        self.assertNotIn("instinct_frontier_expand", models_registry.build_registry_string())
        with unfrozen():
            self.assertIn("tool_expand_world_edge", execution_support.load_registry_entries())

    def test_the_manifest_flags_them_and_the_listing_omits_them(self):
        rows = {row["id"]: row for row in lm.legacy_entries()}
        for name in NAMES:
            self.assertTrue(rows[name]["legacy_frozen"], name)
        self.assertFalse(rows["instinct_hunger"]["legacy_frozen"])
        listing = Registry().manifest(legacy=list(rows.values()))
        listed = {row["id"] for row in listing["legacy"]}
        self.assertTrue(NAMES.isdisjoint(listed))
        self.assertIn("instinct_hunger", listed)
        self.assertEqual(listing["legacy_frozen"], sorted(NAMES))

    def test_no_harness_power_system_or_action_carries_the_names(self):
        from harness import powers
        manifest = powers.REGISTRY.manifest(legacy=lm.legacy_entries())
        for section in ("systems", "actions", "powers", "legacy"):
            self.assertTrue(NAMES.isdisjoint({row["id"] for row in manifest[section]}), section)


class EngineTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        load_village_maps()
        self.engine = backend.engine
        self.engine.reset_world()
        await backend.create_genesis(self.engine, map_name="starter_village")

    def test_the_live_engine_does_not_run_the_instinct(self):
        names = [getattr(e["fn"], "__name__", "") for e in self.engine._registry]
        self.assertNotIn("instinct_frontier_expand", names)

    def test_the_nl_parser_answers_with_a_stable_reason_instead_of_an_action(self):
        packet = self.engine.world_agent._heuristic_plan("expand the frontier to the east", self.engine)
        self.assertNotIn("tool_expand_world_edge", [a["tool_name"] for a in packet["map_actions"]])
        self.assertEqual(packet["skipped_actions"], [{"tool_name": "tool_expand_world_edge", "reason": "legacy_frozen"}])
        with unfrozen():
            packet = self.engine.world_agent._heuristic_plan("expand the frontier to the east", self.engine)
            self.assertIn("tool_expand_world_edge", [a["tool_name"] for a in packet["map_actions"]])
            self.assertNotIn("skipped_actions", packet)

    def test_a_direct_runtime_call_gets_the_frozen_reason(self):
        action = {"tool_name": "tool_expand_world_edge", "parameters": {"edge": "east"}}
        for runner in (self.engine.execution_agent, self.engine.world_agent):
            if hasattr(runner, "_execute_action"):
                result = runner._execute_action(self.engine, dict(action))
                self.assertFalse(result["ok"], runner)
                self.assertEqual(result["reason"], "legacy_frozen", runner)


if __name__ == "__main__":
    unittest.main()
