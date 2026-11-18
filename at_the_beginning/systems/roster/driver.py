"""Roster residents live on anchors: the schedule picks an anchor, an AnchorMover walks there, nothing else moves them.

Called every tick from the ``roster_driver`` step hook (after the movement reconcile). Anchor-driven residents are
the non-controlled humans whose record carries ``roster``; random-walk noise and navigation biases are masked for them
(``anchor_driven_rows``) and task movement is suppressed (``Engine._move_human_toward_point``), so there is exactly one
mover per resident and it always slides.
"""
import torch

from systems.movement.anchor_mover import AnchorMover, StepResult

ROUTINE_ANCHOR = {"sleep": "sleep", "stay_home": "sleep", "return_home": "sleep", "rest": "sleep", "work_site": "work",
                  "guard": "work", "patrol": "work", "gather": "work", "socialize": "talk", "visit_water": "work",
                  "wander_local": "talk"}
ANCHOR_FALLBACKS = {"sleep": ("sleep", "home", "talk", "work"), "work": ("work", "talk", "home"), "talk": ("talk", "work", "home")}
WALK_STEP = 1.0  # units per tick (20 u/s)


class RosterRuntime:
    """Non-saved runtime state: the mover (plans are rebuilt after a restore) and the last arrival per resident."""

    def __init__(self):
        self.mover = AnchorMover(step_len=WALK_STEP)
        self.at_anchor = {}   # human id -> anchor key currently reached ("work", ...)
        self.goal_key = {}    # human id -> anchor key currently walked to
        self.moved = {}       # human id -> distance the driver moved it this tick
        self.checkpoint = None  # positions after the driver ran (start of the task phase)
        self.final_positions = {}  # human id -> where it ended the previous tick (motion limits)
        self.final_epoch = None
        self.trips = {}       # human id -> food/water trip in progress (needs.py); not saved
        self.trip_epoch = None
        self.trips_done = self.rations = self.trip_timeouts = self.trip_blocked = self.portal_uses = 0  # diagnostics (soak report), not saved


def runtime(engine):
    """The engine's non-saved RosterRuntime, created on first use."""
    found = engine.__dict__.get("_roster_runtime")
    if found is None:
        found = engine.__dict__["_roster_runtime"] = RosterRuntime()
    return found


def roster_of(engine, human_id):
    """``(roster binding, resident record)`` of a human id; the binding is None for a resident without a roster."""
    record = engine.resident_store.get(human_id) if human_id else None
    return (record or {}).get("roster"), record


def _controlled(engine, slot):
    return engine.player_control.describe_human_slot(slot) is not None


DRIVER_ENV = "EDEN_ROSTER_DRIVER"
DRIVER_KINDS = ("anchor", "agent")


def driver_kind(roster):
    """Who moves a roster resident: ``anchor`` (this module, the Stage 1 behaviour) or ``agent`` (``systems/actions/agent_driver``, D-008).
    The binding's own ``driver`` wins; otherwise ``EDEN_ROSTER_DRIVER``; the default and any unknown value is ``anchor``."""
    import os
    kind = str((roster or {}).get("driver") or os.environ.get(DRIVER_ENV, "") or "anchor").strip().lower()
    return kind if kind in DRIVER_KINDS else "anchor"


def is_anchor_driven(roster):
    """True for a resident with a roster binding that the anchor driver (not the agent driver) moves."""
    return bool(roster) and driver_kind(roster) == "anchor"


def is_agent_driven(roster):
    """True for a resident with a roster binding that the agent driver moves (D-008)."""
    return bool(roster) and driver_kind(roster) == "agent"


def anchor_driven_slots(engine):
    """Slots of live, non-controlled humans bound to a roster and moved by the anchor driver (empty on legacy maps)."""
    slots = roster_slots(engine, "anchor")
    dormant = getattr(engine, "_dormant_h", None)       # EDEN_WINDOW_DORMANCY: no mover work for a resident outside the integrated window
    return slots if dormant is None else [slot for slot in slots if not bool(dormant[slot])]


def roster_slots(engine, kind):
    """Slots of live, non-controlled humans bound to a roster whose ``driver_kind`` is ``kind`` (``None``: any kind; empty on legacy maps)."""
    from systems.movement.map_contract import get_map_contract
    if get_map_contract(getattr(engine, "_map_name", None)) is None:
        return []
    import genesis_config as cfg
    slots = []
    for slot, human_id in enumerate(engine._human_uid_by_slot):
        if human_id and float(engine.state.h_tensor[slot, cfg.TYPE]) == cfg.AGENT_TYPE_HUMAN and not _controlled(engine, slot):
            roster, _ = roster_of(engine, human_id)
            if roster and (kind is None or driver_kind(roster) == kind):
                slots.append(slot)
    return slots


def anchor_driven_rows(engine, h_indices):
    """Bool mask over ``h_indices`` (the rows ``instinct_move`` iterates) of anchor-driven residents; None if none."""
    if engine is None:
        return None
    slots = set(roster_slots(engine, None))  # both kinds: noise and biases are off for any roster resident, whoever moves it
    if not slots:
        return None
    mask = torch.tensor([int(s) in slots for s in h_indices.tolist()], dtype=torch.bool, device=h_indices.device)
    return mask if bool(mask.any()) else None


def needs_scale_vector(engine, h_tensor):
    """Per-slot needs scale (hunger/thirst rate multiplier) for roster residents; None on maps without one."""
    if engine is None:
        return None
    from systems.movement.map_contract import get_map_contract
    if get_map_contract(getattr(engine, "_map_name", None)) is None:
        return None
    scales = None
    for slot, human_id in enumerate(engine._human_uid_by_slot):
        if not human_id:
            continue
        roster, _ = roster_of(engine, human_id)
        if roster and float(roster.get("needs_scale", 1.0)) != 1.0:
            if scales is None:
                scales = torch.ones(h_tensor.shape[0], dtype=h_tensor.dtype, device=h_tensor.device)
            scales[slot] = float(roster["needs_scale"])
    return scales


def age_scale_vector(engine, h_tensor):
    """Per-slot aging multiplier for roster residents (a 30-minute run is 60 game years at 1.0); None on other maps."""
    from systems.movement.map_contract import get_map_contract
    if engine is None or get_map_contract(getattr(engine, "_map_name", None)) is None:
        return None
    scales = None
    for slot, human_id in enumerate(engine._human_uid_by_slot):
        if not human_id:
            continue
        roster, _ = roster_of(engine, human_id)
        if roster and float(roster.get("age_scale", 1.0)) != 1.0:
            if scales is None:
                scales = torch.ones(h_tensor.shape[0], dtype=h_tensor.dtype, device=h_tensor.device)
            scales[slot] = float(roster["age_scale"])
    return scales


def anchor_positions(engine, roster):
    """World positions of the resident's roster anchors by key (spawn, work, talk, sleep, ...)."""
    from .validate import anchors_from_registry
    anchors = anchors_from_registry(engine._map_name)
    return {key: anchors[anchor_id]["position"] for key, anchor_id in roster["anchors"].items() if anchor_id in anchors}


def map_id_at(engine, point):
    """The placed map whose rectangle contains ``point`` (None outside every placed map)."""
    from systems.movement.map_contract import placed_group
    for entry in placed_group(getattr(engine, "_map_name", None)):
        b = entry["bounds"]
        if b[0] <= point[0] <= b[2] and b[1] <= point[1] <= b[3]:
            return (entry.get("info") or {}).get("map_id") or getattr(engine, "_map_name", None)
    return None


def portal_toward(engine, position, goal):
    """When ``goal`` lies on another placed map than ``position``: the portal ``(from_point, to_point)`` that leaves
    the resident's map (preferring one that lands on the goal's map), else None."""
    here, there = map_id_at(engine, position), map_id_at(engine, goal)
    if here is None or there is None or here == there:
        return None
    from systems.movement.map_contract import find_portal, placed_group
    best = None
    for entry in placed_group(getattr(engine, "_map_name", None)):
        if (entry.get("info") or {}).get("map_id") != here:
            continue
        for portal in entry.get("portals", ()):
            found = find_portal(engine._map_name, portal["id"])
            if found is None or not found["to_loaded"]:
                continue
            candidate = (tuple(found["from"]), tuple(found["to"]), found["portal"]["to_map"])
            if candidate[2] == there:
                return candidate[:2]
            best = best or candidate[:2]
    return best


def use_portal(engine, slot, human_id, target):
    """Move a resident through a portal exactly like the player's portal command does (same teleport bookkeeping)."""
    import genesis_config as cfg
    from systems.movement.spatial import is_standable_point, world_contract
    if not is_standable_point(target, world_contract(engine)):
        return False
    engine.state.h_tensor[slot, cfg.X], engine.state.h_tensor[slot, cfg.Y] = target
    engine._teleport_seq[human_id] = engine._teleport_seq.get(human_id, 0) + 1
    engine._tick_teleports.append((slot, target[0], target[1]))
    engine._force_frame_refresh = True
    state = runtime(engine)
    state.final_positions[human_id] = target  # the motion limiter must not read the jump as a speed violation
    state.mover.forget(human_id)
    state.portal_uses = getattr(state, "portal_uses", 0) + 1
    return True


def current_routine(engine, human_id, resident):
    """The resident's schedule routine kind, refreshed like ``build_schedule_navigation_bias`` does."""
    from systems.schedule.ops import choose_resident_schedule_routine, ensure_resident_schedule, schedule_refresh_due
    from systems.schedule.resolver import tick_to_time_block
    tick = engine.tick
    ensure_resident_schedule(resident, tick)
    current = dict((resident.get("schedule_state", {}) or {}).get("current_routine") or {})
    time_block = tick_to_time_block(tick)
    if not current or str(current.get("time_block", "")).strip() != time_block or schedule_refresh_due(resident, tick):
        decision = choose_resident_schedule_routine(resident, tick, context={
            "reason": "roster_schedule", "has_home": True, "settlement_present": True, "survival_override": False,
            "active_plan_override": False, "urgent_override": False})
        if decision.get("ok"):
            current = dict(decision.get("routine") or {})
            engine.resident_store.touch_resident(human_id)
    return str(current.get("kind", "")).strip()


def goal_anchor_key(roster, routine_kind, override=None):
    """Which of the resident's anchors the routine (or an override such as an open commission) asks for."""
    wanted = override or ROUTINE_ANCHOR.get(routine_kind)
    if wanted is None:
        return None
    for key in ANCHOR_FALLBACKS.get(wanted, (wanted,)):
        if key in roster["anchors"]:
            return key
    return None


def drive_roster_residents(engine, contract=None):
    """One tick of anchor movement for every anchor-driven resident. Returns {human id: StepResult}."""
    import genesis_config as cfg
    results = {}
    runtime(engine).moved = {}
    slots = anchor_driven_slots(engine)
    if not slots:
        return results
    from systems.movement.spatial import world_contract
    contract = contract or world_contract(engine)
    state = runtime(engine)
    from systems.commission.engine import commission_goal_override
    from .needs import after_step as needs_after_step, plan as needs_plan
    for slot in slots:
        human_id = engine._human_uid_by_slot[slot]
        roster, resident = roster_of(engine, human_id)
        if float(engine.state.h_tensor[slot, cfg.HP]) <= 0.0:
            continue
        need = needs_plan(engine, slot, human_id, roster, state)
        if need is not None:  # a food/water trip pre-empts the schedule and an open commission
            key, goal = need[0], need[1]
        else:
            routine = current_routine(engine, human_id, resident)
            key = goal_anchor_key(roster, routine, commission_goal_override(engine, human_id))
            positions = anchor_positions(engine, roster)
            if key is None or key not in positions:
                continue
            goal = positions[key]
        position = (float(engine.state.h_tensor[slot, cfg.X]), float(engine.state.h_tensor[slot, cfg.Y]))
        portal = portal_toward(engine, position, goal)  # the goal is on another map: walk to the portal first
        result = state.mover.step(human_id, position, portal[0] if portal else goal, contract, engine.tick)
        if portal and result.arrived and use_portal(engine, slot, human_id, portal[1]):
            result = StepResult(portal[1], moved=0.0)
        if result.position != position:
            engine.state.h_tensor[slot, cfg.X], engine.state.h_tensor[slot, cfg.Y] = result.position
        if need is not None:
            # reaching a portal is not reaching the well: only the final leg counts as standing at the site
            needs_after_step(engine, slot, human_id, roster, state, StepResult(result.position, blocked=result.blocked) if portal else result)
        state.goal_key[human_id] = key
        state.moved[human_id] = result.moved
        if result.arrived:
            state.at_anchor[human_id] = key
        else:
            state.at_anchor.pop(human_id, None)
        results[human_id] = result
    return results
