"""Food and water loop for roster residents: needs stay bounded for as long as the world runs.

When a resident's thirst or hunger reaches ``needs.threshold`` the driver sends him to the map's drink/eat anchor
(``needs.water.anchor`` / ``needs.food.anchor`` in the roster file) through the normal AnchorMover (portals included),
he stands there ``ticks`` ticks, the need is reset to 0 and the routine resumes. Deterministic: no randomness, no
inventory, no engine tasks. Rules:

* Thirst is checked before hunger; a trip in progress is never interrupted by the other need or by the schedule.
* A trip pre-empts the routine and an open commission. Commission progress is stored in the order and only counts at the
  forge, so an away smith simply pauses (``smith_away``) and resumes on return; nothing is lost or failed.
* No site (``anchor`` null, the resident has ``needs_sites: false``, or the old save has no ``needs`` block) or a site
  that cannot be reached (no path, or the trip exceeds ``trip_timeout_ticks``): a free ration, the need drops by
  ``needs.ration`` on the spot. A resident never starves because of the loop.
* Trips are runtime state (not saved); after Continue a need still over the threshold simply starts a new trip.
* A *possessed* resident is not driven and needs no help: ``instinct_incarnation_stabilize`` pins his hunger and thirst at 0 (and his
  HP at 100) every tick while a player controls him; when the player lets go he is an ordinary roster resident again.
"""
import genesis_config as cfg

KINDS = ("water", "food")
COLUMN = {"water": cfg.THIRST, "food": cfg.HUNGER}


def settings(roster):
    """``(needs settings, has_sites)`` of a roster binding; a save without a ``needs`` block gets the defaults."""
    from .load import DEFAULT_NEEDS
    needs = roster.get("needs") or DEFAULT_NEEDS
    return needs, bool(roster.get("needs_sites", True))


def site_position(engine, needs, kind, has_sites):
    """World position of the water or food anchor, or None when this resident has no site (he gets the ration)."""
    if not has_sites or needs[kind]["anchor"] is None:
        return None
    from .validate import anchors_from_registry
    anchor = anchors_from_registry(engine._map_name).get(needs[kind]["anchor"])
    return None if anchor is None else anchor["position"]


def ration(engine, slot, kind, needs, state, human_id):
    """Free ration: lower the need by ``needs.ration`` on the spot and end any trip."""
    column = COLUMN[kind]
    engine.state.h_tensor[slot, column] = max(0.0, float(engine.state.h_tensor[slot, column]) - needs["ration"])
    state.rations = getattr(state, "rations", 0) + 1
    state.trips.pop(human_id, None)


def plan(engine, slot, human_id, roster, state, *, allow_food=True):
    """Plan needs; ``allow_food=False`` leaves new food requests to the agent ladder.

    Water and already active trips retain their existing behavior. The default
    preserves every legacy caller.
    """
    needs, has_sites = settings(roster)
    if state.trip_epoch != engine.world_epoch:
        state.trips, state.trip_epoch = {}, engine.world_epoch
    h = engine.state.h_tensor
    trip = state.trips.get(human_id)
    if trip is None:
        for kind in KINDS:
            if kind == "food" and not allow_food:
                continue
            if float(h[slot, COLUMN[kind]]) >= needs["threshold"]:
                position = site_position(engine, needs, kind, has_sites)
                if position is None:
                    ration(engine, slot, kind, needs, state, human_id)
                    continue
                trip = state.trips[human_id] = {"kind": kind, "phase": "walk", "started": engine.tick, "stood": 0}
                break
        if trip is None:
            return None
    kind = trip["kind"]
    position = site_position(engine, needs, kind, has_sites)
    if position is None or engine.tick - trip["started"] > needs["trip_timeout_ticks"]:
        ration(engine, slot, kind, needs, state, human_id)
        state.trip_timeouts = getattr(state, "trip_timeouts", 0) + 1
        return None
    return kind, position, trip


def after_step(engine, slot, human_id, roster, state, result):
    """Count the ticks spent standing at the site; finish the trip (need back to 0) when they are used up."""
    trip = state.trips.get(human_id)
    if trip is None:
        return
    needs, _ = settings(roster)
    kind = trip["kind"]
    if result.blocked:  # no path / stuck: do not wait for the timeout, the ration is the guaranteed answer
        ration(engine, slot, kind, needs, state, human_id)
        state.trip_blocked = getattr(state, "trip_blocked", 0) + 1
        return
    if not result.arrived:
        return
    trip["phase"] = "use"
    trip["stood"] += 1
    if trip["stood"] >= needs[kind]["ticks"]:
        engine.state.h_tensor[slot, COLUMN[kind]] = 0.0
        state.trips.pop(human_id, None)
        state.trips_done = getattr(state, "trips_done", 0) + 1
