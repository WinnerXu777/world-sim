from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    import instincts_and_tools as iat
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import instincts_and_tools as iat

from .execution_actions import ExecutionActionMixin
from .execution_selectors import ExecutionSelectorMixin
from .execution_support import EXECUTION_SCHEMA_VERSION, atomic_write_json, load_registry_entries
from .execution_validation import ExecutionValidationMixin


class ExecutionAgentRuntime(ExecutionValidationMixin, ExecutionSelectorMixin, ExecutionActionMixin):
    def __init__(self, state_path: Path | None = None):
        self.state_path = state_path
        self.registry_entries = load_registry_entries()
        self.history: list[dict[str, Any]] = []
        self.last_error: dict[str, Any] | None = None
        self._instinct_bits: dict[str, int] = {}
        self._runtime_param_cache: dict[str, dict[str, Any]] = {}
        self._load_state()
        self._sync_loaded_instincts()

    def _load_state(self) -> None:
        if self.state_path is None or not self.state_path.exists():
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return
        instinct_bits = payload.get("instinct_bits", {})
        if isinstance(instinct_bits, dict):
            self._instinct_bits = {
                str(name): int(bit)
                for name, bit in instinct_bits.items()
                if str(name).strip()
            }

    def _save_state(self) -> None:
        if self.state_path is None:
            return
        payload = {
            "schema_version": EXECUTION_SCHEMA_VERSION,
            "instinct_bits": dict(sorted(self._instinct_bits.items())),
        }
        atomic_write_json(self.state_path, payload)

    def _sync_loaded_instincts(self) -> None:
        for bit, fn in iat.ACQUIRED_INSTINCTS.items():
            self._instinct_bits.setdefault(fn.__name__, int(bit))

    def clear_history(self) -> None:
        self.history.clear()
        self.last_error = None

    def register_instinct_bit(self, instinct_name: str, bit: int) -> None:
        self._instinct_bits[str(instinct_name)] = int(bit)
        self._save_state()

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "known_tools": len(self.registry_entries),
            "known_instinct_bits": dict(sorted(self._instinct_bits.items())),
            "limits": self.limits_snapshot(),
            "history": self.history[-10:],
            "last_error": self.last_error,
        }

