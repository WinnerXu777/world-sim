"""The LLM switch (1008implementation.md section 1.1): per tier/role modes ``off | shadow | on`` plus the Tier 1 policy.

Everything defaults to ``off`` / ``rules``: no network, no threads. Changing anything bumps ``epoch`` (the model epoch), so jobs
sent under the old setting are dropped when they come back. The switch lives in the process, never in a saved world.
"""
from __future__ import annotations

import threading

MODES = ("off", "shadow", "on")
TIER1_POLICIES = ("rules", "matrix")
SLOTS = ("tier2", "tier3_resident", "tier3_dialogue", "tier3_world")
ROLE_SLOT = {"decide": "tier2", "resident": "tier3_resident", "dialogue": "tier3_dialogue", "world": "tier3_world"}
SLOT_ENV = {"tier2": "EDEN_TIER2", "tier3_resident": "EDEN_TIER3_RESIDENT", "tier3_dialogue": "EDEN_TIER3_DIALOGUE",
            "tier3_world": "EDEN_TIER3_WORLD"}


class SwitchError(ValueError):
    pass


class ModelSwitch:
    def __init__(self, tier1: str = "rules", modes: dict | None = None):
        self._lock = threading.Lock()
        self.epoch = 0
        self.tier1 = "rules"
        self.modes = {slot: "off" for slot in SLOTS}
        self.set(tier1=tier1, **(modes or {}))
        self.epoch = 0  # construction is not a toggle

    @classmethod
    def from_env(cls, env) -> "ModelSwitch":
        modes = {slot: env[name].strip().lower() for slot, name in SLOT_ENV.items() if env.get(name, "").strip()}
        return cls(tier1=env.get("EDEN_TIER1", "rules").strip().lower() or "rules", modes=modes)

    def mode(self, role: str) -> str:
        return self.modes[ROLE_SLOT[role]]

    def any_enabled(self) -> bool:
        return any(mode != "off" for mode in self.modes.values())

    def set(self, tier1: str | None = None, **slot_modes) -> dict:
        """Validate then apply. Returns ``{"changed": {...}, "epoch": n}``; the epoch moves only if something changed."""
        if tier1 is not None and tier1 not in TIER1_POLICIES:
            raise SwitchError(f"tier1 must be one of {TIER1_POLICIES}, got {tier1!r}")
        for slot, mode in slot_modes.items():
            if slot not in SLOTS:
                raise SwitchError(f"unknown slot {slot!r}; choose from {SLOTS}")
            if mode not in MODES:
                raise SwitchError(f"mode for {slot} must be one of {MODES}, got {mode!r}")
        with self._lock:
            changed = {}
            if tier1 is not None and tier1 != self.tier1:
                changed["tier1"] = [self.tier1, tier1]
                self.tier1 = tier1
            for slot, mode in slot_modes.items():
                if self.modes[slot] != mode:
                    changed[slot] = [self.modes[slot], mode]
                    self.modes[slot] = mode
            if changed:
                self.epoch += 1
            return {"changed": changed, "epoch": self.epoch}

    def all_off(self) -> dict:
        return self.set(**{slot: "off" for slot in SLOTS})

    def snapshot(self) -> dict:
        with self._lock:
            return {"tier1": self.tier1, **dict(self.modes), "epoch": self.epoch}
