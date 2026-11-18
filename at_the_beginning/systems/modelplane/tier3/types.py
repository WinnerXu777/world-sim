"""Typed values of the Tier 3 path: what a model may propose (never raw packets), and what the gate decided."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

ROLE_KIND = {"resident": "plan", "dialogue": "line", "world": "intents"}


class PacketError(ValueError):
    """A reply that cannot be turned into a proposal. ``code`` is the stable reason that ends up in the log and the metrics."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail = code, detail


@dataclass(frozen=True)
class PlanProposal:
    resident_id: str
    steps: tuple                 # ({"op": verb id, "args": {...}}, ...)
    confidence: float
    summary: str = ""
    source: str = ""             # provider mode / model id that produced it

    def steps_list(self) -> list:
        return [{"op": s["op"], "args": dict(s.get("args") or {})} for s in self.steps]


@dataclass(frozen=True)
class DialogueLine:
    speaker: str
    listener: str
    text: str
    act: str = ""
    tone: str = "neutral"
    intent: str = ""             # one of the allowed physical intents, or ""
    source: str = ""             # "model" | "fallback"


@dataclass(frozen=True)
class WorldIntent:
    power: str
    args: dict
    reason: str = ""


@dataclass(frozen=True)
class GateResult:
    ok: bool
    reason: str = ""             # "" when ok, else a stable code: low_confidence, empty_plan, invalid_packet:<code>, illegal_step:<i>:<code>, ...
    detail: dict = field(default_factory=dict)


@dataclass
class Tier3Result:
    """One finished Tier 3 request as the router records it. ``status``: accepted (mode on, passed the gate), rejected (gate said no:
    use Tier 1/rules), shadow (mode shadow: ``would_apply`` says what the gate would have done; nothing is applied), fallback (the call
    itself failed: timeout, breaker, stale, invalid reply)."""
    kind: str                    # plan | line | intents
    role: str
    status: str
    reason: str = ""
    resident_id: str = ""
    mode: str = ""               # the switch mode when the request was made
    proposal: object = None
    would_apply: Optional[bool] = None
    job_id: str = ""
    tick: int = 0
    detail: dict = field(default_factory=dict)

    def summary(self) -> dict:
        return {"kind": self.kind, "role": self.role, "status": self.status, "reason": self.reason, "resident_id": self.resident_id,
                "mode": self.mode, "would_apply": self.would_apply, "job_id": self.job_id, "tick": self.tick}


@dataclass(frozen=True)
class Ticket:
    """What ``request_*`` returns: ``off`` (mode off, nothing was sent), ``pending`` (a job is in flight or was queued now), ``refused``
    (admission or the client refused it; ``reason`` says why)."""
    status: str
    reason: str = ""
    key: str = ""
