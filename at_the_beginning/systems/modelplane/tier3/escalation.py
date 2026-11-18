"""Escalation wiring: which Tier 1 situations are sent to a model, behind the per-role off | shadow | on switch (default off).

There is no engine edit. ``install(dispatch, plane)`` registers one builtin post-step hook; with the resident role off it returns on its
first line (no feature build, no tensor read), so a default game pays one function call per tick. When the role is ``shadow`` or ``on`` the
hook sweeps a small rotating batch of roster residents every ``period`` ticks:

    features (Tier 1 feature builder) -> legality mask (affordance) -> matrix decision -> triggers -> ``Tier3Router.request_plan``

Triggers (``classify``, pure): ``macro:USE_BRAIN`` / ``macro:REPLAN`` / ``macro:PLOT`` (Tier 1 chose a cognitive macro), ``tier1_uncertain``
(the matrix gate: uncertain AND the situation matters), ``unmet_need`` (an urgent hunger/thirst with no legal way to meet it) and
``unresolved_threat`` (a threat with nothing legal that avoids it). Only the first ``max_per_sweep`` triggered residents per sweep are asked.

``shadow`` records what the model would have done (the router stores the gate verdict and never offers the plan). ``on`` runs an accepted plan
through the ActionRunner (``run_plan``), one plan per resident, after the gate's dry run of its first step. Rejections and failures leave the
resident on Tier 1 / the rules; every reason is counted in ``/model_status`` (``tier3`` block) and logged.
Dialogue and the world director are asked by their own call sites (a talk reply, a decree), not by the sweep: see ``Tier3Router``.
"""
from __future__ import annotations

import time
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Optional

HOOK_NAME = "tier3_escalation"

TRIGGER_ROLE = {"macro:USE_BRAIN": "resident", "macro:REPLAN": "resident", "macro:PLOT": "resident", "tier1_uncertain": "resident",
                "unmet_need": "resident", "unresolved_threat": "resident"}
NEED_ACTIONS = {"hunger": ("eat", "gather"), "thirst": ("drink",)}
THREAT_ACTIONS = ("flee", "hide", "avoid", "defend", "ask_for_help")


@dataclass
class EscalationConfig:
    period: int = 1                  # ticks between sweeps (1: one resident per tick, round robin, so no tick pays for a whole batch)
    batch: int = 1                   # residents examined per sweep (round robin over the roster)
    prefilter: bool = True           # skip residents whose tensor state cannot trigger anything (no work at all for them), and unchanged ones
    max_per_sweep: int = 2           # model requests per sweep
    urgent_need: float = 0.8         # hunger / thirst (0..1) from which a need without a legal action is "unmet"
    significant_threat: float = 0.3  # same thresholds as features.compare_to_rules
    significant_low_hp: float = 0.5
    cooldown_ticks: int = 100        # a resident is not asked twice for the same trigger inside this window
    run_accepted: bool = True        # mode on: run an accepted plan (False: leave it in the router for another consumer)
    step_mode: str = "cursor"        # "cursor": one step at a time, the next waits for the previous task (PlanCursors); "oneshot": run_plan, all at once
    task_timeout_ticks: int = 400    # a step's task that has not ended by then aborts the plan


def classify(row: dict, chosen: Optional[str], uncertain: bool, legal: set, config: EscalationConfig) -> list:
    """Triggers for one resident. ``row`` = feature name -> 0..1, ``chosen`` = Tier 1's macro (None when nothing is legal), ``uncertain`` = the
    matrix gate's verdict (already ANDed with significance), ``legal`` = the set of macro names that are legal now."""
    out = []
    if chosen in ("USE_BRAIN", "REPLAN", "PLOT"):
        out.append(f"macro:{chosen}")
    if uncertain:
        out.append("tier1_uncertain")
    for need, actions in NEED_ACTIONS.items():
        if row.get(need, 0.0) >= config.urgent_need and not (set(actions) & legal):
            out.append("unmet_need")
            break
    if row.get("threat", 0.0) > config.significant_threat and not (set(THREAT_ACTIONS) & legal):
        out.append("unresolved_threat")
    return out


class Escalator:
    def __init__(self, plane, router, *, config: Optional[EscalationConfig] = None, policy=None, gate=None, clock=time.monotonic):
        from systems.decision import matrix
        self.plane, self.router = plane, router
        self.config = config or EscalationConfig()
        self.policy = policy
        self.gate = gate or matrix.GateConfig()
        self._cursor = 0
        self._asked: dict = {}                 # (resident, trigger) -> tick before which it is not asked again
        self._pending_run: dict = {}           # resident -> tick the request was made (mode on: waiting for the plan)
        self._ctx: tuple = (None, None)        # (engine key, (world, services, aff, runner))
        self.cursors = None                    # PlanCursors on the current runner (mode on, step_mode cursor)
        self._aff_world = None                 # (id(world), AffordanceEngine judged by the world alone: no roster-driver demotion)
        self._epoch = None                     # model epoch the cooldowns / waiting plans belong to
        self.counts: Counter = Counter()
        self.recent: deque = deque(maxlen=20)
        self.last_sweep_ms = 0.0
        self._digest: dict = {}                # resident -> inputs digest of its last full evaluation (unchanged inputs are not re-evaluated)

    # -- hook ----------------------------------------------------------------------------------------------------------------------
    def hook(self, engine) -> None:
        if self.plane.mode("resident") == "off":
            return                                                                           # default: nothing runs
        self._sync_epoch()
        tick = int(getattr(engine, "tick", 0))
        if self._pending_run:
            self._collect(tick, engine)
        if self.cursors is not None and self.cursors.cursors:
            self._advance(tick, engine)
        if tick % max(1, self.config.period) == 0:
            self.sweep(engine, tick)

    def _sync_epoch(self) -> None:
        """Any switch change (shadow -> on, a slot toggled, all_off) starts fresh: cooldowns, waiting plans and the router's pending keys belong
        to the old epoch (their jobs are dropped as stale), so a resident that still has an unmet need is asked again at the next sweep."""
        epoch = self.plane.switch.epoch
        if self._epoch is not None and epoch != self._epoch:
            self._asked.clear()
            self._pending_run.clear()
            self.router.forget_pending()
            self.counts["epoch_reset"] += 1
        self._epoch = epoch

    def _world_aff(self, world, services):
        """The affordance engine with the roster-driver table off: "can the world do this?" A roster resident's eat / drink are ``roster_driven`` in
        the Tier 1 mask because the roster needs loop carries them out, which is the opposite of an unmet need."""
        if self._aff_world is None or self._aff_world[0] != id(world):
            from systems.affordance import AffordanceEngine
            self._aff_world = (id(world), AffordanceEngine(world, services, driver_mode="agent"))
        return self._aff_world[1]

    def warm(self) -> None:
        """Pay the one-time costs (imports, the initial matrix) at install, not inside the first tick that needs a decision."""
        from systems.decision import matrix                                  # noqa: F401
        from systems.decision import features                                # noqa: F401
        import systems.actions, systems.affordance                           # noqa: E401,F401
        from systems.actions.weights import default_policy
        self.policy = self.policy or default_policy()

    def _context(self, engine):
        key = (id(engine), getattr(engine, "world_epoch", None))
        if self._ctx[0] != key:
            from harness.adapter import EngineWorld
            from systems.actions import ActionRunner, EngineRecordOps
            from systems.affordance import AffordanceEngine, EngineServices
            world, services = EngineWorld(engine, seed=0), EngineServices(engine)
            aff = AffordanceEngine(world, services)
            runner = ActionRunner(world, services, aff=aff, record_ops=EngineRecordOps(engine))
            self._ctx = (key, (world, services, aff, runner))
            self.router.runner, self.router.world, self.router.aff = runner, world, aff
        return self._ctx[1]

    # -- sweep ---------------------------------------------------------------------------------------------------------------------
    def candidates(self, engine) -> list:
        from systems.actions.dormancy_gate import asleep         # EDEN_WINDOW_DORMANCY: no sweep, no model call for a resident outside the integrated chunks
        roster = [uid for uid in getattr(engine, "_human_uid_by_slot", []) if uid and not asleep(engine, uid)]
        if not roster:
            return []
        n = min(self.config.batch, len(roster))
        start = self._cursor % len(roster)
        self._cursor = (start + n) % len(roster)
        return [roster[(start + i) % len(roster)] for i in range(n)]

    def _worth_evaluating(self, engine, actor: str, tick: int) -> bool:
        """Cheap tensor read, no features / mask: a calm resident (needs below ``urgent_need``, threat and low hp not ``significant``) cannot trigger an unmet need or a threat, and a
        resident whose rounded inputs are the same as at its last evaluation (inside one cooldown window) would get the same answer. Macro triggers
        of calm residents (USE_BRAIN / REPLAN / PLOT chosen by placeholder weights) are intentionally not looked for: nothing is wrong with them."""
        import genesis_config as cfg
        slot = engine._human_slot_for_id(actor)
        if slot < 0:
            return False
        row = engine.state.h_tensor[slot]
        hunger, thirst, threat, hp = float(row[cfg.HUNGER]) / 100.0, float(row[cfg.THIRST]) / 100.0, float(row[cfg.THREAT]) / 100.0, float(row[cfg.HP]) / 100.0
        c = self.config
        if hunger < c.urgent_need and thirst < c.urgent_need and threat <= c.significant_threat and (1.0 - hp) <= c.significant_low_hp:
            self._digest.pop(actor, None)
            self.counts["skipped:calm"] += 1
            return False
        digest = (round(hunger, 1), round(thirst, 1), round(threat, 1), round(hp, 1), tick // max(1, c.cooldown_ticks))
        if self._digest.get(actor) == digest:
            self.counts["skipped:unchanged"] += 1
            return False
        self._digest[actor] = digest
        return True

    def sweep(self, engine, tick: int) -> dict:
        began = time.perf_counter()
        residents = self.candidates(engine)
        if self.config.prefilter:
            residents = [actor for actor in residents if self._worth_evaluating(engine, actor, tick)]
        report = {"tick": tick, "examined": len(residents), "triggered": [], "requested": [], "skipped": []}
        if not residents:
            self.last_sweep_ms = (time.perf_counter() - began) * 1000.0
            return report
        from systems.decision import matrix
        from systems.decision.features import FEATURE_INDEX, build_features
        world, services, aff, _runner = self._context(engine)
        from systems.actions.weights import default_policy
        self.policy = self.policy or default_policy()
        batch = build_features(world, services, residents)
        Mw = self._world_aff(world, services).mask(residents)                    # one mask, judged by the world, not by the driver table (D-008)
        result = self.policy.decide(batch.X, batch.P, Mw)
        significant = (batch.X[:, FEATURE_INDEX["threat"]] > self.config.significant_threat) | \
                      (batch.X[:, FEATURE_INDEX["low_hp"]] > self.config.significant_low_hp)
        uncertain = self.policy.gate(result, significant, self.gate)
        names = result.names()
        asked = 0
        for i, actor in enumerate(residents):
            if not bool(batch.alive[i]):
                continue
            legal = {matrix.MENU[j] for j in Mw[i].nonzero().flatten().tolist()}
            triggers = classify(batch.row(actor), names[i], bool(uncertain[i]), legal, self.config)
            if not triggers:
                continue
            report["triggered"].append((actor, triggers))
            for trigger in triggers:
                self.counts[f"trigger:{trigger}"] += 1
            if asked >= self.config.max_per_sweep:
                report["skipped"].append((actor, "sweep_budget"))
                self.counts["skipped:sweep_budget"] += 1
                continue
            trigger = triggers[0]
            if self._asked.get((actor, trigger), -1) > tick:
                report["skipped"].append((actor, "cooldown"))
                self.counts["skipped:cooldown"] += 1
                continue
            ticket = self.router.request_plan(actor, trigger, parent_tier=1, tick=tick)
            self._asked[(actor, trigger)] = tick + self.config.cooldown_ticks
            if len(self._asked) > 4096:
                self._asked = {k: v for k, v in self._asked.items() if v > tick}
            asked += 1
            report["requested"].append((actor, trigger, ticket.status, ticket.reason))
            self.counts[f"request:{ticket.status}"] += 1
            if ticket.status == "pending" and self.plane.mode("resident") == "on":
                self._pending_run[actor] = tick
        self.last_sweep_ms = (time.perf_counter() - began) * 1000.0
        self.recent.append({k: report[k] for k in ("tick", "examined", "requested")})
        return report

    # -- mode on: run what the gate accepted ---------------------------------------------------------------------------------------
    def _epoch_key(self, engine) -> str:
        """A plan belongs to one world epoch and one model epoch: a world reset or a switch change aborts it (stale_epoch)."""
        return f"{getattr(engine, 'world_epoch', '')}:{self.plane.switch.epoch}"

    def _cursors(self):
        from systems.actions import PlanCursors
        runner = self._ctx[1][3]
        if self.cursors is None or self.cursors.runner is not runner:
            if self.cursors is not None and self.cursors.cursors:
                self.counts["run:failed:runner_replaced"] += len(self.cursors.cursors)
            self.cursors = PlanCursors(runner, timeout_ticks=self.config.task_timeout_ticks)
        return self.cursors

    def _advance(self, tick: int, engine) -> list:
        events = self.cursors.advance(tick, self._epoch_key(engine))
        for event in events:
            self.counts["run:ok" if event["status"] == "done" else f"run:failed:{event['reason']}"] += 1
            self.plane._log({"type": "tier3_run", "resident_id": event["actor"], "tick": tick, "ok": event["status"] == "done",
                             "code": event["reason"] or "ok", "completed": event["completed"], "failed_at": event["failed_at"]})
        return events

    def _collect(self, tick: int, engine=None) -> list:
        from systems.actions import run_plan
        done = []
        for actor, asked_at in list(self._pending_run.items()):
            result = self.router.poll_plan(actor)
            if result is None:
                if tick - asked_at > 600:                                                    # never answered: forget it
                    del self._pending_run[actor]
                    self.counts["run:expired"] += 1
                continue
            del self._pending_run[actor]
            if result.status != "accepted" or not self.config.run_accepted:
                self.counts[f"run:{result.status}"] += 1
                continue
            if self.config.step_mode == "cursor" and engine is not None:
                self._cursors().start(actor, result.proposal.steps_list(), confidence=result.proposal.confidence, tick=tick,
                                      epoch=self._epoch_key(engine))
                self.counts["run:started"] += 1
                self._advance(tick, engine)
                continue
            outcome = run_plan(self._ctx[1][3], actor, result.proposal.steps_list(), proposer="tier3", confidence=result.proposal.confidence)
            self.counts["run:ok" if outcome["ok"] else f"run:failed:{outcome['code']}"] += 1
            done.append((actor, outcome["code"], outcome["completed"]))
            self.plane._log({"type": "tier3_run", "resident_id": actor, "tick": tick, "ok": outcome["ok"], "code": outcome["code"],
                             "completed": outcome["completed"], "failed_at": outcome["failed_at"]})
        return done

    def status(self) -> dict:
        return {"config": {"period": self.config.period, "batch": self.config.batch, "max_per_sweep": self.config.max_per_sweep,
                           "cooldown_ticks": self.config.cooldown_ticks, "run_accepted": self.config.run_accepted},
                "routes": dict(TRIGGER_ROLE), "counts": dict(self.counts), "waiting_for_plan": len(self._pending_run),
                "plans_running": {} if self.cursors is None else self.cursors.status()["active"],
                "last_sweep_ms": round(self.last_sweep_ms, 3), "recent": list(self.recent)[-5:]}


def install(dispatch, plane, *, runner=None, config: Optional[EscalationConfig] = None) -> Escalator:
    """Build the router + escalator for ``plane`` and register the post-step hook (idempotent; builtin so ``DISPATCH.clear()`` keeps it)."""
    from .router import Tier3Router
    existing = getattr(plane, "escalator", None)
    if existing is not None:
        return existing
    router = plane.tier3 or Tier3Router(plane, runner=runner)
    escalator = Escalator(plane, router, config=config)
    escalator.warm()
    plane.escalator = escalator
    if not any(name == HOOK_NAME for name, _ in dispatch.post_step_hooks):
        dispatch.register_post_step_hook(HOOK_NAME, engine_hook, builtin=True)
    return escalator


def engine_hook(engine) -> None:
    """The one registered hook: finds the engine's plane (``engine._model_plane``) so a stale plane from another engine is never driven."""
    plane = engine.__dict__.get("_model_plane")
    escalator = None if plane is None else plane.escalator
    if escalator is not None:
        escalator.hook(engine)


def uninstall(dispatch) -> None:
    dispatch.unregister_hook(HOOK_NAME)
    dispatch.builtin_names.discard(HOOK_NAME)
