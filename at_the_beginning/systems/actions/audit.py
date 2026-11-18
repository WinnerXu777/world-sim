"""One audit entry per action call, accepted or rejected: an in-memory ring plus an optional JSONL sink. Not wired to the engine."""
from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from typing import Optional


class AuditLog:
    def __init__(self, maxlen: int = 4000, sink: Optional[str] = None):
        self.entries: deque = deque(maxlen=maxlen)
        self.sink = Path(sink) if sink else None
        self.total = 0

    def record(self, entry: dict) -> dict:
        self.total += 1
        entry = {"seq": self.total, **entry}
        self.entries.append(entry)
        if self.sink is not None:
            self.sink.parent.mkdir(parents=True, exist_ok=True)
            with self.sink.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, sort_keys=True, default=str) + "\n")
        return entry

    @property
    def last(self) -> Optional[dict]:
        return self.entries[-1] if self.entries else None

    def reasons(self) -> dict:
        out: dict = {}
        for e in self.entries:
            out[e["code"]] = out.get(e["code"], 0) + 1
        return out

    def clear(self) -> None:
        self.entries.clear()
