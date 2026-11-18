"""DecisionService: run the active provider, validate, fall back to rules, log, and drop stale results."""
import time
from collections import Counter

from .contract import DecisionError, DecisionResult, summarize, validate_probabilities, validate_request
from .log import DecisionLog
from .providers import RulesDecisionProvider


class DecisionService:
    """Runs a provider, falls back to rules when it fails, drops stale answers and logs every decision."""
    def __init__(self, provider=None, fallback=None, log=None, clock=time.perf_counter):
        self.fallback = fallback if fallback is not None else RulesDecisionProvider()
        self.provider = provider if provider is not None else self.fallback
        self.log = log if log is not None else DecisionLog(None)
        self.clock = clock
        self.counts = Counter()
        self.status_extras = {}  # name -> callable returning a JSON-able dict, merged into status() (e.g. the model plane)

    def decide(self, request):
        """Return a validated DecisionResult. Never raises for provider trouble: it falls back to rules."""
        validate_request(request)
        started = self.clock()
        note = ""
        mode = self.provider.mode
        try:
            probabilities = validate_probabilities(request.options, self.provider.decide(request))
            mode = getattr(self.provider, "last_mode", None) or mode  # a plane-backed provider reports who really answered
        except Exception as exc:  # noqa: BLE001 - any provider failure must degrade to rules, not break gameplay
            note = f"{type(exc).__name__}: {exc}"
            probabilities = validate_probabilities(request.options, self.fallback.decide(request))
            mode = "fallback" if self.provider is not self.fallback else self.fallback.mode
            self.counts["fallbacks"] += 1
        top, top_p, margin = summarize(request.options, probabilities)
        result = DecisionResult(job_id=request.job_id, resident_id=request.resident_id, world_epoch=request.world_epoch,
                                state_revision=request.state_revision, probabilities=probabilities, top_option=top,
                                top_p=top_p, margin=margin, provider_mode=mode,
                                latency_ms=round((self.clock() - started) * 1000.0, 3), note=note)
        self.counts["requests"] += 1
        self.counts[f"mode_{mode}"] += 1
        return result

    def apply_if_fresh(self, request, result, *, world_epoch, state_revision, chosen=None, how="argmax"):
        """True if the result may be applied now. A stale result (epoch or revision moved on) is dropped and logged.

        On success the decision is logged with ``chosen`` (default: the top option) and how it was chosen.
        """
        if result.world_epoch != world_epoch or request.world_epoch != world_epoch:
            self.counts["stale_dropped"] += 1
            self.log.record_drop(request.job_id, "stale_world_epoch", resident_id=request.resident_id)
            return False
        if result.state_revision != state_revision or request.state_revision != state_revision:
            self.counts["stale_dropped"] += 1
            self.log.record_drop(request.job_id, "stale_state_revision", resident_id=request.resident_id)
            return False
        self.log.record_decision(request, result, chosen=chosen or result.top_option, how=how,
                                 validation="fallback" if result.provider_mode == "fallback" else "ok")
        return True

    def status(self):
        return {"provider_mode": self.provider.mode, "fallback_mode": self.fallback.mode, "counts": dict(self.counts),
                "log_path": None if self.log.path is None else str(self.log.path), "log_write_errors": self.log.write_errors,
                **{name: fn() for name, fn in self.status_extras.items()}}


__all__ = ["DecisionError", "DecisionService"]
