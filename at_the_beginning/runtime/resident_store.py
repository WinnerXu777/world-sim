from __future__ import annotations

import copy
import json
import os
import random
from pathlib import Path
from typing import Any

import torch

try:
    import genesis_config as cfg
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg

try:
    from systems.construction.lifecycle import ensure_construction_behavior_state
    from systems.crafting.ops import ensure_resident_crafting_state
    from systems.goal.ops import ensure_resident_goals, refresh_goals_for_event, request_goal_review, review_resident_goals
    from systems.occupation.ops import ensure_resident_occupation
    from systems.planning.ops import ensure_resident_plans, queue_reasoning_review
    from systems.personality.ops import ensure_resident_personality, refresh_resident_pressures
    from systems.schedule.ops import choose_resident_schedule_routine, ensure_resident_schedule
    from systems.tasks.ops import ensure_resident_tasks
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.construction.lifecycle import ensure_construction_behavior_state
    from at_the_beginning.systems.crafting.ops import ensure_resident_crafting_state
    from at_the_beginning.systems.goal.ops import (
        ensure_resident_goals,
        refresh_goals_for_event,
        request_goal_review,
        review_resident_goals,
    )
    from at_the_beginning.systems.occupation.ops import ensure_resident_occupation
    from at_the_beginning.systems.planning.ops import ensure_resident_plans, queue_reasoning_review
    from at_the_beginning.systems.personality.ops import ensure_resident_personality, refresh_resident_pressures
    from at_the_beginning.systems.schedule.ops import choose_resident_schedule_routine, ensure_resident_schedule
    from at_the_beginning.systems.tasks.ops import ensure_resident_tasks


RESIDENT_SCHEMA_VERSION = 1
MAX_DECISION_HISTORY = 24
FLUSH_EVERY_TICKS = 20
RECENT_EVENT_LIMIT = 14
RESOURCE_MEMORY_LIMIT = 8
THREAT_MEMORY_LIMIT = 10
DEAD_EVENT_LIMIT = 6

PERMANENT_RELATION_TAGS = {"parent", "child", "family", "mate"}

RELATION_POLICY: dict[str, dict[str, Any]] = {
    "parent": {"permanent": True, "salience": 0.98},
    "child": {"permanent": True, "salience": 0.98},
    "family": {"permanent": True, "salience": 0.96},
    "mate": {"permanent": True, "salience": 0.92},
    "rival": {"ttl_years": (1, 4), "salience": 0.82},
    "friend": {"ttl_years": (2, 6), "salience": 0.72},
    "tribe_mate": {"ttl_years": (1, 3), "salience": 0.55},
    "neighbor": {"ttl_years": (1, 2), "salience": 0.35},
    "known": {"ttl_years": (1, 2), "salience": 0.25},
    "customer": {"permanent": True, "salience": 0.7},
}

EVENT_POLICY: dict[str, dict[str, Any]] = {
    "death": {"permanent": True, "salience": 1.0},
    "killed_human": {"permanent": True, "salience": 0.98},
    "killed_by": {"permanent": True, "salience": 1.0},
    "child_birth": {"permanent": True, "salience": 0.96},
    "born_to_parent": {"permanent": True, "salience": 0.96},
    "decision": {"ttl_years": (1, 3), "salience": 0.6},
    "attack": {"ttl_years": (1, 3), "salience": 0.72},
    "attacked": {"ttl_years": (1, 3), "salience": 0.78},
    "hunt_attack": {"ttl_years": (1, 2), "salience": 0.55},
    "hunt_kill": {"ttl_years": (2, 5), "salience": 0.82},
    "witnessed_death": {"ttl_years": (2, 5), "salience": 0.86},
    "world_decree": {"ttl_years": (1, 2), "salience": 0.42},
    "divine_gift": {"permanent": True, "salience": 0.9},
    "divine_heal": {"ttl_years": (4, 10), "salience": 0.85},
    "weather_changed": {"ttl_years": (1, 3), "salience": 0.3},
    "commission_requested": {"ttl_years": (1, 3), "salience": 0.5},
    "commission_accepted": {"permanent": True, "salience": 0.8},
    "commission_refused": {"permanent": True, "salience": 0.8},
    "commission_ready": {"ttl_years": (2, 5), "salience": 0.6},
    "commission_delivered": {"permanent": True, "salience": 0.88},
    "commission_failed": {"permanent": True, "salience": 0.86},
    "commission_canceled": {"ttl_years": (2, 5), "salience": 0.55},
}

RESOURCE_POLICY: dict[str, dict[str, Any]] = {
    "known_food_sources": {"ttl_years": (1, 2), "salience": 0.42},
    "known_water_sources": {"ttl_years": (1, 3), "salience": 0.48},
}

THREAT_POLICY: dict[str, dict[str, Any]] = {
    "predator": {"ttl_years": (1, 3), "salience": 0.7},
    "hazard": {"ttl_years": (1, 2), "salience": 0.6},
    "death_site": {"ttl_years": (2, 5), "salience": 0.9},
}

MALE_NAMES = [
    "Adam",
    "Noah",
    "Elias",
    "Jonah",
    "Micah",
    "Silas",
    "Asher",
    "Caleb",
    "Ezra",
    "Levi",
]

FEMALE_NAMES = [
    "Eve",
    "Mira",
    "Leah",
    "Ada",
    "Ruth",
    "Iris",
    "Nora",
    "Lena",
    "Thea",
    "Maya",
]


def _human_numeric_id(human_id: str) -> int:
    try:
        return int(human_id.split("_", 1)[1])
    except (IndexError, ValueError):
        return 0


def _resident_name(human_id: str, sex: int) -> str:
    idx = max(_human_numeric_id(human_id) - 1, 0)
    pool = FEMALE_NAMES if sex == 1 else MALE_NAMES
    return f"{pool[idx % len(pool)]}-{idx // len(pool) + 1}"


def _resident_behavior_tick(resident: dict[str, Any], fallback_tick: int = 0) -> int:
    snapshot = resident.get("snapshot", {})
    runtime = resident.get("runtime", {})
    profile = resident.get("profile", {})
    return int(
        snapshot.get(
            "tick",
            runtime.get(
                "last_seen_tick",
                profile.get("created_tick", fallback_tick),
            ),
        )
    )


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(payload, indent=2)
    # Never damage the last good file or conceal a failed replacement.
    # The caller retains dirty state and retries on a later flush.
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _resolve_ttl_ticks(ttl_years: Any) -> int | None:
    if ttl_years is None:
        return None
    if isinstance(ttl_years, (tuple, list)) and len(ttl_years) == 2:
        lo = int(round(float(ttl_years[0])))
        hi = int(round(float(ttl_years[1])))
        lo, hi = min(lo, hi), max(lo, hi)
        years = random.randint(max(lo, 0), max(hi, 0))
    else:
        years = int(round(float(ttl_years)))
    if years <= 0:
        return None
    try:
        from harness import calendar as _calendar
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.harness import calendar as _calendar
    return years * int(_calendar.ticks_per_year())


def _entry_sort_key(entry: dict[str, Any]) -> tuple[float, int, int]:
    salience = float(entry.get("salience", 0.0))
    reinforced = int(entry.get("last_reinforced_tick", entry.get("tick", entry.get("created_tick", 0))))
    created = int(entry.get("created_tick", entry.get("tick", 0)))
    return (salience, reinforced, created)


def _is_entry_active(entry: dict[str, Any], tick: int) -> bool:
    if bool(entry.get("archived", False)):
        return False
    if bool(entry.get("permanent", False)):
        return True
    expires_tick = entry.get("expires_tick")
    if expires_tick is None:
        return True
    return int(expires_tick) >= int(tick)


def _event_policy(kind: str) -> dict[str, Any]:
    policy = dict(EVENT_POLICY.get(str(kind), {}))
    if "permanent" not in policy and "ttl_years" not in policy:
        policy["ttl_years"] = (1, 2)
    policy.setdefault("salience", 0.5)
    return policy


def _relation_policy(kind: str) -> dict[str, Any]:
    policy = dict(RELATION_POLICY.get(str(kind), {}))
    if "permanent" not in policy and "ttl_years" not in policy:
        policy["ttl_years"] = (1, 2)
    policy.setdefault("salience", 0.3)
    return policy


def _resource_policy(bucket: str) -> dict[str, Any]:
    policy = dict(RESOURCE_POLICY.get(str(bucket), {}))
    if "permanent" not in policy and "ttl_years" not in policy:
        policy["ttl_years"] = (1, 2)
    policy.setdefault("salience", 0.4)
    return policy


def _threat_policy(kind: str) -> dict[str, Any]:
    policy = dict(THREAT_POLICY.get(str(kind), {}))
    if "permanent" not in policy and "ttl_years" not in policy:
        policy["ttl_years"] = (1, 2)
    policy.setdefault("salience", 0.65)
    return policy


def _apply_memory_policy(
    entry: dict[str, Any],
    policy: dict[str, Any],
    tick: int,
    *,
    default_class: str,
    base_tick_key: str = "tick",
) -> dict[str, Any]:
    created_tick = int(entry.get("created_tick", entry.get(base_tick_key, tick)))
    last_reinforced_tick = int(entry.get("last_reinforced_tick", entry.get(base_tick_key, created_tick)))
    permanent = bool(entry.get("permanent", policy.get("permanent", False)))
    expires_tick = entry.get("expires_tick")
    if not permanent and expires_tick is None:
        ttl_ticks = _resolve_ttl_ticks(policy.get("ttl_years"))
        if ttl_ticks is not None:
            expires_tick = created_tick + ttl_ticks
    elif expires_tick is not None:
        expires_tick = int(expires_tick)
    entry["memory_class"] = str(entry.get("memory_class", "permanent" if permanent else default_class))
    entry["salience"] = round(float(entry.get("salience", policy.get("salience", 0.5))), 3)
    entry["created_tick"] = created_tick
    entry["last_reinforced_tick"] = last_reinforced_tick
    entry["expires_tick"] = None if permanent else expires_tick
    entry["permanent"] = permanent
    entry["archived"] = bool(entry.get("archived", False))
    return entry


def _reinforce_memory_entry(
    entry: dict[str, Any],
    policy: dict[str, Any],
    tick: int,
    *,
    default_class: str,
    base_tick_key: str = "tick",
    salience_delta: float = 0.04,
) -> dict[str, Any]:
    entry = _apply_memory_policy(
        entry,
        policy,
        tick,
        default_class=default_class,
        base_tick_key=base_tick_key,
    )
    entry["last_reinforced_tick"] = int(tick)
    entry["archived"] = False
    if not bool(entry.get("permanent", False)):
        ttl_ticks = _resolve_ttl_ticks(policy.get("ttl_years"))
        if ttl_ticks is not None:
            entry["expires_tick"] = int(tick) + ttl_ticks
    salience = float(entry.get("salience", policy.get("salience", 0.5)))
    entry["salience"] = round(_clamp(salience + salience_delta, 0.0, 1.0), 3)
    return entry


def _retained_entries(entries: list[dict[str, Any]], tick: int, limit: int) -> list[dict[str, Any]]:
    active = [entry for entry in entries if _is_entry_active(entry, tick)]
    active.sort(
        key=lambda entry: (
            1 if bool(entry.get("permanent", False)) else 0,
            *_entry_sort_key(entry),
        ),
        reverse=True,
    )
    kept = active[: max(limit, 0)] if limit >= 0 else active
    kept.sort(
        key=lambda entry: (
            int(entry.get("tick", entry.get("created_tick", 0))),
            int(entry.get("created_tick", 0)),
            int(entry.get("last_reinforced_tick", 0)),
        )
    )
    return kept


ENSURE_ONCE_ENV = "EDEN_ENSURE_ONCE"
ENSURE_ONCE_EXEMPT = ("snapshot", "runtime", "pressures")      # what a repeat call within one tick may legitimately change


class ResidentAgentStore:
    def __init__(self, root_dir: Path):
        self.root_dir = root_dir
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, dict[str, Any]] = {}
        self._dirty: set[str] = set()
        self._memory_dirty: set[str] = set()
        self._last_flushed_tick: dict[str, int] = {}
        self.save_errors: dict[str, str] = {}
        self._last_failed_flush_tick: dict[str, int] = {}
        self._revisions: dict[str, int] = {}
        self._generation = 0
        self.background_writes = False
        self._attempt_serial = 0
        self._last_attempt_order: dict[str, int] = {}
        self._behavior_seen: dict[str, tuple] = {}        # EDEN_ENSURE_ONCE: human id -> (tick, resident record) of the last full behaviour pass
        self.ensure_once_violations: list = []

    def reset_world(self) -> None:
        self._behavior_seen.clear()
        self._generation += 1
        self._revisions.clear()
        self._last_attempt_order.clear()
        self._attempt_serial = 0
        self._cache.clear()
        self._dirty.clear()
        self._memory_dirty.clear()
        self._last_flushed_tick.clear()
        self.save_errors.clear()
        self._last_failed_flush_tick.clear()
        for path in self.root_dir.glob("*.json"):
            path.unlink(missing_ok=True)

    def _path(self, human_id: str) -> Path:
        return self.root_dir / f"{human_id}.json"

    def _resident_parent_occupations(self, resident: dict[str, Any]) -> list[str]:
        occupations: list[str] = []
        relationships = dict(resident.get("relationships", {}))
        for other_id, relation in relationships.items():
            tags = [str(tag) for tag in list(relation.get("tags", [])) if str(tag).strip()]
            if "parent" not in tags:
                continue
            other = self.get(str(other_id))
            if other is None:
                continue
            occupation_kind = str(other.get("occupation", {}).get("kind", "")).strip()
            if occupation_kind and occupation_kind not in occupations:
                occupations.append(occupation_kind)
        return occupations

    def get(self, human_id: str | None) -> dict[str, Any] | None:
        if not human_id:
            return None
        if human_id not in self._cache:
            path = self._path(human_id)
            if path.exists():
                resident = json.loads(path.read_text(encoding="utf-8"))
                tick = _resident_behavior_tick(resident)
                if self._ensure_behavior_state(resident, human_id=human_id, tick=tick):
                    self._mark_dirty(human_id)
                    self._mark_memory_dirty(human_id)
                self._cache[human_id] = resident
            else:
                return None
        return self._cache[human_id]

    def _snapshot_from_tensor(self, h_tensor: torch.Tensor, slot: int, tick: int) -> dict[str, Any]:
        row = h_tensor[slot].tolist()  # one conversion instead of 15 tensor indexings; float32 -> float is identical
        return {
            "tick": tick,
            "slot": slot,
            "x": round(row[cfg.X], 2),
            "y": round(row[cfg.Y], 2),
            "sex": int(round(row[cfg.H_SEX])),
            "age": round(row[cfg.H_AGE], 3),
            "hp": round(row[cfg.HP], 3),
            "hunger": round(row[cfg.HUNGER], 3),
            "thirst": round(row[cfg.THIRST], 3),
            "threat": round(row[cfg.THREAT], 3),
            "mood": round(row[cfg.MOOD], 3),
            "stamina": round(row[cfg.H_STAMINA], 3),
            "infection": round(row[cfg.H_INFECTION], 3),
            "tribe": round(row[cfg.H_TRIBE], 3),
            "escalated": bool(row[cfg.ESCALATION_FLAG] > 0.0),
        }

    def _ensure_behavior_state(
        self,
        resident: dict[str, Any],
        *,
        human_id: str,
        tick: int,
    ) -> bool:
        changed = False
        profile = resident.setdefault("profile", {})
        sex = int(profile.get("sex", resident.get("snapshot", {}).get("sex", 0)))

        previous_personality = dict(resident.get("personality", {}))
        personality = ensure_resident_personality(resident, human_id=human_id, sex=sex)
        if previous_personality != personality:
            changed = True

        previous_occupation = dict(resident.get("occupation", {}))
        occupation = ensure_resident_occupation(
            resident,
            human_id=human_id,
            personality=resident.get("personality"),
            parent_occupations=self._resident_parent_occupations(resident),
        )
        if previous_occupation != occupation:
            changed = True

        previous_schedule_profile = dict(resident.get("schedule_profile", {}))
        previous_schedule_state = dict(resident.get("schedule_state", {}))
        ensure_resident_schedule(resident, tick)
        if previous_schedule_profile != resident.get("schedule_profile", {}) or previous_schedule_state != resident.get("schedule_state", {}):
            changed = True
        if not resident.get("schedule_state", {}).get("current_routine"):
            schedule_decision = choose_resident_schedule_routine(
                resident,
                tick,
                context={
                    "reason": "bootstrap_schedule",
                    "has_home": True,
                    "settlement_present": True,
                },
            )
            if bool(schedule_decision.get("ok", False)):
                changed = True

        previous_crafting_state = dict(resident.get("crafting_state", {}))
        ensure_resident_crafting_state(resident, tick)
        if previous_crafting_state != resident.get("crafting_state", {}):
            changed = True

        previous_construction_state = dict(resident.get("construction_state", {}))
        previous_construction_profile = dict(resident.get("construction_profile", {}))
        previous_construction_needs = list(resident.get("construction_needs", []))
        previous_construction_projects = list(resident.get("construction_projects", []))
        if ensure_construction_behavior_state(resident, tick=tick):
            changed = True
        elif (
            previous_construction_state != resident.get("construction_state", {})
            or previous_construction_profile != resident.get("construction_profile", {})
            or previous_construction_needs != resident.get("construction_needs", [])
            or previous_construction_projects != resident.get("construction_projects", [])
        ):
            changed = True

        previous_tasks = list(resident.get("tasks", []))
        previous_task_state = dict(resident.get("task_state", {}))
        ensure_resident_tasks(resident, tick)
        if previous_tasks != resident.get("tasks", []) or previous_task_state != resident.get("task_state", {}):
            changed = True

        previous_pressures = dict(resident.get("pressures", {}))
        pressures = refresh_resident_pressures(resident, tick)
        if previous_pressures != pressures:
            changed = True

        previous_goals = list(resident.get("goals", []))
        ensure_resident_goals(resident, tick)
        if previous_goals != resident.get("goals", []):
            changed = True
        previous_plans = list(resident.get("plans", []))
        ensure_resident_plans(resident, tick)
        if previous_plans != resident.get("plans", []):
            changed = True

        resident["profile"]["occupation"] = str(resident.get("occupation", {}).get("kind", ""))
        return changed

    def _refresh_behavior_state(
        self,
        resident: dict[str, Any],
        *,
        human_id: str,
        tick: int,
        reason: str,
    ) -> bool:
        changed = False
        previous_pressures = dict(resident.get("pressures", {}))
        pressures = refresh_resident_pressures(resident, tick)
        if previous_pressures != pressures:
            changed = True
        return changed

    def _mark_memory_dirty(self, human_id: str | None) -> None:
        if human_id:
            self._memory_dirty.add(human_id)

    def touch_resident(self, human_id: str) -> None:
        self._mark_dirty(human_id)
        self._mark_memory_dirty(human_id)

    def run_goal_review_task(self, human_id: str, tick: int, reason: str) -> dict[str, Any] | None:
        resident = self.get(human_id)
        if resident is None:
            return None
        refresh_resident_pressures(resident, tick)
        review_resident_goals(resident, tick, reason=reason, force=True)
        self._mark_dirty(human_id)
        self._mark_memory_dirty(human_id)
        return resident

    def pending_memory_dirty_ids(self) -> list[str]:
        return sorted(self._memory_dirty)

    def clear_memory_dirty_ids(self, human_ids: list[str] | tuple[str, ...] | set[str]) -> None:
        for human_id in human_ids:
            self._memory_dirty.discard(human_id)

    def memory_dirty_count(self) -> int:
        return len(self._memory_dirty)

    def ensure_resident(
        self,
        human_id: str,
        slot: int,
        h_tensor: torch.Tensor,
        tick: int,
        preferred_name: str | None = None,
    ) -> dict[str, Any]:
        resident = self.get(human_id)
        if resident is None:
            sex = int(round(float(h_tensor[slot, cfg.H_SEX])))
            resident = {
                "schema_version": RESIDENT_SCHEMA_VERSION,
                "id": human_id,
                "profile": {
                    "name": preferred_name or _resident_name(human_id, sex),
                    "created_tick": tick,
                    "sex": sex,
                    "life_exp": round(float(h_tensor[slot, cfg.H_LIFE_EXP]), 3),
                },
                "status": {
                    "alive": True,
                    "current_intent": "observe",
                    "last_decision_tick": tick,
                    "last_reason": "created",
                },
                "relationships": {},
                "personality": {},
                "occupation": {},
                "pressures": {},
                "goals": [],
                "goal_state": {},
                "plans": [],
                "planning_state": {},
                "schedule_profile": {},
                "schedule_state": {},
                "crafting_state": {},
                "construction_profile": {},
                "construction_state": {},
                "construction_needs": [],
                "construction_projects": [],
                "tasks": [],
                "task_state": {},
                "memory": {
                    "recent_events": [],
                    "known_food_sources": [],
                    "known_water_sources": [],
                    "last_threats": [],
                },
                "history": {
                    "decisions": [],
                    "world_decrees": [],
                },
                "snapshot": {},
                "runtime": {
                    "slot": slot,
                    "alive": True,
                    "last_seen_tick": tick,
                },
            }
            self._cache[human_id] = resident
            self._ensure_behavior_state(resident, human_id=human_id, tick=tick)
            self._mark_dirty(human_id)
            self._mark_memory_dirty(human_id)
        elif preferred_name and resident["profile"]["name"] != preferred_name:
            resident["profile"]["name"] = preferred_name
            self._mark_dirty(human_id)
            self._mark_memory_dirty(human_id)

        resident["snapshot"] = self._snapshot_from_tensor(h_tensor, slot, tick)
        resident["runtime"]["slot"] = slot
        resident["runtime"]["alive"] = True
        resident["runtime"]["last_seen_tick"] = tick
        if self._behavior_pass(resident, human_id=human_id, tick=tick):
            self._mark_memory_dirty(human_id)
        self._prune_resident_memory(resident, tick, alive=True)
        self._mark_dirty(human_id)
        return resident

    def _behavior_pass(self, resident: dict[str, Any], *, human_id: str, tick: int) -> bool:
        """The behaviour part of ``ensure_resident``. ``EDEN_ENSURE_ONCE`` (default off): ``1`` runs the full pass once per resident per tick and, on
        the repeat calls of the same tick (the sync, the escalation sweep and the reasoning queue each call ``ensure_resident``), only refreshes the
        pressures, which depend on the snapshot that the repeat call just refreshed. ``check`` runs everything as before and records in
        ``ensure_once_violations`` any section other than snapshot/runtime/pressures that a repeat call changed (the proof the skip is pure)."""
        mode = os.environ.get(ENSURE_ONCE_ENV, "")
        if mode not in ("1", "check"):
            return self._ensure_behavior_state(resident, human_id=human_id, tick=tick)
        seen = self._behavior_seen.get(human_id)
        repeat = seen is not None and seen[0] == tick and seen[1] is resident
        if not repeat:
            self._behavior_seen[human_id] = (tick, resident)
            return self._ensure_behavior_state(resident, human_id=human_id, tick=tick)
        if mode == "1":
            previous = dict(resident.get("pressures", {}))
            return previous != refresh_resident_pressures(resident, tick)
        before = {key: copy.deepcopy(value) for key, value in resident.items() if key not in ENSURE_ONCE_EXEMPT}
        pressures_only = copy.deepcopy(resident)
        refresh_resident_pressures(pressures_only, tick)
        changed = self._ensure_behavior_state(resident, human_id=human_id, tick=tick)
        moved = sorted(key for key, value in before.items() if resident.get(key) != value)
        if resident.get("pressures") != pressures_only.get("pressures"):
            moved.append("pressures(full != pressures-only)")
        if moved and len(self.ensure_once_violations) < 200:
            self.ensure_once_violations.append((tick, human_id, moved))
        return changed

    def set_name(self, human_id: str, name: str) -> None:
        resident = self.get(human_id)
        if resident is None:
            return
        resident["profile"]["name"] = name
        self._mark_dirty(human_id)
        self._mark_memory_dirty(human_id)

    def sync_live_population(
        self,
        ids_by_slot: list[str | None],
        h_mask: torch.Tensor,
        h_tensor: torch.Tensor,
        tick: int,
    ) -> None:
        for slot in torch.where(h_mask)[0].tolist():
            human_id = ids_by_slot[slot]
            if human_id is None:
                continue
            self.ensure_resident(human_id, slot, h_tensor, tick)
        self.flush_dirty(tick)

    def mark_dead(self, human_id: str, tick: int) -> None:
        resident = self.get(human_id)
        if resident is None:
            return
        resident["status"]["alive"] = False
        resident["status"]["current_intent"] = "dead"
        resident["status"]["last_reason"] = "died"
        resident["runtime"]["alive"] = False
        resident["runtime"]["last_seen_tick"] = tick
        self.record_event(human_id, tick, "death", note="agent removed from simulation", trim=7)
        request_goal_review(resident, tick, "death")
        self._refresh_behavior_state(resident, human_id=human_id, tick=tick, reason="death")
        self._prune_resident_memory(resident, tick, alive=False)
        self._mark_dirty(human_id)
        self._mark_memory_dirty(human_id)
        self.flush_dirty(force=True)

    def _prune_resident_memory(
        self,
        resident: dict[str, Any],
        tick: int,
        *,
        alive: bool,
    ) -> None:
        memory = resident.setdefault("memory", {})
        recent_events = [
            _apply_memory_policy(dict(entry), _event_policy(str(entry.get("kind", "event"))), tick, default_class="event")
            for entry in list(memory.get("recent_events", []))
        ]
        memory["recent_events"] = _retained_entries(
            recent_events,
            tick,
            RECENT_EVENT_LIMIT if alive else DEAD_EVENT_LIMIT,
        )

        for bucket in ("known_food_sources", "known_water_sources"):
            place_entries = [
                _apply_memory_policy(dict(entry), _resource_policy(bucket), tick, default_class="place")
                for entry in list(memory.get(bucket, []))
            ]
            memory[bucket] = _retained_entries(place_entries, tick, RESOURCE_MEMORY_LIMIT if alive else 0)

        threat_entries = [
            _apply_memory_policy(dict(entry), _threat_policy(str(entry.get("kind", "threat"))), tick, default_class="threat")
            for entry in list(memory.get("last_threats", []))
        ]
        memory["last_threats"] = _retained_entries(threat_entries, tick, THREAT_MEMORY_LIMIT if alive else 0)

        relationships = resident.setdefault("relationships", {})
        kept_relationships: dict[str, dict[str, Any]] = {}
        for other_id, relation in list(relationships.items()):
            tags = [str(tag) for tag in relation.get("tags", []) if str(tag).strip()]
            if not tags and relation.get("kind"):
                tags = [str(relation["kind"])]
            tag_meta = dict(relation.get("tag_meta", {}))
            active_tags: list[str] = []
            filtered_meta: dict[str, dict[str, Any]] = {}
            for tag in tags:
                meta = _apply_memory_policy(
                    dict(tag_meta.get(tag, {})),
                    _relation_policy(tag),
                    tick,
                    default_class="relationship",
                    base_tick_key="last_seen_tick",
                )
                if alive:
                    keep_tag = _is_entry_active(meta, tick)
                else:
                    keep_tag = bool(meta.get("permanent", False))
                if keep_tag:
                    active_tags.append(tag)
                    filtered_meta[tag] = meta
            if not active_tags:
                continue
            relation["tags"] = active_tags
            relation["tag_meta"] = filtered_meta
            relation["kind"] = relation["kind"] if relation.get("kind") in active_tags else active_tags[0]
            relation["last_seen_tick"] = int(relation.get("last_seen_tick", tick))
            kept_relationships[other_id] = relation
        resident["relationships"] = kept_relationships

    def record_event(
        self,
        human_id: str,
        tick: int,
        kind: str,
        *,
        note: str = "",
        other_human_id: str | None = None,
        other_entity_id: int | None = None,
        pos: tuple[float, float] | None = None,
        extra: dict[str, Any] | None = None,
        trim: int = 14,
    ) -> None:
        resident = self.get(human_id)
        if resident is None:
            return
        policy = _event_policy(kind)
        event: dict[str, Any] = {
            "tick": tick,
            "kind": kind,
        }
        if note:
            event["note"] = note
        if other_human_id:
            event["other_human_id"] = other_human_id
        if other_entity_id is not None:
            event["other_entity_id"] = int(other_entity_id)
        if pos is not None:
            event["x"] = round(pos[0], 2)
            event["y"] = round(pos[1], 2)
        if extra:
            event.update(extra)
        event = _apply_memory_policy(event, policy, tick, default_class="event")
        recent = [
            _apply_memory_policy(
                dict(entry),
                _event_policy(str(entry.get("kind", "event"))),
                tick,
                default_class="event",
            )
            for entry in resident["memory"]["recent_events"]
        ]
        recent.append(event)
        resident["memory"]["recent_events"] = _retained_entries(recent, tick, trim)
        refresh_resident_pressures(resident, tick)
        refresh_goals_for_event(resident, tick, kind, event, force_review=False)
        if kind in {"attacked", "killed_by", "child_birth", "born_to_parent", "witnessed_death", "death"}:
            queue_reasoning_review(resident, tick, f"event:{kind}")
        self._mark_dirty(human_id)
        self._mark_memory_dirty(human_id)

    def remember_resource(
        self,
        human_id: str,
        bucket: str,
        entity_id: int,
        pos: tuple[float, float],
        tick: int,
        uid: str | None = None,
        abs_pos: dict | None = None,
    ) -> None:
        """``uid`` (window mode): the source's stable id; entries are then matched and keyed by it, and ``entity_id`` (the slot at the
        time) is only informational. ``abs_pos``: its absolute position (``harness.window.absolute_position``), which survives a re-base.
        Without ``uid`` the entry is exactly the legacy one (slot-keyed)."""
        resident = self.get(human_id)
        if resident is None:
            return
        policy = _resource_policy(bucket)
        memory_list = [
            _apply_memory_policy(dict(entry), policy, tick, default_class="place")
            for entry in resident["memory"][bucket]
        ]
        if uid:
            existing = next((entry for entry in memory_list if entry.get("uid") == uid), None)
        else:
            existing = next((entry for entry in memory_list if "uid" not in entry and int(entry.get("entity_id", -1)) == int(entity_id)), None)
        if existing is None:
            existing = _apply_memory_policy(
                {
                    "entity_id": entity_id,
                    "x": round(pos[0], 2),
                    "y": round(pos[1], 2),
                    "tick": tick,
                },
                policy,
                tick,
                default_class="place",
            )
            if uid:
                existing["uid"] = str(uid)
                if abs_pos is not None:
                    existing["abs"] = dict(abs_pos)
            memory_list.append(existing)
        else:
            existing["x"] = round(pos[0], 2)
            existing["y"] = round(pos[1], 2)
            existing["tick"] = tick
            if uid:
                existing["entity_id"] = entity_id
                if abs_pos is not None:
                    existing["abs"] = dict(abs_pos)
            _reinforce_memory_entry(existing, policy, tick, default_class="place")
        resident["memory"][bucket] = _retained_entries(memory_list, tick, RESOURCE_MEMORY_LIMIT)
        self._refresh_behavior_state(resident, human_id=human_id, tick=tick, reason="resource_memory")
        self._mark_dirty(human_id)
        self._mark_memory_dirty(human_id)

    def remember_threat(
        self,
        human_id: str,
        kind: str,
        pos: tuple[float, float],
        tick: int,
        distance: float,
    ) -> None:
        resident = self.get(human_id)
        if resident is None:
            return
        policy = _threat_policy(kind)
        entries = [
            _apply_memory_policy(
                dict(entry),
                _threat_policy(str(entry.get("kind", "threat"))),
                tick,
                default_class="threat",
            )
            for entry in resident["memory"]["last_threats"]
        ]
        entries.append(
            _apply_memory_policy(
                {
                    "kind": kind,
                    "tick": tick,
                    "x": round(pos[0], 2),
                    "y": round(pos[1], 2),
                    "distance": round(distance, 2),
                },
                policy,
                tick,
                default_class="threat",
            )
        )
        resident["memory"]["last_threats"] = _retained_entries(entries, tick, THREAT_MEMORY_LIMIT)
        refresh_resident_pressures(resident, tick)
        if kind in {"predator", "death_site"}:
            request_goal_review(resident, tick, f"threat:{kind}")
            queue_reasoning_review(resident, tick, f"threat:{kind}")
        self._mark_dirty(human_id)
        self._mark_memory_dirty(human_id)

    def update_relationship(
        self,
        human_id: str,
        other_id: str,
        relation_kind: str,
        closeness_delta: float,
        tick: int,
    ) -> None:
        resident = self.get(human_id)
        if resident is None:
            return
        policy = _relation_policy(relation_kind)
        relation = resident["relationships"].get(
            other_id,
            {
                "kind": relation_kind,
                "closeness": 0.0,
                "last_seen_tick": tick,
                "tags": [relation_kind],
                "tag_meta": {},
            },
        )
        relation["kind"] = relation_kind
        relation["closeness"] = round(
            _clamp(float(relation.get("closeness", 0.0)) + closeness_delta, -1.0, 1.0),
            3,
        )
        relation["last_seen_tick"] = tick
        tags = [str(tag) for tag in relation.get("tags", []) if str(tag).strip()]
        if relation_kind not in tags:
            tags.append(relation_kind)
        relation["tags"] = tags
        tag_meta = dict(relation.get("tag_meta", {}))
        current_meta = tag_meta.get(relation_kind)
        if current_meta is None:
            current_meta = _apply_memory_policy(
                {"last_seen_tick": tick},
                policy,
                tick,
                default_class="relationship",
                base_tick_key="last_seen_tick",
            )
        else:
            current_meta = _reinforce_memory_entry(
                dict(current_meta),
                policy,
                tick,
                default_class="relationship",
                base_tick_key="last_seen_tick",
                salience_delta=0.05,
            )
        current_meta["last_seen_tick"] = tick
        tag_meta[relation_kind] = current_meta
        relation["tag_meta"] = tag_meta
        resident["relationships"][other_id] = relation
        self._prune_resident_memory(
            resident,
            tick,
            alive=bool(resident.get("status", {}).get("alive", True)),
        )
        refresh_resident_pressures(resident, tick)
        if relation_kind in {"parent", "child", "mate", "family", "rival", "friend"}:
            request_goal_review(resident, tick, f"relationship:{relation_kind}")
            queue_reasoning_review(resident, tick, f"relationship:{relation_kind}")
        self._mark_dirty(human_id)
        self._mark_memory_dirty(human_id)

    def record_world_decree(self, tick: int, decree: str) -> None:
        for human_id, resident in self._cache.items():
            if not resident.get("status", {}).get("alive", True):
                continue
            history = resident["history"]["world_decrees"]
            history.append({"tick": tick, "decree": decree})
            resident["history"]["world_decrees"] = history[-12:]
            request_goal_review(resident, tick, "world_decree")
            queue_reasoning_review(resident, tick, "world_decree")
            self._mark_dirty(human_id)

    def record_decision(
        self,
        human_id: str,
        tick: int,
        case: dict[str, Any],
        decision: dict[str, Any],
    ) -> None:
        resident = self.get(human_id)
        if resident is None:
            return
        resident["status"]["current_intent"] = decision["intent"]
        resident["status"]["last_decision_tick"] = tick
        resident["status"]["last_reason"] = decision["reason"]
        resident["history"]["decisions"].append(
            {
                "tick": tick,
                "intent": decision["intent"],
                "reason": decision["reason"],
                "action": decision["action"],
                "distress": round(case["distress"], 3),
            }
        )
        resident["history"]["decisions"] = resident["history"]["decisions"][-MAX_DECISION_HISTORY:]
        self.record_event(
            human_id,
            tick,
            "decision",
            extra={
                "intent": decision["intent"],
                "reason": decision["reason"],
            },
        )
        self._refresh_behavior_state(resident, human_id=human_id, tick=tick, reason="decision")
        self._mark_dirty(human_id)
        self._mark_memory_dirty(human_id)
        self.flush_dirty(force=True)

    def _mark_dirty(self, human_id: str) -> None:
        self._dirty.add(human_id)
        self._revisions[human_id] = self._revisions.get(human_id, 0) + 1

    def capture_dirty(self, tick: int | None = None, force: bool = False, limit: int = 16) -> tuple:
        """Immutable jobs only; capture/acknowledgment stay on the simulation owner."""
        jobs = []
        for human_id in sorted(self._dirty, key=lambda key: (self._last_attempt_order.get(key, -1), key)):
            if len(jobs) >= limit:
                break
            if not force and tick is not None:
                last_tick = max(self._last_flushed_tick.get(human_id, -10_000),
                                self._last_failed_flush_tick.get(human_id, -10_000))
                if tick - last_tick < FLUSH_EVERY_TICKS:
                    continue
            resident = self._cache.get(human_id)
            if resident is None:
                self._dirty.discard(human_id)
                continue
            jobs.append((human_id, self._generation, self._revisions.get(human_id, 0),
                         str(self._path(human_id)), json.dumps(resident, ensure_ascii=False), tick))
        return tuple(jobs)

    def acknowledge_writes(self, results: tuple) -> None:
        for human_id, generation, revision, tick, error in results:
            if generation != self._generation:
                continue
            self._attempt_serial += 1
            self._last_attempt_order[human_id] = self._attempt_serial
            if error is not None:
                self.save_errors[human_id] = error
                if tick is not None:
                    self._last_failed_flush_tick[human_id] = tick
                continue
            self.save_errors.pop(human_id, None)
            self._last_failed_flush_tick.pop(human_id, None)
            if self._revisions.get(human_id, 0) == revision:
                self._dirty.discard(human_id)
            if tick is not None:
                self._last_flushed_tick[human_id] = tick

    def flush_dirty(self, tick: int | None = None, force: bool = False) -> None:
        if self.background_writes:
            return
        self.acknowledge_writes(write_resident_batch(self.capture_dirty(tick, force, max(len(self._dirty), 1))))

    def resident_count(self) -> int:
        return len(set(self._cache) | {path.stem for path in self.root_dir.glob("*.json")})


def write_resident_batch(jobs: tuple) -> tuple:
    """Worker entry: receives serialized copies and paths, never an Engine/store."""
    results = []
    for human_id, generation, revision, path, serialized, tick in jobs:
        error = None
        try:
            _atomic_write_json(Path(path), json.loads(serialized))
        except OSError as exc:
            error = f"{type(exc).__name__}: {exc}"
        results.append((human_id, generation, revision, tick, error))
    return tuple(results)
