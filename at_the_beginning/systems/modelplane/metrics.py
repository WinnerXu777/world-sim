"""Per role and lane counters and latency percentiles for /model_status. Thread safe; bounded memory."""
from __future__ import annotations

import threading
from collections import Counter, defaultdict, deque


def percentile(values, q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(q * (len(ordered) - 1)))))
    return ordered[index]


class ModelMetrics:
    COUNTERS = ("requests", "ok", "timeouts", "fallbacks", "stale_drops", "validation_rejects", "escalations", "skipped",
                "shadow_ok", "agreed", "disagreed", "breaker_open", "transport_errors", "http_errors", "gate_accepted", "gate_rejected")

    def __init__(self, window: int = 512):
        self._lock = threading.Lock()
        self.counts: dict = defaultdict(Counter)       # (role, lane) -> Counter
        self.latency: dict = defaultdict(lambda: deque(maxlen=window))
        self.queue_age: dict = defaultdict(lambda: deque(maxlen=window))
        self.reasons: dict = defaultdict(Counter)      # role -> fallback/skip reason

    def count(self, role: str, lane: str, name: str, n: int = 1) -> None:
        with self._lock:
            self.counts[(role, lane)][name] += n

    def reason(self, role: str, reason: str) -> None:
        with self._lock:
            self.reasons[role][reason] += 1

    def observe(self, role: str, lane: str, latency_ms: float, queue_age_ms: float) -> None:
        with self._lock:
            self.latency[(role, lane)].append(float(latency_ms))
            self.queue_age[(role, lane)].append(float(queue_age_ms))

    def snapshot(self) -> dict:
        with self._lock:
            out = {}
            for (role, lane), counter in self.counts.items():
                lat, age = self.latency[(role, lane)], self.queue_age[(role, lane)]
                total = counter["requests"] or 1
                shadow = counter["agreed"] + counter["disagreed"]
                out.setdefault(role, {})[lane] = {
                    **{name: counter[name] for name in self.COUNTERS},
                    "latency_ms": {"p50": round(percentile(lat, 0.5), 2), "p95": round(percentile(lat, 0.95), 2),
                                   "p99": round(percentile(lat, 0.99), 2)},
                    "queue_age_ms": {"p50": round(percentile(age, 0.5), 2), "p99": round(percentile(age, 0.99), 2)},
                    "fallback_rate": round(counter["fallbacks"] / total, 4),
                    "agreement": None if not shadow else round(counter["agreed"] / shadow, 4)}
            for role, reasons in self.reasons.items():
                out.setdefault(role, {})["reasons"] = dict(reasons)
            return out
