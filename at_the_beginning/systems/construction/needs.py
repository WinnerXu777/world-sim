from __future__ import annotations

"""Deterministic building-need evaluation scaffolding."""

from typing import Any

from .catalog import BASIC_BUILDING_KINDS, building_scope, construction_blueprint
from .schema import build_construction_need


def _need_summary(building_kind: str, scope: str) -> str:
    label = str(construction_blueprint(building_kind).get("label", building_kind.replace("_", " "))).strip()
    return f"{label} [{scope}]"


def _stable_need_id(prefix: str, identity: str, building_kind: str) -> str:
    normalized_prefix = str(prefix or "need").strip() or "need"
    normalized_identity = str(identity or "shared").strip() or "shared"
    normalized_building = str(building_kind or "").strip() or "building"
    return f"{normalized_prefix}_{normalized_identity}_{normalized_building}"


def evaluate_personal_building_needs(
    resident: dict[str, Any],
    *,
    tick: int,
    has_shelter: bool,
    owner_human_id: str,
) -> list[dict[str, Any]]:
    needs: list[dict[str, Any]] = []
    if not bool(has_shelter):
        needs.append(
            build_construction_need(
                _stable_need_id("personal", owner_human_id, "personal_shelter"),
                "personal_shelter",
                tick=tick,
                scope="personal",
                priority=0.84,
                source="survival",
                owner_human_id=owner_human_id,
                summary=_need_summary("personal_shelter", "personal"),
            )
        )
    return needs


def evaluate_occupation_building_needs(
    resident: dict[str, Any],
    *,
    tick: int,
    occupation_kind: str,
    has_farm_plot: bool = True,
    owner_human_id: str = "",
) -> list[dict[str, Any]]:
    occupation_kind = str(occupation_kind or "").strip()
    needs: list[dict[str, Any]] = []
    if occupation_kind == "farmer" and not bool(has_farm_plot):
        needs.append(
            build_construction_need(
                _stable_need_id("occupation", owner_human_id or occupation_kind, "farm_plot"),
                "farm_plot",
                tick=tick,
                scope="occupation",
                priority=0.62,
                source="occupation",
                owner_human_id=owner_human_id or None,
                summary=_need_summary("farm_plot", "occupation"),
            )
        )
    return needs


def evaluate_settlement_building_needs(
    *,
    tick: int,
    population: int,
    shelter_capacity: float,
    has_well: bool,
    has_market_anchor: bool,
    settlement_id: str = "",
) -> list[dict[str, Any]]:
    needs: list[dict[str, Any]] = []
    if int(population) > 0 and float(shelter_capacity) < float(population):
        needs.append(
            build_construction_need(
                _stable_need_id("settlement", settlement_id or "shared", "personal_shelter"),
                "personal_shelter",
                tick=tick,
                scope="settlement",
                priority=0.68,
                source="settlement",
                settlement_id=settlement_id or None,
                summary=_need_summary("personal_shelter", "settlement"),
            )
        )
    if int(population) >= 4 and not bool(has_well):
        needs.append(
            build_construction_need(
                _stable_need_id("settlement", settlement_id or "shared", "village_well"),
                "village_well",
                tick=tick,
                scope="settlement",
                priority=0.74,
                source="survival",
                settlement_id=settlement_id or None,
                summary=_need_summary("village_well", "settlement"),
            )
        )
    if int(population) >= 5 and not bool(has_market_anchor):
        needs.append(
            build_construction_need(
                _stable_need_id("settlement", settlement_id or "shared", "market_anchor"),
                "market_anchor",
                tick=tick,
                scope="settlement",
                priority=0.46,
                source="occupation",
                settlement_id=settlement_id or None,
                summary=_need_summary("market_anchor", "settlement"),
            )
        )
    return needs


def evaluate_plan_building_need(
    building_kind: str,
    *,
    tick: int,
    summary: str = "",
    owner_human_id: str | None = None,
    settlement_id: str | None = None,
    priority: float = 0.58,
) -> dict[str, Any] | None:
    needle = str(building_kind or "").strip()
    if needle not in BASIC_BUILDING_KINDS and not construction_blueprint(needle):
        return None
    return build_construction_need(
        _stable_need_id("plan", owner_human_id or settlement_id or needle, needle),
        needle,
        tick=tick,
        scope=building_scope(needle) or "strategic",
        priority=priority,
        source="planning",
        owner_human_id=owner_human_id,
        settlement_id=settlement_id,
        summary=str(summary or _need_summary(needle, building_scope(needle) or "strategic")),
    )


def rank_construction_needs(needs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        [dict(need) for need in list(needs) if isinstance(need, dict)],
        key=lambda record: (
            float(record.get("priority", 0.0)),
            int(record.get("created_tick", 0)),
        ),
        reverse=True,
    )


__all__ = [
    "evaluate_occupation_building_needs",
    "evaluate_personal_building_needs",
    "evaluate_plan_building_need",
    "evaluate_settlement_building_needs",
    "rank_construction_needs",
]
