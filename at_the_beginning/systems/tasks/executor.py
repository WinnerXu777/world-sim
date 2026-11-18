from __future__ import annotations

"""Compatibility re-export layer for the refined task package layout."""

from .dispatcher import execute_active_task_step
from .families.combat import combat_task_specs
from .families.occupation import (
    baseline_provisioning_task_specs,
    baseline_task_candidates,
    builder_work_task_specs,
    farmer_work_task_specs,
    fisherman_work_task_specs,
    gatherer_work_task_specs,
    guard_work_task_specs,
    healer_work_task_specs,
    hunter_work_task_specs,
    routine_task_specs,
    should_activate_builder_work,
    should_activate_farmer_work,
    should_activate_fisherman_work,
    should_activate_gatherer_work,
    should_activate_guard_work,
    should_activate_healer_work,
    should_activate_hunter_work,
    should_activate_trader_work,
    should_activate_woodcutter_work,
    suggested_occupation_task_kind,
    trader_work_task_specs,
    woodcutter_work_task_specs,
)
from .families.social import social_task_specs
from .families.strategic import strategic_task_specs
from .families.survival import survival_task_specs

__all__ = [
    "baseline_provisioning_task_specs",
    "baseline_task_candidates",
    "builder_work_task_specs",
    "combat_task_specs",
    "execute_active_task_step",
    "farmer_work_task_specs",
    "fisherman_work_task_specs",
    "gatherer_work_task_specs",
    "guard_work_task_specs",
    "healer_work_task_specs",
    "hunter_work_task_specs",
    "routine_task_specs",
    "social_task_specs",
    "strategic_task_specs",
    "should_activate_builder_work",
    "should_activate_farmer_work",
    "should_activate_fisherman_work",
    "should_activate_gatherer_work",
    "should_activate_guard_work",
    "should_activate_healer_work",
    "should_activate_hunter_work",
    "should_activate_trader_work",
    "should_activate_woodcutter_work",
    "survival_task_specs",
    "suggested_occupation_task_kind",
    "trader_work_task_specs",
    "woodcutter_work_task_specs",
]
