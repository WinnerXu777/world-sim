"""Circuit breaker per endpoint: open after N consecutive failures, half-open probe after a cool-down."""
from __future__ import annotations

import threading
import time


class CircuitBreaker:
    CLOSED, OPEN, HALF_OPEN = "closed", "open", "half_open"

    def __init__(self, failure_threshold: int = 5, open_seconds: float = 5.0, clock=time.monotonic):
        self.failure_threshold = int(failure_threshold)
        self.open_seconds = float(open_seconds)
        self.clock = clock
        self._lock = threading.Lock()
        self._failures = 0
        self._opened_at = 0.0
        self._state = self.CLOSED
        self._probing = False
        self.opened_count = 0

    @property
    def state(self) -> str:
        with self._lock:
            return self._effective_state()

    def _effective_state(self) -> str:
        if self._state == self.OPEN and self.clock() - self._opened_at >= self.open_seconds:
            return self.HALF_OPEN
        return self._state

    def allow(self) -> bool:
        """May a request go out now? Half-open admits exactly one probe at a time."""
        with self._lock:
            state = self._effective_state()
            if state == self.CLOSED:
                return True
            if state == self.HALF_OPEN and not self._probing:
                self._state, self._probing = self.HALF_OPEN, True
                return True
            return False

    def record_success(self) -> None:
        with self._lock:
            self._failures, self._state, self._probing = 0, self.CLOSED, False

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            was_probe = self._probing
            self._probing = False
            if was_probe or self._failures >= self.failure_threshold:
                if self._state != self.OPEN:
                    self.opened_count += 1
                self._state, self._opened_at = self.OPEN, self.clock()

    def snapshot(self) -> dict:
        with self._lock:
            return {"state": self._effective_state(), "consecutive_failures": self._failures, "opened_count": self.opened_count}
