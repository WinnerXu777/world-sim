"""Deterministic fault injection for the mock server (Gate A: timeouts, garbage, slow and stale replies).

A fault spec is ``{"kind": ..., "rate": 0..1, "roles": [...]?, "delay_ms": n?, "variant": n?}``. Whether a request is hit is a pure
function of (seed, job_id, kind), so a run is reproducible. Kinds:
  hang      the HTTP handler sleeps ``delay_ms`` (default 5000) before answering: the caller's timeout fires
  slow      the backend takes ``delay_ms`` (default 400); beyond the request deadline the server answers 504
  error500  HTTP 500 with a plain-text body
  garbage   HTTP 200 with a body that is not a valid reply (variants: non-JSON, truncated JSON, wrong shape, empty)
  bad_result  valid envelope whose result breaks the contract (wrong option set, probabilities not summing to 1, ...)
  stale     valid envelope echoing a different world_epoch / state_revision
"""
from __future__ import annotations

import hashlib

KINDS = ("hang", "slow", "error500", "garbage", "bad_result", "stale")
GARBAGE = ("this is not json", '{"ok": true, "job_id": "x", "result": {"probabil', "[1, 2, 3]", "")


def _unit(seed, job_id, kind) -> float:
    digest = hashlib.sha256(f"{seed}|{job_id}|{kind}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2.0 ** 64


class FaultPlan:
    def __init__(self, specs=None, seed: int = 0):
        self.seed = seed
        self.specs = []
        self.hits: dict = {}
        self.set(specs or [])

    def set(self, specs) -> None:
        clean = []
        for spec in specs:
            if spec.get("kind") not in KINDS:
                raise ValueError(f"unknown fault kind {spec.get('kind')!r}; choose one of {KINDS}")
            rate = float(spec.get("rate", 1.0))
            if not 0.0 <= rate <= 1.0:
                raise ValueError("fault rate must be in [0, 1]")
            clean.append({**spec, "rate": rate})
        self.specs = clean

    def pick(self, job_id: str, role: str, kind: str):
        """The first spec of ``kind`` that hits this request, or None."""
        for spec in self.specs:
            if spec["kind"] != kind or (spec.get("roles") and role not in spec["roles"]):
                continue
            if _unit(self.seed, job_id, kind) < spec["rate"]:
                self.hits[kind] = self.hits.get(kind, 0) + 1
                return spec
        return None

    def to_list(self):
        return list(self.specs)


def garbage_body(spec, job_id: str) -> str:
    variant = spec.get("variant")
    if variant is None:
        variant = int(_unit("variant", job_id, "garbage") * len(GARBAGE))
    return GARBAGE[int(variant) % len(GARBAGE)]


def corrupt_result(role: str, result: dict, spec, job_id: str) -> dict:
    """Return a result that violates the contract for ``role``."""
    variant = spec.get("variant")
    if variant is None:
        variant = int(_unit("variant", job_id, "bad_result") * 3)
    if role == "decide":
        probs = dict(result["probabilities"])
        key = next(iter(probs))
        if variant % 3 == 0:
            probs[key] = probs[key] + 0.5          # does not sum to 1
        elif variant % 3 == 1:
            probs["not_an_offered_option"] = 0.0     # option-set mismatch
        else:
            probs[key] = -0.2                       # negative
        return {"probabilities": probs}
    responses = [dict(r) for r in result["responses"]]
    if variant % 3 == 0:
        return {**result, "responses": responses[:-1] if len(responses) > 1 else []}   # wrong count
    responses[0] = {"packet": "not an object"} if variant % 3 == 1 else {"packet": {"map_actions": "nope", "speech_text": "", "intent": "", "plans": "nope"}}
    return {**result, "responses": responses}
