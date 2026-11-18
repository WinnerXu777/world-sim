from __future__ import annotations

import random
import re
from typing import Any

import torch

try:
    import genesis_config as cfg
    import instincts_and_tools as iat
    import map_geo
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning import genesis_config as cfg
    from at_the_beginning import instincts_and_tools as iat
    from at_the_beginning import map_geo

from .common import animal_mask as _animal_mask
from .common import clamp as _clamp
from .common import live_human_mask as _live_human_mask
from .common import window_mode


class ExecutionSelectorMixin:
    def _entity_centroid_for_mask(self, engine: Any, entity_mask: torch.Tensor) -> tuple[float, float]:
        if not entity_mask.any():
            return cfg.MAP_WIDTH / 2.0, cfg.MAP_HEIGHT / 2.0
        cx = float(engine.state.m_tensor[entity_mask, cfg.CX].float().mean().item())
        cy = float(engine.state.m_tensor[entity_mask, cfg.CY].float().mean().item())
        return cx, cy

    def _biome_type_ids(self, biome: str) -> set[int]:
        lookup = {
            "forest": {cfg.M_FOREST},
            "grass": {cfg.M_GRASS},
            "lake": {cfg.M_LAKE},
            "sea": {cfg.M_SEA},
            "mountain": {cfg.M_MOUNTAIN},
            "beach": {cfg.M_BEACH},
            "house": {cfg.M_HOUSE},
            "village": {cfg.M_VILLAGE},
            "farm": {cfg.M_FARM},
            "well": {cfg.M_WELL},
            "wall": {cfg.M_WALL},
        }
        return lookup.get(str(biome).strip().lower(), set())

    def _compare_op_mask(self, left: torch.Tensor, op: str, right: float | torch.Tensor) -> torch.Tensor:
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        if op == ">=":
            return left >= right
        if op == "<=":
            return left <= right
        if op == ">":
            return left > right
        if op == "<":
            return left < right
        raise ValueError(f"Unsupported comparison op: {op}")

    @staticmethod
    def _aggregate_column_value(
        tensor: torch.Tensor,
        base_mask: torch.Tensor,
        col_idx: int,
        agg_name: str,
    ) -> torch.Tensor:
        active = tensor[base_mask, col_idx]
        if active.numel() == 0:
            return torch.tensor(0.0, device=tensor.device)
        agg_name = agg_name.strip().lower()
        if agg_name == "max":
            return active.max()
        if agg_name == "min":
            return active.min()
        if agg_name == "second_max":
            unique_vals = torch.unique(active)
            if unique_vals.numel() == 1:
                return unique_vals[0]
            return unique_vals.sort(descending=True).values[1]
        if agg_name == "second_min":
            unique_vals = torch.unique(active)
            if unique_vals.numel() == 1:
                return unique_vals[0]
            return unique_vals.sort(descending=False).values[1]
        raise ValueError(f"Unsupported aggregate selector: {agg_name}")

    def _sample_points_from_entity_mask(
        self,
        engine: Any,
        entity_mask: torch.Tensor,
        count: int,
    ) -> list[list[float]]:
        points: list[list[float]] = []
        live_entity_ids = torch.where(entity_mask)[0].tolist()
        tile_indices: list[int] = []
        for eid in live_entity_ids:
            geo = map_geo.MAP_GEO.get(int(eid))
            if geo is None:
                continue
            tile_indices.extend(map_geo.tiles_of(int(eid)))

        if tile_indices:
            for _ in range(max(count, 0)):
                tile_idx = random.choice(tile_indices)
                px, py = map_geo.tile_center_px(tile_idx)
                points.append([float(px), float(py)])
            return points

        for _ in range(max(count, 0)):
            if not live_entity_ids:
                break
            eid = random.choice(live_entity_ids)
            points.append(
                [
                    float(engine.state.m_tensor[eid, cfg.CX]),
                    float(engine.state.m_tensor[eid, cfg.CY]),
                ]
            )
        return points

    def _resolve_symbolic_value(self, engine: Any, value: str) -> Any:
        if hasattr(cfg, value):
            return getattr(cfg, value)

        for alias, type_ids in {
            key: self._biome_type_ids(key)
            for key in ("forest", "grass", "lake", "sea", "mountain", "beach")
        }.items():
            if value in {f"{alias}_cx", f"{alias}_cy"}:
                live_mask = engine.state.m_tensor[:, cfg.M_TYPE] > 0
                type_mask = torch.zeros_like(live_mask)
                for type_id in type_ids:
                    type_mask |= engine.state.m_tensor[:, cfg.M_TYPE] == float(type_id)
                cx, cy = self._entity_centroid_for_mask(engine, type_mask & live_mask)
                return cx if value.endswith("_cx") else cy

        centroid_match = re.fullmatch(r"centroid\((.+)\)", value.strip())
        if centroid_match:
            entity_mask = self._resolve_entity_selector(engine, centroid_match.group(1))
            cx, cy = self._entity_centroid_for_mask(engine, entity_mask)
            return [cx, cy]

        return value

    def _resolve_value_spec(self, engine: Any, spec: dict[str, Any]) -> Any:
        kind = str(spec.get("kind", "")).strip()
        if kind in {"const", "literal"}:
            return self._resolve_constant(engine, spec.get("value"))
        if kind == "cfg":
            name = str(spec.get("name", "")).strip()
            if not hasattr(cfg, name):
                raise ValueError(f"Unknown cfg constant: {name}")
            return getattr(cfg, name)
        if kind == "point":
            return [
                float(self._resolve_constant(engine, spec.get("x", 0.0))),
                float(self._resolve_constant(engine, spec.get("y", 0.0))),
            ]
        if kind == "centroid":
            selector = spec.get("selector")
            entity_mask = self._resolve_entity_selector(engine, selector)
            cx, cy = self._entity_centroid_for_mask(engine, entity_mask)
            return [cx, cy]
        if kind == "biome_center":
            biome = str(spec.get("biome", "")).strip().lower()
            selector = {
                "kind": "type_ids",
                "type_ids": list(self._biome_type_ids(biome)),
            }
            entity_mask = self._resolve_entity_selector(engine, selector)
            cx, cy = self._entity_centroid_for_mask(engine, entity_mask)
            axis = spec.get("axis")
            if axis == "x":
                return cx
            if axis == "y":
                return cy
            return [cx, cy]
        if kind == "sample_tiles":
            count = int(spec.get("count", 1))
            selector = spec.get("selector")
            biome = str(spec.get("biome", "")).strip().lower()
            if selector is None and biome:
                selector = {"kind": "type_ids", "type_ids": list(self._biome_type_ids(biome))}
            entity_mask = self._resolve_entity_selector(engine, selector)
            return self._sample_points_from_entity_mask(engine, entity_mask, count)
        return {
            key: self._resolve_constant(engine, value)
            for key, value in spec.items()
        }

    def _tool_exists(self, tool_name: str) -> bool:
        tool_name = str(tool_name).strip()
        if not tool_name:
            return False
        if tool_name in self.registry_entries:
            return True
        if tool_name in {"set_attr", "instinct_born", "entity_born", "animal_born"}:
            return True
        return callable(getattr(iat, tool_name, None))

    def _instinct_exists(self, instinct_name: str) -> bool:
        instinct_name = str(instinct_name).strip()
        if not instinct_name:
            return False
        if instinct_name in self._instinct_bits:
            return True
        if instinct_name in self.registry_entries:
            return True
        if callable(getattr(iat, instinct_name, None)):
            return True
        return any(getattr(fn, "__name__", "") == instinct_name for fn in iat.ACQUIRED_INSTINCTS.values())

    @staticmethod
    def _entity_type_registered(type_id: int) -> bool:
        return int(type_id) in cfg.MAP_SCHEMA

    def _sprite_status(self, engine: Any, type_id: int, style_family: str | None = None) -> dict[str, Any]:
        rag = None
        ensure_light_rag = getattr(engine, "ensure_light_rag", None)
        if callable(ensure_light_rag):
            rag = ensure_light_rag()
        if rag is not None and hasattr(rag, "get_sprite"):
            sprite_info = dict(rag.get_sprite(int(type_id)))
            if style_family and sprite_info.get("style_ref_sprite_id") is None and hasattr(rag, "get_style_reference"):
                sprite_info["style_ref_sprite_id"] = rag.get_style_reference(style_family)
            return sprite_info
        return {
            "exists": False,
            "sprite_id": None,
            "description": None,
            "style_family": style_family,
            "style_ref_sprite_id": None,
        }

    def _build_follow_up_plan(
        self,
        engine: Any,
        packet: dict[str, Any],
        instinct_assignments: list[dict[str, Any]],
        *,
        execution_ready: bool,
        stage: str,
    ) -> dict[str, Any]:
        assignment_by_name = {
            str(item.get("name", "")).strip(): dict(item)
            for item in instinct_assignments
            if str(item.get("name", "")).strip()
        }
        follow_ups = {
            "stage": stage,
            "execution_ready": execution_ready,
            "instinct_codegen": {
                "pending": [],
                "skipped_existing": [],
                "blocked_until_execution_ok": [],
            },
            "tool_codegen": {
                "pending": [],
                "skipped_existing": [],
                "blocked_until_execution_ok": [],
            },
            "entity_registration": {
                "pending": [],
                "skipped_existing": [],
                "blocked_until_execution_ok": [],
            },
            "sprite_generation": {
                "pending": [],
                "skipped_existing": [],
                "blocked_until_execution_ok": [],
            },
        }

        for instinct in list(packet.get("new_instincts") or []):
            name = str(instinct.get("name", "")).strip()
            assignment = assignment_by_name.get(name)
            enriched = dict(instinct)
            if assignment is not None:
                enriched["bit"] = int(assignment["bit"])
                enriched["bit_status"] = assignment.get("status")
            if self._instinct_exists(name):
                enriched["reason"] = "already_in_registry"
                follow_ups["instinct_codegen"]["skipped_existing"].append(enriched)
            elif execution_ready:
                enriched["reason"] = "ready_after_execution"
                follow_ups["instinct_codegen"]["pending"].append(enriched)
            else:
                enriched["reason"] = "wait_for_execution_success"
                follow_ups["instinct_codegen"]["blocked_until_execution_ok"].append(enriched)

        for action_group in ("map_actions", "human_actions"):
            for action in list(packet.get(action_group) or []):
                if action.get("tool_name") != "propose_new_tool":
                    continue
                params = action.get("parameters") or {}
                proposed_name = str(params.get("name", "")).strip()
                enriched = {
                    "group": action_group,
                    "name": proposed_name,
                    "description": params.get("description", ""),
                    "why_existing_tools_insufficient": params.get("why_existing_tools_insufficient", ""),
                }
                if self._tool_exists(proposed_name):
                    enriched["reason"] = "already_in_registry"
                    follow_ups["tool_codegen"]["skipped_existing"].append(enriched)
                elif execution_ready:
                    enriched["reason"] = "ready_after_execution"
                    follow_ups["tool_codegen"]["pending"].append(enriched)
                else:
                    enriched["reason"] = "wait_for_execution_success"
                    follow_ups["tool_codegen"]["blocked_until_execution_ok"].append(enriched)

        for entity in list(packet.get("new_entities") or []):
            type_id = int(entity.get("type_id", -1))
            enriched = dict(entity)
            enriched["type_id"] = type_id
            sprite_status = self._sprite_status(engine, type_id, str(entity.get("style_family", "")).strip() or None)
            enriched["sprite_exists"] = bool(sprite_status.get("exists"))
            enriched["sprite_id"] = sprite_status.get("sprite_id")
            if sprite_status.get("style_ref_sprite_id") is not None:
                enriched["style_ref_sprite_id"] = sprite_status.get("style_ref_sprite_id")

            if self._entity_type_registered(type_id):
                enriched["reason"] = "already_in_registry"
                follow_ups["entity_registration"]["skipped_existing"].append(dict(enriched))
            elif execution_ready:
                enriched["reason"] = "ready_after_execution"
                follow_ups["entity_registration"]["pending"].append(dict(enriched))
            else:
                enriched["reason"] = "wait_for_execution_success"
                follow_ups["entity_registration"]["blocked_until_execution_ok"].append(dict(enriched))

            if enriched["sprite_exists"]:
                enriched["reason"] = "sprite_already_exists"
                follow_ups["sprite_generation"]["skipped_existing"].append(dict(enriched))
            elif execution_ready:
                enriched["reason"] = "ready_after_execution"
                follow_ups["sprite_generation"]["pending"].append(dict(enriched))
            else:
                enriched["reason"] = "wait_for_execution_success"
                follow_ups["sprite_generation"]["blocked_until_execution_ok"].append(dict(enriched))

        return follow_ups

    def _resolve_constant(self, engine: Any, value: Any) -> Any:
        if isinstance(value, dict):
            if "kind" in value:
                return self._resolve_value_spec(engine, value)
            return {
                key: self._resolve_constant(engine, item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._resolve_constant(engine, item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._resolve_constant(engine, item) for item in value)
        if isinstance(value, str):
            return self._resolve_symbolic_value(engine, value)
        return value

    def _human_name_mask(self, engine: Any, names: list[str]) -> torch.Tensor:
        mask = torch.zeros(engine.state.h_tensor.shape[0], dtype=torch.bool, device=engine.state.h_tensor.device)
        wanted = {name.strip() for name in names if name.strip()}
        for slot, human_id in enumerate(engine._human_uid_by_slot):
            resident = engine.resident_store.get(human_id)
            if not resident:
                continue
            resident_name = str(resident.get("profile", {}).get("name", "")).strip()
            if resident_name in wanted:
                mask[slot] = True
        return mask

    def _evaluate_boolean_mask(self, engine: Any, expression: str, target: str) -> torch.Tensor:
        expr = expression.strip()
        if not expr:
            raise ValueError("Empty selector expression")

        if target == "human":
            base_mask = _live_human_mask(engine.state.h_tensor)
            tensor = engine.state.h_tensor
        else:
            base_mask = engine.state.m_tensor[:, cfg.M_TYPE] > 0
            tensor = engine.state.m_tensor

        clauses_or = re.split(r"\s+or\s+", expr)
        result = torch.zeros_like(base_mask)
        for clause_or in clauses_or:
            clause_and_mask = base_mask.clone()
            for clause in re.split(r"\s+and\s+", clause_or):
                sub = clause.strip().strip("()")
                if not sub:
                    continue

                name_match = re.fullmatch(r"H_NAME\s+in\s+\[(.*)\]", sub)
                if name_match and target == "human":
                    names = [item.strip().strip("'\"") for item in name_match.group(1).split(",")]
                    clause_and_mask &= self._human_name_mask(engine, names)
                    continue

                bit_match = re.fullmatch(r"col19_bit\((\d+)\)\s*==\s*1", sub)
                if bit_match and target == "human":
                    bit = int(bit_match.group(1))
                    mask = iat.instinct_bits.test_bit(tensor, bit)   # exact for bits 0..63 (G-D0-2)
                    clause_and_mask &= mask
                    continue

                rank_match = re.fullmatch(r"rank\((\w+),(asc|desc)\)\s*(<=|>=|==|<|>)\s*(\d+)", sub)
                if rank_match:
                    col_name, order, op, raw_limit = rank_match.groups()
                    col_idx = getattr(cfg, col_name)
                    active_idx = torch.where(base_mask)[0]
                    values = tensor[active_idx, col_idx]
                    descending = order == "desc"
                    sorted_idx = active_idx[values.argsort(descending=descending)]
                    ranks = torch.zeros_like(base_mask, dtype=torch.float32)
                    if sorted_idx.numel():
                        ranks[sorted_idx] = torch.arange(1, sorted_idx.numel() + 1, device=ranks.device)
                    limit = float(raw_limit)
                    if op == "<=":
                        clause_and_mask &= ranks <= limit
                    elif op == ">=":
                        clause_and_mask &= ranks >= limit
                    elif op == "==":
                        clause_and_mask &= ranks == limit
                    elif op == "<":
                        clause_and_mask &= ranks < limit
                    else:
                        clause_and_mask &= ranks > limit
                    continue

                dist_match = re.fullmatch(r"dist\(([-.\d]+)\s*,\s*([-.\d]+)\)\s*(<=|>=|==|<|>)\s*([-.\d]+)", sub)
                if dist_match:
                    tx, ty, op, raw_limit = dist_match.groups()
                    px = tensor[:, cfg.X] if target == "human" else tensor[:, cfg.CX]
                    py = tensor[:, cfg.Y] if target == "human" else tensor[:, cfg.CY]
                    dist = ((px - float(tx)) ** 2 + (py - float(ty)) ** 2).sqrt()
                    limit = float(raw_limit)
                    if op == "<=":
                        clause_and_mask &= dist <= limit
                    elif op == ">=":
                        clause_and_mask &= dist >= limit
                    elif op == "==":
                        clause_and_mask &= dist == limit
                    elif op == "<":
                        clause_and_mask &= dist < limit
                    else:
                        clause_and_mask &= dist > limit
                    continue

                dist_to_match = re.fullmatch(r"dist_to\((.+)\)\s*(<=|>=|==|<|>)\s*([-.\d]+)", sub)
                if dist_to_match and target == "human":
                    entity_expr, op, raw_limit = dist_to_match.groups()
                    entity_mask = self._resolve_entity_selector(engine, entity_expr)
                    if entity_mask.any():
                        entity_points = engine.state.m_tensor[entity_mask][:, [cfg.CX, cfg.CY]]
                        distances = torch.full_like(base_mask, float("inf"), dtype=torch.float32)
                        for slot in torch.where(base_mask)[0].tolist():
                            px = float(engine.state.h_tensor[slot, cfg.X])
                            py = float(engine.state.h_tensor[slot, cfg.Y])
                            d = torch.sqrt((entity_points[:, 0] - px) ** 2 + (entity_points[:, 1] - py) ** 2)
                            distances[slot] = float(d.min().item()) if d.numel() else float("inf")
                    else:
                        distances = torch.full_like(base_mask, float("inf"), dtype=torch.float32)
                    limit = float(raw_limit)
                    if op == "<=":
                        clause_and_mask &= distances <= limit
                    elif op == ">=":
                        clause_and_mask &= distances >= limit
                    elif op == "==":
                        clause_and_mask &= distances == limit
                    elif op == "<":
                        clause_and_mask &= distances < limit
                    else:
                        clause_and_mask &= distances > limit
                    continue

                comp_match = re.fullmatch(r"(\w+)\s*(==|!=|>=|<=|>|<)\s*(.+)", sub)
                if comp_match:
                    left_name, op, raw_right = comp_match.groups()
                    if not hasattr(cfg, left_name):
                        raise ValueError(f"Unknown selector column: {left_name}")
                    col_idx = getattr(cfg, left_name)
                    left = tensor[:, col_idx]
                    raw_right = raw_right.strip()
                    agg_match = re.fullmatch(r"(max|min|second_max|second_min)\((\w+)\)", raw_right)
                    if agg_match:
                        agg_name, right_name = agg_match.groups()
                        if not hasattr(cfg, right_name):
                            raise ValueError(f"Unknown selector max column: {right_name}")
                        right_idx = getattr(cfg, right_name)
                        right = self._aggregate_column_value(tensor, base_mask, right_idx, agg_name)
                    elif hasattr(cfg, raw_right):
                        right = float(getattr(cfg, raw_right))
                    else:
                        right = float(raw_right)
                    if op == "==":
                        clause_and_mask &= left == right
                    elif op == "!=":
                        clause_and_mask &= left != right
                    elif op == ">=":
                        clause_and_mask &= left >= right
                    elif op == "<=":
                        clause_and_mask &= left <= right
                    elif op == ">":
                        clause_and_mask &= left > right
                    else:
                        clause_and_mask &= left < right
                    continue

                raise ValueError(f"Unsupported selector clause: {sub}")

            result |= clause_and_mask
        return result & base_mask

    def _resolve_structured_selector(self, engine: Any, selector: dict[str, Any], target: str) -> torch.Tensor:
        kind = str(selector.get("kind", "")).strip()
        if target == "human":
            base_mask = _live_human_mask(engine.state.h_tensor)
            tensor = engine.state.h_tensor
            coord_x = cfg.X
            coord_y = cfg.Y
        else:
            base_mask = engine.state.m_tensor[:, cfg.M_TYPE] > 0
            tensor = engine.state.m_tensor
            coord_x = cfg.CX
            coord_y = cfg.CY

        if kind == "all":
            return base_mask
        if kind == "compare":
            col_name = str(selector.get("col", "")).strip()
            if not hasattr(cfg, col_name):
                raise ValueError(f"Unknown selector column: {col_name}")
            col_idx = getattr(cfg, col_name)
            op = str(selector.get("op", "==")).strip()
            value = selector.get("value")
            agg_match = re.fullmatch(r"(max|min|second_max|second_min)\((\w+)\)", str(value).strip())
            if agg_match:
                agg_name, right_name = agg_match.groups()
                if not hasattr(cfg, right_name):
                    raise ValueError(f"Unknown selector max column: {right_name}")
                right_idx = getattr(cfg, right_name)
                right = self._aggregate_column_value(tensor, base_mask, right_idx, agg_name)
            else:
                right = self._resolve_constant(engine, value)
            return self._compare_op_mask(tensor[:, col_idx], op, right) & base_mask
        if kind == "and":
            result = base_mask.clone()
            for term in selector.get("terms", []):
                result &= self._resolve_structured_selector(engine, term, target)
            return result
        if kind == "or":
            result = torch.zeros_like(base_mask)
            for term in selector.get("terms", []):
                result |= self._resolve_structured_selector(engine, term, target)
            return result & base_mask
        if kind == "not":
            term = selector.get("term")
            if not isinstance(term, dict):
                raise ValueError("not selector requires dict term")
            return (~self._resolve_structured_selector(engine, term, target)) & base_mask
        if kind == "name_in" and target == "human":
            return self._human_name_mask(engine, list(selector.get("names", []))) & base_mask
        if kind == "instinct_bit" and target == "human":
            bit = int(selector.get("bit", 0))
            expected = int(selector.get("value", 1))
            mask = iat.instinct_bits.test_bit(tensor, bit).long() == expected   # exact for bits 0..63 (G-D0-2)
            return mask & base_mask
        if kind == "rank":
            col_name = str(selector.get("col", "")).strip()
            if not hasattr(cfg, col_name):
                raise ValueError(f"Unknown selector rank column: {col_name}")
            col_idx = getattr(cfg, col_name)
            order = str(selector.get("order", "desc")).strip().lower()
            op = str(selector.get("op", "<=")).strip()
            limit = float(selector.get("value", 1))
            active_idx = torch.where(base_mask)[0]
            values = tensor[active_idx, col_idx]
            sorted_idx = active_idx[values.argsort(descending=(order == "desc"))]
            ranks = torch.zeros_like(base_mask, dtype=torch.float32)
            if sorted_idx.numel():
                ranks[sorted_idx] = torch.arange(1, sorted_idx.numel() + 1, device=ranks.device)
            return self._compare_op_mask(ranks, op, limit) & base_mask
        if kind == "dist":
            point = selector.get("point")
            if isinstance(point, dict):
                tx, ty = self._resolve_value_spec(engine, point)
            elif isinstance(point, (list, tuple)) and len(point) == 2:
                tx, ty = self._resolve_constant(engine, point[0]), self._resolve_constant(engine, point[1])
            else:
                tx = self._resolve_constant(engine, selector.get("x", 0.0))
                ty = self._resolve_constant(engine, selector.get("y", 0.0))
            dist = ((tensor[:, coord_x] - float(tx)) ** 2 + (tensor[:, coord_y] - float(ty)) ** 2).sqrt()
            return self._compare_op_mask(dist, str(selector.get("op", "<")).strip(), float(selector.get("value", 0.0))) & base_mask
        if kind == "dist_to" and target == "human":
            entity_selector = selector.get("selector")
            entity_mask = self._resolve_entity_selector(engine, entity_selector)
            distances = torch.full_like(base_mask, float("inf"), dtype=torch.float32)
            if entity_mask.any():
                entity_points = engine.state.m_tensor[entity_mask][:, [cfg.CX, cfg.CY]]
                for slot in torch.where(base_mask)[0].tolist():
                    px = float(engine.state.h_tensor[slot, cfg.X])
                    py = float(engine.state.h_tensor[slot, cfg.Y])
                    d = torch.sqrt((entity_points[:, 0] - px) ** 2 + (entity_points[:, 1] - py) ** 2)
                    distances[slot] = float(d.min().item()) if d.numel() else float("inf")
            return self._compare_op_mask(
                distances,
                str(selector.get("op", "<")).strip(),
                float(selector.get("value", 0.0)),
            ) & base_mask
        if kind == "type_ids" and target == "entity":
            result = torch.zeros_like(base_mask)
            for type_id in selector.get("type_ids", []):
                result |= tensor[:, cfg.M_TYPE] == float(int(self._resolve_constant(engine, type_id)))
            return result & base_mask
        if kind in {"human_ids", "human_slots", "entity_ids", "entity_slots", "radius"}:
            if target == "human":
                return self._resolve_human_selector(engine, selector)
            return self._resolve_entity_selector(engine, selector)
        raise ValueError(f"Unsupported structured selector kind: {kind}")

    def _resolve_human_selector(self, engine: Any, selector: Any) -> torch.Tensor:
        h_mask = _live_human_mask(engine.state.h_tensor)
        if selector is None:
            return h_mask
        if isinstance(selector, str):
            if selector == "all_humans":
                return h_mask
            if selector == "escalated_humans":
                return h_mask & (engine.state.h_tensor[:, cfg.ESCALATION_FLAG] > 0.0)
            return self._evaluate_boolean_mask(engine, selector, "human")
        if isinstance(selector, dict):
            if selector.get("kind") in {
                "all",
                "compare",
                "and",
                "or",
                "not",
                "name_in",
                "instinct_bit",
                "rank",
                "dist",
                "dist_to",
            }:
                return self._resolve_structured_selector(engine, selector, "human")
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
        if isinstance(selector, str):
            return self._evaluate_boolean_mask(engine, selector, "entity")
        if isinstance(selector, dict):
            if selector.get("kind") in {
                "all",
                "compare",
                "and",
                "or",
                "not",
                "rank",
                "dist",
                "type_ids",
            }:
                return self._resolve_structured_selector(engine, selector, "entity")
            kind = selector.get("kind")
            if kind == "type_ids":
                type_ids = {int(self._resolve_constant(engine, v)) for v in selector.get("type_ids", [])}
                result = torch.zeros_like(mask)
                for type_id in type_ids:
                    result |= m_tensor[:, cfg.M_TYPE] == float(type_id)
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
        resolved = {key: self._resolve_constant(engine, value) for key, value in params.items()}
        if "mask" in resolved:
            resolved["mask"] = self._resolve_human_selector(engine, resolved["mask"])
        if "human_ids" in resolved and "mask" not in resolved:
            resolved["mask"] = self._resolve_human_selector(
                engine,
                {"kind": "human_ids", "ids": resolved.pop("human_ids")},
            )
        if "entity_mask" in resolved:
            resolved["entity_mask"] = self._resolve_entity_selector(engine, resolved["entity_mask"])
        if "entity_ids" in resolved and "entity_mask" not in resolved:
            resolved["entity_mask"] = self._resolve_entity_selector(
                engine,
                {"kind": "entity_ids", "ids": resolved.pop("entity_ids")},
            )
        if "center" in resolved:
            center = resolved.pop("center")
            resolved.setdefault("center_x", float(center[0]))
            resolved.setdefault("center_y", float(center[1]))
            resolved.setdefault("cx", float(center[0]))
            resolved.setdefault("cy", float(center[1]))
        if "target_point" in resolved:
            target_point = resolved.pop("target_point")
            resolved.setdefault("target_x", float(target_point[0]))
            resolved.setdefault("target_y", float(target_point[1]))
        return resolved

