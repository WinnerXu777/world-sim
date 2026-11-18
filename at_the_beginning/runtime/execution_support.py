from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

EXECUTION_SCHEMA_VERSION = 1
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
REGISTRY_PATH = ROOT_DIR / "models" / "tools_and_instincts_registry.py"
EXECUTION_REQUIRED_TOP_KEYS = {"thought", "map_actions", "human_actions", "new_entities", "new_instincts"}
EXECUTION_REQUIRED_ENTITY_KEYS = {
    "type_id",
    "label",
    "description",
    "style_family",
    "diffusion_prompt",
    "diffusion_negative",
}
EXECUTION_REQUIRED_INSTINCT_KEYS = {"name", "description", "heritable", "mask"}
EXECUTION_ALLOWED_STYLE_FAMILIES = {
    "water_entities",
    "fire_entities",
    "nature_entities",
    "disaster_entities",
    "human_entities",
}
EXECUTION_INTERNAL_PARAMS = {
    "ctx",
    "h_tensor",
    "m_tensor",
    "pop_count_ref",
    "entity_count_ref",
    "device",
    "engine",
    "player_control_runtime",
}


def _frontier_frozen() -> bool:
    try:
        import genesis_config as cfg
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning import genesis_config as cfg
    return bool(getattr(cfg, "FREEZE_LEGACY_FRONTIER", True))


def load_registry_entries() -> dict[str, dict[str, Any]]:
    if not REGISTRY_PATH.exists():
        return {}
    spec = importlib.util.spec_from_file_location("eden_tools_registry", REGISTRY_PATH)
    if spec is None or spec.loader is None:
        return {}
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    entries: dict[str, dict[str, Any]] = {}
    for attr_name in ("TIER_A", "TIER_B", "TIER_C"):
        for entry in getattr(module, attr_name, []):
            name = entry.get("name")
            if isinstance(name, str) and name:
                if entry.get("legacy_frozen") and _frontier_frozen():
                    continue                    # D-005: frozen tools are not offered while FREEZE_LEGACY_FRONTIER is set
                entries[name] = dict(entry)
    return entries


def signature_param_names(signature: str | None) -> set[str]:
    if not signature or "(" not in signature or ")" not in signature:
        return set()
    body = signature[signature.find("(") + 1 : signature.rfind(")")]
    names: set[str] = set()
    for raw_token in body.split(","):
        token = raw_token.strip()
        if not token:
            continue
        token = token.lstrip("*")
        token = token.split("=", 1)[0].strip()
        token = token.split(":", 1)[0].strip()
        if token:
            names.add(token)
    return names


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    import time as _time
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    data = json.dumps(payload, indent=2)
    tmp.write_text(data, encoding="utf-8")
    for attempt in range(3):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            _time.sleep(0.05)
    try:
        path.write_text(data, encoding="utf-8")
    except PermissionError:
        pass
    try:
        tmp.unlink(missing_ok=True)
    except OSError:
        pass
