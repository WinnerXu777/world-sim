"""Recorded backend: replays answers from a JSONL file. A missing recording is an error (the game falls back).

Accepted lines: (a) decision-log records (``type: decision`` with resident_id, trigger, probabilities), (b) recorder lines
``{"role": ..., "key": ..., "result": {...}}`` written by ``Recorder`` below.
"""
from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from ..contract import Envelope
from .base import Backend, BackendError, CallContext


def request_key(envelope: Envelope) -> str:
    if envelope.role == "decide":
        return f"{envelope.payload['resident_id']}|{envelope.payload['trigger']}"
    blob = json.dumps({"mode": envelope.payload["mode"], "cases": envelope.payload["cases"]}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class RecordedBackend(Backend):
    kind = "recorded"
    provider_mode = "recorded"
    model_id = "recorded-v1"

    def __init__(self, path: str | None = None, records: list | None = None):
        self.path = path
        self.table: dict = {}
        self.error = ""
        try:
            lines = records if records is not None else self._read(path)
        except OSError as exc:
            self.error = f"cannot read recording: {exc}"
            lines = []
        for rec in lines:
            if rec.get("type") == "decision" and "probabilities" in rec:
                self.table[("decide", f"{rec['resident_id']}|{rec['trigger']}")] = {"probabilities": rec["probabilities"]}
            elif "role" in rec and "key" in rec and "result" in rec:
                self.table[(rec["role"], rec["key"])] = rec["result"]

    @staticmethod
    def _read(path):
        if not path:
            return []
        out = []
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn last line from a crash mid-write
        return out

    def ready(self):
        if self.error:
            return False, self.error
        return True, f"{len(self.table)} recordings"

    def handle(self, envelope: Envelope, ctx: CallContext) -> dict:
        try:
            return self.table[(envelope.role, request_key(envelope))]
        except KeyError as exc:
            raise BackendError("backend_error", f"no recording for {envelope.role} {request_key(envelope)[:40]}") from exc


class Recorder(Backend):
    """Wraps a backend and appends every successful (role, key, result) to a JSONL file, building a replay corpus."""

    def __init__(self, inner: Backend, path: str):
        self.inner, self.path = inner, Path(path)
        self._lock = threading.Lock()
        self.kind, self.provider_mode, self.model_id = inner.kind, inner.provider_mode, inner.model_id

    def ready(self):
        return self.inner.ready()

    def handle(self, envelope: Envelope, ctx: CallContext) -> dict:
        result = self.inner.handle(envelope, ctx)
        line = json.dumps({"role": envelope.role, "key": request_key(envelope), "result": result}, sort_keys=True)
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        return result
