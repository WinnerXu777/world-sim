"""Create recoloured resident variants from existing four-direction sheets (hue shift of the blue range only).

  .venv/Scripts/python.exe tools/make_character_variants.py [--out myassets/characters]

Derived work: the sources are adventurer_pack_2 sheets whose licence is not supplied in the repository, so
the variants inherit that status. Replace both before any public release.
"""
import argparse
import colorsys
import json
from pathlib import Path

import numpy as np
from PIL import Image

# name -> (source sheet, target hue 0..1, saturation scale, value scale)
VARIANTS = {
    "stalker_smith": ("dungeon_stalker", 0.07, 1.55, 1.10),   # blue steel -> copper/bronze
    "stalker_iven": ("dungeon_stalker", 0.33, 1.35, 1.00),    # blue steel -> forest green
    "elven_elsa": ("elven_adventurer", 0.98, 1.50, 1.00),     # blue cape -> crimson
}
BLUE = (0.50, 0.72)  # hue range (180..260 deg) treated as the blue accent
MIN_SAT = 0.16


def recolour(img, hue, s_scale, v_scale):
    a = np.asarray(img.convert("RGBA")).astype(np.float32) / 255.0
    out = a.copy()
    h, w, _ = a.shape
    changed = 0
    for y in range(h):
        for x in range(w):
            r, g, b, al = a[y, x]
            if al <= 0.0:
                continue
            hh, ss, vv = colorsys.rgb_to_hsv(r, g, b)
            if BLUE[0] <= hh <= BLUE[1] and ss >= MIN_SAT:
                nr, ng, nb = colorsys.hsv_to_rgb(hue, min(1.0, ss * s_scale), min(1.0, vv * v_scale))
                out[y, x, :3] = (nr, ng, nb)
                changed += 1
    return Image.fromarray((out * 255.0 + 0.5).astype(np.uint8)), changed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="myassets/characters")
    args = ap.parse_args()
    out = Path(args.out)
    report = {}
    for name, (src, hue, s, v) in VARIANTS.items():
        im = Image.open(out / f"{src}.png")
        new, changed = recolour(im, hue, s, v)
        new.save(out / f"{name}.png")
        report[name] = {"source": f"{src}.png", "pixels_recoloured": changed, "size": list(new.size)}
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
