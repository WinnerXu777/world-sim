"""1008 WS-D D8: GET /chunks and GET /chunk/{cx}/{cy} (api/chunk_routes.py). Standalone app, inline ChunkService (workers=0): no engine,
no worker processes. Bytes and sha256 are cross-checked against the generator golden of the Model plane (tests/golden/worldgen_hashes.json)."""
import hashlib
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "at_the_beginning"))
from api import chunk_routes  # noqa: E402
from systems.worldgen import PinnedSet, generate_chunk, starter_village_area  # noqa: E402
from systems.worldgen.service import ChunkService  # noqa: E402

SEED = 1008
VILLAGE = PinnedSet([starter_village_area()])
GOLDEN = json.loads((ROOT / "tests" / "golden" / "worldgen_hashes.json").read_text(encoding="utf-8"))["entries"]


def inline_service():
    return ChunkService(SEED, pinned=VILLAGE, workers=0, inline_budget=4)


def make_client(factory=inline_service):
    router = chunk_routes.build_chunk_router(None, service_factory=factory)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app), router.chunk_routes


def wait_ready(client, query, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = client.get("/chunks", params=query).json()
        if all(c["state"] != "pending" for c in body["chunks"]):
            return body
        time.sleep(0.02)
    raise AssertionError("chunks never became ready")


class FlagTests(unittest.TestCase):
    def test_off_by_default(self):
        self.assertFalse(chunk_routes.enabled({}))
        self.assertFalse(chunk_routes.enabled({chunk_routes.FLAG: "0"}))
        self.assertTrue(chunk_routes.enabled({chunk_routes.FLAG: "1"}))

    def test_routes_do_not_exist_unless_mounted(self):
        with TestClient(FastAPI()) as client:
            self.assertEqual(client.get("/chunk/0/0").status_code, 404)
            self.assertEqual(client.get("/chunks", params={"cx0": 0, "cy0": 0, "cx1": 0, "cy1": 0}).status_code, 404)


class MountTests(unittest.TestCase):
    """The single hook in map_test.py: flag off -> the engine app has no chunk routes; flag on -> it has them next to /map_file."""

    CODE = ("import sys; sys.path.insert(0, %r); import map_test; "
            "print(sorted(r.path for r in map_test.app.routes if 'chunk' in r.path or r.path.startswith('/map_file')))")

    def paths(self, flag):
        env = {k: v for k, v in os.environ.items() if k != chunk_routes.FLAG}
        if flag:
            env[chunk_routes.FLAG] = "1"
        done = subprocess.run([sys.executable, "-c", self.CODE % str(ROOT / "at_the_beginning")], capture_output=True, text=True, env=env,
                              cwd=str(ROOT / "at_the_beginning"), timeout=300)
        self.assertEqual(done.returncode, 0, done.stderr[-1500:])
        return eval(done.stdout.strip().splitlines()[-1])

    def test_flag_off_has_no_chunk_routes_and_flag_on_adds_exactly_two(self):
        off, on = self.paths(False), self.paths(True)
        self.assertEqual(off, ["/map_file/{map_id}"])
        self.assertEqual(sorted(set(on) - set(off)), ["/chunk/{cx}/{cy}", "/chunks"])


class ChunkBytesTests(unittest.TestCase):
    def test_bytes_etag_and_304(self):
        with make_client()[0] as client:
            response = client.get("/chunk/2/0")
            self.assertEqual(response.status_code, 200)
            expected = generate_chunk(SEED, 2, 0, pinned=VILLAGE)
            self.assertEqual(response.content, expected.payload)
            sha = hashlib.sha256(response.content).hexdigest()
            self.assertEqual(sha, expected.sha256)
            self.assertEqual(response.headers["etag"], f'"{sha}"')
            self.assertEqual(response.headers["cache-control"], "no-cache")
            self.assertEqual(response.headers["content-type"], "application/json")
            for header in (f'"{sha}"', f'W/"{sha}"', f'"x", "{sha}"', "*"):
                cached = client.get("/chunk/2/0", headers={"If-None-Match": header})
                self.assertEqual(cached.status_code, 304, header)
                self.assertEqual(cached.content, b"")
                self.assertEqual(cached.headers["etag"], f'"{sha}"')
            stale = client.get("/chunk/2/0", headers={"If-None-Match": '"0000"'})
            self.assertEqual((stale.status_code, stale.content), (200, expected.payload))

    def test_sha256_matches_the_generator_golden_of_the_model_plane(self):
        with make_client()[0] as client:
            for cx, cy in ((0, 0), (1, 0), (2, 0), (-1, 0), (3, 2)):
                entry = GOLDEN[f"village/1008/{cx}/{cy}"]
                response = client.get(f"/chunk/{cx}/{cy}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(hashlib.sha256(response.content).hexdigest(), entry["sha256"], (cx, cy))
                self.assertEqual(len(response.content), entry["bytes"])

    def test_negative_coordinates_and_the_document_identity(self):
        with make_client()[0] as client:
            document = client.get("/chunk/-9/4").json()
            self.assertEqual(document["map_id"], "chunk_-9_4")
            self.assertEqual((document["chunk"]["cx"], document["chunk"]["cy"]), (-9, 4))

    def test_out_of_range_coordinates_are_rejected_not_generated(self):
        with make_client()[0] as client:
            for path in (f"/chunk/{2 ** 40 + 1}/0", f"/chunk/0/{-(2 ** 40) - 1}"):
                response = client.get(path)
                self.assertEqual((response.status_code, response.json()["reason"]), (400, "coordinate_out_of_range"), path)
            self.assertEqual(client.get("/chunk/abc/0").status_code, 422)
            self.assertEqual(client.get(f"/chunk/{2 ** 40}/0").status_code, 200)       # the limit itself is allowed

    def test_pending_answers_503_with_retry_after(self):
        class Never:
            world_seed = SEED
            failed = {}

            def request(self, coord, priority=0.0):
                return "queued"

            def peek(self, coord):
                return None

            get = peek

            def is_pending(self, coord):
                return True

            def pump(self):
                return []

            def close(self):
                pass

        original = chunk_routes.READY_TIMEOUT
        chunk_routes.READY_TIMEOUT = 0.05
        self.addCleanup(setattr, chunk_routes, "READY_TIMEOUT", original)
        with make_client(Never)[0] as client:
            response = client.get("/chunk/0/0")
            self.assertEqual((response.status_code, response.json()["reason"], response.headers["retry-after"]), (503, "chunk_pending", "1"))

    def test_a_failed_generation_answers_500_and_can_be_retried(self):
        calls = {"n": 0}

        def flaky(args):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            from systems.worldgen.generate import generate_payload
            return generate_payload(args)

        def factory():
            return ChunkService(SEED, pinned=VILLAGE, workers=0, generate=flaky)

        with make_client(factory)[0] as client:
            first = client.get("/chunk/5/5")
            self.assertEqual((first.status_code, first.json()["reason"]), (500, "chunk_failed"))
            second = client.get("/chunk/5/5")
            self.assertEqual(second.status_code, 200)
            self.assertEqual(second.content, generate_chunk(SEED, 5, 5, pinned=VILLAGE).payload)


class WorkerProcessTests(unittest.TestCase):
    def test_a_real_process_pool_serves_the_same_bytes(self):
        client, routes = make_client(lambda: ChunkService(SEED, pinned=VILLAGE, workers=2))
        self.addCleanup(routes.close)
        with client:
            response = client.get("/chunk/3/2")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(hashlib.sha256(response.content).hexdigest(), GOLDEN["village/1008/3/2"]["sha256"])
            body = wait_ready(client, {"cx0": 0, "cy0": 0, "cx1": 2, "cy1": 2}, timeout=30.0)
            self.assertEqual(len(body["chunks"]), 9)


class WindowTests(unittest.TestCase):
    def test_descriptors_become_ready_with_the_bytes_hash_and_urls(self):
        query = {"cx0": -1, "cy0": -1, "cx1": 1, "cy1": 1}
        with make_client()[0] as client:
            body = wait_ready(client, query)
            self.assertEqual((body["world_seed"], body["chunk_tiles"], body["units_per_tile"]), (str(SEED), 32, 8))
            self.assertEqual(len(body["chunks"]), 9)
            self.assertEqual([c["chunk_id"] for c in body["chunks"]], [f"{x}:{y}" for y in (-1, 0, 1) for x in (-1, 0, 1)])
            for item in body["chunks"]:
                cx, cy = map(int, item["chunk_id"].split(":"))
                self.assertEqual(item["url"], f"/chunk/{cx}/{cy}")
                self.assertEqual(item["revision"], 0)
                self.assertEqual(item["sha256"], GOLDEN.get(f"village/1008/{cx}/{cy}", {}).get("sha256", item["sha256"]))
                self.assertEqual(client.get(item["url"]).headers["etag"], f'"{item["sha256"]}"')

    def test_pending_descriptors_have_no_hash_and_pinned_chunks_say_so(self):
        with make_client()[0] as client:
            first = client.get("/chunks", params={"cx0": 0, "cy0": 0, "cx1": 3, "cy1": 3}).json()
            self.assertTrue(any(c["state"] == "pending" and c["sha256"] is None for c in first["chunks"]))
            body = wait_ready(client, {"cx0": 0, "cy0": 0, "cx1": 3, "cy1": 3})
            by_id = {c["chunk_id"]: c for c in body["chunks"]}
            self.assertEqual(by_id["0:0"]["state"], "pinned_map")
            self.assertTrue(by_id["0:0"]["pinned_map"])
            self.assertEqual(by_id["3:3"]["state"], "ready")
            self.assertNotIn("pinned_map", by_id["3:3"])

    def test_nearest_the_window_centre_is_requested_first(self):
        requests = {}

        class Recorder:
            world_seed = SEED
            failed = {}

            def request(self, coord, priority=0.0):
                requests[(coord.x, coord.y)] = priority

            def peek(self, coord):
                return None

            def is_pending(self, coord):
                return False

            def pump(self):
                return []

            def close(self):
                pass

        with make_client(Recorder)[0] as client:
            client.get("/chunks", params={"cx0": 10, "cy0": 10, "cx1": 14, "cy1": 14})
        self.assertEqual(len(requests), 25)
        self.assertEqual(requests[(12, 12)], 0.0)
        self.assertEqual(min(requests, key=requests.get), (12, 12))
        self.assertGreater(requests[(10, 10)], requests[(11, 12)])
        self.assertEqual(requests[(10, 10)], requests[(14, 14)])

    def test_limits_and_validation(self):
        with make_client()[0] as client:
            ok = client.get("/chunks", params={"cx0": 0, "cy0": 0, "cx1": 14, "cy1": 14})
            self.assertEqual(ok.status_code, 200)
            self.assertEqual(len(ok.json()["chunks"]), 225)
            big = client.get("/chunks", params={"cx0": 0, "cy0": 0, "cx1": 15, "cy1": 0})
            self.assertEqual((big.status_code, big.json()["reason"]), (400, "window_too_large"))
            reversed_window = client.get("/chunks", params={"cx0": 2, "cy0": 0, "cx1": 1, "cy1": 0})
            self.assertEqual((reversed_window.status_code, reversed_window.json()["reason"]), (400, "invalid_window"))
            far = client.get("/chunks", params={"cx0": 2 ** 41, "cy0": 0, "cx1": 2 ** 41, "cy1": 0})
            self.assertEqual((far.status_code, far.json()["reason"]), (400, "coordinate_out_of_range"))
            self.assertEqual(client.get("/chunks", params={"cx0": 0}).status_code, 422)


class PlacementOriginTests(unittest.TestCase):
    def test_origin_is_discoverable_from_any_fully_pinned_chunk(self):
        # A map at nonzero/negative origin fully spanning 2x2 chunks (w=64, h=64)
        # Map x0=32 (chunk x=1), y0=-64 (chunk y=-2), w=64, h=64
        # Fully spans chunks (1, -2), (2, -2), (1, -1), (2, -1)
        from systems.worldgen.pinned import PinnedArea
        area = PinnedArea("town", 32, -64, 64, 64)
        
        def factory():
            return ChunkService(SEED, pinned=PinnedSet([area]), workers=0, inline_budget=4)
        
        with make_client(factory)[0] as client:
            body = wait_ready(client, {"cx0": 0, "cy0": -3, "cx1": 3, "cy1": 0})
            by_id = {c["chunk_id"]: c for c in body["chunks"]}
            
            # ALL fully pinned chunks should have the origin metadata so it is discoverable
            for cid in ("1:-2", "2:-2", "1:-1", "2:-1"):
                chunk = by_id[cid]
                self.assertEqual(chunk["state"], "pinned_map", cid)
                self.assertEqual(chunk["pinned_map"], "town", cid)
                self.assertEqual(chunk["placement_origin_absolute_units"], [32 * 8, -64 * 8], cid)
            
            # Partial chunk semantics: chunk 0, -2 is NOT fully pinned because area x0 is 32, missing x=0..32.
            partial = by_id["0:-2"]
            self.assertEqual(partial["state"], "ready")
            self.assertNotIn("placement_origin_absolute_units", partial)
            self.assertNotIn("pinned_map", partial)

            # Procedural descriptor behavior
            procedural = by_id["0:0"]
            self.assertEqual(procedural["state"], "ready")
            self.assertNotIn("placement_origin_absolute_units", procedural)
            self.assertNotIn("pinned_map", procedural)

    def test_absence_of_flags_and_hash_semantics_preserved(self):
        with make_client()[0] as client:
            body = wait_ready(client, {"cx0": 3, "cy0": 2, "cx1": 3, "cy1": 2})
            chunk = body["chunks"][0]
            self.assertEqual(chunk["state"], "ready")
            self.assertEqual(chunk["sha256"], GOLDEN["village/1008/3/2"]["sha256"])
            self.assertNotIn("placement_origin_absolute_units", chunk)
            self.assertNotIn("pinned_map", chunk)

    def test_large_int_coordinates_preserved_and_service_injection_compatibility(self):
        from systems.worldgen.pinned import PinnedArea
        # Large absolute tile coordinates beyond float precision issues
        area = PinnedArea("far_town", 5000000 * 32, -5000000 * 32, 32, 32)
        
        def factory():
            return ChunkService(SEED, pinned=PinnedSet([area]), workers=0, inline_budget=1)
            
        with make_client(factory)[0] as client:
            body = wait_ready(client, {"cx0": 5000000, "cy0": -5000000, "cx1": 5000000, "cy1": -5000000})
            chunk = body["chunks"][0]
            self.assertEqual(chunk["state"], "pinned_map")
            self.assertEqual(chunk["placement_origin_absolute_units"], [5000000 * 32 * 8, -5000000 * 32 * 8])
            self.assertIsInstance(chunk["placement_origin_absolute_units"][0], int)
            self.assertIsInstance(chunk["placement_origin_absolute_units"][1], int)



if __name__ == "__main__":
    unittest.main()
