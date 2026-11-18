"""S3: hunger and thirst drain as the first system migrated onto the harness (pilot, behind ``EDEN_HARNESS_NEEDS=1``).

The two legacy registry entries ``instinct_hunger`` (priority 15) and ``instinct_thirst`` (16) are replaced by ONE entry,
``instinct_needs``, registered at the first one's priority. It expresses the same drain as harness effects and applies them through
the world's ``EffectApplier`` (bounds, revision, one code path), in the order that keeps every float32 operation of the legacy code:

1. ``Delta hunger`` and ``Delta thirst`` (each times the calendar rate class ``needs``, 1.0 flag off),
   scaled per-slot by ``needs_scale_vector(engine, h_tensor)`` when present (the table bounds clamp both at 100, no lower bound);
2. ``Delta hp -2.0`` for live rows whose unscaled hunger is >= 90 (own apply: legacy subtracts hunger damage before thirst damage, and
   float32 ``(hp - 2) - d`` is not always ``hp - (2 + d)``);
3. ``Delta hp -THIRST_DAMAGE_RATE`` and ``Delta mood -0.4`` for rows whose unscaled thirst is >= 90, and ``Set critical_health`` for the
   rows whose flag changes (1 when scaled hunger or unscaled thirst >= 90, else 0), in one apply.

Roster residents with ``needs_scale`` (such as the shipped starter_village with scale 0.015) are migrated to this harness effect path.
Falls back to the two legacy functions when:
- the engine has no harness world on this tensor,
- a live row has no stable id,
- a scale vector is invalid, negative, or non-finite,
- exact scaled hunger or thirst would exceed 100 (which current FieldSpec hi=100 bounds cannot faithfully represent without diverging from legacy),
- or an entity with HP > 100 receives damage (where legacy clamps only lo=0 while FieldSpec clamps 0..100).
Scale handling does not change inactive rows; default-off registry behavior stays unchanged.
"""
from __future__ import annotations

import os

import torch

FLAG = "EDEN_HARNESS_NEEDS"
NAME = "instinct_needs"
HUNGER_DAMAGE = 2.0
CRITICAL_AT = 90.0
THIRST_MOOD_LOSS = 0.4


def enabled() -> bool:
    from . import engine_hooks
    return os.environ.get(FLAG, "") == "1" and engine_hooks.enabled()


def make_instinct_needs(legacy_hunger, legacy_thirst):
    """The replacement registry entry. ``legacy_*`` are the original functions (the fallback)."""
    import genesis_config as cfg
    from systems.roster import driver
    from . import engine_hooks

    def instinct_needs(ctx: dict, h_tensor: torch.Tensor, **kwargs) -> None:
        engine = ctx.get("engine")
        h_mask = ctx.get("h_mask")
        world = None if engine is None else engine_hooks.runtime(engine).world
        humans = None if world is None else world.table("humans")
        if (engine is None or world is None or humans is None
                or humans.tensor is not h_tensor
                or not isinstance(h_mask, torch.Tensor) or not h_mask.any()):
            legacy_hunger(ctx, h_tensor, **kwargs)
            legacy_thirst(ctx, h_tensor, **kwargs)
            return

        uids = getattr(engine, "_human_uid_by_slot", None)
        if uids is None:
            legacy_hunger(ctx, h_tensor, **kwargs)
            legacy_thirst(ctx, h_tensor, **kwargs)
            return

        slots_tensor = h_mask.nonzero(as_tuple=False).flatten()
        slots = slots_tensor.tolist()
        ids = tuple(uids[s] for s in slots)
        if not all(ids):
            legacy_hunger(ctx, h_tensor, **kwargs)
            legacy_thirst(ctx, h_tensor, **kwargs)
            return

        from .calendar import rate_scale
        from .effects import Delta, Set

        scales = driver.needs_scale_vector(engine, h_tensor)

        h_rate = cfg.HUNGER_TICK_RATE * rate_scale("needs")
        t_rate = cfg.THIRST_TICK_RATE * rate_scale("needs")

        before_h = h_tensor[slots_tensor, cfg.HUNGER]
        before_t = h_tensor[slots_tensor, cfg.THIRST]

        unscaled_h = torch.clamp(before_h + h_rate, max=100.0)
        unscaled_t = torch.clamp(before_t + t_rate, max=100.0)

        if scales is None:
            delta_h = h_rate
            delta_t = t_rate
            scaled_h = unscaled_h
            scaled_t = unscaled_t
        else:
            if (not isinstance(scales, torch.Tensor) or scales.dim() != 1
                    or scales.shape[0] < h_tensor.shape[0]):
                legacy_hunger(ctx, h_tensor, **kwargs)
                legacy_thirst(ctx, h_tensor, **kwargs)
                return
            active_scales = scales[slots_tensor]
            if not torch.isfinite(active_scales).all() or (active_scales < 0.0).any():
                legacy_hunger(ctx, h_tensor, **kwargs)
                legacy_thirst(ctx, h_tensor, **kwargs)
                return

            delta_h = (unscaled_h - before_h) * active_scales
            delta_t = (unscaled_t - before_t) * active_scales
            scaled_h = before_h + delta_h
            scaled_t = before_t + delta_t

            # Boundary fallback: FieldSpec clamps hunger and thirst at hi=100.0.
            # If exact legacy value would exceed 100.0, harness bounds cannot faithfully represent it.
            if (scaled_h > 100.0).any() or (scaled_t > 100.0).any():
                legacy_hunger(ctx, h_tensor, **kwargs)
                legacy_thirst(ctx, h_tensor, **kwargs)
                return
            if not torch.isfinite(scaled_h).all() or not torch.isfinite(scaled_t).all():
                legacy_hunger(ctx, h_tensor, **kwargs)
                legacy_thirst(ctx, h_tensor, **kwargs)
                return

        # Starving and dehydrated masks (computed on unscaled states, exactly as legacy does)
        starving_mask = unscaled_h >= CRITICAL_AT
        dehydrated_mask = unscaled_t >= CRITICAL_AT

        # Boundary fallback for HP: FieldSpec for HP is 0..100.
        # Legacy does not clamp HP at 100 on damage. If an entity has HP > 100 and takes damage,
        # harness bounds would clamp it to 100.0, diverging from legacy.
        if starving_mask.any():
            starving_slots = slots_tensor[starving_mask]
            if (h_tensor[starving_slots, cfg.HP] > 100.0).any():
                legacy_hunger(ctx, h_tensor, **kwargs)
                legacy_thirst(ctx, h_tensor, **kwargs)
                return
        if dehydrated_mask.any():
            dehydrated_slots = slots_tensor[dehydrated_mask]
            if (h_tensor[dehydrated_slots, cfg.HP] > 100.0).any():
                legacy_hunger(ctx, h_tensor, **kwargs)
                legacy_thirst(ctx, h_tensor, **kwargs)
                return

        apply = world.apply

        # 1. Apply hunger and thirst deltas
        if scales is None:
            drain_effects = [
                Delta("humans", ids, "hunger", cfg.HUNGER_TICK_RATE * rate_scale("needs")),
                Delta("humans", ids, "thirst", cfg.THIRST_TICK_RATE * rate_scale("needs")),
            ]
        else:
            drain_effects = [
                Delta("humans", ids, "hunger", delta_h.tolist()),
                Delta("humans", ids, "thirst", delta_t.tolist()),
            ]
        apply(drain_effects, cause="system:needs")

        # 2. Starvation HP damage (separate apply to preserve float32 subtraction order)
        if starving_mask.any():
            starving_ids = tuple(uids[s] for s in slots_tensor[starving_mask].tolist())
            apply([Delta("humans", starving_ids, "hp", -(HUNGER_DAMAGE * rate_scale("starvation")))],
                  cause="system:needs")

        # 3. Dehydration HP damage, mood loss, and critical health refresh
        effects = []
        if dehydrated_mask.any():
            dehydrated_ids = tuple(uids[s] for s in slots_tensor[dehydrated_mask].tolist())
            effects += [
                Delta("humans", dehydrated_ids, "hp", -(cfg.THIRST_DAMAGE_RATE * rate_scale("damage_recovery"))),
                Delta("humans", dehydrated_ids, "mood", -THIRST_MOOD_LOSS),
            ]

        # Exact legacy sequential critical timing:
        # hunger tick refreshes critical and then hunger is restored to scaled_h;
        # thirst tick then evaluates critical with current hunger (scaled_h) and unscaled thirst (unscaled_t);
        # then thirst is restored to scaled_t.
        crit_mask = (scaled_h >= CRITICAL_AT) | (unscaled_t >= CRITICAL_AT)
        critical = torch.zeros(h_tensor.shape[0], dtype=torch.bool, device=h_tensor.device)
        critical[slots_tensor] = crit_mask

        flag = h_tensor[:, cfg.CRITICAL_HEALTH]
        for value, rows in ((1.0, critical & (flag != 1.0)), (0.0, h_mask & ~critical & (flag != 0.0))):
            if rows.any():
                effects.append(Set("humans", tuple(uids[s] for s in rows.nonzero(as_tuple=False).flatten().tolist()),
                                   "critical_health", value))
        if effects:
            apply(effects, cause="system:needs")

    instinct_needs.__name__ = NAME
    instinct_needs.originals = (legacy_hunger, legacy_thirst)
    return instinct_needs


def install(engine) -> bool:
    """Replace ``instinct_hunger`` and ``instinct_thirst`` in ``engine._registry`` by ``instinct_needs`` (idempotent).
    Returns True when the swap happened (or was already done)."""
    entries = {getattr(e["fn"], "__name__", ""): e for e in engine._registry}
    if NAME in entries:
        return True
    hunger, thirst = entries.get("instinct_hunger"), entries.get("instinct_thirst")
    if hunger is None or thirst is None:
        return False
    engine.unregister(hunger["fn"])
    engine.unregister(thirst["fn"])
    engine.register(make_instinct_needs(hunger["fn"], thirst["fn"]), priority=hunger["priority"], **hunger["kwargs"])
    return True
