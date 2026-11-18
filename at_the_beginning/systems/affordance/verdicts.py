"""Small value types of the affordance engine: a verdict (legal or not, and why), an option, a resolved call."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Verdict:
    """The answer to "can this happen?": ``ok`` and, when not, a stable ``reason`` code (see ``REASONS``).

    ``reachability`` is "exact" when the answer came from a straight line or a finished path search, "approx" when the search
    budget ran out and the straight-line answer was used, "" when no movement was involved.
    """
    ok: bool
    reason: str = ""
    detail: dict = field(default_factory=dict)
    reachability: str = ""
    distance: Optional[float] = None

    def to_dict(self) -> dict:
        out = {"ok": self.ok, "reason": self.reason}
        if self.detail:
            out["detail"] = dict(self.detail)
        if self.reachability:
            out["reachability"] = self.reachability
        if self.distance is not None:
            out["distance"] = round(self.distance, 2)
        return out


def yes(detail: Optional[dict] = None, *, reachability: str = "", distance: Optional[float] = None) -> Verdict:
    return Verdict(True, "", dict(detail or {}), reachability, distance)


def no(reason: str, **detail) -> Verdict:
    return Verdict(False, reason, detail)


# Stable reason codes. The audit log and the model's repair message use these strings, so they are part of the contract.
REASONS = (
    "dead", "unknown_verb", "system_missing", "invalid_params", "no_item", "no_edible", "no_source", "not_needed", "unreachable",
    "out_of_range", "blocked", "no_room", "no_station", "no_recipe", "missing_ingredients", "missing_tool", "wrong_occupation",
    "no_target", "target_dead", "self_target", "not_offered", "no_anchor", "already_there", "threatened", "no_plan", "no_motive",
    "no_site", "not_wired", "rate_limited", "roster_driven",
)


@dataclass(frozen=True)
class Option:
    """One thing the resident could do right now, with the concrete parameters the model may pass."""
    verb: str
    params: dict
    verdict: Verdict
    targets: tuple = ()

    @property
    def legal(self) -> bool:
        return self.verdict.ok

    @property
    def distance(self) -> Optional[float]:
        return self.verdict.distance

    def to_dict(self) -> dict:
        return {"verb": self.verb, "params": dict(self.params), "verdict": self.verdict.to_dict(), "targets": list(self.targets)}


@dataclass(frozen=True)
class ActionCall:
    """A macro resolved to a concrete verb call: what the runner executes."""
    verb: str
    params: dict
    macro: str = ""
