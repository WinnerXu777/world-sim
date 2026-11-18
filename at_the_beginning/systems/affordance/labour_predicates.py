"""Legality of the labour verbs ``work_for`` and ``collect_wage`` (``EDEN_LABOUR=1``; flag off: ``not_wired`` and no candidates). Imported at the end of ``predicates.py``."""
from __future__ import annotations

from . import config
from .predicates import Verdict, _alive, _nearest_neighbours, _target, no, verb, yes


def _flag_off():
    from systems.labour import enabled
    return None if enabled() else no("not_wired", why="EDEN_LABOUR is off")


def _jobs(S):
    from systems.labour import runtime
    return runtime.of(S.services)


def _candidates_work(S):
    from systems.labour import enabled
    if not enabled() or not S.obs.alive or _jobs(S).of_worker(S.actor, S.obs.tick) is not None:
        return []
    return [{"target": n.id} for n in _nearest_neighbours(S) if n.dist <= config.RADIUS["interact"]]


@verb("work_for", "can_work_for", _candidates_work)
def work_for(S, target: str = "") -> Verdict:
    dead = _alive(S) or _flag_off()
    if dead:
        return dead
    n, problem = _target(S, target)
    if problem:
        return problem
    if _jobs(S).of_worker(S.actor, S.obs.tick) is not None:
        return no("already_working")
    reach = S.interact(n.x, n.y)
    return yes(distance=reach.distance) if reach.ok else Verdict(False, reach.reason, {"target": target}, "", reach.distance)


def _candidates_collect(S):
    from systems.labour import enabled
    if not enabled() or not S.obs.alive:
        return []
    job = _jobs(S).of_worker(S.actor, S.obs.tick)
    if job is None or S.obs.tick < job.ready_at or job.employer not in {n.id for n in _nearest_neighbours(S) if n.dist <= config.RADIUS["interact"]}:
        return []
    return [{"target": job.employer}]


@verb("collect_wage", "can_collect_wage", _candidates_collect)
def collect_wage(S, target: str = "") -> Verdict:
    dead = _alive(S) or _flag_off()
    if dead:
        return dead
    n, problem = _target(S, target)
    if problem:
        return problem
    job = _jobs(S).between(S.actor, target, S.obs.tick)
    if job is None:
        return no("no_job", target=target)
    if S.obs.tick < job.ready_at:
        return no("shift_not_done", ready_at=job.ready_at, tick=S.obs.tick)
    if S.world.items.quantity(target, job.item) < job.qty:
        return no("employer_cannot_pay", item=job.item, qty=job.qty)
    reach = S.interact(n.x, n.y)
    if not reach.ok:
        return Verdict(False, reach.reason, {"target": target}, "", reach.distance)
    room = S.world.items.room(S.actor, job.item)
    if room is not None and room < job.qty:
        return no("no_room", item=job.item, room=room)
    return yes({"job": {"id": job.id, "item": job.item, "qty": job.qty}}, distance=reach.distance)
