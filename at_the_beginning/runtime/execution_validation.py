from __future__ import annotations

import inspect
from typing import Any

import torch

try:
    import instincts_and_tools as iat
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import instincts_and_tools as iat

from .execution_support import (
    EXECUTION_ALLOWED_STYLE_FAMILIES,
    EXECUTION_INTERNAL_PARAMS,
    EXECUTION_REQUIRED_ENTITY_KEYS,
    EXECUTION_REQUIRED_INSTINCT_KEYS,
    EXECUTION_REQUIRED_TOP_KEYS,
    signature_param_names,
)


class ExecutionValidationMixin:
    def limits_snapshot(self) -> dict[str, Any]:
        return {
            "required_top_keys": sorted(EXECUTION_REQUIRED_TOP_KEYS),
            "required_new_entity_keys": sorted(EXECUTION_REQUIRED_ENTITY_KEYS),
            "required_new_instinct_keys": sorted(EXECUTION_REQUIRED_INSTINCT_KEYS),
            "dynamic_entity_type_id_min": 50,
            "instinct_bit_range": [0, 63],
            "history_limit": 30,
            "supported_mask_features": [
                "and/or boolean clauses",
                "max(column)",
                "second_max(column)",
                "name membership via H_NAME in [...]",
                "col19_bit(n)==1",
                "rank(COL,asc|desc)",
                "dist(x,y)",
                "dist_to(entity_mask)",
            ],
            "proposal_gates": {
                "new_instincts_trigger_codegen_after_execution": True,
                "new_entities_trigger_sprite_generation_after_execution": True,
                "registry_check_required": True,
            },
            "unsupported_mask_features": [
                "nested helper calls inside string DSL",
                "sample(...) inside legacy string DSL",
                "arbitrary arithmetic inside string masks",
            ],
        }

    def _next_available_instinct_bit(self) -> int:
        used = set(self._instinct_bits.values()) | {int(bit) for bit in iat.ACQUIRED_INSTINCTS.keys()}
        for bit in range(0, 64):
            if bit not in used:
                return bit
        raise ValueError("No free instinct bits remain in 0..63")

    def _ensure_instinct_bit(
        self,
        instinct_name: str,
        *,
        reserve: bool,
        allow_allocate: bool,
    ) -> tuple[int | None, dict[str, Any] | None]:
        instinct_name = str(instinct_name).strip()
        if not instinct_name:
            return None, None
        bit = self._instinct_bits.get(instinct_name)
        if bit is not None:
            return bit, {"name": instinct_name, "bit": bit, "status": "known"}
        if not allow_allocate:
            return None, None
        bit = self._next_available_instinct_bit()
        status = "reserved" if reserve else "preview"
        return bit, {"name": instinct_name, "bit": bit, "status": status}

    def _commit_instinct_assignments(self, assignments: list[dict[str, Any]]) -> None:
        changed = False
        for assignment in assignments:
            name = str(assignment.get("name", "")).strip()
            if not name:
                continue
            bit = int(assignment["bit"])
            if self._instinct_bits.get(name) == bit:
                continue
            self._instinct_bits[name] = bit
            changed = True
        if changed:
            self._save_state()

    def _runtime_param_spec(self, tool_name: str) -> dict[str, Any]:
        cached = self._runtime_param_cache.get(tool_name)
        if cached is not None:
            return cached

        if tool_name == "set_attr":
            spec = {
                "required": {"col", "value"},
                "accepted": {
                    "mask",
                    "entity_mask",
                    "human_ids",
                    "entity_ids",
                    "center",
                    "center_x",
                    "center_y",
                    "col",
                    "value",
                    "mode",
                },
                "accepts_extra": True,
            }
            self._runtime_param_cache[tool_name] = spec
            return spec

        if tool_name == "instinct_born":
            spec = {
                "required": set(),
                "accepted": {"x", "y", "sex", "life_exp", "age", "name", "preferred_name", "type_id", "spawn_points"},
                "accepts_extra": True,
            }
            self._runtime_param_cache[tool_name] = spec
            return spec

        if tool_name == "entity_born":
            spec = {
                "required": {"cx", "cy", "m_type"},
                "accepted": {"cx", "cy", "m_type", "hp", "scale", "register_geo", "col_vals"},
                "accepts_extra": True,
            }
            self._runtime_param_cache[tool_name] = spec
            return spec

        if tool_name == "animal_born":
            spec = {
                "required": {"cx", "cy", "species"},
                "accepted": {"cx", "cy", "species", "sex", "life_exp"},
                "accepts_extra": True,
            }
            self._runtime_param_cache[tool_name] = spec
            return spec

        if tool_name == "tool_assign_control_target":
            spec = {
                "required": set(),
                "accepted": {"controller_id", "target_kind", "target_id", "target_name", "mode"},
                "accepts_extra": False,
            }
            self._runtime_param_cache[tool_name] = spec
            return spec

        if tool_name == "tool_release_control_target":
            spec = {
                "required": set(),
                "accepted": {"controller_id", "target_kind", "target_id"},
                "accepts_extra": False,
            }
            self._runtime_param_cache[tool_name] = spec
            return spec

        if tool_name == "tool_set_control_target_mode":
            spec = {
                "required": {"controller_id", "mode"},
                "accepted": {"controller_id", "mode"},
                "accepts_extra": False,
            }
            self._runtime_param_cache[tool_name] = spec
            return spec

        if tool_name == "tool_assign_player_control":
            spec = {
                "required": set(),
                "accepted": {"controller_id", "human_id", "human_name", "mode"},
                "accepts_extra": False,
            }
            self._runtime_param_cache[tool_name] = spec
            return spec

        if tool_name == "tool_release_player_control":
            spec = {
                "required": set(),
                "accepted": {"controller_id", "human_id"},
                "accepts_extra": False,
            }
            self._runtime_param_cache[tool_name] = spec
            return spec

        if tool_name == "tool_set_control_mode":
            spec = {
                "required": {"controller_id", "mode"},
                "accepted": {"controller_id", "mode"},
                "accepts_extra": False,
            }
            self._runtime_param_cache[tool_name] = spec
            return spec

        fn = getattr(iat, tool_name, None)
        if fn is None:
            spec = {"required": set(), "accepted": set(), "accepts_extra": False}
            self._runtime_param_cache[tool_name] = spec
            return spec

        signature = inspect.signature(fn)
        required: set[str] = set()
        accepted: set[str] = set()
        accepts_extra = False
        for param_name, param in signature.parameters.items():
            if param_name in EXECUTION_INTERNAL_PARAMS:
                continue
            if param.kind is inspect.Parameter.VAR_KEYWORD:
                accepts_extra = True
                continue
            if param.kind is inspect.Parameter.VAR_POSITIONAL:
                continue
            accepted.add(param_name)
            if param.default is inspect._empty:
                required.add(param_name)
        spec = {"required": required, "accepted": accepted, "accepts_extra": accepts_extra}
        self._runtime_param_cache[tool_name] = spec
        return spec

    def _parse_action(
        self,
        action_group: str,
        index: int,
        action: Any,
        packet_instinct_names: set[str],
        reserve_instinct_bits: bool,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        assignments: list[dict[str, Any]] = []

        if not isinstance(action, dict):
            errors.append({"group": action_group, "index": index, "reason": "action_not_object"})
            return None, errors, warnings, assignments

        tool_name = str(action.get("tool_name", "")).strip()
        if not tool_name:
            errors.append({"group": action_group, "index": index, "reason": "missing_tool_name"})
            return None, errors, warnings, assignments

        if tool_name not in self.registry_entries:
            errors.append(
                {
                    "group": action_group,
                    "index": index,
                    "tool_name": tool_name,
                    "reason": "tool_not_in_registry",
                }
            )
            return None, errors, warnings, assignments

        if tool_name not in {
            "set_attr",
            "instinct_born",
            "entity_born",
            "animal_born",
            "tool_assign_control_target",
            "tool_release_control_target",
            "tool_set_control_target_mode",
            "tool_assign_player_control",
            "tool_release_player_control",
            "tool_set_control_mode",
        } and not hasattr(iat, tool_name):
            errors.append(
                {
                    "group": action_group,
                    "index": index,
                    "tool_name": tool_name,
                    "reason": "tool_not_implemented",
                }
            )
            return None, errors, warnings, assignments

        params = action.get("parameters", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            errors.append(
                {
                    "group": action_group,
                    "index": index,
                    "tool_name": tool_name,
                    "reason": "parameters_not_object",
                }
            )
            return None, errors, warnings, assignments

        normalized_params = dict(params)
        if tool_name in {"tool_grant_instinct", "tool_revoke_instinct", "tool_enlighten"}:
            instinct_name = str(normalized_params.get("instinct_name", "")).strip()
            if "bit" not in normalized_params and instinct_name:
                bit, assignment = self._ensure_instinct_bit(
                    instinct_name,
                    reserve=reserve_instinct_bits,
                    allow_allocate=tool_name != "tool_revoke_instinct" and instinct_name in packet_instinct_names,
                )
                if bit is None:
                    errors.append(
                        {
                            "group": action_group,
                            "index": index,
                            "tool_name": tool_name,
                            "reason": "unknown_instinct_bit",
                            "instinct_name": instinct_name,
                        }
                    )
                    return None, errors, warnings, assignments
                normalized_params["bit"] = bit
                if assignment is not None:
                    assignments.append(assignment)

        if tool_name == "instinct_born" and "preferred_name" not in normalized_params and "name" in normalized_params:
            normalized_params["preferred_name"] = normalized_params["name"]

        runtime_spec = self._runtime_param_spec(tool_name)
        registry_params = signature_param_names(self.registry_entries[tool_name].get("signature"))
        missing = sorted(k for k in runtime_spec["required"] if k not in normalized_params)
        if tool_name == "instinct_born":
            has_pair = "x" in normalized_params and "y" in normalized_params
            has_points = "spawn_points" in normalized_params
            if not has_pair and not has_points:
                missing.extend(["x/y_or_spawn_points"])
        if tool_name == "tool_assign_control_target" and not (
            normalized_params.get("target_id") or normalized_params.get("target_name")
        ):
            missing.extend(["target_id_or_target_name"])
        if tool_name == "tool_release_control_target" and not (
            normalized_params.get("controller_id") or normalized_params.get("target_id")
        ):
            missing.extend(["controller_id_or_target_id"])
        if tool_name == "tool_assign_player_control" and not (
            normalized_params.get("human_id") or normalized_params.get("human_name")
        ):
            missing.extend(["human_id_or_human_name"])
        if tool_name == "tool_release_player_control" and not (
            normalized_params.get("controller_id") or normalized_params.get("human_id")
        ):
            missing.extend(["controller_id_or_human_id"])
        if missing:
            errors.append(
                {
                    "group": action_group,
                    "index": index,
                    "tool_name": tool_name,
                    "reason": "missing_required_parameters",
                    "missing": missing,
                }
            )
            return None, errors, warnings, assignments

        unknown = sorted(
            key
            for key in normalized_params.keys()
            if key not in (runtime_spec["accepted"] | registry_params)
        )
        if unknown and not runtime_spec["accepts_extra"]:
            warnings.append(
                {
                    "group": action_group,
                    "index": index,
                    "tool_name": tool_name,
                    "reason": "unknown_parameters_ignored",
                    "parameters": unknown,
                }
            )

        return {"tool_name": tool_name, "parameters": normalized_params}, errors, warnings, assignments

    def validate_packet(
        self,
        packet: Any,
        *,
        reserve_instinct_bits: bool = False,
    ) -> dict[str, Any]:
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        instinct_assignments: list[dict[str, Any]] = []

        if not isinstance(packet, dict):
            return {"ok": False, "errors": [{"reason": "packet_not_object"}], "warnings": []}

        missing_top = sorted(EXECUTION_REQUIRED_TOP_KEYS - set(packet.keys()))
        if missing_top:
            return {
                "ok": False,
                "errors": [{"reason": "missing_top_level_keys", "missing": missing_top}],
                "warnings": [],
            }

        normalized_packet = {
            "thought": str(packet.get("thought", "")),
            "map_actions": [],
            "human_actions": [],
            "new_entities": list(packet.get("new_entities") or []),
            "new_instincts": list(packet.get("new_instincts") or []),
        }

        for field in ("map_actions", "human_actions", "new_entities", "new_instincts"):
            if not isinstance(packet.get(field), list):
                errors.append({"reason": "field_not_list", "field": field})

        packet_instinct_names: set[str] = set()
        if not errors:
            for index, entity in enumerate(normalized_packet["new_entities"]):
                if not isinstance(entity, dict):
                    errors.append({"reason": "new_entity_not_object", "index": index})
                    continue
                missing_entity = sorted(EXECUTION_REQUIRED_ENTITY_KEYS - set(entity.keys()))
                if missing_entity:
                    errors.append({"reason": "new_entity_missing_keys", "index": index, "missing": missing_entity})
                    continue
                if int(entity["type_id"]) < 50:
                    errors.append(
                        {
                            "reason": "new_entity_type_id_reserved",
                            "index": index,
                            "type_id": int(entity["type_id"]),
                        }
                    )
                if entity["style_family"] not in EXECUTION_ALLOWED_STYLE_FAMILIES:
                    errors.append(
                        {
                            "reason": "invalid_style_family",
                            "index": index,
                            "style_family": entity["style_family"],
                        }
                    )

            for index, instinct in enumerate(normalized_packet["new_instincts"]):
                if not isinstance(instinct, dict):
                    errors.append({"reason": "new_instinct_not_object", "index": index})
                    continue
                missing_instinct = sorted(EXECUTION_REQUIRED_INSTINCT_KEYS - set(instinct.keys()))
                if missing_instinct:
                    errors.append(
                        {"reason": "new_instinct_missing_keys", "index": index, "missing": missing_instinct}
                    )
                    continue
                name = str(instinct["name"]).strip()
                if not name.startswith("instinct_"):
                    errors.append({"reason": "new_instinct_invalid_name", "index": index, "name": name})
                    continue
                if name in packet_instinct_names:
                    errors.append({"reason": "duplicate_new_instinct_name", "name": name})
                    continue
                packet_instinct_names.add(name)
                bit, assignment = self._ensure_instinct_bit(
                    name,
                    reserve=reserve_instinct_bits,
                    allow_allocate=True,
                )
                if bit is not None and assignment is not None:
                    instinct_assignments.append(assignment)

        if errors:
            return {"ok": False, "errors": errors, "warnings": warnings}

        has_propose_instinct = False
        for action_group in ("map_actions", "human_actions"):
            for index, action in enumerate(packet[action_group]):
                parsed, action_errors, action_warnings, action_assignments = self._parse_action(
                    action_group,
                    index,
                    action,
                    packet_instinct_names,
                    reserve_instinct_bits,
                )
                errors.extend(action_errors)
                warnings.extend(action_warnings)
                instinct_assignments.extend(action_assignments)
                if parsed is None:
                    continue
                normalized_packet[action_group].append(parsed)
                if parsed["tool_name"] == "propose_new_instinct":
                    has_propose_instinct = True

        if has_propose_instinct and not normalized_packet["new_instincts"]:
            errors.append({"reason": "propose_new_instinct_requires_new_instincts"})

        deduped_assignments: list[dict[str, Any]] = []
        seen_assignments: set[tuple[str, int]] = set()
        for assignment in instinct_assignments:
            key = (assignment["name"], int(assignment["bit"]))
            if key in seen_assignments:
                continue
            seen_assignments.add(key)
            deduped_assignments.append(assignment)

        return {
            "ok": len(errors) == 0,
            "packet": normalized_packet if not errors else None,
            "errors": errors,
            "warnings": warnings,
            "instinct_assignments": deduped_assignments,
        }

