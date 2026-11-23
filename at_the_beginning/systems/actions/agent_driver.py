"""The agent driver (D-008, ``1008_agent_driver_design.md``): residents whose roster binding says ``driver == "agent"`` are moved by a Tier 1 decision
instead of the hard anchor driver.

Three layers, as in the design:

* **Tier 0 (instincts)**: the food / water trip of ``systems/roster/needs`` (``needs.plan`` / ``after_step``) is unchanged and runs every tick; a trip
  pre-empts everything, exactly as in the anchor driver.
* **Tier 1**: when no trip is running, a *macro* (one of the 24 of ``decision.matrix.MACRO_ACTIONS``) is chosen for the resident and translated to an
  anchor goal. ``RulesTier1`` is the rules scorer: it gives the macro that realises the schedule routine (or the open commission) a score no other macro
  can reach, so the walk is the roster one. ``MatrixTier1`` adds that rules prior to the matrix scores (``prior_strength``; 0 = the pure matrix) over
  the legality mask judged by the world alone. Cadence: a resident is re-scored when its signature (routine, commission override, trip) changes
  (immediately) or every ``decide_period`` ticks, staggered by slot; between decisions the macro is kept.
* **Execution**: the same ``AnchorMover`` and portals as the anchor driver; while a task from an action is queued or active the task system owns the
  resident's movement and the driver yields (one mover per resident).

One builtin step hook (``agent_driver``, installed by ``systems/roster/install``). A no-op while no resident has ``driver == "agent"``, so the default
(``anchor``) is byte-identical to before. Runtime state is the roster's non-saved ``RosterRuntime`` (``goal_key``, ``moved``, ``at_anchor``).
"""
from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Optional

from . import bonds_day, care_day, credit_day, dormancy_gate, emotion_day, guard_day, justice_day
from .weights import default_policy      # the rules prior unless EDEN_MATRIX_WEIGHTS names a verified trained file
from . import ladder as ladder_module
from . import market_day
from . import tier2 as tier2_module
from . import reputation as reputation_module

HOOK_NAME = "agent_driver"
TIER1_ENV = "EDEN_AGENT_TIER1"                 # "rules" (default) | "matrix"
PERIOD_ENV = "EDEN_AGENT_DECIDE_PERIOD"        # ticks between re-scoring of a resident whose signature did not change (default 10)
ACTIONS_ENV = "EDEN_AGENT_ACTIONS"             # "1": Tier 1 macros that are not plain routine / site goals run through ActionRunner (default off)
# Macros that can become a runner call, and the verbs a routed call may resolve to (a macro whose first legal verb is not here stays a walk).
ACTION_MACROS = frozenset({"eat", "rest", "gather", "socialise", "trade", "help", "work_at_station", "ask_for_help", "hide"})
ROUTABLE_VERBS = frozenset({"eat", "rest", "craft", "store_item", "fetch_item", "give_item", "request_item", "greet", "chat", "comfort",
                            "eat_from_node", "gather_from_node", "approach_node", "ask_for_help", "hide"})
REST_STAMINA = 40.0                            # rules: rest (the sleep task) when stamina is at or below this and nobody threatens
SOCIAL_COOLDOWN = 300                          # rules: ticks between two greetings / chats of one resident
LADDER_PERIOD = 10                             # EDEN_AGENT_LADDER: ticks between two evaluations of the escalation ladder for one resident (staggered by slot)
LADDER_STARVE_ENV = "EDEN_LADDER_STARVE"       # =1: no last-resort ration at all, the ladder owns food at every level (a resident the ladder cannot feed can starve)
LADDER_TIER0_HUNGER = 90.0                     # EDEN_AGENT_LADDER: from here the free ration of Tier 0 takes over again (a resident the ladder could not feed never starves silently)
TASK_PATIENCE = 400                            # agent driver (all agent residents): ticks an action's task may own a resident's movement before the watchdog clears it
TASK_CRITICAL_NEED = 75.0                      # agent driver (all agent residents): a task is cleared at once when hunger or thirst reaches this
REFUSAL_COOLDOWN = 20                          # a refused or unresolved routed macro is not asked again for this many ticks

# The macro that realises each schedule routine kind (roster.driver.ROUTINE_ANCHOR gives the anchor; here the *decision* is named).
ROUTINE_MACRO = {"sleep": "sleep", "stay_home": "sleep", "return_home": "go_home", "rest": "rest",
                 "work_site": "work_at_station", "guard": "work_at_station", "patrol": "work_at_station", "gather": "work_at_station",
                 "visit_water": "work_at_station", "socialize": "socialise", "wander_local": "socialise"}
# The anchor key a chosen macro walks to; a macro that is not here does not move the resident (the routine's anchor stays the goal).
MACRO_ANCHOR = {"sleep": "sleep", "go_home": "sleep", "rest": "sleep", "work_at_station": "work", "gather": "work", "build": "work",
                "repair": "work", "socialise": "talk", "trade": "talk", "help": "talk"}
THREAT_INTERRUPT = 30.0                         # THREAT column (0..100) from which a resident is re-scored at once (features' significant_threat 0.3)
HP_DROP_INTERRUPT = 10.0                        # an HP loss of at least this much since the previous tick (an attack) re-scores at once
PRIOR = 100.0                                   # score of the rules macro; far above anything the placeholder matrix weights reach


@dataclass(frozen=True)
class Goal:
    """What a resident is walking to this tick. ``kind``: ``need`` (a food/water trip), ``commission`` or ``routine``."""
    kind: str
    key: str                 # anchor key ("work", "sleep", ...) or need kind ("water", "food")
    position: tuple
    need: Optional[tuple] = None   # the ``needs.plan`` result of a trip, needed by ``needs.after_step``
    source: str = "rules"
    macro: str = ""


@dataclass
class Row:
    """One resident's inputs for a Tier 1 decision this tick."""
    slot: int
    human_id: str
    roster: dict
    resident: dict
    routine: str
    override: Optional[str]
    alert: tuple = (False, False)      # (threat at or above THREAT_INTERRUPT, HP dropped sharply since the previous tick)

    def signature(self) -> tuple:
        return (self.routine, self.override, self.alert)


# -- Tier 1 ---------------------------------------------------------------------------------------------------------------------------

def rules_macro(routine: str, override: Optional[str]) -> str:
    """The rules scorer's answer: an open commission means working at the station, else the macro of the schedule routine."""
    if override:
        return "work_at_station"
    return ROUTINE_MACRO.get(routine, "idle")


def rules_prior(rows: list):
    """N x K float64 prior over ``decision.matrix.MENU``: ``PRIOR`` on the rules macro of each row, 0 elsewhere."""
    import torch
    from systems.decision.matrix import ACTION_INDEX, K
    prior = torch.zeros((len(rows), K), dtype=torch.float64)
    for i, row in enumerate(rows):
        prior[i, ACTION_INDEX[rules_macro(row.routine, row.override)]] = PRIOR
    return prior


class RulesTier1:
    """Tier 1 = rules. No features, no mask: the macro is a function of the routine and the commission override only."""
    name = "rules"

    def decide(self, engine, rows: list) -> dict:
        return {row.human_id: rules_macro(row.routine, row.override) for row in rows}


class MatrixTier1:
    """Tier 1 = the matrix: scores ``X@W + ... + b`` plus ``prior_strength * rules_prior`` over the world-judged legality mask, argmax of the legal macros.
    With ``prior_strength`` 1 and the rules macro legal this is the rules answer; with 0 it is the pure matrix."""
    name = "matrix"

    def __init__(self, policy=None, prior_strength: float = 1.0):
        self.policy = policy
        env = os.environ.get("EDEN_MATRIX_PRIOR_STRENGTH")                 # measurement knob: 1 (default) = the rules macro wins when legal, 0 = the pure matrix
        self.prior_strength = float(env) if env not in (None, "") else float(prior_strength)
        self._ctx = (None, None)
        self.decisions = 0
        self.no_legal = 0
        self.keep_detail = False         # EDEN_AGENT_TIER2: keep each row's legal macros and distribution for the Tier 2 gate
        self.last_detail: dict = {}
        self.last_instinct = None        # (E, E @ W_ext) of the last batch while an instinct flag is on

    def _context(self, engine):
        key = (id(engine), getattr(engine, "world_epoch", None))
        if self._ctx[0] != key:
            from harness.adapter import EngineWorld
            from systems.affordance import AffordanceEngine, EngineServices
            world, services = EngineWorld(engine, seed=0), EngineServices(engine)
            self._ctx = (key, (world, services, AffordanceEngine(world, services, driver_mode="agent")))
        return self._ctx[1]

    def warm(self, engine) -> float:
        """Pay the one-time costs (affordance context, feature builder, first mask, torch kernels) before the first real decision. Returns ms."""
        import time
        from systems.decision import matrix
        from systems.decision.features import build_features
        began = time.perf_counter()
        self.policy = self.policy or default_policy()
        world, services, aff = self._context(engine)
        ids = [u for u in getattr(engine, "_human_uid_by_slot", []) if u]
        if ids:
            batch = build_features(world, services, ids)
            self.policy.scores(batch.X, batch.P)
            aff.mask(ids)
        return (time.perf_counter() - began) * 1000.0

    def decide(self, engine, rows: list) -> dict:
        import torch
        from systems.decision import instinct_features, matrix
        from systems.decision.features import build_features
        self.policy = self.policy or default_policy()
        world, services, aff = self._context(engine)
        ids = [row.human_id for row in rows]
        batch = build_features(world, services, ids)
        legal = aff.mask(ids).clone()
        if self.prior_strength > 0:      # walking to the routine's anchor is always possible even when the macro as an *action* is not legal now (nobody to talk to)
            for i, row in enumerate(rows):
                legal[i, matrix.ACTION_INDEX[rules_macro(row.routine, row.override)]] = True
        scores = self.policy.scores(batch.X, batch.P) + self.prior_strength * rules_prior(rows)
        self.last_instinct = instinct_features.scores(engine, ids)        # EDEN_TEMPERATURE / EDEN_WOUNDS / EDEN_DANGER: the cold / hot / wounded / fear block (None with every flag off)
        if self.last_instinct is not None:
            scores = scores + self.last_instinct[1]
        n_macro = len(matrix.MACRO_ACTIONS)                                   # the commission outcomes are not walks
        scores = scores[:, :n_macro].masked_fill(~legal[:, :n_macro], float("-inf"))
        out = {}
        if self.keep_detail:
            self.last_detail = {}
        for i, row in enumerate(rows):
            if not bool(legal[i, :n_macro].any()):
                self.no_legal += 1
                out[row.human_id] = rules_macro(row.routine, row.override)       # nothing legal: the rules answer, never a stall
                continue
            out[row.human_id] = matrix.MENU[int(torch.argmax(scores[i]))]
            if self.keep_detail:
                idx = torch.nonzero(legal[i, :n_macro]).flatten()
                p = torch.softmax(scores[i, idx] / self.policy.temperature, dim=0)
                self.last_detail[row.human_id] = {"legal": [matrix.MENU[int(j)] for j in idx], "probabilities": {matrix.MENU[int(j)]: float(q) for j, q in zip(idx, p)}}
        self.decisions += len(rows)
        return out


def actions_enabled() -> bool:
    return os.environ.get(ACTIONS_ENV, "") == "1"


def tier1_from_env():
    kind = os.environ.get(TIER1_ENV, "rules").strip().lower()
    return MatrixTier1() if kind == "matrix" else RulesTier1()


def decide_period() -> int:
    try:
        return max(1, int(os.environ.get(PERIOD_ENV, "10")))
    except ValueError:
        return 10


# -- goals ----------------------------------------------------------------------------------------------------------------------------

def macro_goal(engine, row: Row, macro: str) -> Optional[Goal]:
    """The anchor goal of a Tier 1 macro: its own anchor key if it has one, else the routine's. The commission override always wins its anchor."""
    from systems.roster.driver import anchor_positions, goal_anchor_key
    if row.override or macro == rules_macro(row.routine, row.override):
        wanted = row.override            # the rules macro (or an open commission) keeps the routine's own anchor, so Tier 1 = rules is the roster walk exactly
    else:
        wanted = MACRO_ANCHOR.get(macro)
    key = goal_anchor_key(row.roster, row.routine, wanted)
    positions = anchor_positions(engine, row.roster)
    if key is None or key not in positions:
        return None
    return Goal("commission" if row.override else "routine", key, tuple(positions[key]), source="tier1", macro=macro)


def _plan_tier0_needs(engine, slot, human_id, roster, state, ladder_on=None):
    """Keep Tier 0 water, while opt-in balance leaves sub-emergency food to the ladder."""
    import genesis_config as cfg
    from systems.roster.needs import plan as needs_plan
    from .market_day import balance_enabled
    if ladder_on is None:
        ladder_on = actions_enabled() and ladder_module.enabled()
    if ladder_on and balance_enabled():
        limit = float("inf") if os.environ.get(LADDER_STARVE_ENV, "") == "1" else LADDER_TIER0_HUNGER
        return needs_plan(engine, slot, human_id, roster, state,
                          allow_food=float(engine.state.h_tensor[slot, cfg.HUNGER]) >= limit)
    return needs_plan(engine, slot, human_id, roster, state)


def rules_goal(engine, slot: int, human_id: str, roster: dict, resident: dict, state) -> Optional[Goal]:
    """Tier 0 + rules in one call (the fallback when Tier 1 raises): trip, else commission, else routine."""
    from systems.commission.engine import commission_goal_override
    from systems.roster.driver import current_routine
    need = _plan_tier0_needs(engine, slot, human_id, roster, state)
    if need is not None:
        return Goal("need", need[0], tuple(need[1]), need=need, source="tier0")
    row = Row(slot, human_id, roster, resident, current_routine(engine, human_id, resident), commission_goal_override(engine, human_id))
    return macro_goal(engine, row, rules_macro(row.routine, row.override))


def _owns_movement_task(resident) -> bool:
    return any(str(task.get("status", "")) in ("queued", "active") for task in (resident or {}).get("tasks", []) or [])


class AgentDriver:
    """Per-engine runtime."""

    def __init__(self, tier1=None, period: Optional[int] = None):
        from .r61 import enabled as r61_enabled
        self.r61_enabled = r61_enabled()
        self.r61_routable = ROUTABLE_VERBS | {"retaliate", "forgive", "invite"} if self.r61_enabled else ROUTABLE_VERBS
        self.tier1 = tier1 or tier1_from_env()
        self.period = decide_period() if period is None else max(1, int(period))
        self.last_hp: dict = {}        # human id -> HP seen on the previous tick (sharp-drop interrupt)
        self.cache: dict = {}          # human id -> {"sig": signature, "macro": str, "tick": int}
        self.last_goal: dict = {}      # human id -> Goal of the previous tick
        self.errors = 0
        self.ticks_driven = 0
        self.yielded = 0               # resident-ticks left to the task system
        self.decided = 0               # residents scored by Tier 1
        self.interrupts = 0            # of those, re-scored because the signature changed
        self.warmed = False
        self.warm_ms = 0.0
        self.routed: Counter = Counter()       # EDEN_AGENT_ACTIONS: "<verb>:ok" / "<verb>:<runner code>" / "none:<macro>" per routed macro
        self.cool: dict = {}                   # (human id, macro) -> tick before which the macro is not routed again
        self._runner_ctx = (None, None)
        self.dormant: set = set()              # human ids dormant on the previous tick (EDEN_WINDOW_DORMANCY)
        self.task_seen: dict = {}              # human id -> (task id, first tick seen): the watchdog of EDEN_AGENT_LADDER
        self.ladder = ladder_module.Ladder()   # EDEN_AGENT_LADDER: cooldowns, errands, the acceptance timeline
        self.market_log: list = []             # EDEN_MARKET: [{"day", "tick", "changed": {item: [old, new]}}] per daily price update
        self.tier2 = tier2_module.Tier2() if tier2_module.enabled() else None      # EDEN_AGENT_TIER2: the macro-menu question for unsure, important rows
        if self.tier2 is not None and hasattr(self.tier1, "keep_detail"):
            self.tier1.keep_detail = True

    def warm(self, engine) -> float:
        """Warm Tier 1 once (no-op for a Tier 1 without ``warm``, e.g. the rules). Called by the first ``step`` if nobody did; a server calls it at start."""
        warm = getattr(self.tier1, "warm", None)
        self.warm_ms = float(warm(engine)) if callable(warm) else 0.0
        self.warmed = True
        return self.warm_ms

    # -- Tier 1 macros through ActionRunner (EDEN_AGENT_ACTIONS) ------------------------------------------------------------------
    def runner(self, engine):
        """The ActionRunner of this engine / world epoch: world-judged legality (driver_mode "agent"), engine record ops, its own audit log."""
        key = (id(engine), getattr(engine, "world_epoch", None))
        if self._runner_ctx[0] != key:
            from harness.adapter import EngineWorld
            from systems.affordance import AffordanceEngine, EngineServices
            from .recordops import EngineRecordOps
            from .runner import ActionRunner
            world, services = EngineWorld(engine, seed=0), EngineServices(engine)
            self._runner_ctx = (key, ActionRunner(world, services, aff=AffordanceEngine(world, services, driver_mode="agent"),
                                                  record_ops=EngineRecordOps(engine)))
        return self._runner_ctx[1]

    def route(self, engine, human_id: str, macro: str, tick: int):
        """Resolve ``macro`` to a verb call and run it through the ActionRunner (``proposer`` tier1:<provider>). Returns the ActionResult or None
        (nothing legal / not a routable verb / cooling down). A refusal arms a cooldown and is counted under its runner code."""
        if self.cool.get((human_id, macro), -1) > tick:
            return None
        runner = self.runner(engine)
        call = runner.aff.resolve(macro, human_id)
        if call is None or call.verb not in self.r61_routable or (call.verb == "eat" and "item" not in call.params):
            self.routed[f"none:{macro}"] += 1
            self.cool[(human_id, macro)] = tick + REFUSAL_COOLDOWN
            return None
        result = runner.run(human_id, call.verb, call.params, proposer=f"tier1:{getattr(self.tier1, 'name', 'custom')}")
        if result.ok:
            self.routed[f"{call.verb}:ok"] += 1
        else:
            self.routed[f"{call.verb}:{result.code}"] += 1
            self.cool[(human_id, macro)] = tick + REFUSAL_COOLDOWN
        return result

    def rules_action(self, engine, row: "Row", state, tick: int) -> Optional[str]:
        """The rules scorer's action layer (flag on): rest when worn out and safe, greet / chat at the talk anchor on a socialising routine."""
        import genesis_config as cfg
        h = engine.state.h_tensor
        if float(h[row.slot, cfg.H_STAMINA]) <= REST_STAMINA and float(h[row.slot, cfg.THREAT]) < THREAT_INTERRUPT and row.routine != "sleep":
            return "rest"
        if row.routine in ("socialize", "wander_local") and state.at_anchor.get(row.human_id) == "talk" and self.cool.get((row.human_id, "social"), -1) <= tick:
            return "socialise"
        return None

    # -- one tick ---------------------------------------------------------------------------------------------------------------------
    def step(self, engine) -> dict:
        import genesis_config as cfg
        from systems.commission.engine import commission_goal_override
        from systems.movement.spatial import world_contract
        from systems.roster.driver import StepResult, current_routine, portal_toward, roster_of, roster_slots, runtime, use_portal
        from systems.roster.needs import after_step as needs_after_step, settings as needs_settings_of
        acts = actions_enabled()
        ladder_on = acts and ladder_module.enabled()
        if self.r61_enabled and getattr(engine, "_r61_invitations", None) is not None:
            self.runner(engine).expire_invitations(int(engine.tick))
        slots = dormancy_gate.filter_slots(self, engine, roster_slots(engine, "agent"))     # EDEN_WINDOW_DORMANCY: residents outside the integrated chunks do nothing
        results = {}
        if not slots:
            return results
        state = runtime(engine)
        contract = world_contract(engine)
        tick = int(engine.tick)
        if acts:
            market_day.step(self, engine, tick)        # EDEN_MARKET: the daily scarcity update and the keepers' repricing (a no-op while the flag is off)
            credit_day.step(self, engine, tick)        # EDEN_CREDIT: repayment errands, overdue notes, defaults (a no-op while the flag is off)
            justice_day.step(self, engine, tick)       # EDEN_JUSTICE: reports to an authority, enforcement errands, lapsed cases (a no-op while the flag is off)
            bonds_day.step(self, engine, tick)         # EDEN_BONDS: forgive, apologise, befriend, court between residents who stand together (a no-op while the flag is off)
            emotion_day.step(self, engine, tick)       # EDEN_EMOTION: lazy grudge decay, grief and comfort, jealousy, the two slow drives (a no-op while the flag is off)
            care_day.step(self, engine, tick)          # EDEN_TEMPERATURE / EDEN_WOUNDS: dress wounds, light a fire when cold (a no-op while both flags are off)
            guard_day.step(self, engine, tick)         # EDEN_DEFEND: the combat hook, guard posts (expiry, errands, rules that open them), the answer to a blow (a no-op while the flag is off)
        # pass 1: Tier 0 and the inputs of Tier 1 (the same calls, in the same order, as the anchor driver makes for each resident)
        entries, due = [], []
        for slot in slots:
            human_id = engine._human_uid_by_slot[slot]
            roster, resident = roster_of(engine, human_id)
            hp = float(engine.state.h_tensor[slot, cfg.HP])
            if hp <= 0.0:
                continue
            hurt = (self.last_hp.get(human_id, hp) - hp) >= HP_DROP_INTERRUPT
            self.last_hp[human_id] = hp
            alert = (float(engine.state.h_tensor[slot, cfg.THREAT]) >= THREAT_INTERRUPT, bool(hurt))
            if _owns_movement_task(resident):
                self._watchdog(engine, slot, human_id, resident, tick)
            if _owns_movement_task(resident):   # one mover per resident: while an action's task is queued or active the task system walks it
                self.yielded += 1
                continue
            if acts and human_id not in state.trips:
                needs_settings, _ = needs_settings_of(roster)
                if float(engine.state.h_tensor[slot, cfg.HUNGER]) >= needs_settings["threshold"]:
                    self.route(engine, human_id, "eat", tick)       # edible food in the pack is eaten at the trip threshold instead of walking to the site
            need = None
            if not (ladder_on and self._ladder_owns_food(engine, slot, human_id, roster, state)):
                need = _plan_tier0_needs(engine, slot, human_id, roster, state, ladder_on)
            if need is not None:
                self.cache.pop(human_id, None)           # a trip ending re-scores the resident at once
                entries.append((slot, human_id, roster, Goal("need", need[0], tuple(need[1]), need=need, source="tier0"), None))
                continue
            row = Row(slot, human_id, roster, resident, current_routine(engine, human_id, resident), commission_goal_override(engine, human_id), alert)
            entries.append((slot, human_id, roster, None, row))
            cached = self.cache.get(human_id)
            if cached is None or cached["sig"] != row.signature():
                if cached is not None:
                    self.interrupts += 1
                due.append(row)
            elif (tick - cached["tick"]) >= self.period and (tick + slot) % self.period == 0:
                due.append(row)
        # pass 2: Tier 1 for the residents that are due, one batch
        if due:
            if not self.warmed:
                self.warm(engine)
            try:
                macros = self.tier1.decide(engine, due)
            except Exception:  # noqa: BLE001 - a failing Tier 1 answers with the rules for this batch, it never stops the residents
                self.errors += 1
                macros = RulesTier1().decide(engine, due)
            if self.tier2 is not None:
                try:
                    macros = self.tier2.refine(engine, due, macros, getattr(self.tier1, "last_detail", {}), tick,
                                               {row.human_id: (self.cache.get(row.human_id) or {}).get("macro", "") for row in due})
                except Exception:  # noqa: BLE001 - Tier 2 trouble leaves Tier 1's macros
                    self.errors += 1
            for row in due:
                self.cache[row.human_id] = {"sig": row.signature(), "macro": macros[row.human_id], "tick": tick}
            self.decided += len(due)
            if acts:
                for row in due:
                    macro = macros[row.human_id]
                    if (macro in ACTION_MACROS or (macro == "attack" and self.r61_enabled)) and macro != rules_macro(row.routine, row.override):
                        wanted = macro                                   # the matrix chose something other than the routine's walk
                    else:
                        wanted = self.rules_action(engine, row, state, tick)
                    if wanted is None:
                        continue
                    result = self.route(engine, row.human_id, wanted, tick)
                    if result is not None and result.ok and wanted == "socialise":
                        self.cool[(row.human_id, "social")] = tick + SOCIAL_COOLDOWN
        if acts and reputation_module.enabled():      # EDEN_REPUTATION: discovery of losses, opinions, gossip, restitution, forgiveness
            reputation_module.step(self, engine, tick)
        if ladder_on:                      # the escalation ladder for hungry residents (forage, trade, beg, steal), after Tier 1 has chosen its macros
            self._ladder_pass(engine, entries, tick)
        # pass 3: goals and movement
        for slot, human_id, roster, goal, row in entries:
            if row is not None and acts and _owns_movement_task(row.resident):
                self.yielded += 1                                        # a routed action queued a task this tick: the task system walks from now on
                continue
            if goal is None and ladder_on:
                errand = self.ladder.errand_goal(human_id, tick, engine)
                if errand is not None:
                    goal = Goal("errand", "errand", tuple(errand), source="ladder", macro=self.ladder.errands[human_id].rung)
            if goal is None:
                goal = macro_goal(engine, row, self.cache[human_id]["macro"])
            if goal is None:
                continue
            self.last_goal[human_id] = goal
            position = (float(engine.state.h_tensor[slot, cfg.X]), float(engine.state.h_tensor[slot, cfg.Y]))
            portal = portal_toward(engine, position, goal.position)
            result = state.mover.step(human_id, position, portal[0] if portal else goal.position, contract, engine.tick)
            if portal and result.arrived and use_portal(engine, slot, human_id, portal[1]):
                result = StepResult(portal[1], moved=0.0)
            if result.position != position:
                engine.state.h_tensor[slot, cfg.X], engine.state.h_tensor[slot, cfg.Y] = result.position
            if goal.need is not None:
                needs_after_step(engine, slot, human_id, roster, state, StepResult(result.position, blocked=result.blocked) if portal else result)
            state.goal_key[human_id] = goal.key
            state.moved[human_id] = result.moved
            if result.arrived:
                state.at_anchor[human_id] = goal.key
            else:
                state.at_anchor.pop(human_id, None)
            results[human_id] = result
            if goal.kind == "errand" and (result.arrived or self.ladder.near(human_id, result.position)):
                self.ladder.arrive(self, engine, human_id, tick)
        self.ticks_driven += 1
        return results

    # -- the escalation ladder (EDEN_AGENT_LADDER) -----------------------------------------------------------------------------------
    @staticmethod
    def _ladder_owns_food(engine, slot: int, human_id: str, roster: dict, state) -> bool:
        """True when only hunger is over the trip threshold (and below the last-resort level): the ladder feeds the resident, Tier 0 does not ration it.
        Thirst, a trip in progress, and hunger from ``LADDER_TIER0_HUNGER`` up stay with Tier 0 unchanged."""
        import genesis_config as cfg
        from systems.roster.needs import settings as needs_settings_of
        if human_id in state.trips:
            return False
        needs, _ = needs_settings_of(roster)
        h = engine.state.h_tensor
        hunger, thirst = float(h[slot, cfg.HUNGER]), float(h[slot, cfg.THIRST])
        limit = float("inf") if os.environ.get(LADDER_STARVE_ENV, "") == "1" else LADDER_TIER0_HUNGER
        return thirst < needs["threshold"] <= hunger < limit

    def _watchdog(self, engine, slot: int, human_id: str, resident: dict, tick: int) -> None:
        """A task that owns the resident's movement for ``TASK_PATIENCE`` ticks, or while a need is critical, is cleared. A roster resident's task
        can stay active for ever (the task system suppresses its walking), and a resident stuck in one would die of thirst with the ladder or Tier 0 locked out."""
        import genesis_config as cfg
        from systems.tasks.ops import clear_resident_tasks
        h = engine.state.h_tensor
        current = next((t for t in resident.get("tasks", []) if str(t.get("status", "")) in ("queued", "active")), None)
        key = str((current or {}).get("id", ""))
        seen = self.task_seen.get(human_id)
        if seen is None or seen[0] != key:
            self.task_seen[human_id] = seen = (key, tick)
        critical = max(float(h[slot, cfg.HUNGER]), float(h[slot, cfg.THIRST])) >= TASK_CRITICAL_NEED
        if critical or tick - seen[1] >= TASK_PATIENCE:
            clear_resident_tasks(resident, tick, reason="watchdog")
            engine.resident_store.touch_resident(human_id)
            self.task_seen.pop(human_id, None)
            self.routed["watchdog:cleared_critical" if critical else "watchdog:cleared_patience"] += 1

    def _ladder_pass(self, engine, entries: list, tick: int) -> None:
        for slot, human_id, _roster, _goal, row in entries:
            if row is None or human_id in self.ladder.errands or (tick + slot) % LADDER_PERIOD != 0:
                continue
            try:
                self.ladder.decide(self, engine, human_id, tick)
            except Exception:  # noqa: BLE001 - a failing rung never stops the residents
                self.errors += 1
                self.ladder.note(tick, human_id, "ladder", "decide", "error")

    def status(self) -> dict:
        return {"tier1": getattr(self.tier1, "name", "custom"), "prior": PRIOR, "prior_strength": getattr(self.tier1, "prior_strength", None),
                "period": self.period, "ticks_driven": self.ticks_driven, "errors": self.errors,
                "yielded": self.yielded, "decided": self.decided, "interrupts": self.interrupts, "residents": len(self.last_goal),
                "actions": {"enabled": actions_enabled(), "routed": dict(self.routed)},
                "ladder": self.ladder.status(), "tier2": self.tier2.status() if self.tier2 is not None else {"enabled": False}}


def driver_of(engine) -> AgentDriver:
    found = engine.__dict__.get("_agent_driver")
    if found is None:
        found = engine.__dict__["_agent_driver"] = AgentDriver()
    return found


def hook(engine) -> None:
    driver_of(engine).step(engine)


def install(dispatch) -> None:
    """Register the step hook (idempotent). Called from ``systems/roster/install.install_smith_loop`` next to ``roster_driver``."""
    if not any(name == HOOK_NAME for name, _ in dispatch.step_hooks):
        dispatch.register_step_hook(HOOK_NAME, hook, builtin=True)
