"""The combat hook of the guard posts (``systems/combat/modifiers.COMBAT_MODIFIER``): a guard in reach of the person (or the place) being attacked takes the blow at ``TAKE`` of the damage.

A pure function of the tensors and the guard book (it records the blow in the book, which is its own state, never in a tensor), deterministic, never chained: the resolver calls it once per
intent. A guard that is dead, dormant, restrained, below ``MIN_HP``, out of reach, or the attacker itself does not intercept. The first post by id that qualifies takes the blow.
"""
from __future__ import annotations

import math

from . import MIN_HP, TAKE


def make(engine, book_of):
    """The hook for ``engine``; ``book_of()`` returns the guard book (looked up at call time, so a re-created book is picked up)."""
    import genesis_config as cfg

    def modifier(h_tensor, attacker_slot: int, target_slot: int, damage: float):
        book = book_of()
        if book is None or not book.posts:
            return target_slot, damage
        uids = engine._human_uid_by_slot
        if target_slot >= len(uids) or not uids[target_slot]:
            return target_slot, damage
        charge = uids[target_slot]
        tx, ty = float(h_tensor[target_slot, cfg.X]), float(h_tensor[target_slot, cfg.Y])
        dormant = engine.__dict__.get("_dormant_h")
        posts = list(book.for_charge(charge))
        for post in book.places():
            if post.guard != charge and math.hypot(post.xy[0] - tx, post.xy[1] - ty) <= post.radius:
                posts.append(post)
        for post in sorted(posts, key=lambda p: p.id):
            guard_slot = engine._human_slot_for_id(post.guard)
            if guard_slot is None or guard_slot < 0 or guard_slot in (attacker_slot, target_slot):
                continue
            if float(h_tensor[guard_slot, cfg.HP]) < MIN_HP or float(h_tensor[guard_slot, cfg.H_RESTRAINED]) > 0.0:
                continue
            if dormant is not None and guard_slot < len(dormant) and bool(dormant[guard_slot]):
                continue
            if math.hypot(float(h_tensor[guard_slot, cfg.X]) - tx, float(h_tensor[guard_slot, cfg.Y]) - ty) > post.radius:
                continue
            attacker = uids[attacker_slot] if attacker_slot < len(uids) else ""
            book.blow(int(getattr(engine, "tick", 0)), post.guard, charge, attacker, post.id)
            return guard_slot, float(damage) * TAKE
        return target_slot, damage

    return modifier
