from __future__ import annotations

import torch
try:
    from harness.clamp import clamp_rows_
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.harness.clamp import clamp_rows_

try:
    from genesis_config import H_COOLDOWN, H_INFECTION, HP, MOOD, THREAT, TYPE
    from systems.health.damage import apply_human_damage, apply_human_heal
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.genesis_config import H_COOLDOWN, H_INFECTION, HP, MOOD, THREAT, TYPE
    from at_the_beginning.systems.health.damage import apply_human_damage, apply_human_heal


def apply_plague_effect(
    affected: torch.Tensor,
    h_tensor: torch.Tensor,
    *,
    decay_rate: float = 2.0,
    infection_gain: float = 30.0,
    threat_gain: float = 15.0,
    mood_drop: float = 20.0,
) -> None:
    """Compound plague effect: damage + infection + threat + mood loss."""
    if not affected.any():
        return
    apply_human_damage(affected, h_tensor, decay_rate, hp_col=HP)
    h_tensor[affected, H_INFECTION] += infection_gain
    clamp_rows_(h_tensor, affected, H_INFECTION, hi=100.0)
    h_tensor[affected, THREAT] += threat_gain
    clamp_rows_(h_tensor, affected, THREAT, hi=100.0)
    h_tensor[affected, MOOD] -= mood_drop
    clamp_rows_(h_tensor, affected, MOOD, lo=0.0)


def apply_bless_effect(
    affected: torch.Tensor,
    h_tensor: torch.Tensor,
    *,
    target_hp: float = 100.0,
    target_mood: float = 90.0,
) -> None:
    """Compound blessing effect: full heal + calm + reset cooldown/infection."""
    if not affected.any():
        return
    apply_human_heal(affected, h_tensor, target_hp, hp_col=HP, max_hp=target_hp)
    h_tensor[affected, MOOD] = target_mood
    h_tensor[affected, H_COOLDOWN] = 0.0
    h_tensor[affected, H_INFECTION] = 0.0
    h_tensor[affected, THREAT] = 0.0


def kill_humans(
    affected: torch.Tensor,
    h_tensor: torch.Tensor,
    pop_count_ref: list,
) -> bool:
    """Remove affected humans from the sim immediately."""
    if not affected.any():
        return False
    pop_count_ref[0] -= int(affected.sum().item())
    h_tensor[affected] = 0.0
    return True


def apply_area_attack_effect(
    ctx: dict,
    h_tensor: torch.Tensor,
    pop_count_ref: list,
    *,
    center_x: float,
    center_y: float,
    radius: float,
    device: str,
    agent_radial_mask_fn,
    flee_fn,
    flee_radius_multiplier: float = 2.5,
) -> dict:
    """Kill humans in the blast radius and flee nearby survivors outward."""
    h_mask = ctx["h_mask"]
    kill_mask = agent_radial_mask_fn(h_tensor, h_mask, center_x, center_y, radius, device)
    flee_mask = agent_radial_mask_fn(
        h_tensor,
        h_mask,
        center_x,
        center_y,
        radius * float(flee_radius_multiplier),
        device,
    ) & ~kill_mask
    kill_humans(kill_mask, h_tensor, pop_count_ref)
    if flee_mask.any():
        flee_fn(ctx, h_tensor, (center_x, center_y), flee_mask=flee_mask, device=device)
    return {"h_mask": h_tensor[:, TYPE] > 0}
