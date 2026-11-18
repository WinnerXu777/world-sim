"""Tier 2 for the agent driver (``EDEN_AGENT_TIER2=1``, default off; needs ``EDEN_AGENT_TIER1=matrix``): the macro-menu ``DecisionRequest`` builder and its use.

When the matrix is unsure about a resident's macro (top probability or margin under the ``GateConfig`` thresholds) and the situation matters (a need, a threat or an injury),
``Tier2.refine`` asks the decision service one typed question: the **legal** macros as options, a structured snapshot as state, topic ``macro``. The model plane's own switch
decides what happens (``off``: rules answer, no network; ``shadow``: rules answer applied and the model's answer logged beside it; ``on``: the model's answer once it has
arrived, rules meanwhile). The rules answer for topic ``macro`` is Tier 1's own distribution (a registered scorer), so every fallback, a missing plane and the shadow
mode give exactly the Tier 1 macro, and only a model answer ever changes it. The question is keyed by the situation (``state_revision`` = a hash of the legal set, the running
macro and the bucketed needs), so asking again in an unchanged situation finds the answer the model returned earlier; a changed situation is a new question.
"""
from __future__ import annotations

import math
import os
import zlib
from collections import Counter
from typing import Optional

ENV = "EDEN_AGENT_TIER2"
TOPIC = "macro"
TRIGGER_PREFIX = "macro_review"
SIGNIFICANT_NEED = 50.0         # hunger or thirst from here up matters
SIGNIFICANT_THREAT = 30.0       # the same level the driver's threat interrupt uses
SIGNIFICANT_HP = 50.0           # below this the resident is hurt
BUCKET = 10.0                   # needs are bucketed to this width in the situation hash
DEADLINE_MS = 1000

DESCRIPTION = {
    "eat": "eat what the resident carries or walk to its food site", "drink": "drink at the water site", "rest": "rest to recover stamina",
    "sleep": "go to bed and sleep", "work_at_station": "work at the resident's station", "gather": "gather resources",
    "go_home": "walk home", "socialise": "talk with someone nearby", "trade": "trade or buy with a neighbour or a stall",
    "help": "help someone in need", "avoid": "keep away from a person or a place", "flee": "run from danger", "defend": "stand and defend",
    "attack": "attack a target (destructive)", "explore": "explore the surroundings", "build": "build something", "repair": "repair something",
    "ask_for_help": "ask a neighbour for help or food", "hide": "hide from danger", "idle": "do nothing for now",
    "continue_plan_step": "carry on with the current plan", "USE_BRAIN": "escalate to deliberate reasoning (Tier 3)",
    "REPLAN": "throw the plan away and plan again", "PLOT": "scheme (destructive)"}
DESTRUCTIVE = ("attack", "PLOT")


def enabled() -> bool:
    return os.environ.get(ENV, "") == "1"


def significant(hunger: float, thirst: float, threat: float, hp: float) -> bool:
    return max(hunger, thirst) >= SIGNIFICANT_NEED or threat >= SIGNIFICANT_THREAT or hp < SIGNIFICANT_HP


def uncertain(top_p: float, margin: float, config=None) -> bool:
    from systems.decision.matrix import GateConfig
    config = config or GateConfig()
    return top_p < config.min_top_p or margin < config.min_margin


def situation_revision(legal, running: str, needs: dict) -> int:
    """A stable int for 'the same question': the legal set, the running macro and the needs in 10-point buckets."""
    key = "|".join(sorted(legal)) + f"#{running}#" + ",".join(f"{k}={int(float(v) // BUCKET)}" for k, v in sorted(needs.items()))
    return zlib.crc32(key.encode("utf-8")) & 0x7FFFFFFF


def macro_scorer(request) -> dict:
    """The rules answer for topic ``macro``: Tier 1's own distribution (softmax at the service temperature gives it back)."""
    from systems.decision.providers import SOFTMAX_TEMPERATURE
    given = request.state.get("tier1", {})
    return {o.id: SOFTMAX_TEMPERATURE * math.log(max(float(given.get(o.id, 0.0)), 1e-12)) for o in request.options}


def build_request(*, human_id: str, world_epoch: str, tick: int, legal: list, probabilities: dict, running: str, needs: dict, extra: Optional[dict] = None):
    """The typed question for one resident: ``legal`` macros (already judged by the affordance engine) with Tier 1's distribution in the state."""
    from systems.decision import DecisionOption, DecisionRequest
    options = tuple(DecisionOption(m, DESCRIPTION.get(m, m), ("destructive",) if m in DESTRUCTIVE else ()) for m in legal)
    revision = situation_revision(legal, running, needs)
    state = {"needs": {k: round(float(v), 1) for k, v in sorted(needs.items())}, "running": running, "tier1": {m: round(float(probabilities.get(m, 0.0)), 4) for m in legal},
             **(extra or {})}
    return DecisionRequest(job_id=f"{human_id}:{TOPIC}:{revision}", resident_id=human_id, world_epoch=str(world_epoch), state_revision=revision, tick=int(tick),
                           trigger=f"{TRIGGER_PREFIX}:{revision}", question_kind="choice", options=options, state=state, priority="active", deadline_ms=DEADLINE_MS,
                           topic=TOPIC)


class Tier2:
    def __init__(self, gate=None, service=None):
        self.gate = gate
        self.service = service
        self.counts: Counter = Counter()
        self.log: list = []             # [{"tick", "actor", "tier1", "chosen", "mode", "top_p", "margin"}], capped
        self._registered = None

    def _service(self, engine):
        if self.service is not None:
            service = self.service
        else:
            from systems.commission.engine import decision_service
            service = decision_service(engine)
        if self._registered is not service:
            register = getattr(service.fallback, "register_scorer", None)
            if callable(register):
                register(TOPIC, macro_scorer)
            self._registered = service
        return service

    @staticmethod
    def needs_of(engine, human_id: str) -> dict:
        import genesis_config as cfg
        slot = engine._human_slot_for_id(human_id)
        h = engine.state.h_tensor
        return {"hunger": float(h[slot, cfg.HUNGER]), "thirst": float(h[slot, cfg.THIRST]), "threat": float(h[slot, cfg.THREAT]),
                "hp": float(h[slot, cfg.HP]), "mood": float(h[slot, cfg.MOOD])}

    def refine(self, engine, rows: list, macros: dict, details: dict, tick: int, running: Optional[dict] = None) -> dict:
        """Ask for the rows the gate marks; returns ``macros`` with the model's choice where a model answered. ``details``: human id -> ``{"legal", "probabilities"}``; ``running``: human id -> the macro it was on."""
        if not details:
            return macros
        out = dict(macros)
        service = self._service(engine)
        for row in rows:
            detail = details.get(row.human_id)
            if not detail or len(detail["legal"]) < 2:
                continue
            probs = detail["probabilities"]
            ordered = sorted(probs.values(), reverse=True)
            top_p, margin = ordered[0], ordered[0] - (ordered[1] if len(ordered) > 1 else 0.0)
            needs = self.needs_of(engine, row.human_id)
            if not (uncertain(top_p, margin, self.gate) and significant(needs["hunger"], needs["thirst"], needs["threat"], needs["hp"])):
                self.counts["not_gated"] += 1
                continue
            request = build_request(human_id=row.human_id, world_epoch=getattr(engine, "world_epoch", ""), tick=tick, legal=detail["legal"], probabilities=probs,
                                    running=(running or {}).get(row.human_id, ""), needs=needs, extra={"routine": row.routine})
            self.counts["asked"] += 1
            result = service.decide(request)
            self.counts[f"mode_{result.provider_mode}"] += 1
            fresh = service.apply_if_fresh(request, result, world_epoch=request.world_epoch, state_revision=request.state_revision, how="tier2_macro")
            chosen = result.top_option if fresh and result.top_option in detail["legal"] else out[row.human_id]
            if chosen != out[row.human_id]:
                self.counts["changed"] += 1
            if len(self.log) < 2000:
                self.log.append({"tick": int(tick), "actor": row.human_id, "tier1": out[row.human_id], "chosen": chosen, "mode": result.provider_mode,
                                 "top_p": round(top_p, 3), "margin": round(margin, 3)})
            out[row.human_id] = chosen
        return out

    def status(self) -> dict:
        return {"enabled": enabled(), "counts": dict(self.counts), "log": len(self.log)}
