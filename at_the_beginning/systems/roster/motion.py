"""Task-phase movement on authored maps: one bounded, sliding mover instead of straight-line writes (finding 5)."""
import math

from systems.movement.spatial import slide, snap_to_standable, world_contract

from .driver import is_anchor_driven, roster_of, runtime


def move_task_actor(engine, slot, tx, ty, magnitude):
    """Handle a task move on an authored map. Always returns True (the caller must not move the actor itself).

    Roster residents are moved only by the roster driver, so a task step is ignored for them. Everyone else walks
    toward the (snapped-to-standable) target with ``AnchorMover``: at most one walk step per tick, always slid.
    """
    import genesis_config as cfg
    human_id = engine._human_uid_by_slot[slot]
    roster, _ = roster_of(engine, human_id)
    if is_anchor_driven(roster):  # an agent-driven roster resident (D-008) walks its tasks like any other resident
        return True
    contract = world_contract(engine)
    goal = snap_to_standable((float(tx), float(ty)), contract)
    if goal is None:
        return True
    position = (float(engine.state.h_tensor[slot, cfg.X]), float(engine.state.h_tensor[slot, cfg.Y]))
    result = runtime(engine).mover.step(("task", human_id), position, goal, contract, engine.tick)
    if result.position != position:
        engine.state.h_tensor[slot, cfg.X], engine.state.h_tensor[slot, cfg.Y] = result.position
    return True


MAX_STEP_PER_TICK = 1.5  # units a non-controlled human may move in one tick on an authored map (sprint speed)


def record_checkpoint(engine):
    """Step hook, after the roster driver: remember where everyone stands before the task phase runs."""
    from systems.movement.map_contract import get_map_contract
    if get_map_contract(getattr(engine, "_map_name", None)) is None:
        return
    runtime(engine).checkpoint = engine.state.h_tensor[:, :2].clone()


def apply_motion_limits(engine):
    """Post-step hook: a non-controlled human moves at most MAX_STEP_PER_TICK from where it ended the previous tick,
    whatever moved it (instincts, decisions, talk reactions, task steps), and the move is slid through the walls."""
    import genesis_config as cfg
    from systems.movement.map_contract import get_map_contract
    state = runtime(engine)
    if get_map_contract(getattr(engine, "_map_name", None)) is None:
        return 0
    if state.final_epoch != engine.world_epoch:  # a new or restored world: earlier positions mean nothing
        state.final_positions, state.final_epoch = {}, engine.world_epoch
    contract = None
    limited = 0
    h = engine.state.h_tensor
    for slot, human_id in enumerate(engine._human_uid_by_slot):
        if not human_id or float(h[slot, cfg.TYPE]) != cfg.AGENT_TYPE_HUMAN:
            continue
        end = (float(h[slot, cfg.X]), float(h[slot, cfg.Y]))
        if engine.player_control.describe_human_slot(slot) is not None:
            state.final_positions[human_id] = end
            continue
        start = state.final_positions.get(human_id)
        if start is None and state.checkpoint is not None:
            start = (float(state.checkpoint[slot, 0]), float(state.checkpoint[slot, 1]))
        if start is not None:
            moved = math.hypot(end[0] - start[0], end[1] - start[1])
            if moved > 1e-9:
                if moved > MAX_STEP_PER_TICK:
                    scale = MAX_STEP_PER_TICK / moved
                    end = (start[0] + (end[0] - start[0]) * scale, start[1] + (end[1] - start[1]) * scale)
                    limited += 1
                contract = contract or world_contract(engine)
                end = slide(start, end, contract)
                h[slot, cfg.X], h[slot, cfg.Y] = end
        state.final_positions[human_id] = end
    return limited
