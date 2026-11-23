"""Register the roster and smith-loop hooks and executors on a Dispatcher (idempotent). All are no-ops on legacy maps."""


def roster_genesis_hook(engine, map_name):
    """Genesis hook: spawn the roster's residents when the map has a usable roster."""
    from .apply import apply_roster, has_roster
    if has_roster(map_name):
        apply_roster(engine, map_name)


def roster_driver_hook(engine):
    """Step hook: one tick of anchor movement, portal crossings and food/water trips."""
    from .driver import drive_roster_residents
    drive_roster_residents(engine)


def agent_driver_hook(engine):
    """Step hook: Tier 1 moves the roster residents whose driver is "agent" (imported only when there is one)."""
    from .driver import roster_slots
    if roster_slots(engine, "agent"):
        from systems.actions.agent_driver import hook
        hook(engine)


def invitation_expiry_hook(engine):
    """Expire invitations even in worlds without agent-driven residents."""
    if getattr(engine, "_r61_invitations", None) is not None:
        from systems.actions.agent_driver import driver_of
        driver_of(engine).runner(engine).expire_invitations(int(engine.tick))


def motion_checkpoint_hook(engine):
    """Step hook: remember where the driver left every resident (the start of the task phase)."""
    from .motion import record_checkpoint
    record_checkpoint(engine)


def motion_limits_hook(engine):
    """Post-step hook: cap and slide this tick's movement of every non-controlled human."""
    from .motion import apply_motion_limits
    apply_motion_limits(engine)


def commission_tick_hook(engine):
    """Post-step hook: advance every open commission order by one tick."""
    from systems.commission.engine import commission_tick
    commission_tick(engine)


def god_weather_expiry_hook(engine):
    """Post-step hook: end a god-set weather at its end tick (roster worlds; the nature cycle is off there)."""
    from systems.god.expiry import expire_weather
    expire_weather(engine)


def install_smith_loop(dispatch):
    """Register the roster, commission and god hooks and executors on ``dispatch`` (idempotent)."""
    names = {name for hooks in (dispatch.step_hooks, dispatch.post_step_hooks, dispatch.genesis_hooks) for name, _ in hooks}
    if "roster_apply" not in names:
        dispatch.register_genesis_hook("roster_apply", roster_genesis_hook, builtin=True)
    if "roster_driver" not in names:
        dispatch.register_step_hook("roster_driver", roster_driver_hook, builtin=True)
    if "agent_driver" not in names:  # D-008: moves roster residents whose driver is "agent"; a no-op while none is (the default)
        dispatch.register_step_hook("agent_driver", agent_driver_hook, builtin=True)
    import os
    if os.environ.get("EDEN_VERBS_R61") == "1" and "invitation_expiry" not in names:
        dispatch.register_step_hook("invitation_expiry", invitation_expiry_hook, builtin=True)
    if "motion_checkpoint" not in names:
        dispatch.register_step_hook("motion_checkpoint", motion_checkpoint_hook, builtin=True)
    if "motion_limits" not in names:
        dispatch.register_post_step_hook("motion_limits", motion_limits_hook, builtin=True)
    if "commission_tick" not in names:
        dispatch.register_post_step_hook("commission_tick", commission_tick_hook, builtin=True)
    if "god_weather_expiry" not in names:
        dispatch.register_post_step_hook("god_weather_expiry", god_weather_expiry_hook, builtin=True)
    from systems.commission.engine import execute_commission
    for action in ("commission_request", "commission_cancel", "commission_collect"):
        dispatch.register_executor(action, execute_commission)
    from systems.god.commands import ACTIONS, execute_god
    for action in ACTIONS:
        dispatch.register_executor(action, execute_god)
    return dispatch
