"""
Canonical generated-tool templates for smaller open-source models.

This file is a reference only. It shows the preferred composition style:

1. import from a domain `ops` module
2. keep mask/selection logic small
3. avoid raw tensor column writes when a helper exists
4. return a minimal semantic payload
"""

from __future__ import annotations

from typing import Any


HEALTH_TOOL_TEMPLATE = """
try:
    from systems.health.ops import apply_plague, apply_bless, damage_humans, kill_humans_now
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.health.ops import apply_plague, apply_bless, damage_humans, kill_humans_now


def tool_example_health_effect(ctx: dict, h_tensor, mask=None, **_) -> dict:
    h_mask = ctx["h_mask"]
    affected = (mask & h_mask) if mask is not None else h_mask
    if not affected.any():
        return {}
    apply_plague(affected, h_tensor, decay_rate=3.0, infection_gain=10.0)
    return {}
""".strip()


NATURE_TOOL_TEMPLATE = """
try:
    from systems.nature.ops import trigger_storm, trigger_wildfire
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.nature.ops import trigger_storm, trigger_wildfire


def tool_example_nature_event(ctx: dict, h_tensor, m_tensor, *, center_x: float, center_y: float, radius: float, device: str = "cpu", **_) -> dict:
    return trigger_storm(
        ctx,
        h_tensor,
        center_x=center_x,
        center_y=center_y,
        radius=radius,
        device=device,
        agent_radial_mask_fn=_agent_radial_mask,
    )
""".strip()


FULL_TEMPLATE = """
from __future__ import annotations

try:
    from systems.<domain>.ops import <helper_names>
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.<domain>.ops import <helper_names>


def tool_<name>(ctx: dict, h_tensor=None, m_tensor=None, **_) -> dict:
    # 1. Build the smallest valid mask or target set.
    # 2. Call reusable ops helpers.
    # 3. Return only the semantic flags the engine needs.
    return {}
""".strip()


ANTI_PATTERN_NOTES = [
    "Do not start by writing raw tensor columns if an ops helper already exists.",
    "Do not import the giant instincts_and_tools.py file into a new generated helper module.",
    "Do not hardcode keyboard, mouse, or renderer-specific behavior into tool logic.",
    "If the helper you need does not exist, add it to the domain ops layer first.",
]


def print_templates() -> None:
    print("--- Health Tool Template ---")
    print(HEALTH_TOOL_TEMPLATE)
    print()
    print("--- Nature Tool Template ---")
    print(NATURE_TOOL_TEMPLATE)
    print()
    print("--- Full Skeleton ---")
    print(FULL_TEMPLATE)
    print()
    print("--- Anti-Patterns ---")
    for note in ANTI_PATTERN_NOTES:
        print(f"- {note}")


if __name__ == "__main__":
    print_templates()
