"""End of a god-set weather on roster worlds.

On a roster world the nature cycle (which used to end weather and roll the next one) is switched off, so ``set_weather`` records its
end in the persisted god ledger (``inventory_state["god"]["weather"] = {kind, ends_tick}``, saved and restored with the world) and this
post-step hook turns the weather back to clear at that tick. It never starts a disaster, never re-enables the cycle and never touches
weather that something else has changed since. Paused time does not advance the tick, so a pause delays the end.
"""
from .events import commit_event
from .state import store, witnesses


def expire_weather(engine):
    """Post-step hook: if the god's weather has reached its end tick, set the weather to clear once. Returns True when it did."""
    entry = (engine.inventory_state.get("god") or {}).get("weather")
    if not entry or engine.tick < int(entry.get("ends_tick", 0)):
        return False
    store(engine).pop("weather", None)
    state = engine._nature_state
    previous = state.get("weather")
    if previous != entry.get("kind"):
        return False  # somebody else changed it since: nothing of ours to end
    outdoors = witnesses(engine, (0.0, 0.0), exterior_only=True)
    state.update(weather="clear", weather_started_tick=engine.tick, weather_duration_ticks=0, weather_ends_tick=engine.tick)
    commit_event(engine, "weather_changed", point=(0.0, 0.0), witnesses=outdoors, note="the weather cleared",
                 extra={"weather": "clear", "previous": previous, "expired": True})
    return True
