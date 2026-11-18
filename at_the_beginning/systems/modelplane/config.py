"""Model plane settings. Environment names (all optional; the defaults mean "no models, no network"):

EDEN_TIER1=rules|matrix            Tier 1 policy (the matrix lands in systems/decision/matrix.py)
EDEN_TIER2=off|shadow|on           Tier 2 (decide role: Clef-style typed choice)
EDEN_TIER3_RESIDENT / _DIALOGUE / _WORLD = off|shadow|on
EDEN_MODEL_URL                     base URL of the model server (http://127.0.0.1:8100); the role route is appended
EDEN_TIER2_URL, EDEN_TIER3_<ROLE>_URL            per role base URL override
EDEN_TIER2_KEY_ENV, EDEN_TIER3_<ROLE>_KEY_ENV    NAME of the environment variable that holds the API key (never the key itself)
EDEN_TIER2_MODEL, EDEN_TIER3_<ROLE>_MODEL        model id, sent as the X-Model-Id header
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from .wire import ROLE_ROUTES
from .switch import ROLE_SLOT, SLOT_ENV

DEFAULT_LIMITS = {"decide": {"max_in_flight": 4, "per_minute": 600}, "resident": {"max_in_flight": 2, "per_minute": 60},
                  "dialogue": {"max_in_flight": 4, "per_minute": 240}, "world": {"max_in_flight": 1, "per_minute": 20}}


@dataclass
class Endpoint:
    base_url: str = ""
    key_env: str = ""
    model: str = ""

    def url(self, role: str) -> str:
        return self.base_url.rstrip("/") + ROLE_ROUTES[role] if self.base_url else ""

    def headers(self, environ=None) -> dict:
        environ = os.environ if environ is None else environ
        headers = {"Content-Type": "application/json"}
        key = environ.get(self.key_env, "") if self.key_env else ""
        if key:
            headers["Authorization"] = f"Bearer {key}"
        if self.model:
            headers["X-Model-Id"] = self.model
        return headers

    def public(self, role: str) -> dict:
        """Safe to show in /model_status: never the key, only whether the named variable is set."""
        return {"url": self.url(role), "model": self.model, "key_env": self.key_env,
                "key_present": bool(self.key_env and os.environ.get(self.key_env))}


@dataclass
class ModelPlaneConfig:
    endpoints: dict = field(default_factory=dict)     # role -> Endpoint
    limits: dict = field(default_factory=lambda: {r: dict(v) for r, v in DEFAULT_LIMITS.items()})
    workers: int = 2
    queue_limit: int = 64
    cooldown_s: float = 2.0
    max_depth: int = 1
    breaker_threshold: int = 5
    breaker_open_s: float = 5.0
    grace_ms: int = 50

    def endpoint(self, role: str) -> Endpoint:
        return self.endpoints.get(role) or Endpoint()

    @classmethod
    def from_env(cls, env=None) -> "ModelPlaneConfig":
        env = os.environ if env is None else env
        base = env.get("EDEN_MODEL_URL", "").strip()
        endpoints = {}
        for role, slot in ROLE_SLOT.items():
            prefix = SLOT_ENV[slot]
            endpoints[role] = Endpoint(base_url=env.get(f"{prefix}_URL", base).strip(),
                                       key_env=env.get(f"{prefix}_KEY_ENV", env.get("EDEN_MODEL_KEY_ENV", "")).strip(),
                                       model=env.get(f"{prefix}_MODEL", "").strip())
        return cls(endpoints=endpoints)
