"""Validate authored 2D map files.

    .venv/Scripts/python.exe tools/validate_map.py MAP.json [MORE.json ...] [--base-dir DIR] [--actor-radius R]

Prints errors and warnings; exits 1 if any error was found, 0 otherwise.
With several maps, portals between them are cross-checked. --base-dir is the
directory sprite references are relative to (enables the sprite-exists check).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))
from world_map import check_map_file, check_portal_targets  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("maps", nargs="+", type=Path)
    parser.add_argument("--base-dir", type=Path, default=None, help="directory sprite references are relative to")
    parser.add_argument("--actor-radius", type=float, default=None, help="override the spatial.py actor radius")
    args = parser.parse_args(argv)

    errors = 0
    loaded = []
    for path in args.maps:
        world_map, issues = check_map_file(path, args.base_dir, args.actor_radius)
        if world_map is not None:
            loaded.append(world_map)
        errors += _report(str(path), issues)
        if world_map is not None:
            print(f"{path}: map_id={world_map.map_id} revision={world_map.revision} size_tiles={list(world_map.size_tiles)} "
                  f"units_per_tile={world_map.units_per_tile} actor_radius={world_map.actor_radius} walls={len(world_map.walls)} anchors={len(world_map.anchors)} "
                  f"entities={len(world_map.entities)} portals={len(world_map.portals)}")
    if len(loaded) > 1:
        errors += _report("portals", check_portal_targets(loaded))
    print("FAILED" if errors else "OK", f"({errors} error(s))")
    return 1 if errors else 0


def _report(label, issues):
    for issue in issues:
        print(f"{label}: {issue}")
    return sum(1 for i in issues if i.severity == "error")


if __name__ == "__main__":
    sys.exit(main())
