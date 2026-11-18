from __future__ import annotations

from typing import Any

import torch

try:
    import genesis_config as cfg
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg

from .common import (clamp, live_human_mask, move_away, move_toward, nearest_entity, nearest_human, perception_bounded,
                     window_mode)
from .resident_store import ResidentAgentStore
from .tiny_runtime import TINY_MODE_NORMAL, TINY_MODE_URGENT


def _perception_scale(tick: int) -> float:
    try:
        from harness import calendar as _calendar
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.harness import calendar as _calendar
    return _calendar.perception_scale(tick)

try:
    from systems.construction import construction_prompt_payload, construction_prompt_summary
    from systems.escalation import (
        build_candidate,
        build_escalation_prompt_payload,
        distress_proxy_from_row,
        select_processing_batch,
        summarize_escalation,
    )
    from systems.crafting.ops import crafting_prompt_payload, crafting_prompt_summary
    from systems.memory.retrieval import build_human_memory_bundle
    from systems.goal.ops import goal_prompt_payload, goal_prompt_summary, primary_goal_payload
    from systems.occupation.ops import occupation_prompt_payload, occupation_prompt_summary
    from systems.planning.ops import active_plan_payload, plan_prompt_payload, plan_prompt_summary
    from systems.personality import legacy_decision_traits
    from systems.personality.ops import personality_prompt_payload, personality_prompt_summary
    from systems.schedule.ops import schedule_prompt_payload, schedule_prompt_summary
    from systems.tasks.ops import active_task_payload, task_prompt_payload, task_prompt_summary
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.construction import construction_prompt_payload, construction_prompt_summary
    from at_the_beginning.systems.escalation import (
        build_candidate,
        build_escalation_prompt_payload,
        distress_proxy_from_row,
        select_processing_batch,
        summarize_escalation,
    )
    from at_the_beginning.systems.crafting.ops import crafting_prompt_payload, crafting_prompt_summary
    from at_the_beginning.systems.memory.retrieval import build_human_memory_bundle
    from at_the_beginning.systems.goal.ops import goal_prompt_payload, goal_prompt_summary, primary_goal_payload
    from at_the_beginning.systems.occupation.ops import occupation_prompt_payload, occupation_prompt_summary
    from at_the_beginning.systems.planning.ops import active_plan_payload, plan_prompt_payload, plan_prompt_summary
    from at_the_beginning.systems.personality import legacy_decision_traits
    from at_the_beginning.systems.personality.ops import personality_prompt_payload, personality_prompt_summary
    from at_the_beginning.systems.schedule.ops import schedule_prompt_payload, schedule_prompt_summary
    from at_the_beginning.systems.tasks.ops import active_task_payload, task_prompt_payload, task_prompt_summary


DEFAULT_DECISION_BATCH_FPS = 0.5
DEFAULT_DECISION_BATCH_INTERVAL_TICKS = max(1, int(round(cfg.TICK_RATE_HZ / DEFAULT_DECISION_BATCH_FPS)))
DEFAULT_MAX_BATCH_SIZE = 16
URGENT_DECISION_COOLDOWN_TICKS = max(1, int(round(cfg.TICK_RATE_HZ * 0.5)))


class HumanAgentRuntime:
    def __init__(self, resident_store: ResidentAgentStore):
        self.resident_store = resident_store
        self.history: list[dict[str, Any]] = []
        self.batch_history: list[dict[str, Any]] = []
        self.route_history: list[dict[str, Any]] = []
        self.deferred_task_history: list[dict[str, Any]] = []
        self.completed_consequence_sources: list[str] = []
        self.batch_interval_ticks = DEFAULT_DECISION_BATCH_INTERVAL_TICKS
        self.max_batch_size = DEFAULT_MAX_BATCH_SIZE
        self.urgent_cooldown_ticks = URGENT_DECISION_COOLDOWN_TICKS
        self._pending_since_tick: dict[str, int] = {}
        self._last_decision_tick_by_human: dict[str, int] = {}
        self._deferred_normal_tasks: dict[str, dict[str, Any]] = {}
        self._last_batch_tick = -10**9

    def reset(self) -> None:
        self.history.clear()
        self.batch_history.clear()
        self.route_history.clear()
        self.deferred_task_history.clear()
        self.completed_consequence_sources.clear()
        self._pending_since_tick.clear()
        self._last_decision_tick_by_human.clear()
        self._deferred_normal_tasks.clear()
        self._last_batch_tick = -10**9

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "history": self.history[-10:],
            "recent_batches": self.batch_history[-10:],
            "pending_queue_size": len(self._pending_since_tick),
            "pending_human_ids": sorted(self._pending_since_tick.keys())[:24],
            "batch_interval_ticks": self.batch_interval_ticks,
            "batch_interval_seconds": round(self.batch_interval_ticks / float(cfg.TICK_RATE_HZ), 3),
            "max_batch_size": self.max_batch_size,
            "urgent_cooldown_ticks": self.urgent_cooldown_ticks,
            "last_batch_tick": self._last_batch_tick,
            "recent_routes": self.route_history[-10:],
            "deferred_normal_queue_size": len(self._deferred_normal_tasks),
            "deferred_due_human_ids": sorted(
                [
                    human_id
                    for human_id, task in self._deferred_normal_tasks.items()
                    if int(task.get("due_tick", 10**9)) <= int(self._last_batch_tick + self.batch_interval_ticks)
                ]
            )[:24],
            "recent_deferred_tasks": self.deferred_task_history[-10:],
            "recent_completed_consequence_sources": self.completed_consequence_sources[-10:],
        }

    def _distress_proxy(self, row: torch.Tensor) -> float:
        return distress_proxy_from_row(row)

    @staticmethod
    def _task_priority(task: dict[str, Any], route_decision: Any | None = None) -> float:
        if route_decision is None:
            return round(float(task.get("priority", 0.0)), 3)
        return round(
            max(
                float(task.get("priority", 0.0)),
                float(getattr(route_decision, "priority", 0.0)),
                float(getattr(route_decision, "normal_score", 0.0)),
                float(getattr(route_decision, "goal_review_score", 0.0)),
            ),
            3,
        )

    def _register_deferred_normal_task(self, route_decision: Any, tick: int) -> None:
        if not bool(route_decision.consequence_ticket_requested or route_decision.goal_review_requested):
            return
        source_key = str(getattr(route_decision, "consequence_ticket_source_key", "")).strip()
        if source_key and source_key in self.completed_consequence_sources:
            return
        human_id = str(route_decision.human_id)
        due_tick = int(route_decision.consequence_due_tick if route_decision.consequence_due_tick is not None else tick)
        primary_reason = str(
            route_decision.consequence_ticket_reason
            or route_decision.goal_review_reason
            or route_decision.normal_reason
            or "normal_followup"
        )
        task = self._deferred_normal_tasks.get(human_id)
        if task is None:
            task = {
                "human_id": human_id,
                "due_tick": due_tick,
                "priority": self._task_priority({}, route_decision),
                "reason": primary_reason,
                "reasons": [],
                "goal_review_requested": False,
                "created_tick": int(tick),
                "last_updated_tick": int(tick),
                "source_tags": [],
                "source_keys": [],
            }
        task["due_tick"] = min(int(task.get("due_tick", due_tick)), due_tick)
        task["priority"] = self._task_priority(task, route_decision)
        task["last_updated_tick"] = int(tick)
        reasons = [str(reason) for reason in task.get("reasons", []) if str(reason).strip()]
        for reason in [
            primary_reason,
            str(route_decision.goal_review_reason or ""),
            str(route_decision.reaction_ticket_reason or ""),
        ]:
            normalized = str(reason).strip()
            if normalized and normalized not in reasons:
                reasons.append(normalized)
        task["reasons"] = reasons[:6]
        task["reason"] = task["reasons"][0] if task["reasons"] else primary_reason
        task["goal_review_requested"] = bool(
            task.get("goal_review_requested", False) or route_decision.goal_review_requested
        )
        source_tags = [str(tag) for tag in task.get("source_tags", []) if str(tag).strip()]
        for tag in getattr(route_decision, "route_tags", []):
            normalized_tag = str(tag).strip()
            if normalized_tag and normalized_tag not in source_tags:
                source_tags.append(normalized_tag)
        task["source_tags"] = source_tags[:8]
        source_keys = [str(key) for key in task.get("source_keys", []) if str(key).strip()]
        if source_key and source_key not in source_keys:
            source_keys.append(source_key)
        task["source_keys"] = source_keys[:8]
        self._deferred_normal_tasks[human_id] = task

    def _collect_due_deferred_tasks(
        self,
        route_bundle: dict[str, Any],
        *,
        tick: int,
    ) -> tuple[list[Any], dict[str, dict[str, Any]]]:
        if (int(tick) - int(self._last_batch_tick)) < int(self.batch_interval_ticks):
            return [], {}

        combined: dict[str, Any] = {
            decision.human_id: decision for decision in route_bundle.get("scheduled_normals", [])
        }
        task_by_human: dict[str, dict[str, Any]] = {}

        for human_id, task in sorted(
            self._deferred_normal_tasks.items(),
            key=lambda item: (
                -float(item[1].get("priority", 0.0)),
                int(item[1].get("due_tick", 10**9)),
                str(item[0]),
            ),
        ):
            if int(task.get("due_tick", 10**9)) > int(tick):
                continue
            decision = route_bundle["decision_by_human"].get(human_id)
            if decision is None:
                continue
            combined.setdefault(human_id, decision)
            task_by_human[human_id] = task

        scheduled_normals = list(combined.values())
        scheduled_normals.sort(
            key=lambda decision: (
                -self._task_priority(task_by_human.get(decision.human_id, {}), decision),
                decision.human_id,
            )
        )
        scheduled_normals = scheduled_normals[: max(self.max_batch_size, 0)]
        selected_task_by_human = {
            decision.human_id: task_by_human[decision.human_id]
            for decision in scheduled_normals
            if decision.human_id in task_by_human
        }
        return scheduled_normals, selected_task_by_human

    def acknowledge_reasoning_handoff(
        self,
        human_id: str,
        *,
        source_key: str = "",
    ) -> dict[str, Any]:
        target_human_id = str(human_id or "").strip()
        if not target_human_id:
            return {"ok": False, "reason": "human_id_missing"}
        self._pending_since_tick.pop(target_human_id, None)
        removed = self._deferred_normal_tasks.pop(target_human_id, None)
        normalized_source = str(source_key or "").strip()
        if normalized_source and normalized_source not in self.completed_consequence_sources:
            self.completed_consequence_sources.append(normalized_source)
            self.completed_consequence_sources = self.completed_consequence_sources[-30:]
        return {
            "ok": True,
            "human_id": target_human_id,
            "removed_deferred": bool(removed is not None),
            "source_key": normalized_source,
        }

    def ingest_external_trigger(
        self,
        engine: Any,
        human_id: str,
        *,
        force_immediate_urgent: bool = True,
        force_process: bool = False,
        source_tag: str = "",
    ) -> dict[str, Any]:
        target_human_id = str(human_id or "").strip()
        if not target_human_id:
            return {"ok": False, "reason": "human_id_missing"}

        slot = -1
        for idx, candidate_id in enumerate(engine._human_uid_by_slot):
            if str(candidate_id or "") == target_human_id:
                slot = int(idx)
                break
        if slot < 0 or slot >= engine.state.h_tensor.shape[0]:
            return {"ok": False, "reason": "human_missing", "human_id": target_human_id}
        if int(engine.state.h_tensor[slot, cfg.TYPE]) != int(cfg.AGENT_TYPE_HUMAN):
            return {"ok": False, "reason": "human_inactive", "human_id": target_human_id}

        player_control = getattr(engine, "player_control", None)
        if player_control is not None:
            controlled_mask = player_control.controlled_human_mask(engine)
            if 0 <= slot < controlled_mask.shape[0] and bool(controlled_mask[slot]):
                return {"ok": False, "reason": "human_player_controlled", "human_id": target_human_id}

        resident = self.resident_store.ensure_resident(target_human_id, slot, engine.state.h_tensor, engine.tick)
        candidate = build_candidate(
            engine,
            slot,
            target_human_id,
            resident,
            escalated_flag=bool(float(engine.state.h_tensor[slot, cfg.ESCALATION_FLAG]) > 0.0),
            pending_since_tick=int(self._pending_since_tick.get(target_human_id, engine.tick)),
            last_decision_tick=int(self._last_decision_tick_by_human.get(target_human_id, -10**9)),
        )
        route_bundle = select_processing_batch(
            [candidate],
            tick=int(engine.tick),
            batch_interval_ticks=self.batch_interval_ticks,
            max_batch_size=1,
            last_batch_tick=self._last_batch_tick,
            urgent_cooldown_ticks=self.urgent_cooldown_ticks,
        )
        route_decision = route_bundle["decision_by_human"].get(target_human_id)
        if route_decision is None:
            return {"ok": False, "reason": "route_missing", "human_id": target_human_id}

        if route_decision.should_consider:
            self._pending_since_tick.setdefault(target_human_id, int(engine.tick))
        self._register_deferred_normal_task(route_decision, int(engine.tick))

        result = {
            "ok": True,
            "human_id": target_human_id,
            "slot": int(slot),
            "lane": str(route_decision.lane),
            "priority": round(float(route_decision.priority), 3),
            "urgent_score": round(float(route_decision.urgent_score), 3),
            "normal_score": round(float(route_decision.normal_score), 3),
            "goal_review_requested": bool(route_decision.goal_review_requested),
            "reaction_ticket_requested": bool(route_decision.reaction_ticket_requested),
            "consequence_ticket_requested": bool(route_decision.consequence_ticket_requested),
            "consequence_ticket_source_key": str(route_decision.consequence_ticket_source_key),
            "consequence_due_tick": route_decision.consequence_due_tick,
            "route_tags": list(route_decision.route_tags),
            "processed": False,
            "source_tag": str(source_tag or "").strip(),
        }
        should_process_now = bool(
            force_process and route_decision.should_consider
        ) or bool(force_immediate_urgent and route_decision.lane == "urgent")
        if not should_process_now:
            return result

        memory_rag = getattr(engine, "memory_rag", None)
        if memory_rag is not None:
            engine.flush_memory_graph_queue(human_ids=[target_human_id], save=False, force=True)

        case = self._build_case(engine, slot, target_human_id, resident)
        case["escalation"] = build_escalation_prompt_payload(route_decision)
        case["escalation_summary"] = summarize_escalation(route_decision)
        case["goal_review_requested"] = False
        case["deferred_task"] = None
        decision = self._decide_batch(engine, [case])[0]
        outcome, case_touched = self._process_case_decision(engine, case, decision)
        if memory_rag is not None and case_touched:
            engine.flush_memory_graph_queue(human_ids=case_touched, save=False, force=True)
        outcome["trigger"] = "orchestrated_external"
        if source_tag:
            outcome["source_tag"] = str(source_tag)
        self.history.append(outcome)
        self.history = self.history[-30:]
        result["processed"] = True
        if force_process and route_decision.lane != "urgent":
            result["forced_process"] = True
        result["outcome"] = dict(outcome)
        return result

    @staticmethod
    def _tiny_mode_for_case(case: dict[str, Any]) -> str:
        escalation = dict(case.get("escalation") or {})
        if str(escalation.get("lane", "")).strip().lower() == "urgent":
            return TINY_MODE_URGENT
        return TINY_MODE_NORMAL

    def _build_tiny_case(self, case: dict[str, Any], *, mode: str) -> dict[str, Any]:
        return {
            "resident_model_mode": str(mode),
            "human_id": str(case.get("human_id", "")),
            "local_state": {
                "distress": round(float(case.get("distress", 0.0)), 3),
                "hunger": round(float(case.get("hunger", 0.0)), 3),
                "thirst": round(float(case.get("thirst", 0.0)), 3),
                "threat": round(float(case.get("threat", 0.0)), 3),
                "mood": round(float(case.get("mood", 0.0)), 3),
                "hp": round(float(case.get("hp", 0.0)), 3),
                "stamina": round(float(case.get("stamina", 0.0)), 3),
            },
            "nearby": {
                "food": dict(case.get("food") or {}),
                "water": dict(case.get("water") or {}),
                "shelter": dict(case.get("shelter") or {}),
                "hazard": dict(case.get("hazard") or {}),
                "predator": dict(case.get("predator") or {}),
                "ally": dict(case.get("ally") or {}),
            },
            "personality_summary": str(case.get("personality_summary", "")),
            "occupation_summary": str(case.get("occupation_summary", "")),
            "schedule_summary": str(case.get("schedule_summary", "")),
            "task_summary": str(case.get("task_summary", "")),
            "goal_summary": str(case.get("goal_summary", "")),
            "plan_summary": str(case.get("plan_summary", "")),
            "primary_goal": dict(case.get("primary_goal") or {}),
            "active_plan": dict(case.get("active_plan") or {}),
            "escalation": dict(case.get("escalation") or {}),
            "deferred_task": dict(case.get("deferred_task") or {}),
        }

    def _fallback_tiny_decision_packet(self, case: dict[str, Any], *, mode: str) -> dict[str, Any]:
        decision = self._decide(case)
        escalation = dict(case.get("escalation") or {})
        return {
            "resident_model_mode": str(mode),
            "human_id": str(case.get("human_id", "")),
            "lane": str(escalation.get("lane", "")),
            "intent": str(decision.get("intent", "")),
            "reason": str(decision.get("reason", "")),
            "action": dict(decision.get("action") or {}),
            "confidence": 0.86 if mode == TINY_MODE_URGENT else 0.72,
            "followup": {
                "goal_review_requested": bool(case.get("goal_review_requested", False)),
                "reaction_ticket_requested": bool(escalation.get("reaction_ticket_requested", False)),
                "consequence_ticket_requested": bool(escalation.get("consequence_ticket_requested", False)),
            },
            "mock": True,
            "source": "tiny_model_mock",
        }

    def _normalize_tiny_decision_packet(self, packet: dict[str, Any], case: dict[str, Any], *, mode: str) -> dict[str, Any]:
        fallback = self._decide(case)
        action = packet.get("action")
        if not isinstance(action, dict) or not action:
            action = dict(fallback.get("action") or {})
        return {
            "intent": str(packet.get("intent") or fallback.get("intent") or "rest"),
            "reason": str(packet.get("reason") or fallback.get("reason") or "fallback decision"),
            "action": dict(action),
            "model_source": str(packet.get("source", "")),
            "model_mode": str(packet.get("resident_model_mode", mode)),
            "model_confidence": round(float(packet.get("confidence", 0.0)), 3),
            "model_mock": bool(packet.get("mock", False)),
            "followup": dict(packet.get("followup") or {}),
        }

    def _decide_batch(self, engine: Any, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tiny_runtime = getattr(engine, "tiny_model_runtime", None)
        if tiny_runtime is None:
            return [self._decide(case) for case in cases]

        decisions: list[dict[str, Any] | None] = [None] * len(cases)
        mode_to_entries: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        for idx, case in enumerate(cases):
            mode = self._tiny_mode_for_case(case)
            mode_to_entries.setdefault(mode, []).append((idx, case))

        for mode, entries in mode_to_entries.items():
            tiny_cases = [self._build_tiny_case(case, mode=mode) for _, case in entries]
            fallback_packets = [self._fallback_tiny_decision_packet(case, mode=mode) for _, case in entries]
            results = tiny_runtime.run_mode_batch(
                mode=mode,
                cases=tiny_cases,
                engine=engine,
                fallback_packets=fallback_packets,
            )
            for (idx, case), result in zip(entries, results):
                packet = dict(result.get("packet") or {})
                decisions[idx] = self._normalize_tiny_decision_packet(packet, case, mode=mode)

        return [decision if decision is not None else self._decide(case) for decision, case in zip(decisions, cases)]

    def _process_case_decision(self, engine: Any, case: dict[str, Any], decision: dict[str, Any]) -> tuple[dict[str, Any], set[str]]:
        h_tensor = engine.state.h_tensor
        slot = case["slot"]
        human_id = case["human_id"]
        touched_ids: set[str] = {human_id}
        self._apply_decision(engine, case, decision)
        h_tensor[slot, cfg.ESCALATION_FLAG] = 0.0

        ally_id = case["ally"]["human_id"]
        if ally_id is not None and case["ally"]["dist"] < cfg.TRIBE_COHESION_RADIUS:
            relation_kind = "tribe_mate" if case["tribe"] != 0.0 else "neighbor"
            self.resident_store.update_relationship(
                human_id,
                ally_id,
                relation_kind,
                closeness_delta=0.05,
                tick=engine.tick,
            )
            touched_ids.add(ally_id)

        self.resident_store.record_decision(human_id, engine.tick, case, decision)
        self._last_decision_tick_by_human[human_id] = int(engine.tick)
        self._pending_since_tick.pop(human_id, None)
        outcome = {
            "tick": engine.tick,
            "human_id": human_id,
            "intent": decision["intent"],
            "reason": decision["reason"],
        }
        if str(decision.get("model_source", "")).strip():
            outcome["decision_source"] = str(decision["model_source"])
            outcome["decision_mode"] = str(decision.get("model_mode", ""))
            outcome["decision_mock"] = bool(decision.get("model_mock", False))
            outcome["decision_confidence"] = round(float(decision.get("model_confidence", 0.0)), 3)
        return outcome, touched_ids

    @staticmethod
    def _source_identity(engine: Any, slot: int) -> dict[str, Any]:
        """Window mode: the stable id and absolute position of a source being remembered (rows are reused, so a slot cannot name it).
        Empty otherwise: the entry stays the legacy slot-keyed one."""
        if not window_mode():
            return {}
        uid = engine._entity_uid_by_slot[int(slot)]
        if not uid:
            return {}
        try:
            from harness.window import absolute_position
        except ImportError:  # pragma: no cover - package import fallback
            from at_the_beginning.harness.window import absolute_position
        row = engine.state.m_tensor[int(slot)]
        return {"uid": str(uid), "abs_pos": absolute_position(engine, float(row[cfg.CX]), float(row[cfg.CY]))}

    def _build_case(self, engine: Any, slot: int, human_id: str, resident: dict[str, Any]) -> dict[str, Any]:
        h_tensor = engine.state.h_tensor
        m_tensor = engine.state.m_tensor
        row = h_tensor[slot]
        px = float(row[cfg.X])
        py = float(row[cfg.Y])
        tribe = float(row[cfg.H_TRIBE])
        distress = (
            float(row[cfg.HUNGER]) / 100.0
            + float(row[cfg.THREAT]) / 100.0
            + (100.0 - float(row[cfg.MOOD])) / 100.0
            + float(row[cfg.CRITICAL_HEALTH])
        )

        # EDEN_PERCEPTION_BOUNDED: a resident only knows rows inside the scan radius of its query (and in its own space once the
        # space columns exist); with the flag off every query is unbounded, as before.
        bounded = perception_bounded()
        space_col = getattr(cfg, "M_SPACE", None)
        human_space_col = getattr(cfg, "H_SPACE", None)

        light = _perception_scale(int(engine.tick))           # 1.0 unless EDEN_CALENDAR=1: it is dark at night, so a resident sees less far

        def sees(radius: float) -> dict[str, Any]:
            if not bounded:
                return {}
            found: dict[str, Any] = {"max_distance": radius * light}
            if space_col is not None and human_space_col is not None:
                found.update(space=int(row[human_space_col]), space_col=space_col)
            return found

        food_eid, food_dist = nearest_entity(
            m_tensor,
            px,
            py,
            type_ids={cfg.M_GRASS, cfg.M_FOREST, cfg.M_BEACH, cfg.M_LAKE, cfg.M_FARM},
            resource_col=cfg.M_RESOURCE_FOOD,
            **sees(cfg.SURVIVAL_SCAN_RADIUS),
        )
        water_eid, water_dist = nearest_entity(
            m_tensor,
            px,
            py,
            type_ids={cfg.M_LAKE, cfg.M_WELL, cfg.M_FARM},
            resource_col=cfg.M_RESOURCE_WATER,
            **sees(cfg.SURVIVAL_SCAN_RADIUS),
        )
        shelter_eid, shelter_dist = nearest_entity(
            m_tensor,
            px,
            py,
            type_ids={cfg.M_HOUSE, cfg.M_VILLAGE, cfg.M_WELL, cfg.M_WALL},
            require_complete=True,
            **sees(cfg.SURVIVAL_SCAN_RADIUS),
        )
        hazard_eid, hazard_dist = nearest_entity(
            m_tensor,
            px,
            py,
            type_ids={cfg.M_LAVA, cfg.M_SEA},
            **sees(cfg.HAZARD_AVOID_RADIUS),
        )
        predator_eid, predator_dist = nearest_entity(
            m_tensor,
            px,
            py,
            type_ids={cfg.M_TIGER, cfg.M_WOLF},
            **sees(cfg.PREDATOR_ALERT_RADIUS),
        )

        h_mask = live_human_mask(h_tensor)
        ally_slot, ally_dist = nearest_human(h_tensor, slot, h_mask, tribe=tribe)
        if ally_slot == -1:
            ally_slot, ally_dist = nearest_human(h_tensor, slot, h_mask, tribe=None)

        ally_id = engine._human_uid_by_slot[ally_slot] if ally_slot != -1 else None
        if food_eid != -1:
            self.resident_store.remember_resource(
                human_id,
                "known_food_sources",
                food_eid,
                (float(m_tensor[food_eid, cfg.CX]), float(m_tensor[food_eid, cfg.CY])),
                engine.tick,
                **self._source_identity(engine, food_eid),
            )
        if water_eid != -1:
            self.resident_store.remember_resource(
                human_id,
                "known_water_sources",
                water_eid,
                (float(m_tensor[water_eid, cfg.CX]), float(m_tensor[water_eid, cfg.CY])),
                engine.tick,
                **self._source_identity(engine, water_eid),
            )
        if predator_eid != -1:
            self.resident_store.remember_threat(
                human_id,
                "predator",
                (float(m_tensor[predator_eid, cfg.CX]), float(m_tensor[predator_eid, cfg.CY])),
                engine.tick,
                predator_dist,
            )
        elif hazard_eid != -1:
            self.resident_store.remember_threat(
                human_id,
                "hazard",
                (float(m_tensor[hazard_eid, cfg.CX]), float(m_tensor[hazard_eid, cfg.CY])),
                engine.tick,
                hazard_dist,
            )
        case = {
            "human_id": human_id,
            "slot": slot,
            "pos": (px, py),
            "distress": distress,
            "hunger": float(row[cfg.HUNGER]),
            "thirst": float(row[cfg.THIRST]),
            "threat": float(row[cfg.THREAT]),
            "mood": float(row[cfg.MOOD]),
            "hp": float(row[cfg.HP]),
            "stamina": float(row[cfg.H_STAMINA]),
            "tribe": tribe,
            "resident": resident,
            "food": {"eid": food_eid, "dist": food_dist},
            "water": {"eid": water_eid, "dist": water_dist},
            "shelter": {"eid": shelter_eid, "dist": shelter_dist},
            "hazard": {"eid": hazard_eid, "dist": hazard_dist},
            "predator": {"eid": predator_eid, "dist": predator_dist},
            "ally": {"slot": ally_slot, "dist": ally_dist, "human_id": ally_id},
        }
        case["personality"] = personality_prompt_payload(resident)
        case["personality_summary"] = personality_prompt_summary(resident)
        case["occupation"] = occupation_prompt_payload(resident)
        case["occupation_summary"] = occupation_prompt_summary(resident)
        case["schedule"] = schedule_prompt_payload(resident)
        case["schedule_summary"] = schedule_prompt_summary(resident)
        case["crafting"] = crafting_prompt_payload(resident)
        case["crafting_summary"] = crafting_prompt_summary(resident)
        case["construction"] = construction_prompt_payload(resident)
        case["construction_summary"] = construction_prompt_summary(resident)
        case["tasks"] = task_prompt_payload(resident)
        case["task_summary"] = task_prompt_summary(resident)
        case["active_task"] = active_task_payload(resident)
        case["pressures"] = dict(resident.get("pressures", {}))
        case["goals"] = goal_prompt_payload(resident)
        case["goal_summary"] = goal_prompt_summary(resident)
        case["primary_goal"] = primary_goal_payload(resident)
        case["plans"] = plan_prompt_payload(resident)
        case["plan_summary"] = plan_prompt_summary(resident)
        case["active_plan"] = active_plan_payload(resident)
        case["escalation"] = None
        memory_rag = getattr(engine, "memory_rag", None)
        if memory_rag is not None:
            case["memory_bundle"] = build_human_memory_bundle(
                memory_rag,
                self.resident_store,
                human_id,
                case=case,
            )
        else:
            case["memory_bundle"] = None
        return case

    def _decide(self, case: dict[str, Any]) -> dict[str, Any]:
        legacy_traits = legacy_decision_traits(case["resident"].get("personality", {}))
        caution = float(legacy_traits["caution"])
        sociability = float(legacy_traits["sociability"])
        resourcefulness = float(legacy_traits["resourcefulness"])
        resolve = float(legacy_traits["resolve"])
        primary_goal = case.get("primary_goal") or {}
        primary_goal_kind = str(primary_goal.get("kind", ""))

        predator_dist = case["predator"]["dist"]
        hazard_dist = case["hazard"]["dist"]
        if case["predator"]["eid"] != -1 and predator_dist < cfg.PREDATOR_ALERT_RADIUS * (1.1 - caution * 0.2):
            return {
                "intent": "flee_predator",
                "reason": "predator pressure overrides all other needs",
                "action": {
                    "type": "move_away",
                    "target_eid": case["predator"]["eid"],
                    "magnitude": cfg.MOVE_STEP * (3.0 + caution),
                },
            }
        if case["hazard"]["eid"] != -1 and hazard_dist < cfg.HAZARD_AVOID_RADIUS * 0.75:
            return {
                "intent": "flee_hazard",
                "reason": "environmental hazard is too close",
                "action": {
                    "type": "move_away",
                    "target_eid": case["hazard"]["eid"],
                    "magnitude": cfg.MOVE_STEP * (2.8 + caution),
                },
            }

        shelter_score = max(
            case["threat"] / 100.0,
            max(0.0, 45.0 - case["hp"]) / 45.0,
            max(0.0, 25.0 - case["stamina"]) / 25.0,
        ) * (1.1 + caution)
        thirst_score = (case["thirst"] / 100.0) * (1.0 + resourcefulness * 0.4)
        hunger_score = (case["hunger"] / 100.0) * (1.0 + resourcefulness * 0.3)
        regroup_score = max(0.0, 45.0 - case["mood"]) / 45.0 * (0.5 + sociability)
        rest_score = max(0.0, 20.0 - case["stamina"]) / 20.0 * (1.0 + resolve * 0.25)

        if case["shelter"]["eid"] == -1:
            shelter_score *= 0.3
        if case["water"]["eid"] == -1:
            thirst_score *= 0.2
        if case["food"]["eid"] == -1:
            hunger_score *= 0.2
        if case["ally"]["slot"] == -1:
            regroup_score = 0.0
        if primary_goal_kind == "guard_home":
            shelter_score *= 1.18
        elif primary_goal_kind == "hoard_food":
            hunger_score *= 1.16
        elif primary_goal_kind == "protect_kin":
            regroup_score *= 1.18
        elif primary_goal_kind == "explore_region":
            rest_score *= 0.92

        options = [
            (
                "seek_shelter",
                shelter_score,
                "threat and low resilience favor shelter",
                {
                    "type": "move_toward",
                    "target_eid": case["shelter"]["eid"],
                    "magnitude": cfg.MOVE_STEP * 2.3,
                },
            ),
            (
                "seek_water",
                thirst_score,
                "thirst is the most urgent recoverable need",
                {
                    "type": "move_toward",
                    "target_eid": case["water"]["eid"],
                    "magnitude": cfg.MOVE_STEP * 2.1,
                },
            ),
            (
                "seek_food",
                hunger_score,
                "hunger is outranking other needs this tick",
                {
                    "type": "move_toward",
                    "target_eid": case["food"]["eid"],
                    "magnitude": cfg.MOVE_STEP * 2.1,
                },
            ),
            (
                "regroup",
                regroup_score,
                "low morale and nearby company make regrouping attractive",
                {
                    "type": "move_toward_human",
                    "target_slot": case["ally"]["slot"],
                    "magnitude": cfg.MOVE_STEP * 1.8,
                },
            ),
            (
                "rest",
                rest_score,
                "fatigue is high enough that recovery wins",
                {
                    "type": "rest",
                },
            ),
        ]
        best_intent, _, reason, action = max(options, key=lambda entry: entry[1])
        return {"intent": best_intent, "reason": reason, "action": action}

    def _apply_decision(self, engine: Any, case: dict[str, Any], decision: dict[str, Any]) -> None:
        h_tensor = engine.state.h_tensor
        m_tensor = engine.state.m_tensor
        slot = case["slot"]
        action = decision["action"]

        if action["type"] == "move_away":
            eid = action["target_eid"]
            if eid != -1:
                move_away(
                    h_tensor,
                    slot,
                    float(m_tensor[eid, cfg.CX]),
                    float(m_tensor[eid, cfg.CY]),
                    float(action["magnitude"]),
                )
            h_tensor[slot, cfg.THREAT] = clamp(float(h_tensor[slot, cfg.THREAT]) - 6.0, 0.0, 100.0)
            h_tensor[slot, cfg.MOOD] = clamp(float(h_tensor[slot, cfg.MOOD]) - 0.5, 0.0, 100.0)
            return

        if action["type"] == "move_toward":
            eid = action["target_eid"]
            if eid != -1:
                tx = float(m_tensor[eid, cfg.CX])
                ty = float(m_tensor[eid, cfg.CY])
                move_toward(h_tensor, slot, tx, ty, float(action["magnitude"]))
                h_tensor[slot, cfg.THREAT] = clamp(float(h_tensor[slot, cfg.THREAT]) - 3.0, 0.0, 100.0)
            return

        if action["type"] == "move_toward_human":
            target_slot = action["target_slot"]
            if target_slot != -1:
                move_toward(
                    h_tensor,
                    slot,
                    float(h_tensor[target_slot, cfg.X]),
                    float(h_tensor[target_slot, cfg.Y]),
                    float(action["magnitude"]),
                )
                h_tensor[slot, cfg.MOOD] = clamp(float(h_tensor[slot, cfg.MOOD]) + 1.0, 0.0, 100.0)
            return

        if action["type"] == "rest":
            h_tensor[slot, cfg.H_STAMINA] = clamp(float(h_tensor[slot, cfg.H_STAMINA]) + 3.0, 0.0, 100.0)
            h_tensor[slot, cfg.MOOD] = clamp(float(h_tensor[slot, cfg.MOOD]) + 1.2, 0.0, 100.0)
            h_tensor[slot, cfg.THREAT] = clamp(float(h_tensor[slot, cfg.THREAT]) - 2.0, 0.0, 100.0)

    def process_escalations(self, engine: Any) -> list[dict[str, Any]]:
        h_tensor = engine.state.h_tensor
        h_mask = live_human_mask(h_tensor)
        player_control = getattr(engine, "player_control", None)
        if player_control is not None:
            h_mask &= ~player_control.controlled_mask(engine)
        dormant = getattr(engine, "_dormant_h", None)
        if dormant is not None:  # EDEN_WINDOW_DORMANCY: no decision, escalation or model call for a resident outside the integrated window
            h_mask &= ~dormant
        candidate_slots = torch.where(h_mask)[0].tolist()
        if not candidate_slots:
            self._pending_since_tick.clear()
            return []

        pending_before = len(self._pending_since_tick)
        resident_by_human: dict[str, dict[str, Any]] = {}
        candidates = []
        for slot in candidate_slots:
            human_id = engine._human_uid_by_slot[slot]
            if human_id is None:
                continue
            resident = self.resident_store.ensure_resident(human_id, slot, h_tensor, engine.tick)
            resident_by_human[human_id] = resident
            candidates.append(
                build_candidate(
                    engine,
                    slot,
                    human_id,
                    resident,
                    escalated_flag=bool(float(h_tensor[slot, cfg.ESCALATION_FLAG]) > 0.0),
                    pending_since_tick=int(self._pending_since_tick.get(human_id, engine.tick)),
                    last_decision_tick=int(self._last_decision_tick_by_human.get(human_id, -10**9)),
                )
            )

        route_bundle = select_processing_batch(
            candidates,
            tick=int(engine.tick),
            batch_interval_ticks=self.batch_interval_ticks,
            max_batch_size=self.max_batch_size,
            last_batch_tick=self._last_batch_tick,
            urgent_cooldown_ticks=self.urgent_cooldown_ticks,
        )
        for route_decision in route_bundle["decisions"]:
            self._register_deferred_normal_task(route_decision, int(engine.tick))

        scheduled_normals, deferred_task_by_human = self._collect_due_deferred_tasks(
            route_bundle,
            tick=int(engine.tick),
        )
        urgent_decisions = list(route_bundle["urgent"])
        considered_ids = {
            decision.human_id
            for decision in route_bundle["decisions"]
            if decision.should_consider
        }
        for human_id in considered_ids:
            self._pending_since_tick.setdefault(human_id, int(engine.tick))
        for human_id in list(self._pending_since_tick):
            if human_id not in considered_ids:
                self._pending_since_tick.pop(human_id, None)

        process_decisions: list[Any] = []
        seen_humans: set[str] = set()
        for route_decision in [*urgent_decisions, *scheduled_normals]:
            if route_decision.human_id in seen_humans:
                continue
            seen_humans.add(route_decision.human_id)
            process_decisions.append(route_decision)
        if any(route_decision.lane != "urgent" for route_decision in process_decisions):
            self._last_batch_tick = int(engine.tick)
        if not process_decisions:
            self.route_history.append(
                {
                    "tick": engine.tick,
                    "considered": len(considered_ids),
                    "urgent": len(urgent_decisions),
                    "scheduled": len(scheduled_normals),
                    "deferred_due": len(deferred_task_by_human),
                    "processed": 0,
                }
            )
            self.route_history = self.route_history[-30:]
            return []

        process_ids = [
            decision.human_id
            for decision in process_decisions
        ]
        memory_rag = getattr(engine, "memory_rag", None)
        if memory_rag is not None and process_ids:
            engine.flush_memory_graph_queue(human_ids=process_ids, save=False, force=True)

        cases: list[dict[str, Any]] = []
        processed_deferred_ids: set[str] = set()
        for route_decision in process_decisions:
            resident = resident_by_human[route_decision.human_id]
            deferred_task = deferred_task_by_human.get(route_decision.human_id)
            if deferred_task is not None:
                if bool(deferred_task.get("goal_review_requested", False)) and hasattr(engine, "world_agent"):
                    engine.world_agent.queue_reasoning_task(
                        {
                            "resident_id": route_decision.human_id,
                            "reason": str(deferred_task.get("reason", "deferred_normal_task")),
                            "review_requested": True,
                            "auto_plan": True,
                        }
                    )
                processed_deferred_ids.add(route_decision.human_id)
            case = self._build_case(engine, route_decision.slot, route_decision.human_id, resident)
            case["escalation"] = build_escalation_prompt_payload(route_decision)
            case["escalation_summary"] = summarize_escalation(route_decision)
            case["goal_review_requested"] = bool(
                deferred_task is not None and deferred_task.get("goal_review_requested", False)
            )
            case["deferred_task"] = None if deferred_task is None else dict(deferred_task)
            cases.append(case)

        decisions = self._decide_batch(engine, cases)
        outcomes: list[dict[str, Any]] = []
        touched_ids: set[str] = set()
        for case, decision in zip(cases, decisions):
            outcome, case_touched = self._process_case_decision(engine, case, decision)
            outcomes.append(outcome)
            touched_ids.update(case_touched)

        if memory_rag is not None and touched_ids:
            engine.flush_memory_graph_queue(human_ids=touched_ids, save=False, force=True)

        for human_id in processed_deferred_ids:
            task = self._deferred_normal_tasks.pop(human_id, None)
            if task is None:
                continue
            for source_key in task.get("source_keys", []):
                normalized_source = str(source_key).strip()
                if normalized_source and normalized_source not in self.completed_consequence_sources:
                    self.completed_consequence_sources.append(normalized_source)
            self.deferred_task_history.append(
                {
                    "tick": engine.tick,
                    "human_id": human_id,
                    "reason": task.get("reason", ""),
                    "goal_review_requested": bool(task.get("goal_review_requested", False)),
                    "source_tags": list(task.get("source_tags", [])),
                }
            )
        self.deferred_task_history = self.deferred_task_history[-30:]
        self.completed_consequence_sources = self.completed_consequence_sources[-30:]

        self.history.extend(outcomes)
        self.history = self.history[-30:]
        self.route_history.append(
            {
                "tick": engine.tick,
                "considered": len(considered_ids),
                "urgent": len(urgent_decisions),
                "scheduled": len(scheduled_normals),
                "deferred_due": len(deferred_task_by_human),
                "goal_review_requested": sum(
                    1 for decision in route_bundle["decisions"] if decision.goal_review_requested
                ),
                "processed": len(outcomes),
            }
        )
        self.route_history = self.route_history[-30:]
        self.batch_history.append(
            {
                "tick": engine.tick,
                "processed": len(outcomes),
                "urgent": len(urgent_decisions),
                "scheduled": len(scheduled_normals),
                "pending_before": pending_before,
                "pending_after": len(self._pending_since_tick),
                "deferred_due": len(deferred_task_by_human),
                "deferred_pending": len(self._deferred_normal_tasks),
                "goal_review_requested": sum(
                    1 for decision in route_bundle["decisions"] if decision.goal_review_requested
                ),
            }
        )
        self.batch_history = self.batch_history[-30:]
        return outcomes
