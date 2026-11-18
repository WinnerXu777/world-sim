"""Which verbs the resident's *driver* will actually carry out (D-008, data only).

The predicates in ``predicates.py`` answer "does the world allow this?". For a roster resident (``record["roster"]``, moved by
``systems.roster.driver`` and fed by ``systems.roster.needs``) some legacy tasks stay ``active`` forever and do nothing, because task
movement is suppressed for them (measured in ``tests/test_actions_roster.py``, ``1008_actions.md`` 10.5). Offering such a verb to Tier 1/2
means the model scores something the action runner will refuse, so while the driver mode is ``"roster"`` the engine turns the verdict of
these verbs into ``roster_driven``:

* always: ``drink``, ``work_shift``, ``gather_resource``, ``follow``, ``attack``, ``avoid``, ``explore_toward``;
* ``eat`` only when the food is at a site or a resource (``detail["source"]`` is ``site`` or ``entity``); eating from the pack works.

``config.DRIVER_MODE`` is ``"roster"`` until D-008 is decided; ``"agent"`` switches the whole table off (every verb is judged by the world
alone). ``AffordanceEngine(driver_mode=...)`` overrides it per engine. Nothing here changes a predicate; the table is applied by the engine
after the predicate answers, in ``options``, ``legal``, ``resolve`` and ``mask`` alike, so the runner (which asks ``legal``) and Tier 1 get
the same answer.
"""
from __future__ import annotations

from typing import Optional

from . import config
from .verdicts import Verdict

ALWAYS = frozenset({"drink", "work_shift", "gather_resource", "follow", "attack", "avoid", "explore_toward", "approach_node"})
AT_SOURCE = {"eat": ("site", "entity")}          # verb -> verdict ``source`` values that need the driver to walk there


def is_roster(record: Optional[dict]) -> bool:
    from systems.roster.driver import is_anchor_driven      # D-008: a resident with driver "agent" is judged by the world alone
    return is_anchor_driven((record or {}).get("roster"))


def demoted(verb: str, verdict: Verdict) -> bool:
    if verb in ALWAYS:
        return True
    sources = AT_SOURCE.get(verb)
    return bool(sources) and (verdict.detail or {}).get("source") in sources


def restrict(S, verb: str, verdict: Verdict, mode: Optional[str] = None) -> Verdict:
    """The verdict the engine reports: ``roster_driven`` when the world allows the verb but the roster driver would not carry it out."""
    if not verdict.ok or (mode or config.DRIVER_MODE) != "roster" or not is_roster(S.obs.record) or not demoted(verb, verdict):
        return verdict
    return Verdict(False, "roster_driven", {"verb": verb, **{k: v for k, v in (verdict.detail or {}).items() if k in ("source", "place", "item")}},
                   verdict.reachability, verdict.distance)
