"""Executors for the god commands (registered on DISPATCH): god_heal, god_spawn_resource, god_weather, god_time."""
from . import powers

ACTIONS = {"god_heal": powers.heal, "god_spawn_resource": powers.spawn_resource, "god_weather": powers.set_weather,
           "god_time": powers.time_control}


def execute_god(engine, action, payload):
    """Executor of the god_* commands: routes ``action`` to its power."""
    power = ACTIONS.get(action)
    if power is None:
        return {"ok": False, "reason": "unknown_action"}
    return power(engine, payload)
