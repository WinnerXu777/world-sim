"""God mode (P5): heal, spawn_resource, weather and time control with witnessed, remembered consequences."""
from .commands import ACTIONS, execute_god
from .events import commit_event, remembers
from .pause import pause_step
from .powers import RESOURCES, WEATHERS, heal, set_weather, spawn_resource, time_control, time_state
from .state import TIME_SCALES, WITNESS_RADIUS, is_paused, set_paused, witnesses

__all__ = ["ACTIONS", "RESOURCES", "TIME_SCALES", "WEATHERS", "WITNESS_RADIUS", "commit_event", "execute_god", "heal", "is_paused",
           "pause_step", "remembers", "set_paused", "set_weather", "spawn_resource", "time_control", "time_state", "witnesses"]
