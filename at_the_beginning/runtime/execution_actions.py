from __future__ import annotations

from typing import Any

try:
    import genesis_config as cfg
    import instincts_and_tools as iat
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg
    from at_the_beginning import instincts_and_tools as iat

from .common import animal_mask as _animal_mask
from .common import live_human_mask as _live_human_mask


class ExecutionActionMixin:
    def _execute_set_attr(self, engine: Any, params: dict[str, Any]) -> dict[str, Any]:
        mode = params.get("mode", "set")
        col = int(params["col"])
        value = float(params["value"])
        if "entity_mask" in params:
            affected = params["entity_mask"]
            tensor = engine.state.m_tensor
            map_dirty = True
        else:
            affected = params.get("mask", _live_human_mask(engine.state.h_tensor))
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
        points = params.get("spawn_points")
        if points is None:
            points = [[float(params["x"]), float(params["y"])]]
        success_count = 0
        preferred_name = str(params.get("preferred_name") or params.get("name") or "").strip() or None
        for idx, point in enumerate(points):
            point_name = preferred_name if idx == 0 else None
            success = engine.spawn(
                float(point[0]),
                float(point[1]),
                float(params.get("sex", 0.0)),
                float(params.get("life_exp", cfg.LIFE_EXP_MAX)),
                age=float(params.get("age", 0.0)),
                preferred_name=point_name,
            )
            success_count += int(success)
        return {
            "ok": success_count > 0,
            "tool_name": "instinct_born",
            "spawned": success_count,
            "frame_dirty": success_count > 0,
        }

    def _execute_spawn_entity(self, engine: Any, params: dict[str, Any]) -> dict[str, Any]:
        entity_id = iat.entity_born(
            engine.state.m_tensor,
            engine._entity_count_ref,
            cx=float(params["cx"]),
            cy=float(params["cy"]),
            m_type=int(self._resolve_constant(engine, params["m_type"])),
            hp=float(params.get("hp", 100.0)),
            scale=float(params.get("scale", 50.0)),
            register_geo=bool(params.get("register_geo", False)),
            device=engine.state.device,
            col_vals=params.get("col_vals"),
        )
        return {
            "ok": entity_id != -1,
            "tool_name": "entity_born",
            "entity_id": entity_id,
            "map_dirty": entity_id != -1,
        }

    def _execute_spawn_animal(self, engine: Any, params: dict[str, Any]) -> dict[str, Any]:
        entity_id = iat.animal_born(
            engine.state.m_tensor,
            engine._entity_count_ref,
            cx=float(params["cx"]),
            cy=float(params["cy"]),
            species=int(self._resolve_constant(engine, params["species"])),
            sex=float(params["sex"]) if "sex" in params else None,
            life_exp=float(params["life_exp"]) if "life_exp" in params else None,
            device=engine.state.device,
        )
        return {
            "ok": entity_id != -1,
            "tool_name": "animal_born",
            "entity_id": entity_id,
            "map_dirty": entity_id != -1,
        }

    def _execute_assign_control_target(self, engine: Any, params: dict[str, Any]) -> dict[str, Any]:
        result = engine.player_control.claim_target(
            engine,
            controller_id=str(params.get("controller_id", "local_player")),
            target_kind=str(params.get("target_kind", "human")),
            target_id=str(params["target_id"]) if params.get("target_id") else None,
            target_name=str(params["target_name"]) if params.get("target_name") else None,
            mode=str(params.get("mode", "possess")),
        )
        result["tool_name"] = "tool_assign_control_target"
        result["frame_dirty"] = bool(result.get("ok"))
        return result

    def _execute_release_control_target(self, engine: Any, params: dict[str, Any]) -> dict[str, Any]:
        result = engine.player_control.release_target(
            engine,
            controller_id=str(params["controller_id"]) if params.get("controller_id") else None,
            target_kind=str(params["target_kind"]) if params.get("target_kind") else None,
            target_id=str(params["target_id"]) if params.get("target_id") else None,
        )
        result["tool_name"] = "tool_release_control_target"
        result["frame_dirty"] = bool(result.get("ok"))
        return result

    def _execute_set_control_target_mode(self, engine: Any, params: dict[str, Any]) -> dict[str, Any]:
        result = engine.player_control.set_mode(
            engine,
            controller_id=str(params["controller_id"]),
            mode=str(params["mode"]),
        )
        result["tool_name"] = "tool_set_control_target_mode"
        result["frame_dirty"] = bool(result.get("ok"))
        return result

    def _execute_assign_player_control(self, engine: Any, params: dict[str, Any]) -> dict[str, Any]:
        result = self._execute_assign_control_target(
            engine,
            {
                "controller_id": params.get("controller_id", "local_player"),
                "target_kind": "human",
                "target_id": params.get("human_id"),
                "target_name": params.get("human_name"),
                "mode": params.get("mode", "possess"),
            },
        )
        result["tool_name"] = "tool_assign_player_control"
        return result

    def _execute_release_player_control(self, engine: Any, params: dict[str, Any]) -> dict[str, Any]:
        result = self._execute_release_control_target(
            engine,
            {
                "controller_id": params.get("controller_id"),
                "target_kind": "human",
                "target_id": params.get("human_id"),
            },
        )
        result["tool_name"] = "tool_release_player_control"
        return result

    def _execute_set_control_mode(self, engine: Any, params: dict[str, Any]) -> dict[str, Any]:
        result = self._execute_set_control_target_mode(engine, params)
        result["tool_name"] = "tool_set_control_mode"
        return result

    def _execute_action(self, engine: Any, action: dict[str, Any]) -> dict[str, Any]:
        tool_name = action["tool_name"]
        params = self._resolve_parameters(engine, dict(action.get("parameters") or {}))
        if tool_name == "set_attr":
            return self._execute_set_attr(engine, params)
        if tool_name == "instinct_born":
            return self._execute_spawn_human(engine, params)
        if tool_name == "entity_born":
            return self._execute_spawn_entity(engine, params)
        if tool_name == "animal_born":
            return self._execute_spawn_animal(engine, params)
        if tool_name == "tool_assign_control_target":
            return self._execute_assign_control_target(engine, params)
        if tool_name == "tool_release_control_target":
            return self._execute_release_control_target(engine, params)
        if tool_name == "tool_set_control_target_mode":
            return self._execute_set_control_target_mode(engine, params)
        if tool_name == "tool_assign_player_control":
            return self._execute_assign_player_control(engine, params)
        if tool_name == "tool_release_player_control":
            return self._execute_release_player_control(engine, params)
        if tool_name == "tool_set_control_mode":
            return self._execute_set_control_mode(engine, params)
        if tool_name in {"propose_new_instinct", "propose_new_tool"}:
            return {"ok": True, "tool_name": tool_name, "proposed_only": True, "frame_dirty": False}

        fn = getattr(iat, tool_name, None)
        if fn is None:
            raise ValueError(f"Unknown runtime tool: {tool_name}")

        h_mask = _live_human_mask(engine.state.h_tensor)
        a_mask = _animal_mask(engine.state.m_tensor)
        ctx = {"h_mask": h_mask, "a_mask": a_mask}
        result = fn(ctx, **{**engine._build_kwargs(), **params})
        payload = {"ok": True, "tool_name": tool_name}
        if isinstance(result, dict):
            payload.update(result)
        return payload

    def execute_packet(
        self,
        engine: Any,
        packet: dict[str, Any],
        *,
        decree_id: int | None = None,
        decree_text: str = "",
    ) -> dict[str, Any]:
        validation = self.validate_packet(packet, reserve_instinct_bits=True)
        preview_packet = {
            "map_actions": list(packet.get("map_actions") or []) if isinstance(packet, dict) else [],
            "human_actions": list(packet.get("human_actions") or []) if isinstance(packet, dict) else [],
            "new_entities": list(packet.get("new_entities") or []) if isinstance(packet, dict) else [],
            "new_instincts": list(packet.get("new_instincts") or []) if isinstance(packet, dict) else [],
        }
        if not validation["ok"]:
            outcome = {
                "ok": False,
                "frame_dirty": False,
                "map_dirty": False,
                "results": [],
                "errors": validation["errors"],
                "warnings": validation["warnings"],
                "proposals": {
                    "new_entities": list(packet.get("new_entities", [])),
                    "new_instincts": list(packet.get("new_instincts", [])),
                    "instinct_assignments": validation.get("instinct_assignments", []),
                    "follow_ups": self._build_follow_up_plan(
                        engine,
                        preview_packet,
                        validation.get("instinct_assignments", []),
                        execution_ready=False,
                        stage="validation_failed",
                    ),
                },
            }
            self.last_error = {
                "tick": engine.tick,
                "decree_id": decree_id,
                "errors": validation["errors"],
            }
            self.history.append(
                {
                    "tick": engine.tick,
                    "decree_id": decree_id,
                    "decree": decree_text,
                    "status": "validation_error",
                    "errors": validation["errors"],
                }
            )
            self.history = self.history[-30:]
            return outcome

        normalized_packet = validation["packet"]
        self._commit_instinct_assignments(validation.get("instinct_assignments", []))
        results: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        frame_dirty = False
        map_dirty = False

        for action_group in ("map_actions", "human_actions"):
            for index, action in enumerate(normalized_packet[action_group]):
                try:
                    result = self._execute_action(engine, action)
                except Exception as exc:
                    errors.append(
                        {
                            "group": action_group,
                            "index": index,
                            "tool_name": action["tool_name"],
                            "reason": "execution_error",
                            "message": str(exc),
                        }
                    )
                    break
                results.append(result)
                frame_dirty = frame_dirty or result.get("frame_dirty", True)
                map_dirty = map_dirty or bool(result.get("map_dirty", False))
            if errors:
                break

        outcome = {
            "ok": len(errors) == 0,
            "frame_dirty": frame_dirty,
            "map_dirty": map_dirty,
            "results": results,
            "errors": errors,
            "warnings": validation["warnings"],
            "proposals": {
                "new_entities": normalized_packet.get("new_entities", []),
                "new_instincts": normalized_packet.get("new_instincts", []),
                "instinct_assignments": validation.get("instinct_assignments", []),
                "follow_ups": self._build_follow_up_plan(
                    engine,
                    normalized_packet,
                    validation.get("instinct_assignments", []),
                    execution_ready=len(errors) == 0,
                    stage="post_execution",
                ),
            },
        }
        if errors:
            self.last_error = {
                "tick": engine.tick,
                "decree_id": decree_id,
                "errors": errors,
            }
        self.history.append(
            {
                "tick": engine.tick,
                "decree_id": decree_id,
                "decree": decree_text,
                "status": "ok" if outcome["ok"] else "execution_error",
                "results": results,
                "errors": errors,
                "warnings": validation["warnings"],
                "instinct_assignments": validation.get("instinct_assignments", []),
                "follow_ups": outcome["proposals"]["follow_ups"],
            }
        )
        self.history = self.history[-30:]
        return outcome

