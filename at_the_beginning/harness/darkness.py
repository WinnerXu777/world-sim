"""2.A2 darkness unease (``EDEN_DARKNESS=1``, default off; USER-DEC-6 unblocked it): a resident out in the dark is uneasy.

One registry instinct, ``instinct_darkness_unease``, installed from ``engine_hooks`` at priority 34.4 (after the temperature and sleep instincts, before ``instinct_heal``). Per tick:

    unease = (1 - light) * outdoors * (1 - FIRE_RELIEF if a fire is within its radius)        light = calendar.active().light_at(tick), 0.05 at night under the long calendar
    mood   -= RATE_MOOD * unease                                                               (scaled like the other body instincts)
    threat += RATE_THREAT * unease, only while below THREAT_CAP                                (a low background fear, never past the cap; it decays by the legacy rule)

``outdoors`` means neither ``H_SHELTER`` nor ``H_SPACE``: indoors the dark is no threat. Under the legacy calendar light is 1.0 by day, 0.5 at dawn and dusk and 0.0 at night, so the
instinct works there too. A fire is any warmth source of ``harness.temperature`` (the placed maps' hearths and the lit fires ``temperature.add_source`` registers): the fire
is the light. Rates are multiplied by ``calendar.rate_scale("needs")`` and the roster's ``needs_scale``. The cap keeps the unease below the threat levels that make a resident flee, so
it colours mood and the Tier 1 ``dark`` / fear features (``unease_of``), it does not clear a village at dusk. All numbers are proposals.
"""
from __future__ import annotations

import os
from typing import Optional

import torch

FLAG = "EDEN_DARKNESS"
NAME = "instinct_darkness_unease"
PRIORITY = 34.4

RATE_MOOD = 0.02          # per tick at full unease, before the scales
RATE_THREAT = 0.05
THREAT_CAP = 25.0
FIRE_RELIEF = 0.8


def enabled() -> bool:
    return os.environ.get(FLAG, "") == "1"


def unease(light: float, outdoors: torch.Tensor, by_fire: torch.Tensor) -> torch.Tensor:
    """float32 [H]: 0..1 per row. Pure."""
    dark = min(1.0, max(0.0, 1.0 - float(light)))
    relief = 1.0 - FIRE_RELIEF * by_fire.float()
    return dark * outdoors.float() * relief


def _modules():
    try:
        from . import calendar, temperature
        from systems.roster.driver import needs_scale_vector
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.harness import calendar, temperature
        from at_the_beginning.systems.roster.driver import needs_scale_vector
    return calendar, temperature, needs_scale_vector


def apply(engine, h_tensor: torch.Tensor, mask: torch.Tensor) -> dict:
    import genesis_config as cfg
    calendar, temperature, needs_scale_vector = _modules()
    light = calendar.active().light_at(int(engine.tick))
    outdoors = ~temperature.indoors(h_tensor) & mask
    by_fire = torch.zeros_like(mask)
    fires = temperature._fires(engine).to(h_tensor.device)
    rows = outdoors.nonzero(as_tuple=False).flatten()
    if fires.shape[0] and rows.numel():
        near = torch.cdist(h_tensor[rows][:, [cfg.X, cfg.Y]], fires[:, :2]) <= fires[:, 2]
        by_fire[rows] = near.any(dim=1)
    felt = unease(light, outdoors, by_fire)
    scale = torch.full_like(felt, float(calendar.rate_scale("needs")))
    per_resident = needs_scale_vector(engine, h_tensor)
    if per_resident is not None:
        scale = scale * per_resident.to(scale.device).float()
    if bool((felt > 0).any()):
        h_tensor[:, cfg.MOOD] = (h_tensor[:, cfg.MOOD] - RATE_MOOD * felt * scale).clamp(0.0, 100.0)
        room = (THREAT_CAP - h_tensor[:, cfg.THREAT]).clamp(min=0.0)
        h_tensor[:, cfg.THREAT] = h_tensor[:, cfg.THREAT] + torch.minimum(RATE_THREAT * felt * scale, room)
    state = {"tick": int(engine.tick), "light": float(light), "unease": felt}
    engine._darkness = state
    return state


def instinct_darkness_unease(ctx: dict, h_tensor: torch.Tensor, **kwargs) -> None:
    engine = ctx.get("engine")
    if engine is None or not ctx["h_mask"].any():
        return
    apply(engine, h_tensor, ctx["h_mask"])


def state_of(engine) -> Optional[dict]:
    return engine.__dict__.get("_darkness")


def unease_of(engine, slot: int) -> float:
    """The unease (0..1) this resident felt on the last tick (0.0 before the first tick or with the flag off)."""
    state = state_of(engine)
    return 0.0 if state is None else float(state["unease"][slot])


def install(engine) -> bool:
    """Register ``instinct_darkness_unease`` once (idempotent)."""
    if any(entry["fn"] is instinct_darkness_unease for entry in engine._registry):
        return False
    engine.register(instinct_darkness_unease, priority=PRIORITY)
    return True
