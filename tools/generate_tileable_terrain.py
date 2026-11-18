"""Generate seamless 48x48 terrain tiles for the 2D client (original work, no third-party art).

Every tile is periodic by construction (all geometry is computed modulo the tile size), so tiles
repeat without seams. Palettes are sampled from the existing medieval_village pack so the new tiles
sit next to the existing grass, buildings and props.

  .venv/Scripts/python.exe tools/generate_tileable_terrain.py [--out myassets/terrain] [--preview PATH]

Outputs: cobble_tileable.png, plank_floor.png, flagstone_slate.png. Deterministic for a given seed.
"""
import argparse
import json
import random
from pathlib import Path

import numpy as np
from PIL import Image

SIZE = 48
SEED = 1006


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _shade(c, f):
    return tuple(max(0, min(255, int(round(v * f)))) for v in c)


def _torus_delta(a, b, size=SIZE):
    d = (a - b + size / 2) % size - size / 2
    return d


def cobble(rng):
    """Toroidal Voronoi stones separated by dark joints, with an upper-left highlight."""
    stones = [_rgb(h) for h in ("#918990", "#86808c", "#8c7e7f", "#a39595", "#afa4a1")]
    joint = _rgb("#545663")
    joint_soft = _rgb("#686977")
    cell = 16  # 3 x 3 seeds
    seeds = []
    for gy in range(SIZE // cell):
        for gx in range(SIZE // cell):
            seeds.append(((gx + 0.5) * cell + rng.uniform(-4, 4), (gy + 0.5) * cell + rng.uniform(-4, 4)))
    colors = [stones[rng.randrange(len(stones))] for _ in seeds]
    img = np.zeros((SIZE, SIZE, 3), dtype=np.uint8)
    for y in range(SIZE):
        for x in range(SIZE):
            px, py = x + 0.5, y + 0.5
            dists = []
            for i, (sx, sy) in enumerate(seeds):
                dx, dy = _torus_delta(px, sx), _torus_delta(py, sy)
                dists.append((dx * dx + dy * dy) ** 0.5)
            order = sorted(range(len(seeds)), key=lambda i: dists[i])
            i0, i1 = order[0], order[1]
            gap = dists[i1] - dists[i0]
            sx, sy = seeds[i0]
            dx, dy = _torus_delta(px, sx), _torus_delta(py, sy)
            if gap < 1.5:
                img[y, x] = joint
            elif gap < 2.6:
                # lit upper-left rim, shaded lower-right rim, soft joint elsewhere
                if dx + dy < -2.0:
                    img[y, x] = _shade(colors[i0], 1.18)
                elif dx + dy > 2.0:
                    img[y, x] = joint_soft
                else:
                    img[y, x] = _shade(colors[i0], 0.92)
            else:
                # deterministic speckle so the stone face is not flat
                n = (x * 73856093 ^ y * 19349663 ^ i0 * 83492791) & 0xFF
                f = 1.0 + (0.035 if n < 40 else -0.035 if n > 215 else 0.0)
                img[y, x] = _shade(colors[i0], f)
    return Image.fromarray(img)


def plank_floor(rng):
    """Long, thin warm-timber floorboards (8 px) with rare staggered butt joints and horizontal grain."""
    woods = [_rgb(h) for h in ("#8a5a34", "#7d5230", "#946238", "#86582f", "#7a4f2c")]
    seam = _rgb("#4a2f1a")
    plank_h = 8
    rows = SIZE // plank_h
    img = np.zeros((SIZE, SIZE, 3), dtype=np.uint8)
    spans = []
    for r in range(rows):
        j1 = rng.randrange(0, SIZE)
        j2 = (j1 + rng.randrange(16, 33)) % SIZE
        spans.append((j1, j2, rng.randrange(len(woods)), rng.randrange(len(woods))))
    for r in range(rows):
        j1, j2, w0, w1 = spans[r]
        length0 = (j2 - j1) % SIZE
        for y in range(plank_h):
            yy = r * plank_h + y
            for x in range(SIZE):
                seg = 0 if ((x - j1) % SIZE) < length0 else 1
                base = woods[w0 if seg == 0 else w1]
                if y == plank_h - 1:
                    c = seam
                elif y == 0:
                    c = _shade(base, 1.14)
                else:
                    # horizontal grain: short darker/lighter runs along the board
                    n = ((x // 5) * 2654435761 ^ yy * 40503 ^ (r * 2 + seg) * 97) & 0xFF
                    grain = 1.0 + (0.06 if n < 30 else -0.06 if n > 226 else 0.0)
                    c = _shade(base, grain)
                img[yy, x] = c
        # butt joints, one at each segment boundary (periodic)
        for y in range(plank_h - 1):
            img[r * plank_h + y, j1 % SIZE] = seam
            img[r * plank_h + y, j2 % SIZE] = seam
    return Image.fromarray(img)


def flagstone(rng):
    """Slate-blue flagstones in staggered rows with 1 px mortar."""
    slates = [_rgb(h) for h in ("#738693", "#677889", "#7f91a0", "#929fa8")]
    mortar = _rgb("#465766")
    row_h = 24
    img = np.zeros((SIZE, SIZE, 3), dtype=np.uint8)
    colors = [[slates[rng.randrange(len(slates))] for _ in range(2)] for _ in range(SIZE // row_h)]
    for r in range(SIZE // row_h):
        offset = 0 if r == 0 else 12
        for y in range(row_h):
            for x in range(SIZE):
                u = (x - offset) % SIZE
                col = u // 24
                lx = u % 24
                base = colors[r][col]
                if y == row_h - 1 or lx == 23:
                    c = mortar
                elif y == 0 or lx == 0:
                    c = _shade(base, 1.14)
                else:
                    n = (x * 668265263 ^ (r * row_h + y) * 374761393) & 0xFF
                    c = _shade(base, 1.0 + (0.035 if n < 36 else -0.035 if n > 220 else 0.0))
                img[r * row_h + y, x] = c
    return Image.fromarray(img)


GENERATORS = {"cobble_tileable": cobble, "plank_floor": plank_floor, "flagstone_slate": flagstone}


def seam_report(im):
    a = np.asarray(im.convert("RGB"), dtype=int)
    return {
        "left_vs_right_edge_mean_abs_diff": float(np.abs(a[:, 0] - a[:, -1]).mean()),
        "top_vs_bottom_edge_mean_abs_diff": float(np.abs(a[0] - a[-1]).mean()),
        "interior_adjacent_column_mean_abs_diff": float(np.abs(a[:, 1:] - a[:, :-1]).mean()),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="myassets/terrain")
    ap.add_argument("--preview", default="")
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    made = {}
    for name, fn in GENERATORS.items():
        im = fn(random.Random(f"{args.seed}:{name}"))
        im.convert("RGBA").save(out / f"{name}.png")
        made[name] = seam_report(im)
    print(json.dumps(made, indent=1))
    if args.preview:
        names = list(GENERATORS)
        tiles = [Image.open(out / f"{n}.png").convert("RGBA") for n in names]
        sheet = Image.new("RGBA", (SIZE * 4 * len(tiles), SIZE * 4), (0, 0, 0, 255))
        for i, t in enumerate(tiles):
            for ty in range(4):
                for tx in range(4):
                    sheet.paste(t, (i * SIZE * 4 + tx * SIZE, ty * SIZE))
        sheet = sheet.resize((sheet.width * 2, sheet.height * 2), Image.NEAREST)
        sheet.save(args.preview)


if __name__ == "__main__":
    main()
