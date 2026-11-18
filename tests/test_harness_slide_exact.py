"""1008 Gate E: ``spatial.slide`` got a broad-phase (``_boxes_near_sweep``) that drops boxes outside the start-to-target sweep.
Dropping may never change an answer, so every result must equal the original ``slide`` (kept here verbatim as the oracle),
bit for bit.  Randomised over many boxes (so the broad-phase is active), touching/overlapping/embedding boxes, starts exactly on
a box edge and one float step either side, the 1e-4 tolerance edges, long displacements, starts outside the bounds, and
non-finite input."""
import math
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "at_the_beginning"))

from systems.movement import spatial  # noqa: E402


def slide_oracle(start, desired, contract):
    """The pre-Gate-E ``spatial.slide``, verbatim."""
    radius = contract["actor_radius"]
    boxes = [(b["min"][0]-radius, b["min"][1]-radius,
              b["max"][0]+radius, b["max"][1]+radius) for b in contract["boxes"]]
    x, y = start
    if any(a+0.0001 < x < c-0.0001 and b+0.0001 < y < d-0.0001 for a, b, c, d in boxes):
        return (x, y)
    bounds = contract["bounds"]
    nx = max(bounds[0]+radius, min(bounds[2]-radius, desired[0]))
    ny = max(bounds[1]+radius, min(bounds[3]-radius, desired[1]))
    for a, b, c, d in boxes:
        if b < y < d:
            if x <= a+0.0001 and nx > a:
                nx = min(nx, a)
            elif x >= c-0.0001 and nx < c:
                nx = max(nx, c)
    for a, b, c, d in boxes:
        if a < nx < c:
            if y <= b+0.0001 and ny > b:
                ny = min(ny, b)
            elif y >= d-0.0001 and ny < d:
                ny = max(ny, d)
    return (nx, ny)


def same(a, b):
    return all((p == q) or (math.isnan(p) and math.isnan(q)) for p, q in zip(a, b)) and len(a) == len(b)


def random_contract(rng, count, extent=120.0, radius=0.35):
    boxes = []
    for _ in range(count):
        cx, cy = rng.uniform(-extent, extent), rng.uniform(-extent, extent)
        hx, hy = rng.choice((0.6, 1.0, 2.0, 5.0)), rng.choice((0.6, 1.0, 3.0))
        if rng.random() < 0.3:                      # grid-aligned, so edges coincide exactly with other boxes' edges
            cx, cy = round(cx), round(cy)
        boxes.append({"id": f"b{len(boxes)}", "min": [cx-hx, cy-hy], "max": [cx+hx, cy+hy]})
    return {"actor_radius": radius, "bounds": (-extent, -extent, extent, extent), "boxes": boxes}


def probe_points(rng, contract, n):
    """Starts and targets biased to sit on box edges, one float step off them, and inside boxes."""
    radius = contract["actor_radius"]
    edges_x = [v for b in contract["boxes"] for v in (b["min"][0]-radius, b["max"][0]+radius)]
    edges_y = [v for b in contract["boxes"] for v in (b["min"][1]-radius, b["max"][1]+radius)]
    out = []
    for _ in range(n):
        x = rng.choice(edges_x) if edges_x and rng.random() < 0.5 else rng.uniform(-130, 130)
        y = rng.choice(edges_y) if edges_y and rng.random() < 0.5 else rng.uniform(-130, 130)
        x += rng.choice((0.0, 0.0, 1e-4, -1e-4, 5e-5, -5e-5, 1e-9, -1e-9, math.ulp(x), -math.ulp(x)))
        y += rng.choice((0.0, 0.0, 1e-4, -1e-4, 5e-5, -5e-5, 1e-9, -1e-9, math.ulp(y), -math.ulp(y)))
        step = rng.choice((0.05, 0.5, 3.0, 40.0, 400.0))
        angle = rng.choice((0.0, math.pi/2, math.pi, -math.pi/2, rng.uniform(0, 2*math.pi)))
        out.append(((x, y), (x + step*math.cos(angle), y + step*math.sin(angle))))
    return out


class SlideExactTests(unittest.TestCase):
    def test_random_contracts_match_the_original_bit_for_bit(self):
        rng = random.Random(1008)
        checked = moved = held = 0
        for count in (0, 1, 47, 48, 49, 160, 330):
            for _ in range(6):
                contract = random_contract(rng, count)
                for start, desired in probe_points(rng, contract, 120):
                    want = slide_oracle(start, desired, contract)
                    got = spatial.slide(start, desired, contract)
                    self.assertTrue(same(got, want), (count, start, desired, got, want))
                    checked += 1
                    moved += got != start
                    held += got == start
        self.assertGreater(checked, 4000)
        self.assertGreater(moved, 500)
        self.assertGreater(held, 50)                # blocked/embedded cases are exercised, not just free movement

    def test_the_broad_phase_actually_narrows(self):
        rng = random.Random(7)
        contract = random_contract(rng, 330)
        kept = spatial._boxes_near_sweep(contract, 0.35, 0.0, 0.0, 0.5, 0.0)
        self.assertLess(len(kept), 40)
        self.assertEqual(len(spatial._boxes_near_sweep(contract, 0.35, 0.0, 0.0, 0.5, 0.0)), len(kept))   # cache hit, same answer

    def test_kept_boxes_keep_contract_order_and_values(self):
        rng = random.Random(11)
        contract = random_contract(rng, 200)
        everything = [spatial._inflated(b, 0.35) for b in contract["boxes"]]
        kept = spatial._boxes_near_sweep(contract, 0.35, -10.0, -10.0, 60.0, 30.0)
        self.assertEqual(kept, [box for box in everything if box in kept])
        self.assertTrue(set(kept) <= set(everything))

    def test_non_finite_input_keeps_every_box(self):
        rng = random.Random(3)
        contract = random_contract(rng, 100)
        for start, desired in (((float("nan"), 0.0), (1.0, 1.0)), ((0.0, 0.0), (float("inf"), 0.0)),
                               ((0.0, float("-inf")), (0.0, 0.0)), ((0.0, 0.0), (float("nan"), float("nan")))):
            self.assertTrue(same(spatial.slide(start, desired, contract), slide_oracle(start, desired, contract)), (start, desired))

    def test_a_different_contract_never_reuses_the_cache(self):
        rng = random.Random(5)
        first, second = random_contract(rng, 90), random_contract(rng, 90)
        for contract in (first, second, first, second):
            for start, desired in probe_points(rng, contract, 40):
                self.assertTrue(same(spatial.slide(start, desired, contract), slide_oracle(start, desired, contract)))
        wider = dict(second, actor_radius=0.5)
        for start, desired in probe_points(rng, wider, 40):
            self.assertTrue(same(spatial.slide(start, desired, wider), slide_oracle(start, desired, wider)))

    def test_start_outside_the_bounds(self):
        rng = random.Random(9)
        contract = random_contract(rng, 120)
        for start, desired in ((( -500.0, 3.0), (0.0, 3.0)), ((500.0, -4.0), (-500.0, -4.0)), ((0.0, 900.0), (0.0, -900.0))):
            self.assertTrue(same(spatial.slide(start, desired, contract), slide_oracle(start, desired, contract)))


if __name__ == "__main__":
    unittest.main()
