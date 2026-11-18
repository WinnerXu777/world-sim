"""Place-memory verbs (``EDEN_PLACES=1``): ``mark_place``, ``remember_place``, ``ask_directions`` (``systems/places``, ``1008_actions.md`` section 10.16).

On their own ``PLACES_REGISTRY`` (``default_registry()`` adds them while the flag is on). Marking and remembering write the actor's own record; asking is a request the asked resident answers by
rules at op time (it must know the place and not hold the asker in distrust), and a yes copies the place into the asker's record.
"""
from __future__ import annotations

from harness.registry import Registry, action

from .draft import ActionDraft, RecordOp
from .verbs.common import emit, read

PLACES_REGISTRY = Registry()
ASK_CLOSENESS = 0.02


@action("mark_place", risk="reversible", precondition="can_move", registry=PLACES_REGISTRY)
def mark_place(world, ctx, name: str = "") -> ActionDraft:
    """Remember where the actor stands under a name of its own."""
    from systems.places import clean_name
    name = clean_name(name)
    x, y = ctx.obs.x, ctx.obs.y
    op = RecordOp("place_mark", {"name": name, "x": x, "y": y, "space": read(world, ctx.actor, "space", 0.0), "source": "mark"})
    return ActionDraft([], emit(world, ctx.actor, "marked_place", {"name": name, "at": [x, y]}, visibility="private"), [op], {"name": name, "at": [x, y]})


@action("remember_place", risk="reversible", precondition="perceives", registry=PLACES_REGISTRY)
def remember_place(world, ctx, place: str = "") -> ActionDraft:
    """Remember a place the actor perceives (an anchor, a food / water site or an entity in view) under its id."""
    detail = ctx.verdict.detail
    op = RecordOp("place_mark", {"name": place, "x": detail["x"], "y": detail["y"], "space": read(world, ctx.actor, "space", 0.0), "source": detail["kind"]})
    return ActionDraft([], emit(world, ctx.actor, "remembered_place", {"place": place, "at": [detail["x"], detail["y"]]}, visibility="private"), [op],
                       {"place": place, "at": [detail["x"], detail["y"]]})


@action("ask_directions", risk="reversible", precondition="can_talk", registry=PLACES_REGISTRY)
def ask_directions(world, ctx, target: str = "", name: str = "") -> ActionDraft:
    """Ask a neighbour where a named place is; if it knows and does not distrust the asker, the place enters the asker's memory (closeness +0.02 each way on a yes)."""
    from systems.places import clean_name
    name = clean_name(name)
    ops = [RecordOp("place_ask", {"target": target, "name": name, "closeness": ASK_CLOSENESS})]
    return ActionDraft([], emit(world, ctx.actor, "asked_directions", {"to": target, "place": name}, others=(target,)), ops, {"target": target, "place": name})
