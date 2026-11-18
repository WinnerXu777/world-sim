"""Resource-node verbs (G-005, behind ``EDEN_MAP_RESOURCES=1``): ``eat_from_node`` and ``gather_from_node``.

Thin wrappers over ``harness/resources.py`` (the effect builders the Harness plane owns): ``ActionDraft(d.effects, d.event, [], d.preview,
produces=d.produces)``. Gathering creates items, so the draft declares ``produces`` and the runner builds the ``ItemPermit`` from it; eating creates
and destroys nothing. They are *not* among the 65 catalog verbs (that vocabulary is pinned by ``tests/test_actions_catalog.py``): they live on their
own ``RESOURCE_REGISTRY``, and a runner without an explicit registry uses ``default_registry()``, the S1 registry plus these two while the flag is on (and the market verbs, ``market_verbs.py``, while ``EDEN_MARKET`` is on).
"""
from __future__ import annotations

from harness import resources
from harness.registry import Registry, action

from .draft import ActionDraft, ActionRefused

RESOURCE_REGISTRY = Registry()


def _node_items() -> tuple:
    from systems.map import resources as map_resources
    return tuple(sorted(set(map_resources.ITEM.values())))


@action("eat_from_node", risk="reversible", precondition="can_eat_from_node", registry=RESOURCE_REGISTRY)
def eat_from_node(world, ctx, node: str = "") -> ActionDraft:
    """Eat from a food resource node (berries, mushrooms, fish) the resident stands at: hunger relief, node food down by one unit."""
    try:
        draft = resources.eat_from_node(world, ctx.actor, node)
    except resources.ResourceRefused as refused:
        raise ActionRefused(refused.reason, refused.detail)
    return ActionDraft(draft.effects, draft.event, [], draft.preview, produces=draft.produces)


@action("gather_from_node", risk="reversible", precondition="can_gather", produces=_node_items(), registry=RESOURCE_REGISTRY)
def gather_from_node(world, ctx, node: str = "", qty: int = 1) -> ActionDraft:
    """Gather qty units from a resource node the resident stands at: the stock leaves the node and the same number of items enter the pack."""
    try:
        draft = resources.gather(world, ctx.actor, node, qty)
    except resources.ResourceRefused as refused:
        raise ActionRefused(refused.reason, refused.detail)
    return ActionDraft(draft.effects, draft.event, [], draft.preview, produces=draft.produces)


@action("approach_node", risk="reversible", precondition="can_approach_node", registry=RESOURCE_REGISTRY)
def approach_node(world, ctx, node: str = "") -> ActionDraft:
    """Walk to a resource node in sight: a ``move_to_place`` point task to the node's centre (inside the node's circle, so ``eat_from_node`` /
    ``gather_from_node`` are legal on arrival). For an anchor-driven roster resident the task would stay inert, so it is refused there."""
    from .draft import queue_task, roster_driven
    from .verbs.common import emit
    roster_driven(ctx, "walking to a node needs the resident's own movement; the anchor driver moves a roster resident only to its anchors")
    detail = ctx.verdict.detail
    ops = [queue_task("move_to_place", priority=0.45, summary=f"walk to {node}", target_kind="point", target_place={"x": detail["x"], "y": detail["y"]},
                      metadata={"via": "action", "node": node})]
    return ActionDraft([], emit(world, ctx.actor, "approached_node", {"node": node}, visibility="private"), ops, {"node": node, "distance": ctx.verdict.distance})


_COMBINED: dict = {}


def default_registry() -> Registry:
    """The registry a runner uses when it is given none: the S1 verbs, plus the node verbs while ``EDEN_MAP_RESOURCES`` is on, the market verbs while ``EDEN_MARKET`` is on the credit verbs while ``EDEN_CREDIT`` is on and the labour verbs while ``EDEN_LABOUR`` is on the justice verbs while ``EDEN_JUSTICE`` is on, the bond verbs while ``EDEN_BONDS`` is on and the place-memory verbs while ``EDEN_PLACES`` is on."""
    from systems.map import resources as map_resources
    from systems import market
    from .verbs import REGISTRY
    extras = []
    if map_resources.enabled():
        extras.append(RESOURCE_REGISTRY)
        from .market_day import balance_enabled
        if balance_enabled():
            from .economy_verbs import ECONOMY_REGISTRY
            extras.append(ECONOMY_REGISTRY)
    if market.enabled():
        from .market_verbs import MARKET_REGISTRY
        extras.append(MARKET_REGISTRY)
    from systems import credit
    if credit.enabled():
        from .credit_verbs import CREDIT_REGISTRY
        extras.append(CREDIT_REGISTRY)
    from systems import labour
    if labour.enabled():
        from .labour_verbs import LABOUR_REGISTRY
        extras.append(LABOUR_REGISTRY)
    from systems import justice
    if justice.enabled():
        from .justice_verbs import JUSTICE_REGISTRY
        extras.append(JUSTICE_REGISTRY)
    from systems import bonds
    if bonds.enabled():
        from .bonds_verbs import BONDS_REGISTRY
        extras.append(BONDS_REGISTRY)
    from systems import places
    if places.enabled():
        from .places_verbs import PLACES_REGISTRY
        extras.append(PLACES_REGISTRY)
    from systems import guard
    if guard.enabled():
        from .guard_verbs import GUARD_REGISTRY
        extras.append(GUARD_REGISTRY)
    from harness import temperature, wounds
    if temperature.enabled() or wounds.enabled():
        from .care_verbs import CARE_REGISTRY
        extras.append(CARE_REGISTRY)
    from systems import rob
    if rob.enabled():
        from .rob_verbs import ROB_REGISTRY
        extras.append(ROB_REGISTRY)
    if not extras:
        return REGISTRY
    key = tuple(id(r) for r in extras)
    cached = _COMBINED.get(key)
    if cached is None or len(cached.actions) != len(REGISTRY.actions) + sum(len(r.actions) for r in extras):
        combined = Registry()
        combined.actions = {**REGISTRY.actions}
        for registry in extras:
            combined.actions.update(registry.actions)
        cached = _COMBINED[key] = combined
    return cached
