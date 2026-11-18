"""Robbery and arrest (``EDEN_ROB=1``, default off; needs ``EDEN_AGENT_ACTIONS``, ``EDEN_AGENT_LADDER``, ``EDEN_REPUTATION``, ``EDEN_JUSTICE`` and ``EDEN_DEFEND``): the ladder's top rung and its answer.

``rob`` is the rung above ``steal``: a desperate resident with a low conscience takes food from a resident's pack by force. The victim can resist, so the outcome is a contest that is a pure
function of both residents' hp and aggression and one deterministic draw (``world.rng("rob", ...)``); a guard standing over the victim (``systems/guard``) is a deterrent in the ladder and the
victim's best defence in the contest. A robbery is seen: the culprit is known at once (``reputation.record_theft(..., violent=True)``), the opinion drop is doubled, and the justice pass takes it
from there; an authority that levies damages from a robber then restrains them (``arrest_or_restrain``) for ``ARREST_TICKS`` through ``harness/restraint.py`` (``EDEN_RESTRAINT``), after which the
restraint counter runs out by itself. Pure rules live here; the verbs in ``actions/rob_verbs.py``, the legality in ``affordance/rob_predicates.py``, the rung in ``actions/ladder.py``.
"""
from __future__ import annotations

import os

ENV = "EDEN_ROB"
ROB_MIN_HP = 50.0            # a robber needs to be fit
ROB_MAX_CONSCIENCE = 0.0     # ``ladder.conscience`` at or below this (steal needs no such bar; the average resident sits near +0.03 and never robs)
ROB_DAMAGE = 12.0            # the victim's hp lost when it is robbed
ROB_BACKLASH = 8.0           # the robber's hp lost when the victim fights it off
OPINION_FACTOR = 2.0         # a robbery costs the victim's regard twice as much as a theft
WITNESS_RADIUS = 80.0        # an awake authority this close to the victim deters the robber
ARREST_TICKS = 300           # how long a convicted robber is held
GUARD_BONUS = 0.35           # a guard in reach adds this to the victim's power
FLOOR, CEIL = 0.10, 0.90     # the robber's chance never leaves this band


def enabled() -> bool:
    return os.environ.get(ENV, "") == "1"


def power(hp: float, aggression: float, guarded: bool = False) -> float:
    """How well a resident fights: its health share, scaled up by temper (0.4 .. 1.0), plus the guard bonus."""
    return max(0.0, min(1.0, float(hp) / 100.0)) * (0.4 + 0.6 * max(0.0, min(1.0, float(aggression)))) + (GUARD_BONUS if guarded else 0.0)


def p_success(robber_power: float, victim_power: float) -> float:
    return max(FLOOR, min(CEIL, 0.5 + 0.5 * (float(robber_power) - float(victim_power))))


def robber_on_record(engine, human_id: str) -> bool:
    """True when the reputation book holds a robbery by this resident whose culprit is known (what an authority needs to hold them)."""
    from systems.actions import reputation
    return any(t.violent and t.thief == human_id and t.culprit_known for t in reputation.of(engine).thefts)


def controlled(engine, slot) -> bool:
    """A player's body: never robbed, never restrained by the model plane."""
    control = getattr(engine, "player_control", None)
    return slot is not None and control is not None and control.describe_human_slot(int(slot)) is not None
