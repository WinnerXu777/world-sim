"""2.A2 temperature comfort (``EDEN_TEMPERATURE=1``, default off; ``1008_instincts_wiring_gap.md`` step 2): the consumer the season never had.

One registry instinct, ``instinct_temperature``, installed from ``engine_hooks`` at priority 34 (after the death checks and the vitals, before ``instinct_heal``), so a cold
resident's HP loss is seen by the next tick's death check and by the heal gate. Per tick, vectorised over ``ctx["h_mask"]`` (dormant rows are already out of it):

    ambient   = SEASON_BASE[season] + WEATHER_OFFSET[weather] + BLOCK_OFFSET[time block]            (one number per tick, from data tables below)
    effective = ambient + SHELTER_BONUS * (H_SHELTER or inside an interior space) + the best warmth source within its radius + clothing (a placeholder 0 until the item class exists)
    cold      = clamp(COMFORT_LOW - effective, 0)         hot = clamp(effective - COMFORT_HIGH, 0)

    stamina -= RATE_STAMINA * cold                         mood -= RATE_MOOD * cold               (comfort costs, from the first degree)
    hp      -= RATE_HP * max(cold - HP_DAMAGE_FROM, 0)     (the cold kills the unprepared: no shelter, no fire, no clothing, a hard night)
    thirst  += RATE_THIRST * hot                           hp  -= RATE_HP * max(hot - HP_DAMAGE_FROM, 0)

Every rate is multiplied by ``calendar.rate_scale("needs")`` (the same table works under either calendar) and by the roster's ``needs_scale`` of the resident
(``systems.roster.driver.needs_scale_vector``, None on a legacy map), so a village whose hunger runs at 1.5 % runs its cold at 1.5 %: the effect acts on residents through the
vitals the model plane already reads (stamina, mood, thirst, hp). Nothing is stored per resident: the last numbers are kept on ``engine._temperature`` for readers
(``cold_of`` / ``hot_of`` for the Tier 1 features ``cold`` and ``hot``).

Warmth sources: map entities of kind ``hearth`` / ``campfire`` of the placed maps (authored, found by position) and the lit fires ``add_source`` registers (the ``light_fire`` verb
calls it with the fire's position, radius, bonus and lifetime). All numbers are proposals; the winter scenario in the as-built section is where they get tuned.
"""
from __future__ import annotations

import os
from typing import Optional

import torch

FLAG = "EDEN_TEMPERATURE"
NAME = "instinct_temperature"
PRIORITY = 34

SEASON_BASE = {"spring": 12.0, "summer": 22.0, "autumn": 10.0, "winter": -4.0}
WEATHER_OFFSET = {"clear": 0.0, "rain": -3.0, "humid": 1.0, "storm": -5.0, "wind": -4.0, "heat": 8.0, "dry": 2.0, "cold": -8.0}
BLOCK_OFFSET = {"dawn": -3.0, "day": 3.0, "dusk": -1.0, "night": -6.0}
COMFORT_LOW, COMFORT_HIGH = 8.0, 30.0
SHELTER_BONUS = 12.0
FIRE_BONUS, FIRE_RADIUS = 18.0, 40.0
HEARTH_KINDS = ("hearth", "campfire")
CLOTHING_BONUS = 0.0                      # degrees every resident gets regardless of what it carries (kept at 0; the garments come from ``systems.clothing``)
CLOTHING_REFRESH = 20                    # ticks between reads of the residents' packs
HP_DAMAGE_FROM = 10.0                     # degrees of deficit (or excess) above which HP is lost
RATE_STAMINA, RATE_MOOD, RATE_HP, RATE_THIRST = 0.02, 0.02, 0.015, 0.02          # per degree per tick
SOURCE_REFRESH = 20                       # ticks between reads of the map entities' hearths


def enabled() -> bool:
    return os.environ.get(FLAG, "") == "1"


# ---- pure ----------------------------------------------------------------------------------------------------------------------------------------------------
def ambient(season: str, weather: str, block: str) -> float:
    return SEASON_BASE.get(season, 12.0) + WEATHER_OFFSET.get(weather, 0.0) + BLOCK_OFFSET.get(block, 0.0)


def deficits(effective: torch.Tensor) -> tuple:
    """(cold, hot): degrees under the comfort band and over it."""
    return (COMFORT_LOW - effective).clamp(min=0.0), (effective - COMFORT_HIGH).clamp(min=0.0)


# ---- sources -------------------------------------------------------------------------------------------------------------------------------------------------
def add_source(engine, x: float, y: float, *, radius: float = FIRE_RADIUS, bonus: float = FIRE_BONUS, ticks: Optional[int] = None) -> dict:
    """A lit fire (or any warmth) at ``(x, y)``; ``ticks`` is its lifetime (None = until removed). A re-base shifts it with the world (``shift_sources``)."""
    source = {"x": float(x), "y": float(y), "radius": float(radius), "bonus": float(bonus), "until": None if ticks is None else int(engine.tick) + int(ticks)}
    engine.__dict__.setdefault("_warmth_sources", []).append(source)
    return source


def shift_sources(engine, dx: float, dy: float) -> int:
    sources = engine.__dict__.get("_warmth_sources", [])
    for source in sources:
        source["x"] += dx
        source["y"] += dy
    engine._temperature_hearths = None                      # the placed maps' hearths moved by the same shift: read them again
    return len(sources)


def _hearths(engine) -> list:
    """(x, y) of the placed maps' hearth entities, read at most every ``SOURCE_REFRESH`` ticks."""
    cache = engine.__dict__.get("_temperature_hearths")
    tick = int(engine.tick)
    if cache is not None and tick - cache[0] < SOURCE_REFRESH:
        return cache[1]
    found = []
    try:
        from systems.movement.map_contract import placed_group
        for entry in placed_group(getattr(engine, "_map_name", None)):
            for entity in entry.get("entities", ()):
                if entity.get("kind") in HEARTH_KINDS:
                    found.append((float(entity["position"][0]), float(entity["position"][1])))
    except Exception:  # noqa: BLE001 - a map without entities has no hearths
        found = []
    engine._temperature_hearths = (tick, found)
    return found


def _fires(engine) -> torch.Tensor:
    """float32 [F, 4]: x, y, radius, bonus of every warmth source alive this tick."""
    tick = int(engine.tick)
    sources = engine.__dict__.get("_warmth_sources")
    rows = [(x, y, FIRE_RADIUS, FIRE_BONUS) for x, y in _hearths(engine)]
    if sources:
        sources[:] = [s for s in sources if s["until"] is None or s["until"] > tick]
        rows += [(s["x"], s["y"], s["radius"], s["bonus"]) for s in sources]
    return torch.tensor(rows, dtype=torch.float32).reshape(-1, 4)


# ---- the instinct --------------------------------------------------------------------------------------------------------------------------------------------
def current_ambient(engine) -> float:
    try:
        from . import calendar as _calendar
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.harness import calendar as _calendar
    tick = int(engine.tick)
    nature = getattr(engine, "_nature_state", None) or {}
    season = str(nature.get("season") or _calendar.season_for_tick(tick))
    return ambient(season, str(nature.get("weather") or "clear"), _calendar.tick_to_time_block(tick))


def indoors(h_tensor: torch.Tensor) -> torch.Tensor:
    """bool [H]: inside a completed shelter structure (``H_SHELTER``) or inside an interior space (``H_SPACE`` != 0: a cottage, a smithy)."""
    import genesis_config as cfg
    return (h_tensor[:, cfg.H_SHELTER] > 0) | (h_tensor[:, cfg.H_SPACE] != 0)


def clothing_vector(engine, h_tensor: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """float32 [H]: the degrees each resident's best garment adds (``systems.clothing.insulation_of`` over the pack in ``engine.inventory_state``). Read every
    ``CLOTHING_REFRESH`` ticks (and when the table changes size); a row outside ``mask`` or without a uid or a pack gets 0.0."""
    cached = engine.__dict__.get("_clothing")
    tick = int(engine.tick)
    if cached is not None and cached["vec"].shape[0] == h_tensor.shape[0] and 0 <= tick - cached["tick"] < CLOTHING_REFRESH and bool((cached["mask"] | ~mask).all()):
        return cached["vec"]
    vec = torch.zeros(h_tensor.shape[0], dtype=torch.float32, device=h_tensor.device)
    try:
        try:
            from systems.clothing import insulation_of
        except ImportError:  # pragma: no cover - package import fallback
            from at_the_beginning.systems.clothing import insulation_of
    except ImportError:  # the item class is not part of this build: nobody is dressed
        insulation_of = None
    packs = (getattr(engine, "inventory_state", None) or {}).get("inventories", {})
    if insulation_of is not None and packs:
        for slot in mask.nonzero(as_tuple=False).flatten().tolist():
            uid = engine._human_uid_by_slot[slot]
            record = packs.get(f"human:{uid}") if uid else None
            if record:
                items: dict = {}
                for stack in record.get("items", []):
                    items[str(stack.get("kind", ""))] = items.get(str(stack.get("kind", "")), 0) + int(stack.get("quantity", 0))
                vec[slot] = insulation_of(items)
    engine._clothing = {"tick": tick, "vec": vec, "mask": mask.clone()}
    return vec


def effective_temperature(engine, h_tensor: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """float32 [H]: the felt temperature of every row (the ambient for rows outside ``mask``)."""
    import genesis_config as cfg
    felt = torch.full((h_tensor.shape[0],), current_ambient(engine), dtype=torch.float32, device=h_tensor.device)
    felt += SHELTER_BONUS * indoors(h_tensor).float() + CLOTHING_BONUS + clothing_vector(engine, h_tensor, mask)
    fires = _fires(engine).to(h_tensor.device)
    rows = mask.nonzero(as_tuple=False).flatten()
    if fires.shape[0] and rows.numel():
        near = torch.cdist(h_tensor[rows][:, [cfg.X, cfg.Y]], fires[:, :2]) <= fires[:, 2]
        felt[rows] += torch.where(near, fires[:, 3].expand_as(near), torch.zeros_like(fires[:, 3]).expand_as(near)).max(dim=1).values
    return felt


def apply(engine, h_tensor: torch.Tensor, mask: torch.Tensor) -> dict:
    """One tick of comfort effects on the rows of ``mask``; returns (and keeps on the engine) ``{"ambient", "cold", "hot"}``."""
    import genesis_config as cfg
    try:
        from . import calendar as _calendar
        from systems.roster.driver import needs_scale_vector
    except ImportError:  # pragma: no cover - package import fallback
        from at_the_beginning.harness import calendar as _calendar
        from at_the_beginning.systems.roster.driver import needs_scale_vector
    felt = effective_temperature(engine, h_tensor, mask)
    cold, hot = deficits(felt)
    cold, hot = torch.where(mask, cold, torch.zeros_like(cold)), torch.where(mask, hot, torch.zeros_like(hot))
    scale = torch.full_like(felt, float(_calendar.rate_scale("needs")))
    per_resident = needs_scale_vector(engine, h_tensor)
    if per_resident is not None:
        scale = scale * per_resident.to(scale.device).float()
    if bool((cold > 0).any()):
        h_tensor[:, cfg.H_STAMINA] = (h_tensor[:, cfg.H_STAMINA] - RATE_STAMINA * cold * scale).clamp(0.0, 100.0)
        h_tensor[:, cfg.MOOD] = (h_tensor[:, cfg.MOOD] - RATE_MOOD * cold * scale).clamp(0.0, 100.0)
    harm = (cold - HP_DAMAGE_FROM).clamp(min=0.0) + (hot - HP_DAMAGE_FROM).clamp(min=0.0)
    if bool((harm > 0).any()):
        h_tensor[:, cfg.HP] = h_tensor[:, cfg.HP] - RATE_HP * harm * scale * (harm > 0)
    if bool((hot > 0).any()):
        h_tensor[:, cfg.THIRST] = (h_tensor[:, cfg.THIRST] + RATE_THIRST * hot * scale).clamp(max=100.0)
    state = {"tick": int(engine.tick), "ambient": current_ambient(engine), "cold": cold, "hot": hot}
    engine._temperature = state
    totals = engine.__dict__.setdefault("_temperature_totals", {"hp": 0.0, "cold_ticks": 0, "damaging_ticks": 0, "sheltered_cold_ticks": 0})
    chilled = cold > 0                                                                     # resident-ticks under the band, for the winter scenario's report
    totals["hp"] += float((RATE_HP * harm * scale).sum())
    totals["cold_ticks"] += int(chilled.sum())
    totals["damaging_ticks"] += int((cold > HP_DAMAGE_FROM).sum())
    totals["sheltered_cold_ticks"] += int((chilled & indoors(h_tensor)).sum())
    return state


def instinct_temperature(ctx: dict, h_tensor: torch.Tensor, **kwargs) -> None:
    engine = ctx.get("engine")
    if engine is None or not ctx["h_mask"].any():
        return
    apply(engine, h_tensor, ctx["h_mask"])


def state_of(engine) -> Optional[dict]:
    return engine.__dict__.get("_temperature")


def cold_of(engine, slot: int) -> float:
    """Degrees under the comfort band this resident felt on the last tick (0.0 before the first tick or with the flag off)."""
    state = state_of(engine)
    return 0.0 if state is None else float(state["cold"][slot])


def hot_of(engine, slot: int) -> float:
    state = state_of(engine)
    return 0.0 if state is None else float(state["hot"][slot])


def install(engine) -> bool:
    """Register ``instinct_temperature`` once (idempotent; a new world re-registers because ``reset_world`` rebuilds the registry from the defaults)."""
    if any(entry["fn"] is instinct_temperature for entry in engine._registry):
        return False
    engine.register(instinct_temperature, priority=PRIORITY)
    return True
