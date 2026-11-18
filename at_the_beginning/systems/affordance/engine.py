"""The affordance engine: the one place that answers "what can this resident do right now?".

* ``options(actor)``: the legal options with concrete parameters (nearest food, a reachable bed, the neighbour in range, the recipe
  the station fits), each with a ``Verdict`` carrying reachability mode and distance;
* ``legal(actor, verb, params)``: the same predicate for one proposed call (the action runner uses this at apply time);
* ``mask(actors)``: the legality mask ``M`` (N x K, ``torch.bool``) over ``decision.matrix.MENU`` for Tier 1; a dead resident's row is
  all False;
* ``resolve(macro, actor)``: the concrete verb call a Tier 1 macro stands for (nearest legal option, ties by id);
* ``commission_options(...)``: the six commission outcomes from the engine's own facts.

It reads the world through the harness ``World`` and a ``Services`` object and never writes anything. Nothing in the engine tick
calls it.
"""
from __future__ import annotations

from typing import Iterable, Optional

from . import commission as comm
from . import driver
from .observation import Observation, observe
from .predicates import VERBS, Situation
from .reach import Reach
from .verdicts import ActionCall, Option, Verdict, no

# Tier 1 macro -> verbs it can resolve to, in order of preference (1008_actions.md section 3). A macro is legal when any of its verbs
# has a legal option; verbs absent from VERBS (market, rumours, law, ...) simply contribute nothing.
MACRO_VERBS = {
    "eat": ("eat", "eat_from_node"), "drink": ("drink",), "rest": ("rest",), "sleep": ("sleep",),
    "work_at_station": ("craft", "work_shift", "go_to_work", "fetch_item", "store_item"),
    "gather": ("gather_resource", "gather_from_node", "approach_node"), "go_home": ("seek_shelter",), "socialise": ("chat", "greet", "follow", "share_news", "gossip"),
    "trade": ("commission_item", "request_item", "give_item", "offer_trade", "accept_trade"), "help": ("give_item", "comfort"), "avoid": ("avoid",),
    "flee": ("flee_to",), "defend": ("defend",), "attack": ("attack",), "explore": ("explore_toward",), "build": ("build_structure",),
    "repair": ("repair",), "ask_for_help": ("ask_for_help",), "hide": ("hide",), "idle": ("idle",),
    "continue_plan_step": ("continue_plan_step",), "USE_BRAIN": ("USE_BRAIN",), "REPLAN": ("REPLAN",), "PLOT": ("PLOT",),
}


class AffordanceEngine:
    def __init__(self, world, services, reach: Optional[Reach] = None, *, driver_mode: Optional[str] = None):
        self.world, self.services = world, services
        self.driver_mode = driver_mode         # None = config.DRIVER_MODE (see driver.py)
        self.reach = reach if reach is not None else Reach(services)

    # situations ---------------------------------------------------------------
    def situation(self, actor: str, *, exact: bool = True) -> Situation:
        return Situation(self.world, self.services, self.reach, observe(self.world, self.services, actor), exact)

    def observation(self, actor: str) -> Observation:
        return observe(self.world, self.services, actor)

    # options ------------------------------------------------------------------
    def options(self, actor: str, *, verbs: Optional[Iterable[str]] = None, include_illegal: bool = False,
                situation: Optional[Situation] = None, first_only: bool = False) -> list:
        """Legal options (or all candidates with ``include_illegal``). ``first_only`` stops each verb at its first legal candidate:
        enough to know *whether* a verb is possible (the mask), and it skips the reachability searches for the rest."""
        S = situation or self.situation(actor)
        out = []
        for name in (sorted(VERBS) if verbs is None else verbs):
            definition = VERBS.get(name)
            if definition is None:
                continue
            for params in definition.candidates(S):
                verdict = driver.restrict(S, name, definition.check(S, **params), self.driver_mode)
                if verdict.ok or include_illegal:
                    out.append(Option(name, dict(params), verdict, _targets(params)))
                    if first_only and verdict.ok:
                        break
        out.sort(key=lambda o: (o.verb, o.distance if o.distance is not None else 0.0, str(sorted(o.params.items()))))
        return out

    def legal(self, actor: str, verb: str, params: Optional[dict] = None, *, situation: Optional[Situation] = None) -> Verdict:
        definition = VERBS.get(verb)
        if definition is None:
            return no("unknown_verb", verb=str(verb))
        params = dict(params or {})
        try:
            S = situation or self.situation(actor)
            return driver.restrict(S, verb, definition.check(S, **params), self.driver_mode)
        except TypeError as exc:                       # unexpected or missing argument names
            return no("invalid_params", why=str(exc))

    # Tier 1 -------------------------------------------------------------------
    def macro_options(self, actor: str, macro: str, *, situation: Optional[Situation] = None) -> list:
        S = situation or self.situation(actor)
        return [o for o in self.options(actor, verbs=MACRO_VERBS.get(macro, ()), situation=S) if _macro_filter(S, macro, o)]

    def resolve(self, macro: str, actor: str, *, situation: Optional[Situation] = None) -> Optional[ActionCall]:
        """First legal option of the macro's preferred verb, nearest first; None when the macro is illegal."""
        S = situation or self.situation(actor)
        options = self.macro_options(actor, macro, situation=S)
        for name in MACRO_VERBS.get(macro, ()):
            mine = sorted((o for o in options if o.verb == name), key=lambda o: (o.distance if o.distance is not None else 0.0, str(sorted(o.params.items()))))
            if mine:
                return ActionCall(name, dict(mine[0].params), macro)
        return None

    def mask(self, actors: list, *, exact: bool = False):
        """``torch.bool`` N x K over ``decision.matrix.MENU``; commission columns follow the offered order addressed to the actor.

        ``exact=False`` (default) answers "can the actor get there" from connected components when it can, which is the cheap path; the
        legal/illegal verdict is the same as with ``exact=True`` (tested), only the distance and path length are not computed."""
        import torch
        from systems.decision.matrix import ACTION_INDEX, COMMISSION_OUTCOMES, K
        out = torch.zeros((len(actors), K), dtype=torch.bool)
        for row, actor in enumerate(actors):
            S = self.situation(actor, exact=exact)
            if not S.obs.alive:
                continue
            cache: dict = {}
            for macro, names in MACRO_VERBS.items():
                if macro in ACTION_INDEX and any(self._verb_legal(S, name, macro, cache) for name in names):
                    out[row, ACTION_INDEX[macro]] = True
            for option in self.commission_outcomes(actor):
                if option in COMMISSION_OUTCOMES:
                    out[row, ACTION_INDEX[option]] = True
        return out

    def _verb_legal(self, S, name, macro, cache) -> bool:
        if macro == "help":                         # the filter looks at who is in need, so every candidate counts
            return any(_macro_filter(S, macro, o) for o in self.options(S.actor, verbs=(name,), situation=S))
        if name not in cache:
            cache[name] = bool(self.options(S.actor, verbs=(name,), situation=S, first_only=True))
        return cache[name]

    # commission ---------------------------------------------------------------
    def commission_options(self, smith: str, customer: str, recipe: str, *, exclude_order: Optional[str] = None) -> list:
        return comm.legal_options(comm.commission_facts(self.world, self.services, smith, customer, recipe, exclude_order=exclude_order))

    def commission_outcomes(self, smith: str) -> list:
        """Outcomes for the oldest ``offered`` order addressed to ``smith`` (empty when there is none or the resident is dead)."""
        orders = comm.offered_orders(self.services, smith)
        if not orders or not comm._alive(self.world, smith):
            return []
        order = orders[0]
        return self.commission_options(smith, order["customer_id"], order["recipe_id"], exclude_order=order["order_id"])


def _targets(params: dict) -> tuple:
    return tuple(str(params[k]) for k in ("target", "source", "container", "place") if params.get(k))


def _macro_filter(S, macro: str, option: Option) -> bool:
    """Extra conditions that make a verb option count for a macro (``help`` is for a neighbour who is actually in need)."""
    if macro != "help":
        return True
    from . import config
    n = S.obs.neighbour(option.params.get("target"))
    if n is None or n.dist > config.RADIUS["help"]:
        return False
    if option.verb == "give_item":                       # feeding someone hungry (there is no water item to hand over)
        return n.hunger >= config.NEED_HELP_HUNGER and option.params.get("item") in config.EDIBLE_ITEMS
    return n.mood <= config.NEED_HELP_MOOD or n.hp < config.NEED_HELP_HP    # comfort
