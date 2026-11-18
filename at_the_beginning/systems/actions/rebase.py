"""Window re-base for the Model plane: shift the absolute positions held outside the tensors by (dx, dy).

``dx``/``dy`` are the amounts ADDED to every window-local coordinate (``SpaceFrame.rebase_shift``). The window manager calls
``rebase_model_plane`` once per re-base on the tick thread, after it shifted the tensors and the registered map contract and before the next
step hook. Only residents with ``H_SPACE == 0`` (the overworld) move; a pocket resident keeps its own frame. Returns ``{holder: count}`` so a
scan test can assert every holder fired; ``dx == dy == 0`` is a no-op with zero counts.
"""
import dataclasses

# Keys under which a resident record keeps an absolute {x, y} dict (task / goal / schedule records and a task's own state).
POSITION_KEYS = ("target_place", "ambush_anchor")
RECORD_FIELDS = ("tasks", "task_state", "goals", "schedule_state", "schedule_profile", "known_places")
FOLLOWING_PURPOSES = ("visit", "restitution", "repay", "labour", "report", "enforce", "guard", "guard_place", "rob")     # errands whose position is recomputed from the person sought every tick (Ladder.errand_goal)
HOLDERS = ("roster_final_positions", "roster_checkpoint", "mover_plans", "mover_no_path", "record_positions", "driver_goals", "ladder_errands")


def _shift_point(point, dx, dy):
    return (point[0] + dx, point[1] + dy)


def _shift_dict(place, dx, dy):
    """Shift an ``{x, y, ...}`` dict in place when both coordinates are numbers (an empty / named-only place is left alone)."""
    x, y = place.get("x"), place.get("y")
    if isinstance(x, (int, float)) and isinstance(y, (int, float)) and not isinstance(x, bool) and not isinstance(y, bool):
        place["x"], place["y"] = x + dx, y + dy
        return 1
    return 0


def _walk(node, dx, dy):
    """Shift every position dict under a POSITION_KEYS key inside ``node`` (dicts and lists, any depth); returns how many moved."""
    moved = 0
    if isinstance(node, dict):
        for key, value in node.items():
            if key in POSITION_KEYS and isinstance(value, dict):
                moved += _shift_dict(value, dx, dy)
            else:
                moved += _walk(value, dx, dy)
    elif isinstance(node, list):
        for item in node:
            moved += _walk(item, dx, dy)
    return moved


def _overworld_humans(engine):
    """``{human id: slot}`` of every resident in space 0."""
    import genesis_config as cfg
    h = engine.state.h_tensor
    return {human_id: slot for slot, human_id in enumerate(engine._human_uid_by_slot)
            if human_id and float(h[slot, cfg.H_SPACE]) == 0.0}


def _entity_in_overworld(engine, uid) -> bool:
    """True when the entity with this uid lives in space 0 (an unknown uid counts as overworld: the errand expires or fails on its own)."""
    import genesis_config as cfg
    try:
        slot = list(engine._entity_uid_by_slot).index(uid)
    except ValueError:
        return True
    return float(engine.state.m_tensor[slot, cfg.M_SPACE]) == 0.0


def rebase_model_plane(engine, dx, dy) -> dict:
    counts = {name: 0 for name in HOLDERS}
    if not (dx or dy):
        return counts
    dx, dy = float(dx), float(dy)
    from systems.roster.driver import runtime
    state = runtime(engine)
    mine = _overworld_humans(engine)

    for human_id in mine:                                                       # where each resident ended the previous tick (motion limits)
        if human_id in state.final_positions:
            state.final_positions[human_id] = _shift_point(state.final_positions[human_id], dx, dy)
            counts["roster_final_positions"] += 1
    if state.checkpoint is not None:                                            # tensor clone of the positions after the driver ran
        for slot in mine.values():
            state.checkpoint[slot, 0] += dx
            state.checkpoint[slot, 1] += dy
            counts["roster_checkpoint"] += 1

    def owner(key):                                                             # mover keys: a human id or ("task", human id)
        return key[1] if isinstance(key, tuple) else key

    for key, plan in state.mover.plans.items():
        if owner(key) in mine:
            plan["goal"] = _shift_point(plan["goal"], dx, dy)
            plan["waypoints"] = [_shift_point(p, dx, dy) for p in plan["waypoints"]]
            counts["mover_plans"] += 1
    for key, (goal, revision, expires) in list(state.mover.no_path.items()):
        if owner(key) in mine:
            state.mover.no_path[key] = (_shift_point(goal, dx, dy), revision, expires)
            counts["mover_no_path"] += 1

    for human_id in mine:                                                       # tasks, goals, schedule: explore_toward / move_to_place points
        record = engine.resident_store.get(human_id)
        if record:
            for name in RECORD_FIELDS:
                counts["record_positions"] += _walk(record.get(name), dx, dy)
            for entry in (record.get("memory") or {}).get("last_threats", []):    # recent perception: feeds the pressures
                if isinstance(entry, dict):
                    counts["record_positions"] += _shift_dict(entry, dx, dy)

    driver = engine.__dict__.get("_agent_driver")
    if driver is not None:
        for human_id, goal in list(driver.last_goal.items()):
            if human_id in mine and goal is not None:
                driver.last_goal[human_id] = dataclasses.replace(goal, position=_shift_point(goal.position, dx, dy))
                counts["driver_goals"] += 1
        for human_id, errand in list(driver.ladder.errands.items()):             # ladder errands hold a fixed position beside a node / container; a visit, restitution, repay, labour, report or enforce errand follows the person live
            if human_id in mine and errand.purpose not in FOLLOWING_PURPOSES and _entity_in_overworld(engine, errand.target):
                errand.position = _shift_point(errand.position, dx, dy)
                counts["ladder_errands"] += 1
    return counts
