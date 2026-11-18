"""Decision contract (1006newdesign.md section 5): typed options in, one probability per option out."""
import math
from dataclasses import dataclass, field

PROVIDER_MODES = ("rules", "matrix", "mock", "recorded", "fallback", "live")
QUESTION_KINDS = ("choice", "yes_no")
PRIORITIES = ("critical", "active", "background")


@dataclass(frozen=True)
class DecisionOption:
    """One option a decision can choose."""
    id: str
    description: str = ""
    tags: tuple = ()


@dataclass(frozen=True)
class DecisionRequest:
    """One question about one resident. ``options`` are already legal (computed from facts before the provider runs)."""
    job_id: str
    resident_id: str
    world_epoch: str
    state_revision: int
    tick: int
    trigger: str            # event type + causal event id, e.g. "commission_request:o_000001"
    question_kind: str
    options: tuple
    state: dict = field(default_factory=dict)  # structured snapshot the provider may read
    priority: str = "active"
    deadline_ms: int = 1000
    topic: str = "generic"  # selects the rules scorer, e.g. "commission"


@dataclass(frozen=True)
class DecisionResult:
    """A provider's answer: one probability per option, with the job identity and the mode that produced it."""
    job_id: str
    resident_id: str
    world_epoch: str
    state_revision: int
    probabilities: dict
    top_option: str
    top_p: float
    margin: float
    provider_mode: str
    latency_ms: float = 0.0
    note: str = ""  # why a fallback happened, when it did


class DecisionError(ValueError):
    """A provider returned something that is not a valid probability distribution over the offered options."""


def validate_request(request):
    """Refuse a request without options or with duplicate or empty option ids."""
    if not request.options:
        raise DecisionError("a request needs at least one option")
    ids = [option.id for option in request.options]
    if len(set(ids)) != len(ids) or any(not isinstance(i, str) or not i for i in ids):
        raise DecisionError("option ids must be unique non-empty strings")
    if request.question_kind not in QUESTION_KINDS:
        raise DecisionError(f"unknown question_kind {request.question_kind!r}")
    if request.priority not in PRIORITIES:
        raise DecisionError(f"unknown priority {request.priority!r}")


def validate_probabilities(options, probabilities, tolerance=1e-6):
    """Return the distribution as a clean dict over exactly the offered option ids, or raise DecisionError."""
    ids = [option.id for option in options]
    if not isinstance(probabilities, dict):
        raise DecisionError("probabilities must be a dict")
    if set(probabilities) != set(ids):
        raise DecisionError(f"probabilities must cover exactly the offered options {ids}, got {sorted(map(str, probabilities))}")
    clean = {}
    for key in ids:
        value = probabilities[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise DecisionError(f"probability for {key!r} must be a finite number >= 0, got {value!r}")
        clean[key] = float(value)
    total = sum(clean.values())
    if abs(total - 1.0) > 1e-3:
        raise DecisionError(f"probabilities must sum to 1, got {total}")
    return {key: value / total for key, value in clean.items()}  # absorb rounding so downstream sums are exact


def summarize(options, probabilities):
    """(top option id, top p, margin to the runner-up). Ties resolve to the earlier option in ``options``."""
    ranked = sorted(((probabilities[o.id], -index, o.id) for index, o in enumerate(options)), reverse=True)
    top_p, _, top = ranked[0]
    margin = top_p - ranked[1][0] if len(ranked) > 1 else top_p
    return top, top_p, margin
