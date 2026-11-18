"""G-005 step 3: resource nodes on the harness. Regrowth as a system, eating and gathering as effect builders.

* ``regrow_nodes(world)``: the harness version of ``systems.nature.ecology.apply_node_regrow``. It computes the new stock of every
  live, not burning node with a positive ``growth_rate`` with the SAME float32 tensor expressions as the legacy function and applies
  them as ``Set`` effects (a per-row cap cannot be a column bound, and ``stock + (min(stock + gain, cap) - stock)`` is not always the
  legacy float32 value), then clears ``depleted_tick`` on nodes that have stock again and emits ``resource_regrown`` for them.
  Behind ``EDEN_HARNESS_RESOURCES=1`` (with ``EDEN_HARNESS=1``) ``install(engine)`` registers it right after the legacy
  ``instinct_resource_regrow`` entry and switches the legacy node regrow off (``engine.node_regrow_external``); the natural-entity
  food regrow and the water cycle stay legacy (they touch every natural row, which has no stable id until it is first addressed).
* ``eat_from_node`` / ``gather``: pure builders returning a ``NodeDraft`` (effects, event, ``consumes``/``produces``, preview) or
  raising ``ResourceRefused(reason, detail)``. Nothing is applied here and nothing in the engine calls them: the S1 verbs in
  ``systems/actions`` (not mine) wrap them. Eating keeps the legacy numbers (``EAT_HUNGER_RESTORE`` hunger relief, ``EAT_RESOURCE_COST``
  food, only while hunger is above 20 and the node has food) and creates or destroys no item. Gathering moves ``qty`` stock units out of
  the node and creates ``qty`` x yield items of the node's item, which is declared in ``produces`` so the runner gives the apply an
  ``ItemPermit(produce={item: qty})``. A node that reaches 0 gets ``depleted_tick`` set and a ``resource_depleted`` event.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Optional

import torch

from . import effects as fx
from .registry import Registry, system

FLAG = "EDEN_HARNESS_RESOURCES"
NAME = "resource_regrow_nodes"
REACH = 1.0                  # an actor acts on a node when it stands within the node's circle plus this margin (backend units)
HUNGER_FLOOR_TO_EAT = 20.0   # legacy eat_from_current_entity: a resident eats only while hunger > 20


def enabled() -> bool:
    from . import engine_hooks
    return os.environ.get(FLAG, "") == "1" and engine_hooks.enabled()


class ResourceRefused(Exception):
    """A refusal with a stable reason code: ``not_a_node``, ``not_edible``, ``too_far``, ``empty``, ``not_hungry``, ``bad_qty``, ``no_actor``, ``no_room``."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason, self.detail = reason, detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


@dataclass
class NodeDraft:
    effects: list = field(default_factory=list)
    event: Optional[fx.Emit] = None
    consumes: tuple = ()
    produces: tuple = ()
    preview: dict = field(default_factory=dict)


def _node_ids():
    from systems.map import resources as map_resources
    return map_resources


def build_registry() -> Registry:
    reg = Registry()

    @system("resource_regrow_nodes", phase="world", reads=("entities.growth_rate", "entities.node_cap", "entities.burning", "entities.node_kind"),
            writes=("entities.food", "entities.node_stock", "entities.depleted_tick"), registry=reg)
    def resource_regrow_nodes(world, food_multiplier: float = 1.0):
        """Resource nodes regrow growth_rate per tick up to their cap (edible nodes in food, material nodes in node_stock)."""
        return regrow_nodes(world, food_multiplier=food_multiplier)

    return reg


REGISTRY = build_registry()


def _cfg():
    import genesis_config as cfg
    return cfg


def regrow_nodes(world, food_multiplier: float = 1.0) -> Optional[int]:
    """Apply one tick of node regrowth through the world's applier. Returns the number of nodes whose stock was written, or None when a
    row has no stable id (the caller then uses the legacy function)."""
    from systems.nature.ecology import EDIBLE_NODE_KINDS
    cfg = _cfg()
    table = world.table("entities")
    m = table.tensor
    col = table.columns
    n = m.shape[0]
    nodes = m[:n, col["type"]] == float(cfg.M_RESOURCE_NODE)
    if not nodes.any():
        return 0
    live = nodes & (m[:n, col["burning"]] == 0) & (m[:n, col["growth_rate"]] > 0)
    uids = table.ids
    written = 0
    if live.any():
        gain = m[:n][live, col["growth_rate"]] * max(0.0, float(food_multiplier))
        edible = torch.isin(m[:n][live, col["node_kind"]].long(), EDIBLE_NODE_KINDS)
        rows = live.nonzero(as_tuple=False).flatten()
        cap = m[:n][live, col["node_cap"]]
        effects = []
        for field_name, pick in (("food", edible), ("node_stock", ~edible)):
            if not pick.any():
                continue
            r = rows[pick]
            ids = tuple(uids[s] for s in r.tolist())
            if not all(ids):
                return None
            new = torch.minimum(m[r, col[field_name]] + gain[pick], cap[pick].clamp(min=0.0))
            effects.append(fx.Set("entities", ids, field_name, new.tolist()))
            written += len(ids)
        if effects:
            world.apply(effects, cause="system:resource_regrow")
    recovered = (nodes & (m[:n, col["burning"]] == 0) & (m[:n, col["growth_rate"]] > 0) & (m[:n, col["depleted_tick"]] >= 0)
                 & ((m[:n, col["food"]] > 0) | (m[:n, col["node_stock"]] > 0)))
    if recovered.any():
        slots = recovered.nonzero(as_tuple=False).flatten().tolist()
        ids = tuple(uids[s] for s in slots)
        if not all(ids):
            return None
        tick = int(world.tick)
        effects = [fx.Set("entities", ids, "depleted_tick", -1.0)]
        for s, node_id in zip(slots, ids):
            effects.append(fx.Emit("resource_regrown", actors=(node_id,), place=(float(m[s, col["x"]]), float(m[s, col["y"]])),
                                   visibility="local", payload={"node": node_id}, event_id=f"res:{node_id}:{tick}:regrown"))
        world.apply(effects, cause="system:resource_regrow")
    return written


# -- install behind the flag ---------------------------------------------------------------------------------------------
def make_regrow_entry(legacy_regrow=None):
    """The registry entry. Falls back to the legacy node regrow when the engine has no harness world on this tensor or a node has no id."""
    from . import engine_hooks

    def instinct_resource_regrow_nodes(ctx: dict, m_tensor: torch.Tensor, engine=None, **_) -> None:
        modifiers = getattr(engine, "_nature_state", {}).get("modifiers", {}) if engine is not None else {}
        multiplier = float(modifiers.get("food_growth", 1.0))
        world = None if engine is None else engine_hooks.runtime(engine).world
        if world is not None and world.table("entities").tensor is m_tensor and regrow_nodes(world, food_multiplier=multiplier) is not None:
            return
        from systems.nature import ecology
        ecology.apply_node_regrow(m_tensor, food_multiplier=multiplier)

    return instinct_resource_regrow_nodes


def install(engine) -> bool:
    """Register ``instinct_resource_regrow_nodes`` after ``instinct_resource_regrow`` and stop the legacy function from regrowing nodes
    itself (idempotent). Returns True when installed or already installed."""
    entries = {getattr(e["fn"], "__name__", ""): e for e in engine._registry}
    if "instinct_resource_regrow_nodes" in entries:
        engine.node_regrow_external = True
        return True
    legacy = entries.get("instinct_resource_regrow")
    if legacy is None:
        return False
    engine.node_regrow_external = True
    engine.register(make_regrow_entry(), priority=legacy["priority"], **legacy["kwargs"])
    return True


def uninstall(engine) -> None:
    """Back to the legacy node regrow (tests; the genesis hook does the same at the start of every world)."""
    engine._registry = [e for e in engine._registry if getattr(e["fn"], "__name__", "") != "instinct_resource_regrow_nodes"]
    engine.node_regrow_external = False


# -- actions ---------------------------------------------------------------------------------------------------------------
def _node(world, node_id: str):
    cfg = _cfg()
    table = world.table("entities")
    slot = table.slot_of(node_id)
    if slot is None or int(table.get(node_id, "type")) != int(cfg.M_RESOURCE_NODE):
        raise ResourceRefused("not_a_node", f"{node_id!r} is not a live resource node")
    return table, slot


def _check_reach(world, actor: str, node_id: str, table) -> None:
    humans = world.table("humans")
    if humans.slot_of(actor) is None:
        raise ResourceRefused("no_actor", f"{actor!r} is not a live resident")
    ax, ay = float(humans.get(actor, "x")), float(humans.get(actor, "y"))
    nx, ny, radius = float(table.get(node_id, "x")), float(table.get(node_id, "y")), float(table.get(node_id, "scale"))
    if math.hypot(ax - nx, ay - ny) > radius + REACH:
        raise ResourceRefused("too_far", f"{actor!r} is {math.hypot(ax - nx, ay - ny):.1f} from {node_id!r} (reach {radius + REACH:.1f})")


def node_item(kind_id: int) -> str:
    res = _node_ids()
    name = next((k for k, v in res.NODE_KIND_IDS.items() if v == int(kind_id)), None)
    if name is None:
        raise ResourceRefused("not_a_node", f"unknown node kind {kind_id}")
    return res.ITEM[name]


def stock_field(kind_id: int) -> str:
    """Where the node keeps its stock: edible kinds in ``food`` (so eating and the scoring read it), material kinds in ``node_stock``."""
    from systems.nature.ecology import EDIBLE_NODE_KINDS
    return "food" if int(kind_id) in set(EDIBLE_NODE_KINDS.tolist()) else "node_stock"


def _depletion(world, table, node_id: str, after: float) -> list:
    """The effects that mark a node that has just reached 0."""
    if after > 0.0:
        return []
    tick = int(world.tick)
    place = (float(table.get(node_id, "x")), float(table.get(node_id, "y")))
    return [fx.Set("entities", (node_id,), "depleted_tick", float(tick)),
            fx.Emit("resource_depleted", actors=(node_id,), place=place, visibility="local", payload={"node": node_id},
                    event_id=f"res:{node_id}:{tick}:depleted")]


def eat_from_node(world, actor: str, node_id: str) -> NodeDraft:
    """Legacy eat numbers against a node: hunger -EAT_HUNGER_RESTORE (floor 0), node food -min(food, EAT_RESOURCE_COST)."""
    cfg = _cfg()
    table, _ = _node(world, node_id)
    kind = int(table.get(node_id, "node_kind"))
    if stock_field(kind) != "food":
        raise ResourceRefused("not_edible", f"{node_id!r} yields {node_item(kind)}, which is not food")
    _check_reach(world, actor, node_id, table)
    humans = world.table("humans")
    hunger = float(humans.get(actor, "hunger"))
    if hunger <= HUNGER_FLOOR_TO_EAT:
        raise ResourceRefused("not_hungry", f"hunger {hunger:.1f} is not above {HUNGER_FLOOR_TO_EAT:.0f}")
    food = float(table.get(node_id, "food"))
    if food <= 0.0:
        raise ResourceRefused("empty", f"{node_id!r} has no food")
    cost = min(food, float(cfg.EAT_RESOURCE_COST))
    relief = min(hunger, float(cfg.EAT_HUNGER_RESTORE))
    effects = [fx.Delta("entities", (node_id,), "food", -cost), fx.Delta("humans", (actor,), "hunger", -relief)]
    effects += _depletion(world, table, node_id, food - cost)
    event = fx.Emit("ate_from_node", actors=(actor,), place=(float(table.get(node_id, "x")), float(table.get(node_id, "y"))),
                    visibility="local", payload={"node": node_id, "item": node_item(kind)})
    return NodeDraft(effects, event, preview={"node": node_id, "food_before": food, "food_after": food - cost, "hunger_relief": relief})


def gather(world, actor: str, node_id: str, qty: int = 1) -> NodeDraft:
    """Move ``qty`` stock units out of the node and create ``qty`` items of its kind (one item per unit)."""
    if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
        raise ResourceRefused("bad_qty", f"qty must be a positive integer, got {qty!r}")
    table, _ = _node(world, node_id)
    _check_reach(world, actor, node_id, table)
    kind = int(table.get(node_id, "node_kind"))
    where = stock_field(kind)
    stock = float(table.get(node_id, where))
    if stock < qty:
        raise ResourceRefused("empty", f"{node_id!r} holds {stock:g}, asked for {qty}")
    item = node_item(kind)
    from systems.inventory.schema import ITEM_KIND_DEFS
    if item not in ITEM_KIND_DEFS:
        raise ResourceRefused("unknown_item", f"{item!r} is not an inventory item kind")
    room = world.items.room(actor, item)
    if room is not None and room < qty:
        raise ResourceRefused("no_room", f"{actor!r} has room for {room} {item}, asked for {qty}")
    effects = [fx.Delta("entities", (node_id,), where, -float(qty)), fx.Transfer(item, qty, None, actor)]
    effects += _depletion(world, table, node_id, stock - qty)
    event = fx.Emit("gathered", actors=(actor,), place=(float(table.get(node_id, "x")), float(table.get(node_id, "y"))),
                    visibility="local", payload={"node": node_id, "item": item, "qty": qty})
    return NodeDraft(effects, event, produces=((item, qty),), preview={"node": node_id, "item": item, "qty": qty, "stock_after": stock - qty})
