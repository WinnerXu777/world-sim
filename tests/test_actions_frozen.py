"""D-005: the old frontier tools (``instinct_frontier_expand``, ``tool_expand_world_edge``) are frozen. No catalog row, affordance verb, plan op or Tier 1
macro offers them, and the runner, the plan adapter and the Tier 3 gate answer ``legacy_frozen`` if a tier names one anyway."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from systems.actions import BY_ID, CATALOG, REGISTRY  # noqa: E402
from systems.actions.catalog import FROZEN_LEGACY  # noqa: E402
from systems.actions.plan_adapter import from_legacy, to_legacy  # noqa: E402
from systems.actions.plan_ops import PLAN_OPS  # noqa: E402
from systems.affordance import VERBS  # noqa: E402
from systems.decision.matrix import MENU  # noqa: E402
from systems.modelplane.tier3.parsers import gate_plan  # noqa: E402
from systems.modelplane.tier3.types import PlanProposal  # noqa: E402
from test_actions_runner import Scene  # noqa: E402


class FrozenFrontierTools(unittest.TestCase):
    def test_the_set_is_the_two_decided_tools(self):
        self.assertEqual(FROZEN_LEGACY, {"instinct_frontier_expand", "tool_expand_world_edge"})

    def test_no_vocabulary_lists_them(self):
        for name in FROZEN_LEGACY:
            self.assertNotIn(name, BY_ID)
            self.assertNotIn(name, REGISTRY.actions)
            self.assertNotIn(name, VERBS)
            self.assertNotIn(name, PLAN_OPS)
            self.assertNotIn(name, MENU)
        self.assertFalse([row.id for row in CATALOG if "frontier" in row.id or "expand" in row.id])

    def test_the_runner_refuses_them_for_every_proposer(self):
        scene = Scene()
        for name in FROZEN_LEGACY:
            for proposer in ("rules", "tier1", "tier2", "tier3"):
                result = scene.runner.run("h_a", name, {}, proposer=proposer, confidence=0.99)
                self.assertFalse(result.ok)
                self.assertEqual(result.code, "legacy_frozen", (name, proposer))

    def test_the_plan_adapter_leaves_them_unmapped_in_both_directions(self):
        for name in FROZEN_LEGACY:
            self.assertEqual(from_legacy([{"op": name}]), {"steps": [], "unmapped": [(0, name, "legacy_frozen")]})
            self.assertEqual(to_legacy([{"op": name, "args": {}}]), {"steps": [], "unmapped": [(0, name, "legacy_frozen")]})

    def test_the_tier3_gate_rejects_a_plan_that_names_them(self):
        scene = Scene()
        for name in FROZEN_LEGACY:
            plan = PlanProposal("h_a", ({"op": "rest", "args": {}}, {"op": name, "args": {}}), 0.99)
            gate = gate_plan(plan, scene.runner, "h_a")
            self.assertFalse(gate.ok)
            self.assertEqual(gate.reason, f"legacy_frozen:{name}")


if __name__ == "__main__":
    unittest.main()
