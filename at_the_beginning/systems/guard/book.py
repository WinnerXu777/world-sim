"""The guard book: open posts and the blows the guards took. Pure data, no engine."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Optional

from . import GUARD_RADIUS


@dataclass
class Post:
    id: str
    guard: str
    kind: str                  # "person" (charge = resident id) | "place" (charge = the guard's anchor key, xy = where it is now)
    charge: str
    opened: int
    until: int
    radius: float = GUARD_RADIUS
    xy: Optional[tuple] = None  # place posts: refreshed every tick by the guard pass (never stored across a re-base)
    status: str = "open"       # open | closed
    reason: str = ""


@dataclass
class Blow:
    tick: int
    guard: str
    charge: str
    attacker: str
    post: str


@dataclass
class GuardBook:
    posts: dict = field(default_factory=dict)
    blows: list = field(default_factory=list)
    counts: Counter = field(default_factory=Counter)
    log: list = field(default_factory=list)
    answered: int = 0          # index into ``blows``: everything before it has been answered by the guard pass
    cool: dict = field(default_factory=dict)       # (guard, attacker) -> tick before which the guard does not answer again
    _next: int = 1

    def open(self, guard: str, kind: str, charge: str, tick: int, until: int, radius: float = GUARD_RADIUS) -> Optional[Post]:
        """A guard stands at most one post; a second call while one is open returns None."""
        if self.of_guard(guard) is not None:
            return None
        post = Post(f"post_{self._next:05d}", guard, kind, charge, int(tick), int(until), float(radius))
        self._next += 1
        self.posts[post.id] = post
        self.counts["opened"] += 1
        self.note(tick, "opened", post)
        return post

    def active(self) -> list:
        return [p for p in self.posts.values() if p.status == "open"]

    def of_guard(self, guard: str) -> Optional[Post]:
        return next((p for p in self.posts.values() if p.status == "open" and p.guard == guard), None)

    def for_charge(self, charge: str) -> list:
        return sorted((p for p in self.posts.values() if p.status == "open" and p.kind == "person" and p.charge == charge), key=lambda p: p.id)

    def places(self) -> list:
        return sorted((p for p in self.posts.values() if p.status == "open" and p.kind == "place" and p.xy is not None), key=lambda p: p.id)

    def close(self, post_id: str, reason: str, tick: int) -> Optional[Post]:
        post = self.posts.get(post_id)
        if post is None or post.status != "open":
            return None
        post.status, post.reason = "closed", reason
        self.counts[f"closed:{reason}"] += 1
        self.note(tick, f"closed:{reason}", post)
        return post

    def blow(self, tick: int, guard: str, charge: str, attacker: str, post: str) -> None:
        self.blows.append(Blow(int(tick), guard, charge, attacker, post))
        self.counts["intercepted"] += 1
        if len(self.blows) > 4096:                     # bounded: drop what was answered long ago
            cut = max(0, self.answered - 1024)
            del self.blows[:cut]
            self.answered -= cut

    def note(self, tick: int, what: str, post: Post) -> None:
        self.log.append({"tick": int(tick), "what": what, "post": post.id, "guard": post.guard, "kind": post.kind, "charge": post.charge})
        if len(self.log) > 2000:
            del self.log[:500]
