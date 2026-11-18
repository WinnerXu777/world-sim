"""The docket: cases an authority has accepted. Pure data, no engine."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Optional

CASE_TTL_DAYS = 2


@dataclass
class Case:
    id: str
    thief: str
    victim: str
    authority: str
    reporter: str
    item: str
    qty: int
    value: float
    opened: int
    expires: int
    status: str = "open"           # open | closed | lapsed
    outcome: str = ""              # paid | part_paid | nothing_to_levy | lapsed


class Docket:
    def __init__(self):
        self.cases: dict = {}
        self.counts: Counter = Counter()
        self.log: list = []
        self.reported: set = set()      # theft event ids already reported to an authority (one report each)
        self._next = 1

    def open(self, thief: str, victim: str, authority: str, reporter: str, item: str, qty: int, value: float, tick: int, day_ticks: int) -> Case:
        case = Case(f"case_{self._next:05d}", thief, victim, authority, reporter, item, int(qty), float(value), int(tick), int(tick) + CASE_TTL_DAYS * int(day_ticks))
        self._next += 1
        self.cases[case.id] = case
        self.counts["opened"] += 1
        self.note(tick, "opened", case)
        return case

    def open_cases(self, authority: Optional[str] = None) -> list:
        return [c for c in self.cases.values() if c.status == "open" and (authority is None or c.authority == authority)]

    def against(self, thief: str, victim: Optional[str] = None) -> Optional[Case]:
        return next((c for c in self.cases.values() if c.status == "open" and c.thief == thief and (victim is None or c.victim == victim)), None)

    def for_authority(self, authority: str, thief: str, tick: Optional[int] = None) -> Optional[Case]:
        return next((c for c in self.cases.values() if c.status == "open" and c.authority == authority and c.thief == thief and (tick is None or tick < c.expires)), None)

    def close(self, case_id: str, outcome: str, tick: int) -> Optional[Case]:
        case = self.cases.get(case_id)
        if case is None or case.status != "open":
            return None
        case.status, case.outcome = "closed", outcome
        self.counts[outcome] += 1
        self.note(tick, outcome, case)
        return case

    def lapse(self, tick: int) -> list:
        gone = [c for c in self.cases.values() if c.status == "open" and tick >= c.expires]
        for case in gone:
            case.status, case.outcome = "lapsed", "lapsed"
            self.counts["lapsed"] += 1
            self.note(tick, "lapsed", case)
        return gone

    def note(self, tick: int, what: str, case: Case) -> None:
        if len(self.log) < 2000:
            self.log.append({"tick": int(tick), "what": what, "case": case.id, "thief": case.thief, "victim": case.victim, "authority": case.authority})
