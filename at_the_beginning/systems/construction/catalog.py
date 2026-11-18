from __future__ import annotations

"""Declarative construction blueprints and categories."""

from typing import Any, Final

try:
    from genesis_config import M_FARM, M_HOUSE, M_STORAGE_CASE, M_VILLAGE, M_WALL, M_WELL
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import M_FARM, M_HOUSE, M_STORAGE_CASE, M_VILLAGE, M_WALL, M_WELL


def _blueprint(
    label: str,
    *,
    category: str,
    scope: str,
    structure_type: int,
    material_requirements: tuple[tuple[str, int], ...],
    producer_hints: tuple[str, ...],
    place_tags: tuple[str, ...],
    auto_emit: bool,
    notes: str = "",
    supported: bool = True,
) -> dict[str, Any]:
    return {
        "label": str(label),
        "category": str(category),
        "scope": str(scope),
        "structure_type": int(structure_type),
        "material_requirements": tuple((str(item_kind), max(int(quantity), 1)) for item_kind, quantity in material_requirements),
        "producer_hints": tuple(str(hint) for hint in producer_hints),
        "place_tags": tuple(str(tag) for tag in place_tags),
        "auto_emit": bool(auto_emit),
        "notes": str(notes or ""),
        "supported": bool(supported),
    }


CONSTRUCTION_CATEGORY_DEFS: Final[dict[str, dict[str, Any]]] = {
    "basic_required": {
        "label": "Basic Required",
        "description": "Deterministic buildings emitted by survival, occupation, or settlement need.",
    },
    "optional_strategic": {
        "label": "Optional Strategic",
        "description": "Structures created by planning or higher-level strategic intent.",
    },
}


BUILDING_BLUEPRINT_DEFS: Final[dict[str, dict[str, Any]]] = {
    "personal_shelter": _blueprint(
        "Personal Shelter",
        category="basic_required",
        scope="personal",
        structure_type=M_HOUSE,
        material_requirements=(("wood_bundle", 6), ("fiber_bundle", 3), ("plank_bundle", 2)),
        producer_hints=("survival", "household"),
        place_tags=("home", "settlement"),
        auto_emit=True,
        notes="Default first shelter when a resident or household lacks safe shelter.",
    ),
    "household_storage": _blueprint(
        "Household Storage",
        category="basic_required",
        scope="household",
        structure_type=M_STORAGE_CASE,
        material_requirements=(("wood_bundle", 3), ("plank_bundle", 1), ("rope", 1)),
        producer_hints=("occupation", "inventory"),
        place_tags=("home", "settlement"),
        auto_emit=True,
        notes="Simple nearby storage when work outputs have nowhere to go.",
    ),
    "farm_plot": _blueprint(
        "Farm Plot",
        category="basic_required",
        scope="occupation",
        structure_type=M_FARM,
        material_requirements=(("wood_bundle", 4), ("fiber_bundle", 2)),
        producer_hints=("occupation",),
        place_tags=("farm", "settlement"),
        auto_emit=True,
        notes="Baseline worksite support for farmers and food production.",
    ),
    "village_well": _blueprint(
        "Village Well",
        category="basic_required",
        scope="settlement",
        structure_type=M_WELL,
        material_requirements=(("stone_chunk", 6), ("wood_bundle", 2), ("rope", 1)),
        producer_hints=("survival", "settlement"),
        place_tags=("settlement", "water"),
        auto_emit=True,
        notes="Shared water support for larger local populations.",
    ),
    "market_anchor": _blueprint(
        "Market Anchor",
        category="basic_required",
        scope="settlement",
        structure_type=M_VILLAGE,
        material_requirements=(("wood_bundle", 8), ("plank_bundle", 3), ("rope", 2)),
        producer_hints=("occupation", "settlement"),
        place_tags=("market", "settlement"),
        auto_emit=True,
        notes="Current placeholder market/shop anchor until dedicated market structures exist.",
    ),
    "wall_segment": _blueprint(
        "Wall Segment",
        category="optional_strategic",
        scope="strategic",
        structure_type=M_WALL,
        material_requirements=(("stone_chunk", 8), ("wood_bundle", 4)),
        producer_hints=("planning", "strategic"),
        place_tags=("gate", "settlement"),
        auto_emit=False,
        notes="Defensive structure used for fortification and protection plans.",
    ),
}


BASIC_BUILDING_KINDS: Final[tuple[str, ...]] = tuple(
    kind for kind, blueprint in BUILDING_BLUEPRINT_DEFS.items() if str(blueprint.get("category", "")) == "basic_required"
)
OPTIONAL_BUILDING_KINDS: Final[tuple[str, ...]] = tuple(
    kind for kind, blueprint in BUILDING_BLUEPRINT_DEFS.items() if str(blueprint.get("category", "")) == "optional_strategic"
)


def construction_blueprint(building_kind: str) -> dict[str, Any]:
    return dict(BUILDING_BLUEPRINT_DEFS.get(str(building_kind or "").strip(), {}))


def building_material_requirements(building_kind: str) -> tuple[tuple[str, int], ...]:
    return tuple(construction_blueprint(building_kind).get("material_requirements", ()))


def building_scope(building_kind: str) -> str:
    return str(construction_blueprint(building_kind).get("scope", "")).strip()


def building_place_tags(building_kind: str) -> tuple[str, ...]:
    return tuple(construction_blueprint(building_kind).get("place_tags", ()))


__all__ = [
    "BASIC_BUILDING_KINDS",
    "BUILDING_BLUEPRINT_DEFS",
    "CONSTRUCTION_CATEGORY_DEFS",
    "OPTIONAL_BUILDING_KINDS",
    "building_material_requirements",
    "building_place_tags",
    "building_scope",
    "construction_blueprint",
]
