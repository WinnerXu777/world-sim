"""Pure rules of the emotions and drives (no engine, no I/O): thresholds, rates and the closed forms. Placeholders in the same sense as the ladder's: named, in one place, easy to tune."""
from __future__ import annotations

# -- grudge decay (daily, lazy) ---------------------------------------------------------------------------------------------------
GRUDGE_DECAY_PER_DAY = 0.04       # a negative closeness rises this much a day toward 0 unless refreshed by a new offence
GRAVE = -0.7                      # a closeness this low is tagged ``grave`` and from then on only rises to ``GRAVE_FLOOR``: a betrayal never fully fades
GRAVE_FLOOR = -0.35
GRAVE_TAG = "grave"
MAX_CATCH_UP_DAYS = 30            # a resident that slept for longer applies this many days at once
OWNED_TAGS = ("thief",)           # the reputation pass decays these (faster, by mercy) and removes the tag at 0: left alone here

# -- grief ------------------------------------------------------------------------------------------------------------------------
GRIEF_MIN = 0.5                   # closeness at which a death is grieved (kin and close friends)
GRIEF_DAYS = 3.0                  # a grief fades to nothing over this many game days
GRIEF_BASE, GRIEF_PER_CLOSENESS = 0.4, 0.6
GRIEF_MOOD_SHOCK = 20.0           # mood points lost at full grief, once
COMFORT_RELIEF = 0.12             # a comforting neighbour lifts the level by this
COMFORT_MIN = 0.3                 # closeness for a neighbour to comfort

# -- jealousy ---------------------------------------------------------------------------------------------------------------------
PARTNER_MIN = 0.6                 # mutual closeness that makes two residents partners (the court verb's range)
RIVAL_MIN = 0.3                   # the partner's closeness to the third resident that counts as attention
TENSION_STEP = 0.1                # per pass, scaled by how possessive the resident is (pride and vengefulness)
TENSION_DECAY_PER_DAY = 0.25
TENSION_WARN = 0.6                # the resident holds it against the rival (closeness drops) and may warn
TENSION_RESENT = 0.03             # closeness lost per pass above ``TENSION_WARN``

# -- drives (two first: curiosity and thrift) -------------------------------------------------------------------------------------
CURIOSITY_RISE_PER_DAY = 0.12     # boredom: scaled by 0.5 + the curiosity trait
CURIOSITY_DISCHARGE = 0.4         # a new place learned
THRIFT_PULL_PER_DAY = 0.25        # toward the trait-set point
THRIFT_SCARCITY = 0.1             # a resident with almost no food on it hoards a little more each day

# -- loyalty ----------------------------------------------------------------------------------------------------------------------
LOYALTY_SPAN = 0.3                # a fully loyal resident (trait 1.0) asks 0.15 less closeness to help or defend, a disloyal one (0.0) 0.15 more


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def threshold(base: float, loyalty_trait: float) -> float:
    """The closeness a resident asks before it helps or defends someone (``base`` at the balanced trait 0.5)."""
    return round(float(base) - LOYALTY_SPAN * (clamp(loyalty_trait) - 0.5), 4)


def decay_grudge(closeness: float, days: int, grave: bool) -> float:
    """Closeness after ``days`` of quiet: a negative value rises toward 0 (a ``grave`` one only to ``GRAVE_FLOOR``); never past the target, never a positive value touched."""
    if closeness >= 0.0 or days <= 0:
        return closeness
    target = GRAVE_FLOOR if grave else 0.0
    if closeness >= target:
        return closeness
    return round(min(target, closeness + GRUDGE_DECAY_PER_DAY * min(int(days), MAX_CATCH_UP_DAYS)), 4)


def is_grave(closeness: float, tags) -> bool:
    return GRAVE_TAG in (tags or ()) or closeness <= GRAVE


def grief_start(closeness: float) -> float:
    return round(clamp(GRIEF_BASE + GRIEF_PER_CLOSENESS * clamp(closeness)), 4)


def grief_now(grief, tick: int, day_ticks: int) -> float:
    """The level of a grief record now: its start level fading linearly over ``GRIEF_DAYS``, less the comfort received; 0 for none."""
    if not isinstance(grief, dict):
        return 0.0
    span = max(1.0, GRIEF_DAYS * float(day_ticks))
    fade = max(0.0, 1.0 - (float(tick) - float(grief.get("since", tick))) / span)
    return round(max(0.0, float(grief.get("level", 0.0)) * fade - float(grief.get("relief", 0.0))), 4)


def possessiveness(traits: dict) -> float:
    return clamp(0.5 * float(traits.get("pride", 0.5)) + 0.5 * float(traits.get("vengefulness", 0.5)))


def tension_after(tension: float, days: float) -> float:
    return round(max(0.0, float(tension) - TENSION_DECAY_PER_DAY * float(days)), 4)


def thrift_point(traits: dict) -> float:
    """Where a resident's thrift settles with nothing pressing: greedy and cautious hoard, sociable give freely."""
    return round(clamp(0.2 + 0.6 * float(traits.get("greed", 0.5)) + 0.2 * float(traits.get("caution", 0.5)) - 0.2 * float(traits.get("sociability", 0.5))), 4)
