"""Decision providers. Stage 1 ships the rules provider and a recorded-replay provider; Clef is a stub."""
import math

from .contract import DecisionError, validate_probabilities

SOFTMAX_TEMPERATURE = 0.35


def softmax(scores, temperature=SOFTMAX_TEMPERATURE):
    """Deterministic softmax over {id: score}; numerically stable."""
    if temperature <= 0 or not math.isfinite(temperature):
        raise ValueError("temperature must be finite and > 0")
    peak = max(scores.values())
    weights = {key: math.exp((value - peak) / temperature) for key, value in scores.items()}
    total = sum(weights.values())
    return {key: weight / total for key, weight in weights.items()}


class DecisionProvider:
    mode = "mock"

    def decide(self, request):
        """Return {option id: probability} for ``request``. May raise; the service falls back to rules."""
        raise NotImplementedError


class RulesDecisionProvider(DecisionProvider):
    """Deterministic scoring from the state snapshot. The permanent fallback.

    ``scorers`` maps a request ``topic`` to ``fn(request) -> {option id: score}``. A topic without a scorer scores
    every option equally (so the first option wins ties). When exactly one option is legal it gets p = 1.0.
    """
    mode = "rules"

    def __init__(self, scorers=None, temperature=SOFTMAX_TEMPERATURE):
        self.scorers = dict(scorers or {})
        self.temperature = temperature

    def register_scorer(self, topic, scorer):
        if not isinstance(topic, str) or not topic or not callable(scorer):
            raise ValueError("a scorer needs a topic name and a callable")
        self.scorers[topic] = scorer

    def decide(self, request):
        ids = [option.id for option in request.options]
        if len(ids) == 1:
            return {ids[0]: 1.0}
        scorer = self.scorers.get(request.topic)
        scores = {key: 0.0 for key in ids}
        if scorer is not None:
            produced = scorer(request)
            for key in ids:
                value = produced.get(key, 0.0)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise DecisionError(f"scorer produced a non-finite score for {key!r}")
                scores[key] = float(value)
        return softmax(scores, self.temperature)


class RecordedDecisionProvider(DecisionProvider):
    """Replays logged decisions by (resident_id, trigger). A missing record raises, so the service falls back."""
    mode = "recorded"

    def __init__(self, records):
        self.table = {}
        for record in records:
            if record.get("type", "decision") != "decision":
                continue
            self.table[(record["resident_id"], record["trigger"])] = dict(record["probabilities"])

    def decide(self, request):
        try:
            recorded = self.table[(request.resident_id, request.trigger)]
        except KeyError as exc:
            raise DecisionError(f"no recorded decision for {request.resident_id!r} / {request.trigger!r}") from exc
        return validate_probabilities(request.options, recorded)


class ModelPending(DecisionError):
    """The model has not answered yet (or was not used). The service falls back to rules for this call."""


class ClefDecisionProvider(DecisionProvider):
    """Tier 2: a thin client of the model server's ``/v1/decide`` (through a model plane), with rules fallback.

    Without a ``plane`` it is the Stage 1 stub and raises NotImplementedError (the service then falls back). With one, the
    plane's switch decides per call: ``off`` = rules only and no network; ``shadow`` = rules answer applied, the model's answer
    logged beside it; ``on`` = the model's validated answer once it has arrived. The tick never waits: on a cache miss the job
    is queued and ``ModelPending`` makes the service use rules this time. ``blocking=True`` waits up to the request deadline and
    is for scripts and tools only. The request/response mapping to a real Clef API is held (modelplane/adapters/clef.py).
    """
    mode = "live"

    def __init__(self, plane=None, fallback=None, blocking=False):
        self.plane = plane
        self.fallback = fallback if fallback is not None else RulesDecisionProvider()
        self.blocking = blocking
        self.last_mode = None

    def decide(self, request):
        if self.plane is None:
            raise NotImplementedError("ClefDecisionProvider needs a model plane; use RulesDecisionProvider")
        probabilities, self.last_mode = self.plane.decide_for_provider(request, self.fallback, blocking=self.blocking)
        return probabilities
