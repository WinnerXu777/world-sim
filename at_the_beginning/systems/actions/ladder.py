"""The escalation ladder (``EDEN_AGENT_LADDER=1``, default off): how a hungry agent resident gets food, ordered by cost and conscience.

Design: ``1008_market_justice_design.md`` section 3. The pure part (``conscience``, ``desperation``, ``thresholds``, ``allowed``) is a function of numbers, so every
threshold is unit-tested without an engine. The engine-facing part (``Ladder``) evaluates the rungs in cost order for one resident on the decision cadence,
runs the verb of the first rung that is allowed and feasible through the ``ActionRunner`` (audit proposer ``tier1:ladder``) or sets an *errand* (walk
somewhere first, act on arrival), and keeps cooldowns so a refusal is not asked again at once. Runtime state only (nothing is saved).

Rungs, in cost order: forage (own pantry, then a food node), work (designed, not built), trade, beg, borrow (designed), steal, rob (designed).
"""
from __future__ import annotations

import math
import os
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

ENV = "EDEN_AGENT_LADDER"
ORDER = ("forage", "work", "buy", "trade", "beg", "borrow", "steal", "rob")
BUILT = ("forage", "trade", "beg", "steal")      # ``buy`` joins while EDEN_MARKET is on, ``borrow`` while EDEN_CREDIT is on, ``work`` while EDEN_LABOUR is on (``Ladder.built``)
BASE = {"forage": 0.0, "work": 0.20, "buy": 0.15, "trade": 0.30, "beg": 0.35, "borrow": 0.50, "steal": 0.65, "rob": 0.85}
RUNGS_ENV = "EDEN_LADDER_RUNGS"        # e.g. "forage,rob": only these rungs are tried (stress runs; unset = all)
ENGAGE_HUNGER = 30.0           # the ladder looks at a resident only from the trip threshold up
COOLDOWN = {"node": 300, "container": 600, "trade": 200, "beg": 200, "stall": 300, "borrow": 400, "work": 300, "report": 600, "enforce": 300, "guard": 300, "rob": 400}
RELIEF_TICKS = 600             # a rung that worked this recently lowers desperation a little
ERRAND_TTL = 1500              # an errand that has not arrived by now is dropped
WATCHED_WAIT = 120             # at a container with a witness near: wait this long, then give up
DEPENDANT_HUNGER = 50.0
CHILD_AGE = 18.0          # roster ages start at 16: under 18 counts as a dependant
KNOWN_RADIUS = 400.0           # a resident knows the nodes and storage of its homestead within this distance
NODE_REACH_SLACK = 0.0


def enabled() -> bool:
    return os.environ.get(ENV, "") == "1"


# -- the pure part ---------------------------------------------------------------------------------------------------------------
def conscience(traits: dict) -> float:
    """-0.8 .. 0.85: what holds a resident back from taking what is not its own."""
    t = lambda name: float(traits.get(name, 0.5))  # noqa: E731
    return 0.35 * t("mercy") + 0.25 * t("loyalty") + 0.25 * t("discipline") - 0.35 * t("deceitfulness") - 0.25 * t("greed") - 0.20 * t("aggression")


def desperation(hunger: float, has_edible: bool, hungry_dependants: int, relieved: bool) -> float:
    return max(0.0, min(1.2, hunger / 100.0 + (0.0 if has_edible else 0.20) + 0.15 * min(3, int(hungry_dependants)) - (0.10 if relieved else 0.0)))


def thresholds(c: float, family_push: float = 0.0) -> dict:
    """The desperation each rung needs for this resident: a high conscience raises the bar of the rungs that cost reputation, family need lowers it."""
    shift = 0.30 * c - float(family_push)
    return {rung: max(0.0, BASE[rung] + (shift if rung in ("steal", "rob", "borrow") else 0.3 * shift)) for rung in ORDER}


def allowed(d: float, c: float, family_push: float = 0.0, pride: float = 0.0, built=BUILT) -> list:
    """Rungs open at desperation ``d`` in the order they are tried. A proud resident would rather be lent to than beg: beg moves after borrow (borrow is not built)."""
    limit = thresholds(c, family_push)
    order = list(ORDER)
    if pride > 0.7:
        order.remove("beg")
        order.insert(order.index("borrow") + 1, "beg")
    return [rung for rung in order if rung in built and d >= limit[rung]]


def household_of_resident(roster_key: str) -> str:
    return str(roster_key or "").split("_", 1)[0]


def household_of_entity(entity_id: str) -> str:
    return str(entity_id or "").split(":", 1)[0].removesuffix("_interior")


# -- the engine-facing part --------------------------------------------------------------------------------------------------------
@dataclass
class Errand:
    rung: str
    purpose: str               # forage_node | fetch | steal | restitution
    position: tuple            # where to walk (an anchor beside the target)
    target: str                # entity or resident id the verb is about
    verb: str
    params: dict
    expires: int
    waited: int = 0
    note: str = ""


@dataclass
class Ladder:
    cool: dict = field(default_factory=dict)       # (human id, kind, key) -> tick before which it is not tried again
    errands: dict = field(default_factory=dict)    # human id -> Errand
    relieved: dict = field(default_factory=dict)   # human id -> tick of the last successful rung
    counts: Counter = field(default_factory=Counter)
    log: list = field(default_factory=list)        # [{"tick", "actor", "rung", "verb", "code", "detail"}]: the acceptance timeline

    @staticmethod
    def built() -> tuple:
        from systems import credit, labour, market, rob
        built = BUILT + (("work",) if labour.enabled() else ()) + (("buy",) if market.enabled() else ()) + (("borrow",) if credit.enabled() else ()) + (("rob",) if rob.enabled() else ())
        only = os.environ.get(RUNGS_ENV, "")
        return tuple(r for r in built if r in only.split(",")) if only else built       # a measurement knob (stress runs): unset = every rung that is built

    def cooling(self, actor: str, kind: str, key: str, tick: int) -> bool:
        return self.cool.get((actor, kind, key), -1) > tick

    def cool_down(self, actor: str, kind: str, key: str, tick: int, span: Optional[int] = None) -> None:
        self.cool[(actor, kind, key)] = tick + int(span if span is not None else COOLDOWN[kind])

    def note(self, tick: int, actor: str, rung: str, verb: str, code: str, **detail) -> None:
        self.counts[f"{rung}:{code}"] += 1
        if len(self.log) < 4000:
            self.log.append({"tick": tick, "actor": actor, "rung": rung, "verb": verb, "code": code, **detail})

    # -- reading the world ------------------------------------------------------------------------------------------------------
    @staticmethod
    def edible_in_pack(obs) -> list:
        from systems.affordance import config
        return [k for k in config.EDIBLE_ITEMS if obs.inventory.get(k, 0) >= 1]

    @staticmethod
    def dependants(engine, obs, traits) -> int:
        """Kin the resident feeds that are hungry: children, or anyone a protective resident looks after."""
        count = 0
        for other, relation in ((obs.record or {}).get("relationships") or {}).items():
            if relation.get("kind") != "family" and "family" not in (relation.get("tags") or []):
                continue
            slot = engine._human_slot_for_id(other)
            if slot is None or slot < 0:
                continue
            import genesis_config as cfg
            h = engine.state.h_tensor
            if float(h[slot, cfg.HP]) <= 0:
                continue
            child = float(h[slot, cfg.H_AGE]) < CHILD_AGE
            if float(h[slot, cfg.HUNGER]) >= DEPENDANT_HUNGER and (child or float(traits.get("protectiveness", 0.5)) >= 0.5):
                count += 1
        return count

    @staticmethod
    def entities_with_stock(runner, kinds, household: str, own: bool):
        """Storage entities of the homestead (own household or foreign) as ``(EntityFact, edible kinds held)``; a container's contents are visible to whoever opens it."""
        from systems.affordance import config
        out = []
        for fact in runner.services.entities():
            if fact.kind not in kinds or not fact.alive:
                continue
            if (household_of_entity(fact.id) == household) != own:
                continue
            held = runner.services.inventory(fact.id)
            edible = [k for k in config.EDIBLE_ITEMS if held.get(k, 0) >= 1]
            out.append((fact, edible))
        return out

    @staticmethod
    def edible_nodes(runner, obs) -> list:
        """``(id, x, y, distance, reach limit)`` of live food nodes with stock the resident knows, nearest first."""
        from harness import resources
        from systems.map import resources as map_resources
        import genesis_config as cfg
        if not map_resources.enabled():
            return []
        try:
            table = runner.world.table("entities")
            m, col, ids = table.tensor, table.columns, table.ids
            types, x, y, scale = m[:, col["type"]], m[:, col["x"]], m[:, col["y"]], m[:, col["scale"]]
            stock, burning, kind = m[:, col["food"]] + m[:, col["node_stock"]], m[:, col["burning"]], m[:, col["node_kind"]].long()
        except (KeyError, AttributeError):
            return []
        import torch
        from systems.nature.ecology import EDIBLE_NODE_KINDS
        dist = ((x - obs.x) ** 2 + (y - obs.y) ** 2).sqrt()
        near = (types == float(cfg.M_RESOURCE_NODE)) & (stock > 0) & (burning == 0) & torch.isin(kind, EDIBLE_NODE_KINDS) & (dist <= KNOWN_RADIUS)
        rows = [(float(dist[s]), ids[s], float(x[s]), float(y[s]), float(scale[s]) + resources.REACH) for s in near.nonzero(as_tuple=False).flatten().tolist() if ids[s]]
        return [(i, nx, ny, d, limit) for d, i, nx, ny, limit in sorted(rows)]

    @staticmethod
    def stand_point(engine, x: float, y: float, radius: float = 14.0):
        """The nearest work / talk anchor of any placed map within ``radius`` of a target (where a resident stands to use it), else the point itself."""
        try:
            from systems.roster.validate import anchors_from_registry
            anchors = anchors_from_registry(engine._map_name)
        except Exception:  # noqa: BLE001 - no registry (synthetic world): walk to the point
            return (x, y)
        best = None
        for info in anchors.values():
            if info["kind"] not in ("work", "talk"):
                continue
            d = math.hypot(info["position"][0] - x, info["position"][1] - y)
            if d <= radius and (best is None or d < best[0]):
                best = (d, info["position"])
        return tuple(best[1]) if best else (x, y)

    # -- the decision -------------------------------------------------------------------------------------------------------------
    def decide(self, driver, engine, human_id: str, tick: int):
        """Evaluate the ladder for one resident. Returns the rung that acted, ``"errand"`` when it set one, or None."""
        from systems.personality.assign import get_personality_traits
        runner = driver.runner(engine)
        S = runner.aff.situation(human_id)
        obs = S.obs
        if not obs.alive or obs.hunger < ENGAGE_HUNGER or human_id in self.errands:
            return None
        record = obs.record or {}
        traits = get_personality_traits(record.get("personality"))
        edible = self.edible_in_pack(obs)
        dependants = self.dependants(engine, obs, traits)
        relieved = tick - self.relieved.get(human_id, -10 ** 9) < RELIEF_TICKS
        d = desperation(obs.hunger, bool(edible), dependants, relieved)
        c = conscience(traits)
        push = 0.15 * float(traits.get("protectiveness", 0.5)) if dependants else 0.0
        household = household_of_resident((record.get("roster") or {}).get("key", ""))
        for rung in allowed(d, c, push, float(traits.get("pride", 0.0)) if "pride" in traits else 0.0, self.built()):
            acted = getattr(self, f"_{rung}")(driver, engine, runner, S, human_id, tick, household, edible, d, dependants)
            if acted:
                return acted
        return None

    def _run(self, driver, engine, runner, human_id, tick, rung, verb, params, **detail):
        result = runner.run(human_id, verb, params, proposer="rules:ladder")
        code = "ok" if result.ok else result.code
        driver.routed[f"ladder.{rung}.{verb}:{code}"] += 1
        self.note(tick, human_id, rung, verb, code, **detail, **({"op": result.ops[0]} if result.ops else {}))
        return result

    def _forage(self, driver, engine, runner, S, human_id, tick, household, edible, d, dependants):
        obs = S.obs
        if edible:                                                           # a meal in the pack: eat it now (hunger above the trip threshold)
            result = self._run(driver, engine, runner, human_id, tick, "forage", "eat", {"item": edible[0]}, source="pack")
            if result.ok:
                self.relieved[human_id] = tick
                return "forage"
        from systems.affordance import config
        for fact, held in self.entities_with_stock(runner, config.STORAGE_KINDS, household, own=True):      # the household's own pantry
            if not held or self.cooling(human_id, "container", fact.id, tick):
                continue
            near = obs.entity(fact.id)
            if near is not None and near.dist <= max(fact.interact_radius, config.RADIUS["interact"]):
                result = self._run(driver, engine, runner, human_id, tick, "forage", "fetch_item", {"item": held[0], "qty": 1, "container": fact.id}, source="pantry")
                if result.ok:
                    self.relieved[human_id] = tick
                    return "forage"
                self.cool_down(human_id, "container", fact.id, tick)
                continue
            self.errands[human_id] = Errand("forage", "fetch", self.stand_point(engine, fact.x, fact.y), fact.id, "fetch_item",
                                            {"item": held[0], "qty": 1, "container": fact.id}, tick + ERRAND_TTL)
            self.note(tick, human_id, "forage", "walk", "errand", target=fact.id, purpose="fetch")
            return "errand"
        from systems.affordance.economy_predicates import owned_farms
        for distance, farm, nx, ny, stock in owned_farms(S, KNOWN_RADIUS):
            if self.cooling(human_id, "node", farm, tick):
                continue
            room = runner.world.items.room(human_id, "crop_bundle")
            qty = min(stock, 3 + dependants, int(room) if room is not None else stock)
            if qty <= 0:
                continue
            params = {"farm": farm, "qty": qty}
            if distance <= config.RADIUS["interact"]:
                result = self._run(driver, engine, runner, human_id, tick, "forage", "harvest_farm", params, source="farm")
                if result.ok:
                    return "forage"
                self.cool_down(human_id, "node", farm, tick)
                continue
            self.errands[human_id] = Errand("forage", "harvest", self.stand_point(engine, nx, ny), farm, "harvest_farm", params, tick + ERRAND_TTL)
            self.note(tick, human_id, "forage", "walk", "errand", target=farm, purpose="harvest")
            return "errand"
        for node, nx, ny, distance, limit in self.edible_nodes(runner, obs):
            if self.cooling(human_id, "node", node, tick):
                continue
            if distance <= limit:
                result = self._run(driver, engine, runner, human_id, tick, "forage", "eat_from_node", {"node": node}, source="node")
                if result.ok:
                    self.relieved[human_id] = tick
                    return "forage"
                self.cool_down(human_id, "node", node, tick)
                continue
            self.errands[human_id] = Errand("forage", "forage_node", self.stand_point(engine, nx, ny), node, "eat_from_node", {"node": node}, tick + ERRAND_TTL)
            self.note(tick, human_id, "forage", "walk", "errand", target=node, purpose="forage_node")
            return "errand"
        return None

    TRADE_GOODS = ("coin", "wood_bundle", "iron_ingot", "fish_catch")
    TRADE_WANTS = ("rations", "crop_bundle", "berries", "mushrooms")
    VISIT_NEAR = 12.0               # a visit ends this close to the person sought (interaction range is 16)

    def _offer_terms(self, S, want: str):
        """``(give, give_qty)`` the resident can pay for one ``want`` at the fair price, or None: the cheapest trade good it holds enough of."""
        from systems.actions.offers import FAIRNESS, item_value
        best = None
        for give in self.TRADE_GOODS:
            have = S.obs.inventory.get(give, 0)
            need = max(1, math.ceil(FAIRNESS * item_value(want) / max(item_value(give), 0.01)))
            if have >= need and (best is None or need * item_value(give) < best[1] * item_value(best[0])):
                best = (give, need)
        return best

    @staticmethod
    def _within_reach(S) -> set:
        from systems.affordance import config
        return {n.id for n in S.obs.neighbours if n.alive and n.dist <= config.RADIUS["interact"]}

    def _people(self, engine, S, human_id: str, kind: str, tick: int) -> list:
        """Residents the actor could ask or trade with, nearest first: alive, within ``KNOWN_RADIUS``, not kin, not hostile, not cooling for this rung."""
        import genesis_config as cfg
        record, h, out = S.obs.record or {}, engine.state.h_tensor, []
        for other in engine._human_uid_by_slot:
            if not other or other == human_id or self.cooling(human_id, kind, other, tick):
                continue
            slot = engine._human_slot_for_id(other)
            if slot is None or slot < 0 or float(h[slot, cfg.HP]) <= 0:
                continue
            relation = (record.get("relationships") or {}).get(other, {})
            if relation.get("kind") == "family" or "family" in (relation.get("tags") or []) or "thief" in (relation.get("tags") or []) \
                    or float(relation.get("closeness", 0.0)) < -0.2:
                continue
            d = math.hypot(float(h[slot, cfg.X]) - S.obs.x, float(h[slot, cfg.Y]) - S.obs.y)
            if d <= KNOWN_RADIUS:
                out.append((d, other))
        return [other for _, other in sorted(out)]

    def _visit(self, engine, human_id: str, tick: int, rung: str, verb: str, target: str, params: dict) -> str:
        import genesis_config as cfg
        slot = engine._human_slot_for_id(target)
        pos = (float(engine.state.h_tensor[slot, cfg.X]), float(engine.state.h_tensor[slot, cfg.Y]))
        self.errands[human_id] = Errand(rung, "visit", pos, target, verb, params, tick + ERRAND_TTL)
        self.note(tick, human_id, rung, "walk", "errand", target=target, purpose="visit")
        return "errand"

    def _buy(self, driver, engine, runner, S, human_id, tick, household, edible, d, dependants):
        """EDEN_MARKET: pay a stall for food. The nearest known stall with an edible the resident can pay; one that cannot pay sells a surplus first; a stall with no food on
        the shelf, or a price out of reach, is recorded as unmet demand (the next daily update raises the price)."""
        from systems.affordance import config
        from systems.market import enabled, runtime
        if not enabled():
            return None
        obs, services = S.obs, runner.services
        book, coin = runtime.of(services), S.obs.inventory.get("coin", 0)
        stalls = [f for f in services.entities() if f.kind in config.STORAGE_KINDS and f.alive and runtime.is_stall(services, f.id)
                  and math.hypot(f.x - obs.x, f.y - obs.y) <= KNOWN_RADIUS and not self.cooling(human_id, "stall", f.id, tick)]
        for fact in sorted(stalls, key=lambda f: (math.hypot(f.x - obs.x, f.y - obs.y), f.id)):
            held = services.inventory(fact.id)
            goods = sorted((k for k in config.EDIBLE_ITEMS if held.get(k, 0) >= 1), key=lambda k: (book.ask(fact.id, k), k))
            if not goods:
                book.record_unmet(fact.id, self.TRADE_WANTS[0], 1)
                self.cool_down(human_id, "stall", fact.id, tick)
                self.note(tick, human_id, "buy", "buy", "out_of_stock", stall=fact.id)
                continue
            item = next((k for k in goods if book.ask(fact.id, k) <= coin), None)
            if item is None:
                if self._sell_surplus(driver, engine, runner, S, human_id, tick, fact, book):
                    return "buy"
                book.record_unmet(fact.id, goods[0], 1)
                self.cool_down(human_id, "stall", fact.id, tick)
                self.note(tick, human_id, "buy", "buy", "cannot_afford", stall=fact.id, price=book.ask(fact.id, goods[0]), coin=coin)
                continue
            qty = max(1, min(held[item], coin // book.ask(fact.id, item), 1 + dependants))
            params = {"container": fact.id, "item": item, "qty": qty}
            near = obs.entity(fact.id)
            if near is not None and near.dist <= max(fact.interact_radius, config.RADIUS["interact"]):
                result = self._run(driver, engine, runner, human_id, tick, "buy", "buy", params, stall=fact.id, item=item)
                if result.ok:
                    self.relieved[human_id] = tick
                    return "buy"
                if result.code == "illegal:out_of_stock":
                    book.record_unmet(fact.id, item, qty)
                self.cool_down(human_id, "stall", fact.id, tick)
                continue
            self.errands[human_id] = Errand("buy", "fetch", self.stand_point(engine, fact.x, fact.y), fact.id, "buy", params, tick + ERRAND_TTL)
            self.note(tick, human_id, "buy", "walk", "errand", target=fact.id, purpose="market")
            return "errand"
        return None

    def _sell_surplus(self, driver, engine, runner, S, human_id, tick, fact, book) -> bool:
        """Sell one of a stack the resident holds two or more of (most valuable first) to a stall it stands at, to raise the coin for food."""
        for kind, q in sorted(S.obs.inventory.items(), key=lambda kv: (-book.value(kv[0]) * kv[1], kv[0])):
            if kind == "coin" or q < 2:
                continue
            params = {"container": fact.id, "item": kind, "qty": 1}
            if runner.aff.legal(human_id, "sell", params).ok:
                return self._run(driver, engine, runner, human_id, tick, "buy", "sell", params, stall=fact.id, item=kind).ok
        return False

    def _trade(self, driver, engine, runner, S, human_id, tick, household, edible, d, dependants, only=None):
        near = self._within_reach(S)
        for target in ([only] if only else self._people(engine, S, human_id, "trade", tick)):
            for want in self.TRADE_WANTS:
                if self.cooling(human_id, "trade", f"{target}:{want}", tick):
                    continue
                terms = self._offer_terms(S, want)
                if terms is None:
                    continue
                params = {"target": target, "give": terms[0], "want": want, "give_qty": terms[1], "want_qty": 1}
                if target not in near:
                    return self._visit(engine, human_id, tick, "trade", "offer_trade", target, params)
                result = self._run(driver, engine, runner, human_id, tick, "trade", "offer_trade", params, target=target, want=want)
                if result.ok and result.ops and result.ops[0].get("accepted"):
                    self.relieved[human_id] = tick
                    return "trade"
                answer = result.ops[0].get("answer") if result.ok and result.ops else result.code
                self.cool_down(human_id, "trade", f"{target}:{want}", tick)
                if answer in ("refuse_distrust", "refuse_thief", "refuse_busy"):
                    self.cool_down(human_id, "trade", target, tick)
                if result.ok:
                    return "trade"                                               # asked and refused: that was this decision's attempt
        return None

    def _beg(self, driver, engine, runner, S, human_id, tick, household, edible, d, dependants, only=None):
        near = self._within_reach(S)
        for target in ([only] if only else self._people(engine, S, human_id, "beg", tick)):
            if self.cooling(human_id, "beg", target, tick):
                continue
            params = {"target": target, "item": "", "qty": 1 + dependants}
            if target not in near:
                return self._visit(engine, human_id, tick, "beg", "request_item", target, params)
            result = self._run(driver, engine, runner, human_id, tick, "beg", "request_item", params, target=target)
            if result.ok and result.ops and result.ops[0].get("gave"):
                self.relieved[human_id] = tick
                return "beg"
            self.cool_down(human_id, "beg", target, tick)
            if result.ok:
                return "beg"
        return None

    def _borrow(self, driver, engine, runner, S, human_id, tick, household, edible, d, dependants, only=None):
        """EDEN_CREDIT: ask a neighbour for a loan of food. A resident already in debt does not ask again; the lender answers by rules (``credit_verbs.respond_to_loan``)."""
        from systems.credit import enabled, runtime
        if not enabled() or runtime.of(runner.services).open_of(human_id):
            return None
        near = self._within_reach(S)
        for target in ([only] if only else self._people(engine, S, human_id, "borrow", tick)):
            if self.cooling(human_id, "borrow", target, tick):
                continue
            params = {"target": target, "item": "", "qty": 1 + dependants}
            if target not in near:
                return self._visit(engine, human_id, tick, "borrow", "borrow_item", target, params)
            result = self._run(driver, engine, runner, human_id, tick, "borrow", "borrow_item", params, target=target)
            if result.ok and result.ops and result.ops[0].get("lent"):
                self.relieved[human_id] = tick
                return "borrow"
            self.cool_down(human_id, "borrow", target, tick)
            if result.ok:
                return "borrow"
        return None

    # -- paying a debt back -------------------------------------------------------------------------------------------------------
    def start_repay(self, driver, engine, runner, human_id: str, loan, tick: int) -> None:
        """Walk to the lender (the errand follows them) and pay on arrival; in reach already: pay now."""
        import genesis_config as cfg
        if loan.lender in self._within_reach(runner.aff.situation(human_id)):
            self.repay(driver, engine, runner, human_id, loan.lender, tick)
            return
        lender_slot = engine._human_slot_for_id(loan.lender)
        h = engine.state.h_tensor
        pos = (float(h[lender_slot, cfg.X]), float(h[lender_slot, cfg.Y]))
        self.errands[human_id] = Errand("repay", "repay", pos, loan.lender, "pay_debt", {}, tick + ERRAND_TTL)
        self.note(tick, human_id, "repay", "walk", "errand", target=loan.lender, purpose="repay")

    def repay(self, driver, engine, runner, human_id: str, lender: str, tick: int) -> bool:
        """Pay the open loan to ``lender`` with the item lent, else coin, as much as clears it (or all of it)."""
        from systems.credit import runtime
        book = runtime.of(runner.services)
        loan = book.between(human_id, lender)
        if loan is None:
            return False
        pack = runner.services.inventory(human_id)
        for kind in (loan.item, "coin"):
            have = pack.get(kind, 0)
            if have > 0:
                qty = min(have, book.units_needed(loan, kind))
                result = self._run(driver, engine, runner, human_id, tick, "repay", "pay_debt", {"target": lender, "item": kind, "qty": qty}, target=lender)
                if result.ok:
                    return True
        return False

    def _work(self, driver, engine, runner, S, human_id, tick, household, edible, d, dependants, only=None):
        """EDEN_LABOUR: ask a neighbour for a paid shift. A yes starts a ``labour`` errand that stays near the employer until the shift is done, then collects the wage."""
        from systems.labour import enabled, runtime
        if not enabled() or runtime.of(runner.services).of_worker(human_id, tick) is not None:
            return None
        near = self._within_reach(S)
        for target in ([only] if only else self._people(engine, S, human_id, "work", tick)):
            if self.cooling(human_id, "work", target, tick):
                continue
            params = {"target": target}
            if target not in near:
                return self._visit(engine, human_id, tick, "work", "work_for", target, params)
            result = self._run(driver, engine, runner, human_id, tick, "work", "work_for", params, target=target)
            if result.ok and result.ops and result.ops[0].get("hired"):
                self._start_labour(engine, human_id, target, tick, result.ops[0])
                return "work"
            self.cool_down(human_id, "work", target, tick)
            if result.ok:
                return "work"
        return None

    def _start_labour(self, engine, human_id: str, employer: str, tick: int, hired: dict) -> None:
        import genesis_config as cfg
        slot = engine._human_slot_for_id(employer)
        pos = (float(engine.state.h_tensor[slot, cfg.X]), float(engine.state.h_tensor[slot, cfg.Y]))
        self.errands[human_id] = Errand("work", "labour", pos, employer, "collect_wage", {"target": employer}, int(hired["expires"]))
        self.note(tick, human_id, "work", "walk", "errand", target=employer, purpose="labour", ready_at=hired["ready_at"])

    @staticmethod
    def _robbed(result) -> bool:
        """The ``rob`` call applied and the robber won the contest (``robbery``, not ``robbery_failed``)."""
        return any(e.type == "robbery" for e in getattr(result.report, "events", None) or [])

    def _arrest(self, driver, engine, runner, authority: str, thief: str, tick: int) -> None:
        """EDEN_ROB (with EDEN_RESTRAINT): the authority that has just levied damages holds a robber on record. A refusal is only logged."""
        from systems import rob
        if rob.enabled() and rob.robber_on_record(engine, thief):
            self._run(driver, engine, runner, authority, tick, "enforce", "arrest_or_restrain", {"target": thief}, target=thief)

    def start_report(self, driver, engine, runner, human_id: str, authority: str, theft, tick: int) -> None:
        """EDEN_JUSTICE: walk to the authority (the errand follows them) and report the theft; in reach already: report now."""
        params = {"target": authority, "about": theft.thief, "item": theft.item, "qty": int(theft.qty), "victim": theft.owner if theft.owner_kind == "resident" else human_id}
        if authority in self._within_reach(runner.aff.situation(human_id)):
            self._run(driver, engine, runner, human_id, tick, "report", "report_theft", params, target=authority)
            return
        self.errands[human_id] = Errand("report", "report", self._position_of(engine, authority), authority, "report_theft", params, tick + ERRAND_TTL)
        self.note(tick, human_id, "report", "walk", "errand", target=authority, purpose="report")

    def start_enforce(self, driver, engine, runner, case, tick: int) -> None:
        """EDEN_JUSTICE: the authority walks to the thief (the errand follows them) and levies the damages; in reach already: levy now."""
        params = {"target": case.thief}
        if case.thief in self._within_reach(runner.aff.situation(case.authority)):
            if self._run(driver, engine, runner, case.authority, tick, "enforce", "levy_damages", params, target=case.thief).ok:
                self._arrest(driver, engine, runner, case.authority, case.thief, tick)
            return
        self.errands[case.authority] = Errand("enforce", "enforce", self._position_of(engine, case.thief), case.thief, "levy_damages", params, tick + ERRAND_TTL)
        self.note(tick, case.authority, "enforce", "walk", "errand", target=case.thief, purpose="enforce")

    def start_guard(self, driver, engine, runner, human_id: str, charge: str, tick: int) -> None:
        """EDEN_DEFEND: walk to the person (the errand follows them) and, in reach, open a guard post with ``defend``; ``arrive`` then holds the errand for the length of the watch."""
        self.errands[human_id] = Errand("guard", "guard", self._position_of(engine, charge), charge, "defend", {"target": charge}, tick + ERRAND_TTL)
        self.note(tick, human_id, "guard", "walk", "errand", target=charge, purpose="guard")

    def hold_guard(self, engine, post) -> None:
        """EDEN_DEFEND: a post that was opened without this ladder (a model's ``defend``) gets its holding errand: stay by the person, or at the place, until the post ends."""
        if post.kind == "person":
            self.errands[post.guard] = Errand("guard", "guard", self._position_of(engine, post.charge), post.charge, "defend", {"target": post.charge}, post.until, note="held")
        elif post.xy is not None:
            self.errands[post.guard] = Errand("guard", "guard_place", tuple(post.xy), post.charge, "defend", {"place": post.charge}, post.until, note="held")

    @staticmethod
    def _position_of(engine, human_id: str) -> tuple:
        import genesis_config as cfg
        slot = engine._human_slot_for_id(human_id)
        return float(engine.state.h_tensor[slot, cfg.X]), float(engine.state.h_tensor[slot, cfg.Y])

    def _steal(self, driver, engine, runner, S, human_id, tick, household, edible, d, dependants):
        from systems.affordance import config
        obs = S.obs
        for fact, held in self.entities_with_stock(runner, config.STORAGE_KINDS, household, own=False):
            if self.cooling(human_id, "container", fact.id, tick):
                continue
            item = held[0] if held else None
            near = obs.entity(fact.id)
            if near is not None and near.dist <= max(fact.interact_radius, config.RADIUS["interact"]):
                if item is None:                                             # opened it: nothing edible inside
                    self.cool_down(human_id, "container", fact.id, tick)
                    continue
                qty = max(1, min(runner.services.inventory(fact.id).get(item, 0), 1 + dependants))
                result = self._run(driver, engine, runner, human_id, tick, "steal", "steal_when_safe", {"container": fact.id, "item": item, "qty": qty}, container=fact.id)
                if result.ok:
                    self.relieved[human_id] = tick
                    return "steal"
                if result.code == "illegal:watched":                         # someone would see: wait nearby for a moment
                    self.errands[human_id] = Errand("steal", "steal", self.stand_point(engine, fact.x, fact.y), fact.id, "steal_when_safe",
                                                    {"container": fact.id, "item": item, "qty": qty}, tick + ERRAND_TTL, waited=0, note="watched")
                    return "errand"
                self.cool_down(human_id, "container", fact.id, tick)
                continue
            self.errands[human_id] = Errand("steal", "steal", self.stand_point(engine, fact.x, fact.y), fact.id, "steal_when_safe",
                                            {"container": fact.id, "item": item or "rations", "qty": 1 + dependants}, tick + ERRAND_TTL)
            self.note(tick, human_id, "steal", "walk", "errand", target=fact.id, purpose="steal")
            return "errand"
        return None

    def _rob(self, driver, engine, runner, S, human_id, tick, household, edible, d, dependants):
        """EDEN_ROB: the top rung. A desperate resident with a low conscience, fit enough to fight, takes food from the nearest resident who carries some, unless an authority or a guard
        would see to it: it walks to them (the errand follows) and calls ``rob``. Never against a dormant resident, a player body, or someone it holds dear."""
        from systems import rob as rules
        from systems.affordance import config as aff
        from systems.guard import runtime as guard_runtime
        from systems.personality.assign import get_personality_traits
        from . import guard_day, justice_day
        obs = S.obs
        if obs.hp < rules.ROB_MIN_HP or conscience(get_personality_traits((obs.record or {}).get("personality"))) > rules.ROB_MAX_CONSCIENCE:
            return None
        judges = [j for j in justice_day.authorities(engine) if j != human_id]
        posts = guard_runtime.of(runner.services)
        candidates = []
        for other in sorted(h for h in engine._human_uid_by_slot if h and h != human_id):
            if self.cooling(human_id, "rob", other, tick) or not guard_day._alive(engine, other) or rules.controlled(engine, engine._human_slot_for_id(other)):
                continue
            held = runner.services.inventory(other)
            item = next((k for k in aff.EDIBLE_ITEMS if held.get(k, 0) >= 1), None)
            if item is None or guard_day._closeness(engine, human_id, other) >= 0.3:
                continue
            distance = guard_day._distance(engine, human_id, other)
            if distance > KNOWN_RADIUS or any(guard_day._distance(engine, j, other) <= rules.WITNESS_RADIUS for j in judges) or posts.for_charge(other):
                continue
            candidates.append((distance, other, item, int(held[item])))
        if not candidates:
            return None
        _, victim, item, have = min(candidates)
        params = {"target": victim, "item": item, "qty": max(1, min(have, 1 + dependants))}
        if victim in self._within_reach(S):
            result = self._run(driver, engine, runner, human_id, tick, "rob", "rob", params, target=victim)
            self.cool_down(human_id, "rob", victim, tick)
            if result.ok and self._robbed(result):
                self.relieved[human_id] = tick
            return "rob" if result.ok else None
        self.errands[human_id] = Errand("rob", "rob", self._position_of(engine, victim), victim, "rob", params, tick + ERRAND_TTL)
        self.note(tick, human_id, "rob", "walk", "errand", target=victim, purpose="rob")
        return "errand"

    # -- errands --------------------------------------------------------------------------------------------------------------------
    def errand_goal(self, human_id: str, tick: int, engine=None):
        """The position an active errand walks to, or None (none, or it expired: the resident is released). A visit follows the person sought."""
        errand = self.errands.get(human_id)
        if errand is None:
            return None
        if tick >= errand.expires:
            self.note(tick, human_id, errand.rung, errand.verb, "errand_expired", target=errand.target)
            del self.errands[human_id]
            return None
        if errand.purpose in ("visit", "restitution", "repay", "labour", "report", "enforce", "guard", "rob") and engine is not None:
            import genesis_config as cfg
            slot = engine._human_slot_for_id(errand.target)
            if slot is not None and slot >= 0:
                errand.position = (float(engine.state.h_tensor[slot, cfg.X]), float(engine.state.h_tensor[slot, cfg.Y]))
        return errand.position

    def near(self, human_id: str, position) -> bool:
        """A visit (or a restitution) ends once the resident is within ``VISIT_NEAR`` of the person, whether or not the mover reports arrival."""
        errand = self.errands.get(human_id)
        return errand is not None and errand.purpose in ("visit", "restitution", "repay", "labour", "report", "enforce", "guard", "guard_place", "rob") \
            and math.hypot(position[0] - errand.position[0], position[1] - errand.position[1]) <= self.VISIT_NEAR

    def arrive(self, driver, engine, human_id: str, tick: int) -> None:
        """The resident reached its errand's position: act. A theft that finds a witness waits and retries; anything else ends the errand."""
        errand = self.errands.get(human_id)
        if errand is None:
            return
        runner = driver.runner(engine)
        params = dict(errand.params)
        if errand.purpose == "harvest":
            table = runner.world.table("entities")
            if table.slot_of(errand.target) is None:
                del self.errands[human_id]
                return
            stock = int(table.get(errand.target, "food"))
            room = runner.world.items.room(human_id, "crop_bundle")
            params["qty"] = min(int(params["qty"]), stock, int(room) if room is not None else stock)
            if params["qty"] <= 0:
                self.cool_down(human_id, "node", errand.target, tick)
                del self.errands[human_id]
                return
        if errand.rung == "till":
            from .market_day import balance_enabled, TILL_FLOAT
            qty = max(0, int(runner.services.inventory(errand.target).get("coin", 0)) - TILL_FLOAT)
            room = runner.world.items.room(human_id, "coin")
            if room is not None:
                qty = min(qty, int(room))
            if not balance_enabled() or qty <= 0:
                del self.errands[human_id]
                return
            params["qty"] = qty
        if errand.purpose == "visit":                                       # in reach of the person sought: ask / offer now
            del self.errands[human_id]
            S = runner.aff.situation(human_id)
            getattr(self, f"_{errand.rung}")(driver, engine, runner, S, human_id, tick, "", [], 0.0, 0, only=errand.target)
            return
        if errand.purpose == "labour":                                      # near the employer: work until the shift is done, then collect the wage
            from systems.labour import runtime as labour_runtime
            job = labour_runtime.of(runner.services).between(human_id, errand.target, tick)
            if job is None:
                self.note(tick, human_id, "work", "collect_wage", "lapsed", target=errand.target)
                del self.errands[human_id]
                return
            if tick < job.ready_at:
                return                                                      # still on shift: stay with the employer
            result = self._run(driver, engine, runner, human_id, tick, "work", "collect_wage", {"target": errand.target}, target=errand.target)
            if result.ok:
                self.relieved[human_id] = tick
            else:
                self.cool_down(human_id, "work", errand.target, tick)
            del self.errands[human_id]
            return
        if errand.purpose in ("guard", "guard_place"):                      # EDEN_DEFEND: in reach of the person (or at the place): open the post once, then stay for the watch
            from systems.guard import runtime as guard_runtime
            book = guard_runtime.of(runner.services)
            post = book.of_guard(human_id)
            if post is not None:
                return
            if errand.note == "held":                                       # the post ended (the guard pass normally removes the errand first)
                del self.errands[human_id]
                return
            result = self._run(driver, engine, runner, human_id, tick, errand.rung, errand.verb, params, target=errand.target)
            post = book.of_guard(human_id) if result.ok else None
            if post is None:
                self.cool_down(human_id, "guard", errand.target, tick)
                del self.errands[human_id]
                return
            errand.expires, errand.note = post.until, "held"
            return
        if errand.purpose == "rob":                                         # in reach of the victim: one attempt, then done (a win or a loss both cool the pair down)
            del self.errands[human_id]
            result = self._run(driver, engine, runner, human_id, tick, "rob", "rob", params, target=errand.target)
            self.cool_down(human_id, "rob", errand.target, tick)
            if result.ok and self._robbed(result):
                self.relieved[human_id] = tick
            return
        if errand.purpose in ("report", "enforce"):                         # in reach of the authority (a report) or of the thief (damages): one call, then done
            del self.errands[human_id]
            result = self._run(driver, engine, runner, human_id, tick, errand.rung, errand.verb, params, target=errand.target)
            if not result.ok:
                self.cool_down(human_id, errand.rung, errand.target, tick)
            elif errand.purpose == "enforce":
                self._arrest(driver, engine, runner, human_id, errand.target, tick)
            return
        if errand.purpose == "repay":                                       # in reach of the lender: pay what is owed
            del self.errands[human_id]
            self.repay(driver, engine, runner, human_id, errand.target, tick)
            return
        if errand.purpose == "steal":                                       # the contents are visible now: pick what is really there
            from systems.affordance import config
            held = runner.services.inventory(errand.target)
            edible = [k for k in config.EDIBLE_ITEMS if held.get(k, 0) >= 1]
            if not edible:
                self.note(tick, human_id, "steal", errand.verb, "empty", target=errand.target)
                self.cool_down(human_id, "container", errand.target, tick)
                del self.errands[human_id]
                return
            params["item"] = edible[0]
            params["qty"] = max(1, min(int(params.get("qty", 1)), held.get(edible[0], 1)))
        result = self._run(driver, engine, runner, human_id, tick, errand.rung, errand.verb, params, target=errand.target)
        if result.ok:
            if errand.purpose == "restitution":                              # the item went back: the victim's grudge eases (actions/reputation.py)
                from . import reputation
                reputation.restituted(engine, human_id, errand.target, tick)
            elif errand.rung != "till":
                self.relieved[human_id] = tick
            del self.errands[human_id]
            return
        if result.code == "illegal:watched" and errand.waited < WATCHED_WAIT:
            errand.waited += 1
            return                                                          # stay at the container and look again next tick
        if errand.purpose == "restitution":
            self.cool_down(human_id, "trade", errand.target, tick)
            del self.errands[human_id]
            return
        kind = "node" if errand.purpose == "forage_node" else ("stall" if errand.rung == "buy" else "container")
        if errand.rung == "buy" and result.code == "illegal:out_of_stock":
            from systems.market import runtime
            runtime.of(runner.services).record_unmet(errand.target, params.get("item", self.TRADE_WANTS[0]), int(params.get("qty", 1)))
        self.cool_down(human_id, kind, errand.target, tick)
        del self.errands[human_id]

    def status(self) -> dict:
        return {"enabled": enabled(), "errands": len(self.errands), "counts": dict(self.counts), "log": len(self.log)}
