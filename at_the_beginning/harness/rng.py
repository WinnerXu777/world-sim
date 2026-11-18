"""Counter-based random streams: ``rng(world_seed, tick, system, entity_id)``.

The legacy engine draws from process-global generators (``random``, ``torch.rand``, ``np.random``), so a result depends on
call order and on how many residents exist. Here every draw is a pure function of ``(world_seed, tick, system, entity_id,
counter)``: adding a resident, reordering systems, or replaying from a save does not change anyone else's numbers, and the
chunk generator can use the same primitives.

Two interfaces, both pure:

* ``rng(...)`` returns a ``Stream`` for scalar use (``random()``, ``uniform``, ``randint``, ``choice``, ``shuffle``, ``normal``);
  it wraps ``numpy.random.Philox`` keyed by a 128-bit blake2b digest of the coordinates.
* ``uniform_for_ids(...)`` / ``normal_for_ids(...)`` are vectorised: element ``i`` depends only on ``ids[i]`` (and the other
  coordinates), never on the other elements or the array length. They use a splitmix64-style integer hash in numpy.

Nothing here touches the global RNGs. ``system`` is a string and is hashed, not interned, so it is stable across processes
(Python's ``hash()`` is not).
"""
from __future__ import annotations

import hashlib
import math
from typing import Sequence

import numpy as np

_MASK64 = (1 << 64) - 1
_GOLDEN = 0x9E3779B97F4A7C15
_M1 = 0xBF58476D1CE4E5B9
_M2 = 0x94D049BB133111EB


def _digest(*parts) -> bytes:
    h = hashlib.blake2b(digest_size=16)
    for part in parts:
        h.update(repr(part).encode("utf-8") if not isinstance(part, bytes) else part)
        h.update(b"\x1f")
    return h.digest()


def system_key(system: str) -> int:
    """Stable 64-bit id of a system name (same in every process)."""
    return int.from_bytes(hashlib.blake2b(str(system).encode("utf-8"), digest_size=8).digest(), "little")


def entity_key(entity_id) -> int:
    """Stable 64-bit key of an entity id (int or string like ``h_000003``)."""
    if isinstance(entity_id, (int, np.integer)) and not isinstance(entity_id, bool):
        return int(entity_id) & _MASK64
    return int.from_bytes(hashlib.blake2b(str(entity_id).encode("utf-8"), digest_size=8).digest(), "little")


class Stream:
    """A short deterministic stream for one ``(seed, tick, system, entity)`` coordinate."""

    __slots__ = ("_gen", "coords")

    def __init__(self, world_seed: int, tick: int, system: str, entity_id=0):
        self.coords = (int(world_seed), int(tick), str(system), entity_id)
        key = np.frombuffer(_digest(int(world_seed), int(tick), system_key(system), entity_key(entity_id)), dtype=np.uint64)
        self._gen = np.random.Generator(np.random.Philox(key=key))

    def random(self) -> float:
        return float(self._gen.random())

    def uniform(self, low: float = 0.0, high: float = 1.0) -> float:
        return float(low) + (float(high) - float(low)) * self.random()

    def randint(self, low: int, high: int) -> int:
        """Inclusive on both ends, like ``random.randint``."""
        return int(self._gen.integers(int(low), int(high) + 1))

    def normal(self, mean: float = 0.0, std: float = 1.0) -> float:
        return float(mean) + float(std) * float(self._gen.standard_normal())

    def choice(self, items: Sequence):
        if not len(items):
            raise IndexError("choice from an empty sequence")
        return items[int(self._gen.integers(0, len(items)))]

    def shuffle(self, items: list) -> list:
        """Shuffle ``items`` in place and return it."""
        for i in range(len(items) - 1, 0, -1):
            j = int(self._gen.integers(0, i + 1))
            items[i], items[j] = items[j], items[i]
        return items

    def uniform_array(self, n: int) -> np.ndarray:
        return self._gen.random(int(n))

    def __repr__(self) -> str:
        return f"Stream{self.coords!r}"


def rng(world_seed: int, tick: int, system: str, entity_id=0) -> Stream:
    """The stream for one coordinate. Same arguments, same numbers, in any process, in any call order."""
    return Stream(world_seed, tick, system, entity_id)


def _mix(x: np.ndarray) -> np.ndarray:
    """splitmix64 finaliser over uint64 arrays (wrapping arithmetic)."""
    with np.errstate(over="ignore"):
        x = (x ^ (x >> np.uint64(30))) * np.uint64(_M1)
        x = (x ^ (x >> np.uint64(27))) * np.uint64(_M2)
        return x ^ (x >> np.uint64(31))


def _base(world_seed: int, tick: int, system: str, salt: int) -> np.uint64:
    h = int.from_bytes(_digest(int(world_seed), int(tick), system_key(system), int(salt)), "little") & _MASK64
    return np.uint64(h)


def hash_for_ids(world_seed: int, tick: int, system: str, ids, salt: int = 0) -> np.ndarray:
    """uint64 hash per id; element ``i`` depends only on ``ids[i]`` and the scalar coordinates."""
    keys = np.asarray([entity_key(i) for i in ids] if not isinstance(ids, np.ndarray) else ids, dtype=np.uint64)
    base = _base(world_seed, tick, system, salt)
    with np.errstate(over="ignore"):
        return _mix(_mix(keys * np.uint64(_GOLDEN) + base) + base)


def uniform_for_ids(world_seed: int, tick: int, system: str, ids, salt: int = 0) -> np.ndarray:
    """Float64 uniforms in [0, 1), one per id, independent of the other ids and of the array length."""
    return (hash_for_ids(world_seed, tick, system, ids, salt) >> np.uint64(11)).astype(np.float64) / float(1 << 53)


def normal_for_ids(world_seed: int, tick: int, system: str, ids, salt: int = 0) -> np.ndarray:
    """Standard normals via Box-Muller from two salted uniform draws per id."""
    u1 = uniform_for_ids(world_seed, tick, system, ids, salt * 2 + 1)
    u2 = uniform_for_ids(world_seed, tick, system, ids, salt * 2 + 2)
    return np.sqrt(-2.0 * np.log(np.maximum(u1, 1e-300))) * np.cos(2.0 * math.pi * u2)
