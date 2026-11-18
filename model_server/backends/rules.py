"""Rules backend: answers with the game's own deterministic scorers (the permanent fallback, served over the wire).

``decide`` uses ``RulesDecisionProvider`` with the registered topic scorers (needs the game package on ``sys.path``;
``/ready`` says so when it is missing). The batch roles use the same built-in heuristics as the mock.
"""
from __future__ import annotations

import sys
from pathlib import Path

from ..contract import Envelope
from .base import Backend, BackendError, CallContext
from .heuristics import batch_result

_GAME_DIR = Path(__file__).resolve().parents[2] / "at_the_beginning"


class RulesBackend(Backend):
    kind = "rules"
    provider_mode = "rules"
    model_id = "rules-v1"

    def __init__(self):
        self._provider = None
        self._error = ""

    def _load(self):
        if self._provider is not None or self._error:
            return
        try:
            if str(_GAME_DIR) not in sys.path:
                sys.path.insert(0, str(_GAME_DIR))
            from systems.commission.decide import make_rules_provider
            self._provider = make_rules_provider()
        except Exception as exc:  # noqa: BLE001 - reported through /ready, not raised at import
            self._error = f"{type(exc).__name__}: {exc}"

    def ready(self):
        self._load()
        return (self._provider is not None, "ok" if self._provider is not None else f"game scorers unavailable: {self._error}")

    def handle(self, envelope: Envelope, ctx: CallContext) -> dict:
        if envelope.role != "decide":
            return batch_result(envelope.payload, "rules")
        self._load()
        if self._provider is None:
            raise BackendError("backend_unavailable", f"game scorers unavailable: {self._error}")
        from systems.decision.contract import DecisionOption, DecisionRequest
        p = envelope.payload
        request = DecisionRequest(job_id=envelope.job_id, resident_id=p["resident_id"], world_epoch=envelope.world_epoch,
                                  state_revision=envelope.state_revision, tick=int(p.get("tick", 0)), trigger=p["trigger"],
                                  question_kind=p["question_kind"], topic=p.get("topic", "generic"), state=p.get("state", {}),
                                  options=tuple(DecisionOption(o["id"], o.get("description", ""), tuple(o.get("tags", ())))
                                                for o in p["options"]))
        return {"probabilities": self._provider.decide(request)}
