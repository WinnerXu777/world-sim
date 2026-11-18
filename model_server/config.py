"""Server configuration from environment variables (names only; secrets are read from the variable a config names).

EDEN_MODEL_BACKEND            default backend kind for every role (mock)
EDEN_MODEL_BACKEND_<ROLE>     per role override: mock | rules | recorded | openai_compat | clef
EDEN_MODEL_<ROLE>_URL / _KEY_ENV / _MODEL / _PATH / _TIMEOUT_S   backend options (openai_compat, clef, recorded)
EDEN_MODEL_RECORD_TO          append every successful answer to this JSONL (builds a replay corpus)
EDEN_MODEL_FAULTS             JSON list of fault specs (mock server testing), e.g. [{"kind":"hang","rate":0.1}]
EDEN_MODEL_FAULT_ADMIN        1 to allow POST /v1/mock/faults at runtime (default 0)
EDEN_MODEL_HOST / EDEN_MODEL_PORT   uvicorn bind (default 127.0.0.1:8100; loopback only unless you change it)
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from .contract import ROLES


@dataclass
class ServerConfig:
    backends: dict = field(default_factory=lambda: {role: ("mock", {}) for role in ROLES})
    faults: list = field(default_factory=list)
    fault_seed: int = 0
    fault_admin: bool = False
    record_to: str = ""
    max_body_bytes: int = 1_000_000
    workers: int = 8

    @classmethod
    def from_env(cls, env=None) -> "ServerConfig":
        env = os.environ if env is None else env
        default = env.get("EDEN_MODEL_BACKEND", "mock")
        backends = {}
        for role in ROLES:
            kind = env.get(f"EDEN_MODEL_BACKEND_{role.upper()}", default)
            options = {}
            for suffix, key in (("URL", "url"), ("KEY_ENV", "key_env"), ("MODEL", "model"), ("PATH", "path"), ("TIMEOUT_S", "timeout_s")):
                value = env.get(f"EDEN_MODEL_{role.upper()}_{suffix}")
                if value:
                    options[key] = value
            backends[role] = (kind, options)
        faults = json.loads(env.get("EDEN_MODEL_FAULTS") or "[]")
        return cls(backends=backends, faults=faults, fault_seed=int(env.get("EDEN_MODEL_FAULT_SEED", "0")),
                   fault_admin=env.get("EDEN_MODEL_FAULT_ADMIN", "0") == "1", record_to=env.get("EDEN_MODEL_RECORD_TO", ""))
