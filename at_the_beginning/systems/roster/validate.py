"""Validate a roster against the loaded maps (anchor ids, kinds, roles, sharing) and the movement contract."""
from .load import ANCHOR_KEYS, Issue

SHAREABLE_KINDS = ("spawn",)  # several residents may start at the same spawn anchor


def anchors_from_registry(map_name):
    """{anchor id: {"kind", "for_role", "position", "map_id"}} for every map placed in the world of ``map_name``."""
    from systems.movement.map_contract import placed_group
    out = {}
    for entry in placed_group(map_name):
        map_id = (entry.get("info") or {}).get("map_id", "")
        for anchor in entry["anchors"]:
            out[anchor["id"]] = {"kind": anchor["kind"], "for_role": anchor.get("for_role"), "position": tuple(anchor["position"]),
                                 "map_id": map_id}
    return out


def anchors_from_world_maps(world_maps):
    """Anchor table from parsed WorldMaps (offline validation); same shape as ``anchors_from_registry``."""
    out = {}
    for world_map in world_maps:
        for anchor in world_map.anchors:
            out[anchor.id] = {"kind": anchor.kind, "for_role": anchor.for_role, "position": tuple(anchor.position),
                              "map_id": world_map.map_id}
    return out


def validate_roster(roster, anchors, contract=None, map_ids=None):
    """Issues for a parsed Roster. ``anchors`` comes from the loaded maps; ``contract`` (optional) adds standability."""
    issues = []
    if map_ids is not None and roster.map_id not in map_ids:
        issues.append(Issue("error", "map_id", f"roster is for {roster.map_id!r}, loaded maps are {sorted(map_ids)}"))
    for kind in ("water", "food"):
        anchor_id = roster.needs[kind]["anchor"]
        if anchor_id is None:
            continue
        anchor = anchors.get(anchor_id)
        if anchor is None:
            issues.append(Issue("error", f"needs.{kind}.anchor", f"unknown anchor id {anchor_id!r}"))
        elif contract is not None:
            from systems.movement.spatial import is_standable_point
            if not is_standable_point(anchor["position"], contract):
                issues.append(Issue("error", f"needs.{kind}.anchor", f"anchor {anchor_id!r} is not standable under the map contract"))
    used = {}
    for index, resident in enumerate(roster.residents):
        for anchor_key, anchor_id in resident.anchors.items():
            path = f"residents[{index}].anchors.{anchor_key}"
            anchor = anchors.get(anchor_id)
            if anchor is None:
                issues.append(Issue("error", path, f"unknown anchor id {anchor_id!r}"))
                continue
            if anchor["kind"] not in ANCHOR_KEYS[anchor_key]:
                issues.append(Issue("error", path, f"anchor {anchor_id!r} has kind {anchor['kind']!r}; {anchor_key!r} needs {ANCHOR_KEYS[anchor_key]}"))
            if resident.role and anchor["for_role"] and anchor["for_role"] != resident.role and anchor_key != "spawn":
                issues.append(Issue("error", path, f"anchor {anchor_id!r} is for role {anchor['for_role']!r}, resident {resident.key!r} is {resident.role!r}"))
            if anchor["kind"] not in SHAREABLE_KINDS:
                if anchor_id in used and used[anchor_id] != resident.key:
                    issues.append(Issue("error", path, f"anchor {anchor_id!r} is also used by resident {used[anchor_id]!r}"))
                used.setdefault(anchor_id, resident.key)
            if contract is not None:
                from systems.movement.spatial import is_standable_point
                if not is_standable_point(anchor["position"], contract):
                    issues.append(Issue("error", path, f"anchor {anchor_id!r} is not standable under the map contract"))
        maps = {anchors[i]["map_id"] for i in resident.anchors.values() if i in anchors}
        spawn = anchors.get(resident.anchors.get("spawn"))
        if spawn and any(m != spawn["map_id"] for m in maps if m) and resident.work_mode == "anchor_only":
            issues.append(Issue("warning", f"residents[{index}]", "anchors span several maps; the resident crosses maps through portals (walks to the portal, then is moved to its target anchor)"))
        if resident.role is None and resident.work_mode == "occupation":
            issues.append(Issue("warning", f"residents[{index}].work_mode", "no role: work_mode 'occupation' has nothing to do; use 'anchor_only'"))
    return issues


def validate_roster_for_world(roster, map_name, contract=None):
    """Convenience: validate against whatever the map registry holds for ``map_name`` (primary + placed maps)."""
    from systems.movement.map_contract import placed_group
    group = placed_group(map_name)
    map_ids = {(e.get("info") or {}).get("map_id") for e in group}
    return validate_roster(roster, anchors_from_registry(map_name), contract, map_ids)
