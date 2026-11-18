from __future__ import annotations

import re
from typing import Any

import torch

try:
    import genesis_config as cfg
    import instincts_and_tools as iat
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg
    from at_the_beginning import instincts_and_tools as iat

try:
    from systems.construction import construction_prompt_payload, construction_prompt_summary
    from systems.crafting.ops import crafting_prompt_payload, crafting_prompt_summary
    from systems.goal.ops import goal_prompt_payload, goal_prompt_summary
    from systems.memory.retrieval import build_human_memory_bundle
    from systems.occupation.ops import occupation_prompt_payload, occupation_prompt_summary
    from systems.personality.ops import personality_prompt_payload, personality_prompt_summary
    from systems.planning.ops import (
        plan_catalog_payload,
        plan_prompt_payload,
        plan_prompt_summary,
        reasoning_review_due,
    )
    from systems.schedule.ops import schedule_prompt_payload, schedule_prompt_summary
    from systems.tasks.ops import active_task_payload, task_prompt_payload, task_prompt_summary
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.construction import construction_prompt_payload, construction_prompt_summary
    from at_the_beginning.systems.crafting.ops import crafting_prompt_payload, crafting_prompt_summary
    from at_the_beginning.systems.goal.ops import goal_prompt_payload, goal_prompt_summary
    from at_the_beginning.systems.memory.retrieval import build_human_memory_bundle
    from at_the_beginning.systems.occupation.ops import occupation_prompt_payload, occupation_prompt_summary
    from at_the_beginning.systems.personality.ops import personality_prompt_payload, personality_prompt_summary
    from at_the_beginning.systems.planning.ops import (
        plan_catalog_payload,
        plan_prompt_payload,
        plan_prompt_summary,
        reasoning_review_due,
    )
    from at_the_beginning.systems.schedule.ops import schedule_prompt_payload, schedule_prompt_summary
    from at_the_beginning.systems.tasks.ops import active_task_payload, task_prompt_payload, task_prompt_summary

from .common import animal_mask, live_human_mask, nearest_entity, window_mode
from .resident_store import ResidentAgentStore


class WorldAgentRuntime:
    def __init__(self, resident_store: ResidentAgentStore):
        self.resident_store = resident_store
        self._queue: list[dict[str, Any]] = []
        self._reasoning_queue: list[dict[str, Any]] = []
        self._queued_reasoning_by_human: dict[str, dict[str, Any]] = {}
        self._next_decree_id = 1
        self._next_reasoning_id = 1
        self.history: list[dict[str, Any]] = []
        self.reasoning_history: list[dict[str, Any]] = []
        self.reasoning_batch_size = 4

    def queue_decree(self, payload: Any) -> dict[str, Any]:
        decree = {
            "decree_id": self._next_decree_id,
            "payload": payload,
        }
        self._next_decree_id += 1
        self._queue.append(decree)
        return {"queued": True, "decree_id": decree["decree_id"], "pending": len(self._queue)}

    def pending_count(self) -> int:
        return len(self._queue)

    def queue_reasoning_task(self, payload: Any) -> dict[str, Any]:
        reasoning_payload = dict(payload or {})
        human_id = str(reasoning_payload.get("resident_id") or reasoning_payload.get("human_id") or "").strip()
        if human_id and human_id in self._queued_reasoning_by_human:
            entry = self._queued_reasoning_by_human[human_id]
            existing_payload = dict(entry.get("payload") or {})
            reasons = [str(reason) for reason in existing_payload.get("reasons", []) if str(reason).strip()]
            new_reason = str(reasoning_payload.get("reason") or "").strip()
            if new_reason and new_reason not in reasons:
                reasons.append(new_reason)
            if reasons:
                existing_payload["reasons"] = reasons[:6]
                existing_payload["reason"] = reasons[0]
            existing_payload["review_requested"] = bool(
                existing_payload.get("review_requested", False) or reasoning_payload.get("review_requested", False)
            )
            entry["payload"] = existing_payload
            return {"queued": True, "reasoning_id": entry["reasoning_id"], "pending": len(self._reasoning_queue), "deduped": True}

        entry = {
            "reasoning_id": self._next_reasoning_id,
            "payload": reasoning_payload,
        }
        self._next_reasoning_id += 1
        self._reasoning_queue.append(entry)
        if human_id:
            self._queued_reasoning_by_human[human_id] = entry
        return {"queued": True, "reasoning_id": entry["reasoning_id"], "pending": len(self._reasoning_queue), "deduped": False}

    def pending_reasoning_count(self) -> int:
        return len(self._reasoning_queue)

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "pending_decrees": len(self._queue),
            "pending_reasoning": len(self._reasoning_queue),
            "recent_decrees": self.history[-10:],
            "recent_reasoning": self.reasoning_history[-10:],
            "reasoning_batch_size": self.reasoning_batch_size,
        }

    @staticmethod
    def _extract_text_payload(payload: Any) -> tuple[str, list[str] | None]:
        if isinstance(payload, dict):
            text = str(payload.get("god_decree") or payload.get("text") or payload.get("command") or "").strip()
            sub_queries = payload.get("sub_queries")
            if isinstance(sub_queries, list):
                filtered = [str(item).strip() for item in sub_queries if str(item).strip()]
                return text, filtered or None
            return text, None
        return str(payload).strip(), None

    @staticmethod
    def _call_world_model_handler(handler: Any, mode: str, cases: list[dict[str, Any]], engine: Any) -> Any:
        if callable(handler):
            try:
                return handler(mode=mode, cases=cases, engine=engine)
            except TypeError:
                try:
                    return handler(mode, cases, engine)
                except TypeError:
                    return handler(mode=mode, cases=cases)

        run_mode_batch = getattr(handler, "run_mode_batch", None)
        if callable(run_mode_batch):
            return run_mode_batch(mode=mode, cases=cases, engine=engine)

        infer_mode_batch = getattr(handler, "infer_mode_batch", None)
        if callable(infer_mode_batch):
            return infer_mode_batch(mode=mode, cases=cases, engine=engine)

        infer_batch = getattr(handler, "infer_batch", None)
        if callable(infer_batch):
            return infer_batch(mode=mode, cases=cases, engine=engine)

        return None

    def _world_model_handler(self, engine: Any) -> tuple[Any | None, str]:
        engine_runner = getattr(engine, "run_world_model_mode_batch", None)
        if callable(engine_runner):
            return engine_runner, "engine.run_world_model_mode_batch"
        handler = getattr(engine, "world_model_handler", None)
        if handler is not None:
            return handler, "engine.world_model_handler"
        world_model = getattr(engine, "world_model", None)
        if world_model is not None:
            return world_model, "engine.world_model"
        return None, "heuristic_fallback"

    def _build_decree_world_model_case(self, payload: Any, engine: Any) -> dict[str, Any]:
        decree_text, sub_queries = self._extract_text_payload(payload)
        tool_bundle = None
        retrieve_light_rag_bundle = getattr(engine, "retrieve_light_rag_bundle", None)
        if decree_text and getattr(engine, "light_rag", None) is None:
            tool_bundle = {
                "enabled": False,
                "query": decree_text,
                "tools": [],
                "context": "",
                "error": "lightrag_not_loaded",
            }
        elif decree_text and callable(retrieve_light_rag_bundle):
            try:
                tool_bundle = retrieve_light_rag_bundle(decree_text, sub_queries=sub_queries)
            except Exception as exc:  # pragma: no cover - retrieval fallback
                tool_bundle = {
                    "enabled": False,
                    "query": decree_text,
                    "tools": [],
                    "context": "",
                    "error": f"lightrag_unavailable:{exc.__class__.__name__}",
                }
        return {
            "world_model_mode": "decree",
            "query": decree_text,
            "sub_queries": list(sub_queries or []),
            "raw_payload": payload,
            "tool_bundle": tool_bundle,
            "execution_limits": getattr(getattr(engine, "execution_agent", None), "limits_snapshot", lambda: {})(),
        }

    def _build_reasoning_query(self, resident: dict[str, Any], resident_id: str, reason_text: str) -> tuple[str, list[str]]:
        personality_summary = personality_prompt_summary(resident)
        occupation_summary = occupation_prompt_summary(resident)
        schedule_summary = schedule_prompt_summary(resident)
        crafting_summary = crafting_prompt_summary(resident)
        construction_summary = construction_prompt_summary(resident)
        task_summary = task_prompt_summary(resident)
        goal_summary = goal_prompt_summary(resident)
        plan_summary = plan_prompt_summary(resident)
        parts = [
            reason_text or "resident reasoning",
            occupation_summary,
            schedule_summary,
            crafting_summary,
            construction_summary,
            task_summary,
            personality_summary,
            goal_summary,
            plan_summary,
        ]
        query_text = " ; ".join(part for part in parts if str(part).strip()) or f"{resident_id} resident reasoning"
        sub_queries = [reason_text or "resident reasoning"]
        if occupation_summary:
            sub_queries.append(f"occupation {occupation_summary}")
        if schedule_summary:
            sub_queries.append(f"schedule {schedule_summary}")
        if crafting_summary:
            sub_queries.append(f"crafting {crafting_summary}")
        if construction_summary:
            sub_queries.append(f"construction {construction_summary}")
        if task_summary:
            sub_queries.append(f"tasks {task_summary}")
        if goal_summary:
            sub_queries.append(f"goals {goal_summary}")
        if plan_summary:
            sub_queries.append(f"plans {plan_summary}")
        archetype = str(resident.get("personality", {}).get("archetype", "")).strip()
        if archetype:
            sub_queries.append(f"personality {archetype}")
        return query_text, sub_queries[:6]

    def _build_reasoning_world_model_case(self, payload: Any, engine: Any) -> dict[str, Any]:
        if isinstance(payload, dict) and ("goal_updates" in payload or "plans" in payload or "goal_review" in payload):
            reason_text = str(payload.get("reason") or payload.get("notes") or "resident reasoning").strip()
            packet = dict(payload)
            packet.setdefault("reasoning_mode", "resident_reasoning")
            packet.setdefault("goal_review", {"requested": True, "reason": reason_text, "force": True})
            packet.setdefault("auto_plan", True)
            resident_id = str(packet.get("resident_id") or packet.get("human_id") or "").strip()
            return {
                "world_model_mode": "resident_reasoning",
                "resident_id": resident_id,
                "reason": reason_text or "resident reasoning",
                "prebuilt_packet": packet,
            }

        reasoning_payload = dict(payload or {})
        resident_id = str(reasoning_payload.get("resident_id") or reasoning_payload.get("human_id") or "").strip()
        resident = self.resident_store.get(resident_id)
        if resident is None:
            return {
                "world_model_mode": "resident_reasoning",
                "resident_id": resident_id,
                "reason": "resident_missing",
                "resident": None,
                "resident_context": {},
                "tool_bundle": None,
                "memory_bundle": None,
                "review_requested": bool(reasoning_payload.get("review_requested", False)),
                "auto_plan": bool(reasoning_payload.get("auto_plan", False)),
            }

        reason_text = str(
            reasoning_payload.get("reason")
            or resident.get("planning_state", {}).get("review_reason", "")
            or "resident reasoning"
        ).strip()
        query_text, sub_queries = self._build_reasoning_query(resident, resident_id, reason_text)
        memory_bundle = None
        if getattr(engine, "memory_rag", None) is not None:
            try:
                memory_bundle = build_human_memory_bundle(
                    engine.memory_rag,
                    self.resident_store,
                    resident_id,
                    query=query_text,
                )
            except Exception as exc:  # pragma: no cover - retrieval fallback
                memory_bundle = {
                    "human_id": resident_id,
                    "resident": resident,
                    "query": query_text,
                    "memory_graph": {
                        "query": query_text,
                        "rows": [],
                        "error": f"memory_rag_unavailable:{exc.__class__.__name__}",
                    },
                }
        tool_bundle = None
        retrieve_light_rag_bundle = getattr(engine, "retrieve_light_rag_bundle", None)
        if getattr(engine, "light_rag", None) is None:
            tool_bundle = {
                "enabled": False,
                "query": query_text,
                "tools": [],
                "context": "",
                "error": "lightrag_not_loaded",
            }
        elif callable(retrieve_light_rag_bundle):
            try:
                tool_bundle = retrieve_light_rag_bundle(query_text, sub_queries=sub_queries)
            except Exception as exc:  # pragma: no cover - retrieval fallback
                tool_bundle = {
                    "enabled": False,
                    "query": query_text,
                    "tools": [],
                    "context": "",
                    "error": f"lightrag_unavailable:{exc.__class__.__name__}",
                }
        resident_context = {
            "crafting": crafting_prompt_payload(resident),
            "crafting_summary": crafting_prompt_summary(resident),
            "construction": construction_prompt_payload(resident),
            "construction_summary": construction_prompt_summary(resident),
            "tasks": task_prompt_payload(resident),
            "task_summary": task_prompt_summary(resident),
            "active_task": active_task_payload(resident),
            "occupation": occupation_prompt_payload(resident),
            "occupation_summary": occupation_prompt_summary(resident),
            "personality": personality_prompt_payload(resident),
            "personality_summary": personality_prompt_summary(resident),
            "schedule": schedule_prompt_payload(resident),
            "schedule_summary": schedule_prompt_summary(resident),
            "goals": goal_prompt_payload(resident),
            "goal_summary": goal_prompt_summary(resident),
            "plans": plan_prompt_payload(resident),
            "plan_summary": plan_prompt_summary(resident),
            "plan_catalog": plan_catalog_payload(),
            "memory_bundle": memory_bundle,
            "tool_bundle": tool_bundle,
        }
        return {
            "world_model_mode": "resident_reasoning",
            "resident_id": resident_id,
            "reason": reason_text or "resident reasoning",
            "resident": resident,
            "resident_context": resident_context,
            "tool_bundle": tool_bundle,
            "memory_bundle": memory_bundle,
            "review_requested": bool(reasoning_payload.get("review_requested", True)),
            "auto_plan": bool(reasoning_payload.get("auto_plan", True)),
            "raw_payload": reasoning_payload,
            "query": query_text,
            "sub_queries": sub_queries,
        }

    def _fallback_world_model_packet(self, mode: str, case: dict[str, Any], engine: Any) -> dict[str, Any]:
        if mode == "decree":
            decree_text = str(case.get("query") or "")
            return self._heuristic_plan(decree_text, engine)

        resident_id = str(case.get("resident_id") or "").strip()
        resident = case.get("resident")
        reason_text = str(case.get("reason") or "resident reasoning").strip()
        if case.get("prebuilt_packet") is not None:
            packet = dict(case["prebuilt_packet"])
            packet.setdefault("reasoning_mode", "resident_reasoning")
            return packet
        if resident is None:
            return {
                "resident_id": resident_id,
                "reasoning_mode": "resident_reasoning",
                "reason": "resident_missing",
                "goal_review": {"requested": False, "reason": "resident_missing", "force": False},
                "goal_updates": [],
                "plans": [],
                "auto_plan": False,
                "notes": "resident missing",
            }
        return {
            "resident_id": resident_id,
            "reasoning_mode": "resident_reasoning",
            "reason": reason_text or "resident reasoning",
            "notes": f"Heuristic resident reasoning for {resident_id}",
            "goal_review": {
                "requested": bool(case.get("review_requested", True)),
                "reason": reason_text or "resident reasoning",
                "force": True,
            },
            "goal_updates": [],
            "plans": [],
            "auto_plan": bool(case.get("auto_plan", True)),
            "resident_context": dict(case.get("resident_context") or {}),
        }

    def _normalize_world_model_response(
        self,
        response: Any,
        *,
        mode: str,
        fallback_packet: dict[str, Any],
        fallback_source: str,
    ) -> dict[str, Any]:
        packet = None
        source = fallback_source
        if isinstance(response, dict):
            source = str(response.get("source") or response.get("model_source") or fallback_source)
            candidate_packet = response.get("packet")
            if isinstance(candidate_packet, dict):
                packet = dict(candidate_packet)
            elif mode == "decree" and ("map_actions" in response or "human_actions" in response):
                packet = dict(response)
            elif mode == "resident_reasoning" and (
                "goal_review" in response or "goal_updates" in response or "plans" in response
            ):
                packet = dict(response)
        if packet is None:
            packet = fallback_packet
            source = f"{fallback_source}:fallback"
        return {"packet": packet, "source": source}

    def _run_world_model_batch(self, mode: str, cases: list[dict[str, Any]], engine: Any) -> list[dict[str, Any]]:
        fallback_packets = [self._fallback_world_model_packet(mode, case, engine) for case in cases]
        handler, fallback_source = self._world_model_handler(engine)
        responses: Any = None
        if handler is not None:
            try:
                responses = self._call_world_model_handler(handler, mode, cases, engine)
            except Exception as exc:  # pragma: no cover - runtime fallback
                fallback_source = f"{fallback_source}_error:{exc.__class__.__name__}"
                responses = None

        if isinstance(responses, dict) and isinstance(responses.get("responses"), list):
            responses = responses["responses"]
        elif isinstance(responses, dict):
            responses = [responses]
        elif not isinstance(responses, list):
            responses = []

        results: list[dict[str, Any]] = []
        for idx, case in enumerate(cases):
            response = responses[idx] if idx < len(responses) else None
            results.append(
                self._normalize_world_model_response(
                    response,
                    mode=mode,
                    fallback_packet=fallback_packets[idx],
                    fallback_source=fallback_source,
                )
            )
        return results

    def _region_center(self, text: str) -> tuple[float, float]:
        cx = cfg.MAP_WIDTH / 2.0
        cy = cfg.MAP_HEIGHT / 2.0
        lower = text.lower()
        if "north" in lower:
            cy = cfg.MAP_HEIGHT * 0.25
        if "south" in lower:
            cy = cfg.MAP_HEIGHT * 0.75
        if "west" in lower:
            cx = cfg.MAP_WIDTH * 0.25
        if "east" in lower:
            cx = cfg.MAP_WIDTH * 0.75
        return cx, cy

    def _entity_center_for_types(self, m_tensor: torch.Tensor, type_ids: set[int]) -> tuple[float, float]:
        eid, _ = nearest_entity(
            m_tensor,
            cfg.MAP_WIDTH / 2.0,
            cfg.MAP_HEIGHT / 2.0,
            type_ids=type_ids,
        )
        if eid == -1:
            return cfg.MAP_WIDTH / 2.0, cfg.MAP_HEIGHT / 2.0
        return float(m_tensor[eid, cfg.CX]), float(m_tensor[eid, cfg.CY])

    def _parse_first_int(self, text: str, default: int) -> int:
        match = re.search(r"\b(\d+)\b", text)
        if not match:
            return default
        return int(match.group(1))

    def _edge_from_text(self, text: str) -> str:
        lower = text.lower()
        if "north" in lower:
            return "north"
        if "south" in lower:
            return "south"
        if "west" in lower:
            return "west"
        if "east" in lower:
            return "east"
        return "auto"

    def _feature_type_from_text(self, text: str) -> int | None:
        lower = text.lower()
        if any(word in lower for word in ("mountain", "mountains", "ridge")):
            return cfg.M_MOUNTAIN
        if any(word in lower for word in ("forest", "woods", "grove")):
            return cfg.M_FOREST
        if any(word in lower for word in ("lake", "pond")):
            return cfg.M_LAKE
        if any(word in lower for word in ("settlement", "village", "town")):
            return cfg.M_VILLAGE
        if "farm" in lower:
            return cfg.M_FARM
        if "well" in lower:
            return cfg.M_WELL
        if "wall" in lower:
            return cfg.M_WALL
        if "beach" in lower:
            return cfg.M_BEACH
        if any(word in lower for word in ("grass", "plain", "meadow")):
            return cfg.M_GRASS
        if any(word in lower for word in ("barren", "wasteland")):
            return cfg.M_BARREN
        return None

    def _match_named_human(self, engine: Any, text: str) -> dict[str, Any] | None:
        lower = text.lower()
        for slot, human_id in enumerate(engine._human_uid_by_slot):
            if human_id is None:
                continue
            resident = self.resident_store.get(human_id)
            resident_name = str(resident["profile"]["name"]) if resident else human_id
            candidates = {
                human_id.lower(),
                resident_name.lower(),
            }
            if any(candidate and candidate in lower for candidate in candidates):
                return {
                    "slot": slot,
                    "human_id": human_id,
                    "human_name": resident_name,
                }
        return None

    def _heuristic_plan(self, text: str, engine: Any) -> dict[str, Any]:
        lower = text.lower()
        center_x, center_y = self._region_center(lower)
        m_tensor = engine.state.m_tensor
        packet = {
            "thought": f"Heuristic world-agent dispatch for decree: {text}",
            "map_actions": [],
            "human_actions": [],
            "new_entities": [],
            "new_instincts": [],
        }

        matched_human = self._match_named_human(engine, lower)
        wants_control = any(phrase in lower for phrase in ("control ", "controlling ", "possess ", "play as ", "take over "))
        wants_release = any(
            phrase in lower
            for phrase in ("release control", "stop controlling", "stop control", "unpossess", "release adam", "release eve")
        )

        if wants_control and matched_human is not None:
            packet["human_actions"].append(
                {
                    "tool_name": "tool_assign_control_target",
                    "parameters": {
                        "controller_id": "local_player",
                        "target_kind": "human",
                        "target_id": matched_human["human_id"],
                        "target_name": matched_human["human_name"],
                        "mode": "possess",
                    },
                }
            )

        if wants_release:
            release_params: dict[str, Any] = {"controller_id": "local_player"}
            if matched_human is not None:
                release_params["target_kind"] = "human"
                release_params["target_id"] = matched_human["human_id"]
            packet["human_actions"].append(
                {
                    "tool_name": "tool_release_control_target",
                    "parameters": release_params,
                }
            )

        requested_feature = self._feature_type_from_text(lower)
        near_phrase = any(phrase in lower for phrase in ("next to", "near ", "beside ", "adjacent to"))
        if requested_feature is not None and near_phrase:
            anchor_type = None
            for probe in (
                ("lake", cfg.M_LAKE),
                ("forest", cfg.M_FOREST),
                ("mountain", cfg.M_MOUNTAIN),
                ("village", cfg.M_VILLAGE),
                ("settlement", cfg.M_VILLAGE),
                ("farm", cfg.M_FARM),
                ("well", cfg.M_WELL),
            ):
                if probe[0] in lower and probe[1] != requested_feature:
                    anchor_type = probe[1]
                    break
            if anchor_type is not None:
                packet["map_actions"].append(
                    {
                        "tool_name": "tool_create_feature_near_feature",
                        "parameters": {
                            "feature_type": requested_feature,
                            "near_type": anchor_type,
                            "search_x": center_x,
                            "search_y": center_y,
                            "offset_distance": 48.0,
                            "count": 3 if requested_feature == cfg.M_FOREST else 1,
                            "segments": 3 if requested_feature == cfg.M_MOUNTAIN else 1,
                        },
                    }
                )

        if any(word in lower for word in ("expand", "frontier", "new area", "new land")):
            if iat.frontier_frozen():       # D-005: frozen; answer with a stable reason instead of an action
                packet.setdefault("skipped_actions", []).append(
                    {"tool_name": "tool_expand_world_edge", "reason": "legacy_frozen"}
                )
            else:
                packet["map_actions"].append(
                    {
                        "tool_name": "tool_expand_world_edge",
                        "parameters": {"edge": self._edge_from_text(lower)},
                    }
                )

        if any(word in lower for word in ("create", "make", "spawn", "raise", "build")) and requested_feature is not None and not near_phrase:
            if requested_feature == cfg.M_LAKE:
                packet["map_actions"].append(
                    {
                        "tool_name": "tool_create_lake",
                        "parameters": {"center_x": center_x, "center_y": center_y},
                    }
                )
            elif requested_feature == cfg.M_FOREST:
                packet["map_actions"].append(
                    {
                        "tool_name": "tool_create_forest_patch",
                        "parameters": {"center_x": center_x, "center_y": center_y},
                    }
                )
            elif requested_feature == cfg.M_MOUNTAIN:
                packet["map_actions"].append(
                    {
                        "tool_name": "tool_create_mountain_chain",
                        "parameters": {
                            "start_x": center_x - 50.0,
                            "start_y": center_y,
                            "end_x": center_x + 50.0,
                            "end_y": center_y,
                            "segments": 3,
                        },
                    }
                )
            elif requested_feature == cfg.M_VILLAGE:
                packet["map_actions"].append(
                    {
                        "tool_name": "tool_settle_area",
                        "parameters": {"center_x": center_x, "center_y": center_y},
                    }
                )

        if any(word in lower for word in ("wildfire", "burn", "fire")):
            fx, fy = self._entity_center_for_types(m_tensor, {cfg.M_FOREST})
            packet["map_actions"].append(
                {
                    "tool_name": "tool_wildfire",
                    "parameters": {"center_x": fx, "center_y": fy, "radius": 90.0},
                }
            )

        if "flood" in lower:
            packet["map_actions"].append({"tool_name": "tool_flood", "parameters": {}})

        if any(word in lower for word in ("drought", "drain")):
            packet["map_actions"].append({"tool_name": "tool_drought", "parameters": {}})

        if "earthquake" in lower:
            packet["map_actions"].append(
                {
                    "tool_name": "tool_earthquake",
                    "parameters": {"center_x": center_x, "center_y": center_y, "radius": 120.0},
                }
            )

        if "storm" in lower:
            packet["map_actions"].append(
                {
                    "tool_name": "tool_storm",
                    "parameters": {"center_x": center_x, "center_y": center_y, "radius": 120.0},
                }
            )

        if any(word in lower for word in ("volcano", "eruption", "lava")):
            vx, vy = self._entity_center_for_types(m_tensor, {cfg.M_MOUNTAIN})
            packet["map_actions"].append(
                {"tool_name": "tool_volcanic_eruption", "parameters": {"center_x": vx, "center_y": vy}}
            )

        if any(word in lower for word in ("plague", "disease", "sick")):
            packet["human_actions"].append({"tool_name": "tool_plague", "parameters": {}})

        if any(word in lower for word in ("bless", "heal", "restore")):
            packet["human_actions"].append({"tool_name": "tool_bless", "parameters": {}})

        if "panic" in lower:
            packet["human_actions"].append(
                {
                    "tool_name": "tool_panic_area",
                    "parameters": {"center_x": center_x, "center_y": center_y, "radius": 90.0},
                }
            )

        if any(word in lower for word in ("calm", "peace")):
            packet["human_actions"].append(
                {
                    "tool_name": "tool_calm_area",
                    "parameters": {"center_x": center_x, "center_y": center_y, "radius": 90.0},
                }
            )

        if any(word in lower for word in ("bounty", "abundance", "fertile", "prosper")):
            packet["map_actions"].append(
                {
                    "tool_name": "tool_bounty_area",
                    "parameters": {"center_x": center_x, "center_y": center_y, "radius": 100.0},
                }
            )

        if any(word in lower for word in ("scarcity", "famine", "blight")):
            packet["map_actions"].append(
                {
                    "tool_name": "tool_scarcity_area",
                    "parameters": {"center_x": center_x, "center_y": center_y, "radius": 100.0},
                }
            )

        if "baby boom" in lower or "fertility" in lower:
            packet["human_actions"].append({"tool_name": "tool_baby_boom", "parameters": {}})

        if "cull" in lower:
            packet["human_actions"].append(
                {
                    "tool_name": "tool_cull",
                    "parameters": {"target_population": self._parse_first_int(lower, max(engine.pop_count - 5, 2))},
                }
            )

        if any(word in lower for word in ("wolf", "wolves")):
            fx, fy = self._entity_center_for_types(m_tensor, {cfg.M_FOREST})
            packet["map_actions"].append(
                {
                    "tool_name": "tool_spawn_animal_group",
                    "parameters": {
                        "species": cfg.M_WOLF,
                        "count": self._parse_first_int(lower, 4),
                        "cx": fx,
                        "cy": fy,
                        "scatter": 35.0,
                    },
                }
            )

        if "tiger" in lower:
            fx, fy = self._entity_center_for_types(m_tensor, {cfg.M_FOREST, cfg.M_GRASS})
            packet["map_actions"].append(
                {
                    "tool_name": "tool_spawn_animal_group",
                    "parameters": {
                        "species": cfg.M_TIGER,
                        "count": self._parse_first_int(lower, 2),
                        "cx": fx,
                        "cy": fy,
                        "scatter": 35.0,
                    },
                }
            )

        if "deer" in lower:
            gx, gy = self._entity_center_for_types(m_tensor, {cfg.M_GRASS})
            packet["map_actions"].append(
                {
                    "tool_name": "tool_spawn_animal_group",
                    "parameters": {
                        "species": cfg.M_DEER,
                        "count": self._parse_first_int(lower, 6),
                        "cx": gx,
                        "cy": gy,
                        "scatter": 40.0,
                    },
                }
            )

        if "sheep" in lower:
            gx, gy = self._entity_center_for_types(m_tensor, {cfg.M_GRASS})
            packet["map_actions"].append(
                {
                    "tool_name": "tool_spawn_animal_group",
                    "parameters": {
                        "species": cfg.M_SHEEP,
                        "count": self._parse_first_int(lower, 6),
                        "cx": gx,
                        "cy": gy,
                        "scatter": 40.0,
                    },
                }
            )

        return packet

    def _resolve_constant(self, value: Any) -> Any:
        if isinstance(value, str) and hasattr(cfg, value):
            return getattr(cfg, value)
        return value

    def _resolve_human_selector(self, engine: Any, selector: Any) -> torch.Tensor:
        h_mask = live_human_mask(engine.state.h_tensor)
        if selector is None:
            return h_mask
        if isinstance(selector, str):
            if selector == "all_humans":
                return h_mask
            if selector == "escalated_humans":
                return h_mask & (engine.state.h_tensor[:, cfg.ESCALATION_FLAG] > 0.0)
            raise ValueError(f"Unsupported human selector string: {selector}")
        if isinstance(selector, dict):
            kind = selector.get("kind")
            if kind == "human_ids":
                ids = set(selector.get("ids", []))
                mask = torch.zeros_like(h_mask)
                for slot, human_id in enumerate(engine._human_uid_by_slot):
                    if human_id in ids:
                        mask[slot] = True
                return mask & h_mask
            if kind == "human_slots":
                mask = torch.zeros_like(h_mask)
                for slot in selector.get("slots", []):
                    if 0 <= int(slot) < mask.shape[0]:
                        mask[int(slot)] = True
                return mask & h_mask
            if kind == "radius":
                center = selector.get("center", [cfg.MAP_WIDTH / 2.0, cfg.MAP_HEIGHT / 2.0])
                radius = float(selector.get("radius", 80.0))
                return iat._agent_radial_mask(
                    engine.state.h_tensor,
                    h_mask,
                    float(center[0]),
                    float(center[1]),
                    radius,
                    engine.state.device,
                )
        raise ValueError(f"Unsupported human selector: {selector}")

    def _resolve_entity_selector(self, engine: Any, selector: Any) -> torch.Tensor:
        m_tensor = engine.state.m_tensor
        mask = m_tensor[:, cfg.M_TYPE] > 0
        if selector is None:
            return mask
        if isinstance(selector, dict):
            kind = selector.get("kind")
            if kind == "type_ids":
                type_ids = {int(self._resolve_constant(v)) for v in selector.get("type_ids", [])}
                result = torch.zeros_like(mask)
                for type_id in type_ids:
                    result |= m_tensor[:, cfg.M_TYPE] == type_id
                return result
            if kind == "entity_ids":
                ids = set(selector.get("ids", []))
                result = torch.zeros_like(mask)
                for slot, entity_id in enumerate(engine._entity_uid_by_slot):
                    if entity_id in ids:
                        result[slot] = True
                return result & mask
            if kind == "entity_slots":
                if window_mode():
                    raise ValueError("entity_slots selectors are not supported when EDEN_WINDOW=1 (entity rows move in and out of the "
                                     "tensor); select by entity_ids")
                result = torch.zeros_like(mask)
                for slot in selector.get("slots", []):
                    if 0 <= int(slot) < result.shape[0]:
                        result[int(slot)] = True
                return result & mask
            if kind == "radius":
                center = selector.get("center", [cfg.MAP_WIDTH / 2.0, cfg.MAP_HEIGHT / 2.0])
                radius = float(selector.get("radius", 80.0))
                result = torch.zeros_like(mask)
                entity_ids = iat._entity_radial_ids(m_tensor, float(center[0]), float(center[1]), radius)
                if entity_ids.numel():
                    result[entity_ids] = True
                return result & mask
        raise ValueError(f"Unsupported entity selector: {selector}")

    def _resolve_parameters(self, engine: Any, params: dict[str, Any]) -> dict[str, Any]:
        resolved = {key: self._resolve_constant(value) for key, value in params.items()}
        if "mask" in resolved:
            resolved["mask"] = self._resolve_human_selector(engine, resolved["mask"])
        if "human_ids" in resolved and "mask" not in resolved:
            resolved["mask"] = self._resolve_human_selector(
                engine, {"kind": "human_ids", "ids": resolved.pop("human_ids")}
            )
        if "entity_mask" in resolved:
            resolved["entity_mask"] = self._resolve_entity_selector(engine, resolved["entity_mask"])
        if "entity_ids" in resolved and "entity_mask" not in resolved:
            resolved["entity_mask"] = self._resolve_entity_selector(
                engine, {"kind": "entity_ids", "ids": resolved.pop("entity_ids")}
            )
        if "center" in resolved:
            center = resolved.pop("center")
            resolved.setdefault("center_x", float(center[0]))
            resolved.setdefault("center_y", float(center[1]))
        return resolved

    def _execute_set_attr(self, engine: Any, params: dict[str, Any]) -> dict[str, Any]:
        mode = params.get("mode", "set")
        col = int(params["col"])
        value = float(params["value"])
        if "entity_mask" in params:
            affected = params["entity_mask"]
            tensor = engine.state.m_tensor
            map_dirty = True
        else:
            affected = params.get("mask", live_human_mask(engine.state.h_tensor))
            tensor = engine.state.h_tensor
            map_dirty = False
        if not affected.any():
            return {"ok": True, "tool_name": "set_attr", "changed": 0, "map_dirty": map_dirty}
        if mode == "set":
            tensor[affected, col] = value
        elif mode == "add":
            tensor[affected, col] += value
        elif mode == "multiply":
            tensor[affected, col] *= value
        else:
            raise ValueError(f"Unsupported set_attr mode: {mode}")
        return {
            "ok": True,
            "tool_name": "set_attr",
            "changed": int(affected.sum().item()),
            "map_dirty": map_dirty,
        }

    def _execute_spawn_human(self, engine: Any, params: dict[str, Any]) -> dict[str, Any]:
        sex = float(params.get("sex", 0.0))
        life_exp = float(params.get("life_exp", cfg.LIFE_EXP_MAX))
        age = float(params.get("age", 0.0))
        preferred_name = params.get("name")
        success = engine.spawn(
            float(params["x"]),
            float(params["y"]),
            sex,
            life_exp,
            age=age,
            preferred_name=preferred_name,
        )
        return {"ok": success, "tool_name": "instinct_born", "frame_dirty": success}

    def _execute_spawn_entity(self, engine: Any, params: dict[str, Any]) -> dict[str, Any]:
        entity_id = iat.entity_born(
            engine.state.m_tensor,
            engine._entity_count_ref,
            cx=float(params["cx"]),
            cy=float(params["cy"]),
            m_type=int(self._resolve_constant(params["m_type"])),
            hp=float(params.get("hp", 100.0)),
            scale=float(params.get("scale", 50.0)),
            register_geo=bool(params.get("register_geo", False)),
            device=engine.state.device,
            col_vals=params.get("col_vals"),
        )
        return {"ok": entity_id != -1, "tool_name": "entity_born", "map_dirty": entity_id != -1}

    def _execute_action(self, engine: Any, action: dict[str, Any]) -> dict[str, Any]:
        tool_name = action.get("tool_name")
        params = self._resolve_parameters(engine, dict(action.get("parameters") or {}))
        if tool_name == "set_attr":
            return self._execute_set_attr(engine, params)
        if tool_name == "instinct_born":
            return self._execute_spawn_human(engine, params)
        if tool_name == "entity_born":
            return self._execute_spawn_entity(engine, params)
        if tool_name in {"propose_new_instinct", "propose_new_tool"}:
            return {"ok": True, "tool_name": tool_name, "proposed_only": True}

        fn = getattr(iat, tool_name, None)
        if fn is None:
            raise ValueError(f"Unknown runtime tool: {tool_name}")

        h_mask = live_human_mask(engine.state.h_tensor)
        a_mask = animal_mask(engine.state.m_tensor)
        ctx = {"h_mask": h_mask, "a_mask": a_mask}
        result = fn(ctx, **{**engine._build_kwargs(), **params})
        payload = {"ok": True, "tool_name": tool_name}
        if isinstance(result, dict):
            payload.update(result)
        return payload

    def prepare_packet(self, payload: Any, engine: Any) -> tuple[str, dict[str, Any], str]:
        if isinstance(payload, dict) and "map_actions" in payload and "human_actions" in payload:
            packet = payload
            decree_text = str(payload.get("thought", "structured decree"))
            return decree_text, packet, "structured_input"

        case = self._build_decree_world_model_case(payload, engine)
        result = self._run_world_model_batch("decree", [case], engine)[0]
        decree_text = str(case.get("query") or "").strip()
        packet = dict(result["packet"])
        if not decree_text:
            decree_text = str(packet.get("thought", "structured decree"))
        return decree_text, packet, str(result.get("source", "heuristic_fallback"))

    def _queue_due_reasoning_reviews(self, engine: Any) -> None:
        h_tensor = engine.state.h_tensor
        h_mask = live_human_mask(h_tensor)
        for slot in torch.where(h_mask)[0].tolist():
            human_id = engine._human_uid_by_slot[slot]
            if human_id is None:
                continue
            resident = self.resident_store.ensure_resident(human_id, slot, h_tensor, engine.tick)
            if reasoning_review_due(resident, int(engine.tick)):
                self.queue_reasoning_task(
                    {
                        "resident_id": human_id,
                        "reason": str(resident.get("planning_state", {}).get("review_reason", "") or "reasoning_review_due"),
                        "review_requested": True,
                        "auto_plan": True,
                    }
                )

    def process_queues(self, engine: Any, decree_dispatcher: Any, plot_dispatcher: Any) -> dict[str, bool]:
        changed = {"frame_dirty": False, "map_dirty": False}
        processed_decrees = False
        while self._queue:
            processed_decrees = True
            entry = self._queue.pop(0)
            decree_text, packet, packet_source = self.prepare_packet(entry["payload"], engine)
            self.resident_store.record_world_decree(engine.tick, decree_text or packet["thought"])
            outcome = decree_dispatcher.execute_packet(
                engine,
                packet,
                decree_id=entry["decree_id"],
                decree_text=decree_text or packet.get("thought", ""),
            )
            changed["frame_dirty"] = changed["frame_dirty"] or outcome.get("frame_dirty", False)
            changed["map_dirty"] = changed["map_dirty"] or outcome.get("map_dirty", False)

            self.history.append(
                {
                    "tick": engine.tick,
                    "decree_id": entry["decree_id"],
                    "thought": packet.get("thought", ""),
                    "packet_source": packet_source,
                    "status": "ok" if outcome.get("ok") else "error",
                    "results": outcome.get("results", []),
                    "errors": outcome.get("errors", []),
                    "warnings": outcome.get("warnings", []),
                    "proposals": outcome.get(
                        "proposals",
                        {
                            "new_entities": packet.get("new_entities", []),
                            "new_instincts": packet.get("new_instincts", []),
                        },
                    ),
                }
            )
            self.history = self.history[-20:]
        if processed_decrees:
            return changed

        self._queue_due_reasoning_reviews(engine)
        if not self._reasoning_queue:
            return changed

        batch = self._reasoning_queue[: max(self.reasoning_batch_size, 0)]
        self._reasoning_queue = self._reasoning_queue[len(batch):]
        flush_memory_graph_queue = getattr(engine, "flush_memory_graph_queue", None)
        if callable(flush_memory_graph_queue):
            try:
                flush_memory_graph_queue(force=True, save=False)
            except TypeError:
                flush_memory_graph_queue(force=True)

        cases: list[dict[str, Any]] = []
        for entry in batch:
            case = self._build_reasoning_world_model_case(entry["payload"], engine)
            case["reasoning_id"] = entry["reasoning_id"]
            cases.append(case)

        results = self._run_world_model_batch("resident_reasoning", cases, engine)
        for entry, case, result in zip(batch, cases, results):
            resident_id = str((entry.get("payload") or {}).get("resident_id") or (entry.get("payload") or {}).get("human_id") or "").strip()
            if resident_id:
                self._queued_reasoning_by_human.pop(resident_id, None)
            reason_text = str(case.get("reason") or "resident reasoning").strip()
            packet = dict(result["packet"])
            outcome = plot_dispatcher.execute_packet(
                engine,
                packet,
                reasoning_id=entry["reasoning_id"],
                reason_text=reason_text,
            )
            changed["frame_dirty"] = changed["frame_dirty"] or outcome.get("frame_dirty", False)
            changed["map_dirty"] = changed["map_dirty"] or outcome.get("map_dirty", False)
            self.reasoning_history.append(
                {
                    "tick": engine.tick,
                    "reasoning_id": entry["reasoning_id"],
                    "resident_id": packet.get("resident_id"),
                    "reason": reason_text,
                    "packet_source": result.get("source", "heuristic_fallback"),
                    "status": "ok" if outcome.get("ok") else "error",
                    "plans_applied": outcome.get("plans_applied", 0),
                    "goal_updates_applied": outcome.get("goal_updates_applied", 0),
                    "errors": outcome.get("errors", []),
                }
            )
            self.reasoning_history = self.reasoning_history[-20:]
        return changed

    def process_pending(self, engine: Any, executor: Any) -> dict[str, bool]:
        changed = {"frame_dirty": False, "map_dirty": False}
        while self._queue:
            entry = self._queue.pop(0)
            decree_text, packet, _ = self.prepare_packet(entry["payload"], engine)
            self.resident_store.record_world_decree(engine.tick, decree_text or packet["thought"])
            outcome = executor.execute_packet(
                engine,
                packet,
                decree_id=entry["decree_id"],
                decree_text=decree_text or packet.get("thought", ""),
            )
            changed["frame_dirty"] = changed["frame_dirty"] or outcome.get("frame_dirty", False)
            changed["map_dirty"] = changed["map_dirty"] or outcome.get("map_dirty", False)
        return changed
