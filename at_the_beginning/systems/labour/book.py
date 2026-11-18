"""The job book: who works for whom, for what wage, until when. Pure data, no engine.

A shift lasts ``WORK_TICKS``; the wage is worth about ``WAGE_VALUE`` (one ration's value) and is paid in an edible the employer can spare, else in coin. The worker must stay near
the employer (the ladder's errand follows them); a shift left unclaimed for ``CLAIM_TTL`` ticks after it is done lapses. One shift at a time per worker, ``MAX_WORKERS`` per
employer.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Optional

WORK_TICKS = 200
WAGE_VALUE = 2.0
CLAIM_TTL = 600
MAX_WORKERS = 2
KEEP = 1                       # an employer keeps at least this many units of a food for itself


def wage_units(unit_value: float) -> int:
    return max(1, int(math.ceil(WAGE_VALUE / max(float(unit_value), 1e-9) - 1e-9)))


@dataclass
class Job:
    id: str
    employer: str
    worker: str
    item: str
    qty: int
    started: int
    ready_at: int
    expires: int
    status: str = "working"        # working | paid | lapsed


class JobBook:
    def __init__(self, value: Callable[[str], float]):
        self.value = value
        self.jobs: dict = {}
        self.counts: Counter = Counter()
        self.log: list = []
        self._next = 1

    def hire(self, employer: str, worker: str, item: str, qty: int, tick: int) -> Job:
        job = Job(f"job_{self._next:05d}", employer, worker, item, int(qty), int(tick), int(tick) + WORK_TICKS, int(tick) + WORK_TICKS + CLAIM_TTL)
        self._next += 1
        self.jobs[job.id] = job
        self.counts["hired"] += 1
        self.note(tick, "hired", job)
        return job

    def of_worker(self, worker: str, tick: Optional[int] = None) -> Optional[Job]:
        return next((j for j in self.jobs.values() if j.status == "working" and j.worker == worker and (tick is None or tick < j.expires)), None)

    def between(self, worker: str, employer: str, tick: Optional[int] = None) -> Optional[Job]:
        job = self.of_worker(worker, tick)
        return job if job is not None and job.employer == employer else None

    def staff(self, employer: str, tick: int) -> int:
        return sum(1 for j in self.jobs.values() if j.status == "working" and j.employer == employer and tick < j.expires)

    def pay(self, job_id: str, tick: int) -> Optional[Job]:
        job = self.jobs.get(job_id)
        if job is None or job.status != "working":
            return None
        job.status = "paid"
        self.counts["paid"] += 1
        self.note(tick, "paid", job)
        return job

    def lapse(self, tick: int) -> list:
        gone = [j for j in self.jobs.values() if j.status == "working" and tick >= j.expires]
        for job in gone:
            job.status = "lapsed"
            self.counts["lapsed"] += 1
            self.note(tick, "lapsed", job)
        return gone

    def note(self, tick: int, what: str, job: Job) -> None:
        if len(self.log) < 2000:
            self.log.append({"tick": int(tick), "what": what, "job": job.id, "employer": job.employer, "worker": job.worker, "item": job.item, "qty": job.qty})
