"""Integer-hash coherent noise, vectorised with numpy, bit-identical on every machine.

No `random`, no `numpy.random`, no torch. The only floating point operations are + - * / and comparisons on float64 (IEEE-754
correctly rounded), with power-of-two lattice spacings so lattice coordinates and fractions are exact; no transcendental
functions and no reductions over floats. Every field is quantised to FIELD_BITS integers before anything thresholds it.
"""
from __future__ import annotations

import numpy as np

from .spec import FIELD_MAX

MASK64 = (1 << 64) - 1
_C1 = 0xBF58476D1CE4E5B9
_C2 = 0x94D049BB133111EB
_GOLDEN = 0x9E3779B97F4A7C15
_P1 = np.uint64(0x9E3779B185EBCA87)
_P2 = np.uint64(0xC2B2AE3D27D4EB4F)
_U30, _U27, _U31 = np.uint64(30), np.uint64(27), np.uint64(31)
_UC1, _UC2 = np.uint64(_C1), np.uint64(_C2)


def mix_int(value: int) -> int:
    """splitmix64 finaliser on a Python int (scalar seed derivation)."""
    value &= MASK64
    value ^= value >> 30
    value = (value * _C1) & MASK64
    value ^= value >> 27
    value = (value * _C2) & MASK64
    value ^= value >> 31
    return value


def derive(seed: int, *parts: int) -> int:
    """Derive a 64-bit sub-seed from a world seed and integers (field id, octave, region coordinates ...)."""
    state = mix_int((int(seed) & MASK64) + _GOLDEN)
    for part in parts:
        state = mix_int(state ^ ((int(part) & MASK64) + _GOLDEN))
    return state


def mix_array(h: np.ndarray) -> np.ndarray:
    with np.errstate(over="ignore"):
        h = h ^ (h >> _U30)
        h = h * _UC1
        h = h ^ (h >> _U27)
        h = h * _UC2
        h = h ^ (h >> _U31)
    return h


def lattice_hash(seed64: int, ix: np.ndarray, iy: np.ndarray) -> np.ndarray:
    """uint64 hash of integer lattice points (int64 arrays, negatives allowed)."""
    with np.errstate(over="ignore"):
        h = ix.astype(np.uint64) * _P1 + iy.astype(np.uint64) * _P2 + np.uint64(seed64)
    return mix_array(h)


_TWO53 = float(1 << 53)


def unit_float(h: np.ndarray) -> np.ndarray:
    """uint64 hash -> float64 in [0, 1), exact."""
    return (h >> np.uint64(11)).astype(np.float64) * (1.0 / _TWO53)


def _fade(t: np.ndarray) -> np.ndarray:
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def value_noise(seed64: int, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """2D value noise in [0, 1). x, y are float64 lattice coordinates (already divided by a power-of-two wavelength)."""
    x0 = np.floor(x)
    y0 = np.floor(y)
    fx = _fade(x - x0)
    fy = _fade(y - y0)
    ix = x0.astype(np.int64)
    iy = y0.astype(np.int64)
    ix1 = ix + 1
    iy1 = iy + 1
    a = unit_float(lattice_hash(seed64, ix, iy))
    b = unit_float(lattice_hash(seed64, ix1, iy))
    c = unit_float(lattice_hash(seed64, ix, iy1))
    d = unit_float(lattice_hash(seed64, ix1, iy1))
    top = a + (b - a) * fx
    bottom = c + (d - c) * fx
    return top + (bottom - top) * fy


def fbm(seed: int, field_id: int, gx: np.ndarray, gy: np.ndarray, wavelengths: tuple[int, ...]) -> np.ndarray:
    """Fractal sum of value-noise octaves over global tile coordinates (int64 arrays), normalised to [0, 1).

    Wavelengths are powers of two in tiles; octave k has amplitude 2**-k.
    """
    total = None
    weight = 0.0
    amp = 1.0
    gxf = gx.astype(np.float64)
    gyf = gy.astype(np.float64)
    for octave, wavelength in enumerate(wavelengths):
        inv = 1.0 / float(wavelength)               # exact: power of two
        n = value_noise(derive(seed, field_id, octave), gxf * inv, gyf * inv)
        total = n * amp if total is None else total + n * amp
        weight += amp
        amp *= 0.5
    return total / weight


def quantise(v: np.ndarray, contrast: float = 2.0) -> np.ndarray:
    """[0, 1) float field -> int32 in [0, FIELD_MAX], stretched about 0.5 by `contrast` (a power of two) so thresholds have room."""
    v = (v - 0.5) * contrast + 0.5
    q = np.floor(v * 4096.0).astype(np.int32)
    return np.clip(q, 0, FIELD_MAX)


def tile_hash(seed: int, salt: int, gx: np.ndarray, gy: np.ndarray) -> np.ndarray:
    """Per-tile uint64 hash for independent random decisions (slice bits for several decisions)."""
    return lattice_hash(derive(seed, 0x7411E, salt), gx.astype(np.int64), gy.astype(np.int64))
