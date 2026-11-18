"""Powers as ``plan()`` (pure) then ``apply()`` (atomic, evented), with the first two legacy tools rebuilt on the harness.

A power is a function ``power(world, **args) -> Draft`` registered with ``@power``. ``plan(world, name, args)`` validates the
arguments against the generated JSON Schema, resolves the typed selector to stable ids, and returns a ``Plan`` (the exact effects,
a preview, the world revision it was made at) without touching the world. ``apply(world, plan)`` applies the plan's effects and
event in ONE atomic ``EffectApplier`` run; if the world's revision moved since the plan was made, the plan is rebuilt from the same
arguments first (value-dependent effects such as ``multiply`` never apply stale numbers), and the report says so.

Ported here: ``set_mood`` (legacy ``tool_set_mood``) and ``plague`` (legacy ``tool_plague``/``apply_plague_effect``). Deliberate
differences from the legacy tools, both caused by legacy bug G-D0-3 (``t[mask, col].clamp_`` clamps a copy and does nothing):

* the harness versions really clamp: mood to 0..100, infection and threat to at most 100, mood and hp to at least 0;
* the legacy tools were reachable only through a string mask DSL; these take a typed selector.

Nothing in the tick loop or the god API calls these yet.

``EDEN_GOD_POWER_PORTS=1`` at registry construction additionally exposes ``set_threat``, ``set_aggression`` and
``reset_cooldown``, plus eight disaster powers (``wildfire``, ``earthquake``, ``storm``, ``volcanic_eruption``,
``drought``, ``flood``, ``area_attack``, ``smite``) through the same plan/apply pipeline. The flag is off by default.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Literal, Optional

import torch

from . import effects as fx
from . import target_selectors as sel
from .numerics import pairwise_distances
from .registry import DEFAULT, Registry, power

MOOD_RANGE = (0.0, 100.0)
HP_MAX = 100.0              # legacy apply_bless_effect: target_hp
BLESS_MOOD = 90.0           # legacy apply_bless_effect target_mood, and tool_baby_boom's mood
FERTILITY_MAX = 2.0         # legacy tool_baby_boom cap
FLEE_STEP = 3.0             # legacy instinct_flee: MOVE_STEP (1.0) * 3.0
MASK_FIELDS = ("acquired_instinct_mask", "acquired_instinct_mask_1", "acquired_instinct_mask_2")   # words of the 64-bit mask


class PowerRefused(Exception):
    """Raised inside a power's planning code for a refusal with a stable reason code."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason, self.detail = reason, detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


@dataclass
class Draft:
    """What a power function returns: who, what changes, and the event to record."""
    targets: sel.Resolution
    effects: list
    preview: dict
    event: Optional[fx.Emit] = None


@dataclass(frozen=True)
class Plan:
    power: str
    args: dict
    ok: bool
    reason: str = ""
    errors: tuple = ()
    targets: tuple = ()
    effects: tuple = ()
    preview: dict = field(default_factory=dict)
    risk: str = "reversible"
    revision: int = 0
    tick: int = 0


@dataclass
class PowerResult:
    ok: bool
    reason: str = ""
    plan: Optional[Plan] = None
    report: Optional[fx.ApplyReport] = None
    replanned: bool = False
    event_ids: tuple = ()


# -- helpers -----------------------------------------------------------------------------------------------------------
def bounded_amounts(current: list, amount: float, lo: Optional[float], hi: Optional[float]) -> list:
    """Per-id delta so that ``current + delta`` stays inside ``[lo, hi]`` (a row already outside moves toward the range only)."""
    out = []
    for value in current:
        target = value + amount
        if lo is not None:
            target = max(lo, target)
        if hi is not None:
            target = min(hi, target)
        out.append(target - value)
    return out


def _humans(world, targets: dict) -> sel.Resolution:
    if not isinstance(targets, dict) or targets.get("of") != "humans":
        raise PowerRefused("invalid_targets", "targets must be a selector over 'humans'")
    try:
        resolution = sel.resolve(targets, world)
    except sel.SelectorError as exc:
        raise PowerRefused("invalid_selector", str(exc)) from None
    if not resolution.ids:
        raise PowerRefused("no_targets", "the selector matched no live resident")
    return resolution


def _resolution(world, selector: dict, ids) -> sel.Resolution:
    return sel.Resolution(selector=selector, ids=tuple(ids), revision=world.revision, tick=int(world.tick))


def _check_amounts(**amounts) -> None:
    for name, value in amounts.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
            raise PowerRefused("invalid_amount", f"{name} must be a finite number >= 0, got {value!r}")


def _area(world, table_name: str, center, radius: float) -> sel.Resolution:
    """Ids of the live rows of a table strictly within ``radius`` of ``center``, by the exact float32 distance the legacy
    ``agent_radial_mask``/``entity_radial_ids`` use (``<``, not ``<=``). Raises ``PowerRefused`` when there are none."""
    if (not isinstance(center, (list, tuple)) or len(center) != 2
            or any(not isinstance(c, (int, float)) or isinstance(c, bool) or not math.isfinite(c) for c in center)):
        raise PowerRefused("invalid_center", "center must be two finite numbers [x, y]")
    table = world.table(table_name)
    slots = [s for s in table.live_slots() if table.ids[s] is not None]
    if slots:
        pos = table.tensor[slots][:, [table.col("x"), table.col("y")]]
        dist = pairwise_distances(pos, torch.tensor([[float(center[0]), float(center[1])]], dtype=pos.dtype)).squeeze(1)
        slots = [s for s, d in zip(slots, dist.tolist()) if d < float(radius)]
    ids = tuple(table.ids[s] for s in slots)
    if not ids:
        raise PowerRefused("no_targets", f"nothing in {table_name!r} within {radius} of {list(center)}")
    return _resolution(world, {"of": table_name, "ids": list(ids)}, ids)


def _centroid(world, ids) -> Optional[tuple]:
    table = world.table("humans")
    points = [table.position(table.slot_of(i)) for i in ids]
    points = [p for p in points if p is not None]
    if not points:
        return None
    return (sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points))


# -- powers ------------------------------------------------------------------------------------------------------------
def build_registry() -> Registry:
    """A registry holding the ported powers (kept separate from ``DEFAULT`` so tests and the manifest can build their own)."""
    reg = Registry()

    @power("set_mood", risk="reversible", registry=reg)
    def set_mood(world, targets: dict, value: float, mode: Literal["set", "add", "multiply"] = "set") -> Draft:
        """Set, add to or scale the mood of the residents a selector matches; the result is clamped to 0..100."""
        resolution = _humans(world, targets)
        table = world.table("humans")
        before = [table.get(i, "mood") for i in resolution.ids]
        lo, hi = MOOD_RANGE
        if mode == "set":
            after = [min(hi, max(lo, float(value)))] * len(before)
        elif mode == "add":
            after = [min(hi, max(lo, b + float(value))) for b in before]
        else:
            after = [min(hi, max(lo, b * float(value))) for b in before]
        effects = [fx.set_("humans", resolution.ids, "mood", after)]
        event = fx.Emit("mood_set", actors=resolution.ids, visibility="private",
                        payload={"mode": mode, "value": float(value), "count": len(resolution.ids)})
        preview = {"affected": list(resolution.ids), "mood_before": dict(zip(resolution.ids, before)),
                   "mood_after": dict(zip(resolution.ids, after)), "mode": mode}
        return Draft(resolution, effects, preview, event)

    @power("plague", risk="destructive", registry=reg)
    def plague(world, targets: dict, decay_rate: float = 2.0, infection_gain: float = 30.0, threat_gain: float = 15.0,
               mood_drop: float = 20.0) -> Draft:
        """Infect the residents a selector matches: lose hp, gain infection and threat, lose mood (all clamped to their range)."""
        if min(decay_rate, infection_gain, threat_gain, mood_drop) < 0:
            raise PowerRefused("invalid_amount", "decay_rate, infection_gain, threat_gain and mood_drop must be >= 0")
        resolution = _humans(world, targets)
        table = world.table("humans")
        ids = resolution.ids
        cur = {name: [table.get(i, name) for i in ids] for name in ("hp", "infection", "threat", "mood")}
        effects = [
            fx.delta("humans", ids, "hp", bounded_amounts(cur["hp"], -decay_rate, 0.0, None)),
            fx.delta("humans", ids, "infection", bounded_amounts(cur["infection"], infection_gain, None, 100.0)),
            fx.delta("humans", ids, "threat", bounded_amounts(cur["threat"], threat_gain, None, 100.0)),
            fx.delta("humans", ids, "mood", bounded_amounts(cur["mood"], -mood_drop, 0.0, None)),
        ]
        event = fx.Emit("plague", actors=ids, place=_centroid(world, ids), visibility="local", radius=80.0,
                        payload={"decay_rate": decay_rate, "count": len(ids)})
        preview = {"affected": list(ids), "hp_before": dict(zip(ids, cur["hp"])), "infection_before": dict(zip(ids, cur["infection"])),
                   "reversible": False}
        return Draft(resolution, effects, preview, event)

    # -- ported in the second batch (evidence: the god-decree keyword path in runtime/world_runtime.py lines 691-735) ------------
    def humans_or_all(world, targets: Optional[dict]) -> sel.Resolution:
        return _humans(world, targets if targets is not None else {"of": "humans"})

    @power("bless", risk="reversible", registry=reg)
    def bless(world, targets: Optional[dict] = None) -> Draft:
        """Heal the residents a selector matches (default: everyone) to full hp, set their mood to 90 and clear their cooldown."""
        resolution = humans_or_all(world, targets)
        table, ids = world.table("humans"), resolution.ids
        hp = [table.get(i, "hp") for i in ids]
        effects = [fx.set_("humans", ids, "hp", [min(HP_MAX, h + HP_MAX) for h in hp]), fx.set_("humans", ids, "mood", BLESS_MOOD),
                   fx.set_("humans", ids, "cooldown", 0.0)]
        event = fx.Emit("blessing", actors=ids, place=_centroid(world, ids), visibility="local", radius=80.0, payload={"count": len(ids)})
        return Draft(resolution, effects, {"affected": list(ids), "hp_before": dict(zip(ids, hp))}, event)

    @power("calm_area", risk="reversible", registry=reg)
    def calm_area(world, center: list, radius: float = 90.0, mood_gain: float = 20.0, threat_drop: float = 25.0) -> Draft:
        """Calm every resident within a radius of a point: mood up (at most 100), threat down (at least 0)."""
        _check_amounts(radius=radius, mood_gain=mood_gain, threat_drop=threat_drop)
        resolution = _area(world, "humans", center, radius)
        table, ids = world.table("humans"), resolution.ids
        threat = [table.get(i, "threat") for i in ids]
        mood = [table.get(i, "mood") for i in ids]
        effects = [fx.delta("humans", ids, "threat", bounded_amounts(threat, -threat_drop, 0.0, None)),
                   fx.delta("humans", ids, "mood", bounded_amounts(mood, mood_gain, None, 100.0))]
        event = fx.Emit("calm", actors=ids, place=tuple(map(float, center)), visibility="local", radius=float(radius),
                        payload={"count": len(ids)})
        return Draft(resolution, effects, {"affected": list(ids), "center": [float(c) for c in center], "radius": float(radius)}, event)

    @power("panic_area", risk="destructive", registry=reg)
    def panic_area(world, center: list, radius: float = 90.0, mood_drop: float = 20.0, threat_gain: float = 30.0,
                   flee_step: float = FLEE_STEP) -> Draft:
        """Frighten every resident within a radius of a point: threat up (at most 100), mood down (at least 0), and push them away."""
        _check_amounts(radius=radius, mood_drop=mood_drop, threat_gain=threat_gain, flee_step=flee_step)
        resolution = _area(world, "humans", center, radius)
        table, ids = world.table("humans"), resolution.ids
        threat = [table.get(i, "threat") for i in ids]
        mood = [table.get(i, "mood") for i in ids]
        slots = [table.slot_of(i) for i in ids]
        pos = table.tensor[slots][:, [table.col("x"), table.col("y")]]
        away = pos - torch.tensor([float(center[0]), float(center[1])], dtype=pos.dtype)
        push = away / away.norm(dim=1, keepdim=True).clamp(min=1e-6) * float(flee_step)
        new_pos = pos + push                               # the executor clamps to the frame bounds like the legacy clamp(0, MAP_*)
        effects = [fx.delta("humans", ids, "threat", bounded_amounts(threat, threat_gain, None, 100.0)),
                   fx.delta("humans", ids, "mood", bounded_amounts(mood, -mood_drop, 0.0, None)),
                   fx.set_("humans", ids, "x", new_pos[:, 0].tolist()), fx.set_("humans", ids, "y", new_pos[:, 1].tolist())]
        event = fx.Emit("panic", actors=ids, place=tuple(map(float, center)), visibility="local", radius=float(radius),
                        payload={"count": len(ids)})
        return Draft(resolution, effects, {"affected": list(ids), "center": [float(c) for c in center], "radius": float(radius)}, event)

    @power("baby_boom", risk="reversible", registry=reg)
    def baby_boom(world, targets: Optional[dict] = None) -> Draft:
        """Raise fertility (at most 2) and clear the cooldown of the matched females, and lift everyone's mood to 90."""
        resolution = humans_or_all(world, targets)
        table, ids = world.table("humans"), resolution.ids
        females = [i for i in ids if table.get(i, "sex") == 1.0]
        effects = []
        if females:
            fertility = [table.get(i, "fertility") for i in females]
            effects += [fx.set_("humans", females, "cooldown", 0.0),
                        fx.delta("humans", females, "fertility", bounded_amounts(fertility, 0.5, None, FERTILITY_MAX))]
        effects.append(fx.set_("humans", ids, "mood", BLESS_MOOD))
        event = fx.Emit("baby_boom", actors=ids, visibility="local", radius=80.0, payload={"count": len(ids), "females": len(females)})
        return Draft(resolution, effects, {"affected": list(ids), "females": list(females)}, event)

    @power("cull", risk="destructive", registry=reg)
    def cull(world, target_population: int) -> Draft:
        """Remove the weakest residents (lowest hp first, lowest slot on ties) until at most ``target_population`` remain."""
        if target_population < 0:
            raise PowerRefused("invalid_amount", "target_population must be >= 0")
        table = world.table("humans")
        live = table.live_slots()
        excess = len(live) - int(target_population)
        if excess <= 0:
            raise PowerRefused("no_targets", f"{len(live)} residents are alive, target is {target_population}")
        order = sorted(live, key=lambda slot: (float(table.tensor[slot, table.col("hp")]), slot))
        ids = tuple(table.ids[slot] for slot in order[:excess])
        resolution = _resolution(world, {"of": "humans", "ids": list(ids)}, ids)
        event = fx.Emit("cull", actors=ids, visibility="local", radius=80.0, payload={"removed": len(ids), "target": int(target_population)})
        return Draft(resolution, [fx.despawn("humans", ids)], {"affected": list(ids), "alive_before": len(live), "reversible": False}, event)

    @power("enlighten", risk="reversible", registry=reg)
    def enlighten(world, bit: int, targets: Optional[dict] = None) -> Draft:
        """Grant an acquired-instinct bit (0..63) to the residents a selector matches (default: everyone). The 64-bit mask is
        stored as three exact 24-bit words (G-D0-2), so only the one word that holds the bit is rewritten."""
        if not isinstance(bit, int) or isinstance(bit, bool) or not 0 <= bit <= 63:
            raise PowerRefused("invalid_bit", f"bit must be an integer in 0..63, got {bit!r}")
        resolution = humans_or_all(world, targets)
        table, ids = world.table("humans"), resolution.ids
        word, shift = divmod(bit, 24)
        field_name = MASK_FIELDS[word]
        if field_name not in table.columns:
            raise PowerRefused("no_mask_column", f"this world has no {field_name!r} column")
        before = [int(table.get(i, field_name)) for i in ids]
        effects = [fx.set_("humans", ids, field_name, [float(value | (1 << shift)) for value in before])]
        event = fx.Emit("enlightened", actors=ids, visibility="private", payload={"bit": bit, "count": len(ids)})
        return Draft(resolution, effects, {"affected": list(ids), "bit": bit, "column": field_name}, event)

    def _entity_rule(world) -> dict:
        rule = world.config.get("resource_model")
        if not rule:
            raise PowerRefused("no_resource_model", "this world does not define which entities carry food, water and fertility")
        return rule

    def _resource_change(world, center, radius, food, water, fertility, sign) -> Draft:
        rule = _entity_rule(world)
        _check_amounts(radius=radius, food=food, water=water, fertility=fertility)
        resolution = _area(world, "entities", center, radius)
        table = world.table("entities")
        natural, carriers = set(rule["natural_types"]), set(rule["natural_types"]) | set(rule["other_types"])
        ids = tuple(i for i in resolution.ids if int(table.get(i, "type")) in carriers)
        if not ids:
            raise PowerRefused("no_targets", "no food or water carrying entity in the area")
        food_hi, water_hi, fert_hi = (rule["max_food"], rule["max_water"], rule["max_fertility"]) if sign > 0 else (None, None, None)
        floor = 0.0 if sign < 0 else None
        cur = {name: [table.get(i, name) for i in ids] for name in ("food", "water", "fertility")}
        effects = [fx.delta("entities", ids, "food", bounded_amounts(cur["food"], sign * food, floor, food_hi)),
                   fx.delta("entities", ids, "water", bounded_amounts(cur["water"], sign * water, floor, water_hi))]
        grassy = tuple(i for i in ids if int(table.get(i, "type")) in natural)
        if grassy:
            fert = [table.get(i, "fertility") for i in grassy]
            effects.append(fx.delta("entities", grassy, "fertility", bounded_amounts(fert, sign * fertility, floor, fert_hi)))
        kind = "bounty" if sign > 0 else "scarcity"
        event = fx.Emit(kind, place=tuple(map(float, center)), visibility="local", radius=float(radius), payload={"entities": len(ids)})
        return Draft(_resolution(world, {"of": "entities", "ids": list(ids)}, ids), effects,
                     {"affected": list(ids), "center": [float(c) for c in center], "radius": float(radius)}, event)

    @power("bounty_area", risk="reversible", registry=reg)
    def bounty_area(world, center: list, radius: float = 90.0, food_gain: float = 20.0, water_gain: float = 20.0,
                    fertility_gain: float = 10.0) -> Draft:
        """Add food, water and fertility to the natural entities, farms and wells within a radius of a point (capped at their maxima)."""
        return _resource_change(world, center, radius, food_gain, water_gain, fertility_gain, +1)

    @power("scarcity_area", risk="destructive", registry=reg)
    def scarcity_area(world, center: list, radius: float = 90.0, food_loss: float = 20.0, water_loss: float = 20.0,
                      fertility_loss: float = 10.0) -> Draft:
        """Remove food, water and fertility from the natural entities, farms and wells within a radius of a point (floored at 0)."""
        return _resource_change(world, center, radius, food_loss, water_loss, fertility_loss, -1)

    if os.environ.get("EDEN_GOD_POWER_PORTS") == "1":
        def adjust(world, targets, value, mode, column, low, high) -> Draft:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise PowerRefused("invalid_amount", "value must be finite")
            try:
                value = float(value)
            except OverflowError:
                raise PowerRefused("invalid_amount", "value must fit a finite float") from None
            if not math.isfinite(value):
                raise PowerRefused("invalid_amount", "value must be finite")
            resolution = _humans(world, targets)
            table, ids = world.table("humans"), resolution.ids
            if column not in table.columns:
                raise PowerRefused("no_column", f"this world has no {column!r} column")
            before = [table.get(i, column) for i in ids]
            if any(not math.isfinite(v) for v in before):
                raise PowerRefused("invalid_state", f"{column} must be finite")
            raw = ([float(value)] * len(ids) if mode == "set" else
                   [b + value for b in before] if mode == "add" else [b * value for b in before])
            if any(not math.isfinite(v) for v in raw):
                raise PowerRefused("invalid_amount", "operation must produce finite values")
            after = [min(high, max(low, v)) for v in raw]
            event = fx.Emit(f"{column}_set", actors=ids, visibility="private",
                            payload={"mode": mode, "value": float(value), "count": len(ids)})
            return Draft(resolution, [fx.set_("humans", ids, column, after)],
                         {"affected": list(ids), f"{column}_before": dict(zip(ids, before)),
                          f"{column}_after": dict(zip(ids, after)), "mode": mode}, event)

        @power("set_threat", risk="reversible", registry=reg)
        def set_threat(world, targets: dict, value: float, mode: Literal["set", "add", "multiply"] = "set") -> Draft:
            """Set, add to or scale selected residents' threat, bounded to 0..100 (EDEN_GOD_POWER_PORTS)."""
            return adjust(world, targets, value, mode, "threat", 0.0, 100.0)

        @power("set_aggression", risk="reversible", registry=reg)
        def set_aggression(world, targets: dict, value: float = 1.0, mode: Literal["set", "add", "multiply"] = "set") -> Draft:
            """Set, add to or scale selected residents' aggression, bounded to 0..1 (EDEN_GOD_POWER_PORTS)."""
            return adjust(world, targets, value, mode, "aggression", 0.0, 1.0)

        @power("reset_cooldown", risk="reversible", registry=reg)
        def reset_cooldown(world, targets: Optional[dict] = None) -> Draft:
            """Clear only the selected residents' reproduction cooldown; defaults to everyone (EDEN_GOD_POWER_PORTS)."""
            resolution = humans_or_all(world, targets)
            table, ids = world.table("humans"), resolution.ids
            if "cooldown" not in table.columns:
                raise PowerRefused("no_column", "this world has no 'cooldown' column")
            before = [table.get(i, "cooldown") for i in ids]
            event = fx.Emit("cooldown_reset", actors=ids, visibility="private", payload={"count": len(ids)})
            return Draft(resolution, [fx.set_("humans", ids, "cooldown", 0.0)],
                         {"affected": list(ids), "cooldown_before": dict(zip(ids, before)),
                          "cooldown_after": dict.fromkeys(ids, 0.0)}, event)

        from . import disaster_powers
        disaster_powers.register_disaster_powers(reg)

    return reg


REGISTRY = build_registry()


# -- plan / apply ------------------------------------------------------------------------------------------------------
def plan(world, name: str, args: dict, registry: Optional[Registry] = None) -> Plan:
    """Validate and compile a power call. Pure: nothing in the world changes, so a refused or failed plan costs nothing."""
    registry = registry or REGISTRY
    args = dict(args or {})
    errors = registry.validate_call(name, args, kind="power")
    if errors:
        return Plan(power=name, args=args, ok=False, reason="invalid_arguments", errors=tuple(errors), revision=world.revision,
                    tick=int(world.tick))
    spec = registry.powers[name]
    risk = spec.extra.get("risk", "reversible")
    try:
        draft = spec.fn(world, **args)
    except PowerRefused as refusal:
        return Plan(power=name, args=args, ok=False, reason=refusal.reason, errors=(refusal.detail,) if refusal.detail else (),
                    risk=risk, revision=world.revision, tick=int(world.tick))
    effects = tuple(draft.effects) + ((draft.event,) if draft.event is not None else ())
    return Plan(power=name, args=args, ok=True, targets=tuple(draft.targets.ids), effects=effects, preview=draft.preview, risk=risk,
                revision=world.revision, tick=int(world.tick))


def apply(world, the_plan: Plan, registry: Optional[Registry] = None) -> PowerResult:
    """Apply a plan atomically. A plan made at an older world revision is rebuilt from its arguments first."""
    if not the_plan.ok:
        return PowerResult(ok=False, reason=the_plan.reason or "plan_not_ok", plan=the_plan)
    replanned = False
    if the_plan.revision != world.revision:
        the_plan = plan(world, the_plan.power, the_plan.args, registry)
        replanned = True
        if not the_plan.ok:
            return PowerResult(ok=False, reason=the_plan.reason, plan=the_plan, replanned=True)
    report = world.apply(list(the_plan.effects), atomic=True, cause=f"power:{the_plan.power}")
    if not report.ok:
        return PowerResult(ok=False, reason="apply_failed", plan=the_plan, report=report, replanned=replanned)
    return PowerResult(ok=True, plan=the_plan, report=report, replanned=replanned, event_ids=tuple(e.id for e in report.events))


def call(world, name: str, args: dict, *, dry_run: bool = False, registry: Optional[Registry] = None) -> PowerResult:
    """``plan`` then (unless ``dry_run``) ``apply``: what a god API route would do."""
    the_plan = plan(world, name, args, registry)
    if dry_run or not the_plan.ok:
        return PowerResult(ok=the_plan.ok, reason=the_plan.reason, plan=the_plan)
    return apply(world, the_plan, registry)
