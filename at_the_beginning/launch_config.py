"""Explicit runtime profiles; source assets and mutable world data are separate."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROFILES = {"gameplay", "render_fixture", "animation_qa"}


@dataclass(frozen=True)
class LaunchConfig:
    profile: str
    data_root: Path
    host: str
    port: int
    seed: int
    map_name: str

    @property
    def development(self) -> bool:
        return self.profile != "gameplay"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "LaunchConfig":
        env = os.environ if environ is None else environ
        profile = env.get("EDEN_PROFILE", "gameplay")
        if profile not in PROFILES:
            raise ValueError(f"EDEN_PROFILE must be one of {sorted(PROFILES)}")
        data_root = Path(env.get("EDEN_DATA_ROOT", str(PROJECT_ROOT / ".runtime" / profile))).resolve()
        legacy = (PROJECT_ROOT / "Data_Storage").resolve()
        if data_root == legacy or data_root.is_relative_to(legacy) or legacy.is_relative_to(data_root):
            raise ValueError("EDEN_DATA_ROOT must be separate from legacy Data_Storage; import saves explicitly")
        port = int(env.get("EDEN_PORT", "8002" if profile == "gameplay" else "8012"))
        if not 1 <= port <= 65535:
            raise ValueError("EDEN_PORT must be between 1 and 65535")
        return cls(profile, data_root, env.get("EDEN_HOST", "127.0.0.1"), port,
                   int(env.get("EDEN_SEED", "905")),
                   env.get("EDEN_MAP", "playable_village" if profile == "gameplay" else "render_test_village"))

    def status(self) -> dict:
        return {"profile": self.profile, "data_root": str(self.data_root),
                "seed": self.seed, "development": self.development,
                "model_mode": "deterministic", "map_name": self.map_name}
