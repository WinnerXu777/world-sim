"""Append-only JSONL decision log, kept outside saves (default ``<data_root>/decisions/decisions.jsonl``)."""
import json
import threading
import time
from pathlib import Path


class DecisionLog:
    """Writes one JSON object per line. ``root=None`` keeps records in memory only (tests, disabled logging)."""

    def __init__(self, root=None, filename="decisions.jsonl", memory_limit=2000):
        self.path = None if root is None else Path(root) / filename
        self.memory_limit = memory_limit
        self.records = []
        self._lock = threading.Lock()
        self.write_errors = 0

    def append(self, record):
        record = {"logged_at": round(time.time(), 3), **record}
        line = json.dumps(record, sort_keys=True, allow_nan=False, default=str)
        with self._lock:
            self.records.append(json.loads(line))
            del self.records[:-self.memory_limit]
            if self.path is not None:
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    with self.path.open("a", encoding="utf-8") as handle:
                        handle.write(line + "\n")
                except OSError:
                    self.write_errors += 1  # logging must never break a decision
        return record

    def record_decision(self, request, result, *, chosen, how, validation="ok", extra=None):
        return self.append({
            "type": "decision", "job_id": request.job_id, "resident_id": request.resident_id, "tick": request.tick,
            "world_epoch": request.world_epoch, "state_revision": request.state_revision, "trigger": request.trigger,
            "topic": request.topic, "question_kind": request.question_kind, "priority": request.priority,
            "state": request.state,
            "options": [{"id": o.id, "description": o.description, "tags": list(o.tags)} for o in request.options],
            "probabilities": result.probabilities, "provider_mode": result.provider_mode, "top_option": result.top_option,
            "top_p": result.top_p, "margin": result.margin, "chosen": chosen, "how": how, "validation": validation,
            "latency_ms": result.latency_ms, "note": result.note, **(extra or {})})

    def record_outcome(self, job_id, outcome, **extra):
        return self.append({"type": "outcome", "job_id": job_id, "outcome": outcome, **extra})

    def record_drop(self, job_id, reason, **extra):
        return self.append({"type": "drop", "job_id": job_id, "reason": reason, **extra})


def read_log(path):
    """Parse a JSONL log file; a malformed trailing line (crash mid-write) is skipped, earlier lines are kept."""
    records = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records
