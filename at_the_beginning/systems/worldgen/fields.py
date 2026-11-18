"""Global coherent fields sampled over any rectangular window of world tiles (int64 tile coordinates).

Every field is defined everywhere and is a function of (seed, tile) only, so adjacent chunks agree by construction.
"""
from __future__ import annotations

import numpy as np

from . import noise
from .spec import FIELD_MAX

# Field ids (part of the hash domain; never reuse).
F_ELEVATION, F_MOISTURE, F_TEMPERATURE, F_RIVER, F_RIVER_WIDTH, F_FORD, F_FOREST, F_LAKE_EDGE = 1, 2, 3, 4, 5, 6, 7, 8

WL_ELEVATION = (256, 128, 64, 32, 16)
WL_MOISTURE = (256, 128, 64, 32)
WL_TEMPERATURE = (512, 256, 128, 64)
WL_RIVER = (128, 64, 32)
WL_RIVER_WIDTH = (64, 32)
WL_FORD = (16, 8)
WL_FOREST = (64, 32, 16)
WL_LAKE_EDGE = (16, 8)


def window_grid(gx0: int, gy0: int, width: int, height: int):
    """Global tile coordinate arrays (int64, shape [height, width]) for a window starting at tile (gx0, gy0)."""
    xs = np.arange(gx0, gx0 + width, dtype=np.int64)
    ys = np.arange(gy0, gy0 + height, dtype=np.int64)
    return np.broadcast_to(xs[None, :], (height, width)).copy(), np.broadcast_to(ys[:, None], (height, width)).copy()


def elevation(seed: int, gx, gy):
    return noise.quantise(noise.fbm(seed, F_ELEVATION, gx, gy, WL_ELEVATION))


def moisture(seed: int, gx, gy):
    return noise.quantise(noise.fbm(seed, F_MOISTURE, gx, gy, WL_MOISTURE))


def temperature(seed: int, gx, gy):
    return noise.quantise(noise.fbm(seed, F_TEMPERATURE, gx, gy, WL_TEMPERATURE))


def river_distance(seed: int, gx, gy):
    """Approximate distance, in 1/16 tile, from each tile to the zero crossing (centre line) of a smooth field.

    |v - 0.5| divided by the local gradient (forward differences, L1 norm) gives tiles-to-the-line regardless of how flat the
    field is, so river width does not blow up at saddle points; where the field is almost flat the distance is large and
    there is simply no river (a stream ends).
    """
    v = noise.fbm(seed, F_RIVER, gx, gy, WL_RIVER)
    vx = noise.fbm(seed, F_RIVER, gx + 1, gy, WL_RIVER)
    vy = noise.fbm(seed, F_RIVER, gx, gy + 1, WL_RIVER)
    grad = np.abs(vx - v) + np.abs(vy - v)
    d = np.abs(v - 0.5) / np.maximum(grad, 1e-6)
    return np.clip(np.floor(d * 16.0), 0, FIELD_MAX).astype(np.int32)


def river_width(seed: int, gx, gy):
    return noise.quantise(noise.fbm(seed, F_RIVER_WIDTH, gx, gy, WL_RIVER_WIDTH))


def ford_noise(seed: int, gx, gy):
    return noise.quantise(noise.fbm(seed, F_FORD, gx, gy, WL_FORD))


def forest_noise(seed: int, gx, gy):
    return noise.quantise(noise.fbm(seed, F_FOREST, gx, gy, WL_FOREST))


def lake_edge_noise(seed: int, gx, gy):
    """float64 in [0, 1) used to roughen lake outlines (kept as float: it only feeds an integer floor below)."""
    return noise.fbm(seed, F_LAKE_EDGE, gx, gy, WL_LAKE_EDGE)
