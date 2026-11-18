"""Game-side model client: an async job queue on worker threads so the 20 Hz tick never blocks.

The tick thread only ever calls ``submit`` (non-blocking, never raises) and ``drain`` (non-blocking). Every failure ends as an
``Outcome`` with ``status == "fallback"``; the caller then uses its deterministic stand-in. With the role switched ``off`` a job is
refused before any queue, thread or socket exists.
"""
from __future__ import annotations

import json
import queue
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from .breaker import CircuitBreaker
from .budget import Admission
from .config import ModelPlaneConfig
from .metrics import ModelMetrics
from .switch import ModelSwitch
from .transport import HttpxTransport, Transport, TransportError, TransportTimeout
from .wire import ROLE_TIER, ROLES, ContractError, Envelope, parse_response

PRIORITY_RANK = {"critical": 0, "active": 1, "background": 2}


@dataclass
class Outcome:
    job: "Job"
    status: str                       # ok | fallback | dropped | skipped
    reason: str = ""
    response: object = None           # ResponseEnvelope when ok
    latency_ms: float = 0.0
    queue_age_ms: float = 0.0

    @property
    def shadow(self) -> bool:
        return self.job.mode == "shadow"


@dataclass
class Job:
    role: str
    payload: dict
    world_epoch: str
    state_revision: int
    job_id: str = ""
    priority: str = "active"
    deadline_ms: int = 1000
    resident_id: str = ""
    causal_id: str = ""
    depth: int = 0                    # 0 = raised by game code; an escalation adds 1
    parent_tier: int = 0              # tier of the job that spawned this one (0 = none)
    cancel_token: str = ""
    meta: dict = field(default_factory=dict)   # caller data carried through untouched (request, stand-in, ...)
    sync: bool = False
    # filled in by the client
    mode: str = "off"
    model_epoch: int = 0
    submitted_at: float = 0.0
    outcome: Optional[Outcome] = None
    _done: threading.Event = field(default_factory=threading.Event, repr=False)

    def __post_init__(self):
        if not self.job_id:
            self.job_id = f"{self.role}:{uuid.uuid4().hex[:12]}"


class ModelClient:
    def __init__(self, config: ModelPlaneConfig, switch: ModelSwitch, transport: Transport | None = None,
                 metrics: ModelMetrics | None = None, admission: Admission | None = None, clock=time.monotonic,
                 game_clock=None):
        self.config = config
        self.switch = switch
        self.transport = transport
        self.metrics = metrics or ModelMetrics()
        # wall clock: queue age, breaker. game clock (game seconds): per-game-minute budgets, cooldowns, dedupe TTL
        self.admission = admission or Admission(config.limits, config.cooldown_s, config.max_depth, clock=game_clock or clock)
        self.clock = clock
        self.breakers: dict = {}
        self.network_calls = 0
        self._queue: queue.PriorityQueue = queue.PriorityQueue()
        self._seq = 0
        self._outbox: deque = deque()
        self._lock = threading.Lock()
        self._cancelled: deque = deque(maxlen=2048)
        self._threads: list = []
        self._stop = threading.Event()
        self._queued = 0

    # ---- tick-thread API ------------------------------------------------------------------------------------------

    def submit(self, job: Job) -> Optional[Outcome]:
        """Queue ``job``. Returns None when queued, or an immediate Outcome (skipped / fallback) when refused. Never raises."""
        try:
            return self._submit(job)
        except Exception as exc:  # noqa: BLE001 - a client bug must degrade to the stand-in, never reach the tick
            return self._refuse(job, "fallback", f"client_error:{type(exc).__name__}")

    def drain(self, max_n: int | None = None) -> list:
        out = []
        while self._outbox and (max_n is None or len(out) < max_n):
            try:
                outcome = self._outbox.popleft()
            except IndexError:
                break
            if outcome.status in ("ok", "fallback") and outcome.job.model_epoch != self.switch.epoch:
                outcome = self._stale(outcome.job, outcome.queue_age_ms)
            out.append(outcome)
        return out

    def cancel(self, token: str) -> None:
        if token:
            self._cancelled.append(token)

    # ---- off-tick API (tools, tests, background) -------------------------------------------------------------------

    def call_sync(self, job: Job) -> Outcome:
        """Submit and wait up to the job's deadline. Do NOT call on the tick thread."""
        job.sync = True
        refused = self.submit(job)
        if refused is not None:
            return refused
        if not job._done.wait(job.deadline_ms / 1000.0 + self.config.grace_ms / 1000.0 + 0.25):
            self.cancel(job.cancel_token)
            return Outcome(job, "fallback", "timeout")
        return job.outcome

    def close(self) -> None:
        self._stop.set()
        for _ in self._threads:
            self._queue.put((99, 0, None))
        for thread in self._threads:
            thread.join(timeout=1.0)
        self._threads.clear()
        if self.transport is not None:
            self.transport.close()

    def status(self) -> dict:
        return {"queued": self._queued, "network_calls": self.network_calls, "workers": len(self._threads),
                "breakers": {url: breaker.snapshot() for url, breaker in self.breakers.items()},
                "admission": self.admission.snapshot(), "outbox": len(self._outbox)}

    # ---- internals ------------------------------------------------------------------------------------------------

    def _lane(self, job):
        return job.priority

    def _refuse(self, job: Job, status: str, reason: str) -> Outcome:
        outcome = Outcome(job, status, reason)
        job.outcome = outcome
        job._done.set()
        counter = "skipped" if status in ("skipped", "dropped") else "fallbacks"
        self.metrics.count(job.role, self._lane(job), counter)
        self.metrics.reason(job.role, reason)
        return outcome

    def _submit(self, job: Job) -> Optional[Outcome]:
        if job.role not in ROLES:
            return self._refuse(job, "skipped", "unknown_role")
        job.mode = self.switch.mode(job.role)
        job.model_epoch = self.switch.epoch
        if job.mode == "off":
            return self._refuse(job, "skipped", "disabled")      # OFF: no queue, no thread, no socket
        endpoint = self.config.endpoint(job.role)
        url = endpoint.url(job.role)
        if not url:
            return self._refuse(job, "fallback", "no_endpoint")
        breaker = self._breaker(url)
        if breaker.state == CircuitBreaker.OPEN:
            self.metrics.count(job.role, self._lane(job), "requests")
            self.metrics.count(job.role, self._lane(job), "breaker_open")
            return self._refuse(job, "fallback", "breaker_open")
        if self._queued >= self.config.queue_limit:
            return self._refuse(job, "skipped", "queue_full")
        ok, reason = self.admission.admit(job.role, job.resident_id, job.causal_id, job.depth, job.parent_tier, ROLE_TIER[job.role])
        if not ok:
            if reason == "escalation_depth" or reason == "escalation_loop":
                self.metrics.count(job.role, self._lane(job), "escalations")
            return self._refuse(job, "skipped", reason)
        job.submitted_at = self.clock()
        if job.depth:
            self.metrics.count(job.role, self._lane(job), "escalations")
        self.metrics.count(job.role, self._lane(job), "requests")
        self._ensure_started()
        with self._lock:
            self._seq += 1
            self._queued += 1
            self._queue.put((PRIORITY_RANK.get(job.priority, 1), self._seq, job))
        return None

    def _breaker(self, url: str) -> CircuitBreaker:
        breaker = self.breakers.get(url)
        if breaker is None:
            breaker = self.breakers.setdefault(url, CircuitBreaker(self.config.breaker_threshold, self.config.breaker_open_s, self.clock))
        return breaker

    def _ensure_started(self) -> None:
        if self._threads:
            return
        with self._lock:
            if self._threads:
                return
            if self.transport is None:
                self.transport = HttpxTransport()
            for index in range(self.config.workers):
                thread = threading.Thread(target=self._worker, name=f"model-client-{index}", daemon=True)
                thread.start()
                self._threads.append(thread)

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                _, _, job = self._queue.get(timeout=0.25)
            except queue.Empty:
                continue
            if job is None:
                return
            with self._lock:
                self._queued -= 1
            try:
                outcome = self._run(job)
            except Exception as exc:  # noqa: BLE001 - never let a worker die
                outcome = Outcome(job, "fallback", f"client_error:{type(exc).__name__}")
            self._finish(job, outcome)

    def _stale(self, job: Job, queue_age_ms: float = 0.0, reason: str = "stale_model_epoch") -> Outcome:
        self.admission.forget(job.role, job.causal_id)   # the question was never answered: it may be asked again
        self.metrics.count(job.role, self._lane(job), "stale_drops")
        self.metrics.reason(job.role, reason)
        return Outcome(job, "dropped", reason, queue_age_ms=queue_age_ms)

    def _run(self, job: Job) -> Outcome:
        started = self.clock()
        age_ms = (started - job.submitted_at) * 1000.0
        if job.model_epoch != self.switch.epoch:
            return self._stale(job, age_ms)
        if job.cancel_token and job.cancel_token in self._cancelled:
            return self._stale(job, age_ms, "cancelled")
        remaining_ms = job.deadline_ms - age_ms
        if remaining_ms <= 5.0:
            self.metrics.count(job.role, self._lane(job), "timeouts")
            return Outcome(job, "fallback", "expired_in_queue", queue_age_ms=age_ms)
        endpoint = self.config.endpoint(job.role)
        url = endpoint.url(job.role)
        breaker = self._breaker(url)
        if not breaker.allow():
            self.metrics.count(job.role, self._lane(job), "breaker_open")
            return Outcome(job, "fallback", "breaker_open", queue_age_ms=age_ms)
        envelope = Envelope(job_id=job.job_id, role=job.role, world_epoch=job.world_epoch, state_revision=job.state_revision,
                            payload=job.payload, priority=job.priority, deadline_ms=max(1, int(remaining_ms)),
                            cancel_token=job.cancel_token)
        body = json.dumps(envelope.to_dict(), separators=(",", ":"), allow_nan=False).encode("utf-8")
        timeout_s = (remaining_ms + self.config.grace_ms) / 1000.0
        sent = time.perf_counter()
        self.network_calls += 1
        try:
            reply = self.transport.post(url, body, endpoint.headers(), timeout_s)
        except TransportTimeout:
            breaker.record_failure()
            self.metrics.count(job.role, self._lane(job), "timeouts")
            return Outcome(job, "fallback", "timeout", queue_age_ms=age_ms)
        except TransportError as exc:
            breaker.record_failure()
            self.metrics.count(job.role, self._lane(job), "transport_errors")
            return Outcome(job, "fallback", f"transport_error:{str(exc)[:60]}", queue_age_ms=age_ms)
        latency_ms = (time.perf_counter() - sent) * 1000.0
        if reply.status != 200:
            if reply.status >= 500:
                breaker.record_failure()
            self.metrics.count(job.role, self._lane(job), "http_errors")
            code = reply.status
            if reply.status == 504:
                self.metrics.count(job.role, self._lane(job), "timeouts")
            return Outcome(job, "fallback", f"http_{code}", latency_ms=latency_ms, queue_age_ms=age_ms)
        try:
            data = json.loads(reply.text)
        except ValueError:
            breaker.record_failure()
            self.metrics.count(job.role, self._lane(job), "validation_rejects")
            return Outcome(job, "fallback", "bad_json", latency_ms=latency_ms, queue_age_ms=age_ms)
        try:
            response = parse_response(data, envelope)
        except ContractError as exc:
            breaker.record_failure()
            if exc.code == "stale_reply":
                self.metrics.count(job.role, self._lane(job), "stale_drops")
                return Outcome(job, "fallback", "stale_reply", latency_ms=latency_ms, queue_age_ms=age_ms)
            self.metrics.count(job.role, self._lane(job), "validation_rejects")
            return Outcome(job, "fallback", f"invalid_reply:{exc.code}", latency_ms=latency_ms, queue_age_ms=age_ms)
        breaker.record_success()
        if latency_ms > job.deadline_ms + self.config.grace_ms:
            self.metrics.count(job.role, self._lane(job), "timeouts")
            return Outcome(job, "fallback", "late_reply", latency_ms=latency_ms, queue_age_ms=age_ms)
        if job.model_epoch != self.switch.epoch:
            return self._stale(job, age_ms)
        return Outcome(job, "ok", response=response, latency_ms=latency_ms, queue_age_ms=age_ms)

    def _finish(self, job: Job, outcome: Outcome) -> None:
        self.admission.release(job.role)
        if outcome.status == "fallback" and outcome.reason:
            self.metrics.count(job.role, self._lane(job), "fallbacks")
            self.metrics.reason(job.role, outcome.reason.split(":")[0])
        elif outcome.status == "ok":
            self.metrics.count(job.role, self._lane(job), "ok")
            self.metrics.observe(job.role, self._lane(job), outcome.latency_ms, outcome.queue_age_ms)
        job.outcome = outcome
        if job.sync:
            job._done.set()
        else:
            self._outbox.append(outcome)
            job._done.set()
