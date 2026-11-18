from __future__ import annotations

try:
    from systems.health.infection import apply_infection_tick
except ImportError:  # pragma: no cover - package import fallback
    from at_the_beginning.systems.health.infection import apply_infection_tick

__all__ = ["apply_infection_tick"]
