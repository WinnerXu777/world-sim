"""Save/Continue guard for authored maps: a save records which map files it was made with; Continue refuses a changed map.

The manifest (map_id, revision, sha256, origin of every placed map) lives in ``inventory_state["map_manifest"]``, schema-free
like the other roster-world records, so ENGINE_FIELDS is unchanged and old saves simply have no manifest. Policy
(1006_map_wire_contract.md section 6): in the gameplay profile Continue is refused with an error naming the old and the new
revision and sha256. Development profiles, or ``EDEN_ALLOW_MAP_MISMATCH=1``, load the save anyway (a notice is printed) and
the next save records the maps actually in use.
"""
from __future__ import annotations

import os

MANIFEST_KEY = "map_manifest"
OVERRIDE_ENV = "EDEN_ALLOW_MAP_MISMATCH"


class MapMismatchError(ValueError):
    """A save was made with a different map file than the one registered now."""


def current_manifest(map_name):
    """[{map_id, revision, sha256, origin}] for the authored maps placed in the world of ``map_name`` (primary first), or None."""
    from systems.movement.map_contract import placed_group
    group = placed_group(map_name)
    if not group or any(e.get("info") is None for e in group):
        return None
    # sha256 is None for a map registered from a parsed object instead of a file (tests): then only revision and origin compare
    return [{"map_id": e["info"]["map_id"], "revision": int(e["info"]["revision"]), "sha256": e["info"].get("sha256"),
             "origin": [float(e["info"]["origin"][0]), float(e["info"]["origin"][1])]} for e in group]


def record(engine):
    """Remember, inside the world state, which map files this world runs on (called at every capture)."""
    manifest = current_manifest(getattr(engine, "_map_name", None))
    if manifest is None:
        engine.inventory_state.pop(MANIFEST_KEY, None)
    else:
        engine.inventory_state[MANIFEST_KEY] = manifest
    return manifest


def enforced(environ=None):
    """True when Continue must refuse a changed map (gameplay profile and no ``EDEN_ALLOW_MAP_MISMATCH``)."""
    environ = os.environ if environ is None else environ
    return environ.get("EDEN_PROFILE", "gameplay") == "gameplay" and environ.get(OVERRIDE_ENV, "") != "1"


def _short(sha):
    return str(sha)[:12]


def mismatches(saved, current):
    """Human-readable differences between a saved manifest and the registered maps (empty list = same maps)."""
    found = []
    registered = {item["map_id"]: item for item in (current or [])}
    for old in saved:
        new = registered.get(old.get("map_id"))
        name = old.get("map_id")
        if new is None:
            found.append(f"map {name!r} (revision {old.get('revision')}, sha256 {old.get('sha256')}) is not registered now")
            continue
        if new["revision"] != old.get("revision"):
            found.append(f"map {name!r} was revised after this save: saved revision {old.get('revision')} "
                         f"(sha256 {old.get('sha256')}), registered revision {new['revision']} (sha256 {new['sha256']})")
        elif new["sha256"] and old.get("sha256") and new["sha256"] != old["sha256"]:
            found.append(f"map {name!r} changed without a revision bump: both revision {new['revision']}, saved sha256 "
                         f"{old.get('sha256')}, registered sha256 {new['sha256']}")
        elif [float(v) for v in new["origin"]] != [float(v) for v in old.get("origin", new["origin"])]:
            found.append(f"map {name!r} is placed elsewhere: saved origin {old.get('origin')}, registered origin {new['origin']}")
    for name in registered.keys() - {old.get("map_id") for old in saved}:
        found.append(f"map {name!r} is registered now but was not part of this world")
    return found


def check(payload, environ=None):
    """Raise MapMismatchError when the save's maps differ from the registered ones (gameplay profile). Returns the
    list of overridden differences (empty when everything matches or the save has no manifest)."""
    state = (payload.get("engine") or {}).get("inventory_state") or {}
    saved = state.get(MANIFEST_KEY)
    if not saved:  # legacy map, or a save from before manifests: nothing to compare
        return []
    found = mismatches(saved, current_manifest(payload["engine"].get("_map_name")))
    if not found:
        return []
    if not enforced(environ):
        print(f"[MapGuard] continuing with changed maps ({OVERRIDE_ENV} or a development profile): " + "; ".join(found))
        return found
    raise MapMismatchError(
        "This save was made with different map files than the ones registered now, so it cannot be continued: "
        + "; ".join(found)
        + f". Start a new world, or restore the map files the save was made with. (Development override: {OVERRIDE_ENV}=1.)")
