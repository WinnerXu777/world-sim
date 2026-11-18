"""Load and validate an authored map file."""
from pathlib import Path

from .parse import loads_strict, parse_map
from .schema import Issue, MapValidationError
from .validate import validate_map


def check_map_file(path, base_dir=None, actor_radius=None):
    """Never raises on bad content. Returns (WorldMap | None, issues)."""
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        return None, [Issue("error", "$", f"cannot read {path}: {exc}")]
    return check_map_bytes(raw, base_dir, actor_radius)


def check_map_bytes(raw, base_dir=None, actor_radius=None):
    """Same as check_map_file for bytes already read (the exact bytes a server would hash and serve)."""
    try:
        text = bytes(raw).decode("utf-8")
    except UnicodeDecodeError as exc:
        return None, [Issue("error", "$", f"not valid UTF-8: {exc}")]
    try:
        data = loads_strict(text)
    except ValueError as exc:  # includes json.JSONDecodeError
        return None, [Issue("error", "$", f"invalid JSON: {exc}")]
    world_map, issues = parse_map(data)
    if world_map is not None and not any(i.severity == "error" for i in issues):
        issues = issues + validate_map(world_map, base_dir, actor_radius)
    return world_map, issues


def load_map_bytes(raw, base_dir=None, actor_radius=None):
    """Like load_map, for bytes. Raises MapValidationError on any error."""
    world_map, issues = check_map_bytes(raw, base_dir, actor_radius)
    if world_map is None or any(i.severity == "error" for i in issues):
        raise MapValidationError(issues)
    return world_map


def load_map(path, base_dir=None, actor_radius=None):
    """Return a WorldMap, or raise MapValidationError if there is any error.

    Warnings are available on ``WorldMap.warnings`` (parse-time warnings only).
    ``base_dir`` enables sprite-file existence checks.
    """
    world_map, issues = check_map_file(path, base_dir, actor_radius)
    if world_map is None or any(i.severity == "error" for i in issues):
        raise MapValidationError(issues)
    return world_map
