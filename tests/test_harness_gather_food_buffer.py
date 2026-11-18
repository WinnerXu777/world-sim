"""1008 P5 follow-up: ``strategic._handle_gather_food_buffer`` takes the food from the resolved source.

The resolver (``Engine._resolve_task_resource_target``) returns the row as ``slot``; the handler used to read ``entity_id``, a key that is not there, so
it always consumed row -1 and ended ``food_source_empty`` (the task could never succeed). Same wiring as ``map_test`` builds for the real bridge."""
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from test_startup_preservation import backend  # noqa: E402,F401  (sets the isolated data root and imports map_test)
from test_map_contract import AsyncRegistryIsolation  # noqa: E402
from test_map_portals import real_world  # noqa: E402
import genesis_config as cfg  # noqa: E402
import instincts_and_tools as iat  # noqa: E402
import map_geo  # noqa: E402
from systems.tasks.contracts import TaskWorldBridge  # noqa: E402
from systems.tasks.families import strategic  # noqa: E402


class GatherFoodBufferTests(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.engine = await real_world()
        self.m = self.engine.state.m_tensor

    def context(self, px, py):
        engine = self.engine
        bridge = TaskWorldBridge(
            gather_radius=24.0,
            resolve_resource_target=lambda kind, x, y, radius=220.0: engine._resolve_task_resource_target(x, y, kind, radius=radius),
            consume_resource_amount=lambda kind, entity_id, quantity=1, **extra: engine._consume_task_resource(kind, entity_id, quantity=quantity, **extra),
            commit_action=lambda **kwargs: None)
        return types.SimpleNamespace(metadata={"desired_quantity": 1}, personal_inventory={"items": []}, bridge=bridge, px=px, py=py,
                                     task_state={}, resident={}, tick=1, set_intent=lambda *a, **k: None)

    def source(self, food):
        slot = iat.entity_born(self.m, self.engine._entity_count_ref, 60.0, 60.0, cfg.M_FOREST, hp=100.0, scale=10.0, register_geo=True,
                               device=self.engine.state.device, col_vals={cfg.M_RESOURCE_FOOD: food})
        self.addCleanup(map_geo.unregister_entity, slot)
        return slot

    async def test_a_nearby_source_is_consumed_and_a_ration_is_added(self):
        slot = self.source(40.0)
        context = self.context(62.0, 62.0)
        with mock.patch.object(strategic, "complete_current_task") as completed:
            self.assertTrue(strategic._handle_gather_food_buffer(context))
        self.assertNotEqual(context.task_state.get("blocked_reason"), "food_source_empty")
        self.assertLess(float(self.m[slot, cfg.M_RESOURCE_FOOD]), 40.0)
        self.assertEqual(sum(i["quantity"] for i in context.personal_inventory["items"] if i["kind"] == "rations"), 1)
        completed.assert_called_once()

    async def test_an_empty_source_still_reports_empty(self):
        self.source(0.0)
        context = self.context(62.0, 62.0)
        self.assertFalse(strategic._handle_gather_food_buffer(context))
        self.assertEqual(context.task_state["blocked_reason"], "food_source_missing")      # the resolver skips rows with no food


if __name__ == "__main__":
    unittest.main()
