"""Pure rules of the bonds (no engine, no I/O): thresholds and step sizes. Placeholders in the same sense as the ladder's: named, in one place, easy to tune."""
from __future__ import annotations

GRUDGE = -0.05              # a closeness at or below this is a grudge (has_grudge) and, seen from the other side, harm (has_harmed)
HOSTILE = -0.2              # below this a resident does not take a friendly approach (befriend / court refused: refuse_distrust)
BEFRIEND_STEP = 0.05
BEFRIEND_CAP = 0.6          # befriending stops adding closeness here (deeper bonds come from help and time, not from talk)
COURT_STEP = 0.04
COURT_MIN = 0.1             # courting needs some fondness already
COURT_CAP = 0.85
APOLOGY_STEP = 0.12         # scaled by the listener's mercy: 0.5 + mercy of a step (mercy 0..1)
APOLOGY_GRAVE = -0.5        # a grudge deeper than this takes a half-size apology
APOLOGY_VS_THIEF = 0.5      # against a thief tag the apology is worth half (restitution is what removes it)
FORGIVE_STEP = 0.15
SELF_RELIEF = 0.02          # the apologiser's own closeness to the forgiven party eases a little


def befriend_step(closeness_a_to_b: float, closeness_b_to_a: float) -> float:
    """The closeness added each way; 0 once both are at the cap."""
    return BEFRIEND_STEP if min(closeness_a_to_b, closeness_b_to_a) < BEFRIEND_CAP else 0.0


def court_step(closeness: float) -> float:
    return COURT_STEP if closeness < COURT_CAP else 0.0


def apology_effect(closeness_of_listener: float, mercy: float, thief: bool) -> float:
    """What the apology adds to the listener's closeness (toward 0, never past it)."""
    if closeness_of_listener > GRUDGE:
        return 0.0
    step = APOLOGY_STEP * (0.5 + max(0.0, min(1.0, mercy)))
    if closeness_of_listener < APOLOGY_GRAVE:
        step *= 0.5
    if thief:
        step *= APOLOGY_VS_THIEF
    return round(min(step, -closeness_of_listener), 4)


def forgive_delta(closeness: float) -> float:
    """What forgiving adds to the forgiver's own closeness (toward 0, never past it); 0 when there is no grudge."""
    if closeness > GRUDGE:
        return 0.0
    return round(min(FORGIVE_STEP, -closeness), 4)
