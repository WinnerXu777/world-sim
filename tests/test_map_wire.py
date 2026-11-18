"""Wire contract (1006_map_wire_contract.md): bootstrap/view `maps` block and GET /map_file/{map_id}."""
import hashlib
import json
import re
import tempfile
import unittest
from pathlib import Path

import httpx

from test_startup_preservation import backend
from test_map_contract import AsyncRegistryIsolation, FIXTURES, LEGACY_KEY_ORDER, SMITH, make_authored_world
from systems.movement.map_contract import register_map_file

# Full key set of a legacy /bootstrap response and of its `spatial` block, captured before the maps feature.
LEGACY_BOOTSTRAP_KEYS = ["inventory", "launch", "map", "protocol", "schema", "session", "session_capability", "spatial",
                         "talk", "world", "world_epoch"]
MAP_BLOCK_KEYS = ["map_id", "format_version", "revision", "sha256", "size_bytes", "url", "map_kind", "units_per_tile",
                  "tile_size_px", "size_tiles", "actor_radius", "origin", "primary"]


class WireCase(AsyncRegistryIsolation, unittest.IsolatedAsyncioTestCase):
    def client(self, **kwargs):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=backend.app), base_url="http://127.0.0.1", **kwargs)

    async def view_window(self, client):
        response = await client.post("/human_view/window", json={"controller_id": "local_player"},
                                     headers={"X-Eden-Session": backend.SESSION_CAPABILITY})
        self.assertEqual(response.status_code, 200)
        return response.json()


class LegacyWireUnchangedTests(WireCase):
    async def test_legacy_bootstrap_and_view_window_key_sets_are_unchanged(self):
        await backend.create_genesis(backend.engine, map_name="playable_village")
        async with self.client() as client:
            body = (await client.get("/bootstrap")).json()
            self.assertEqual(sorted(body), LEGACY_BOOTSTRAP_KEYS)
            self.assertNotIn("maps", body)
            self.assertEqual(list(body["spatial"]), LEGACY_KEY_ORDER)
            view = await self.view_window(client)
            self.assertNotIn("maps", view)
            self.assertEqual(list(view["spatial"]), LEGACY_KEY_ORDER)

    async def test_registered_maps_do_not_leak_into_a_legacy_world(self):
        register_map_file(SMITH, base_dir=FIXTURES)
        await backend.create_genesis(backend.engine, map_name="playable_village")
        async with self.client() as client:
            body = (await client.get("/bootstrap")).json()
            self.assertEqual(sorted(body), LEGACY_BOOTSTRAP_KEYS)
            self.assertEqual(list(body["spatial"]), LEGACY_KEY_ORDER)

    async def test_map_file_route_exists_but_is_404_when_nothing_is_registered(self):
        async with self.client() as client:
            response = await client.get("/map_file/example_smith")
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json(), {"ok": False, "reason": "unknown_map"})


class AuthoredWireTests(WireCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        await make_authored_world()
        self.raw = SMITH.read_bytes()

    async def test_bootstrap_carries_the_maps_block_exactly(self):
        async with self.client() as client:
            body = (await client.get("/bootstrap")).json()
        self.assertEqual(sorted(body), sorted(LEGACY_BOOTSTRAP_KEYS + ["maps"]))
        self.assertEqual(len(body["maps"]), 1)
        block = body["maps"][0]
        self.assertEqual(list(block), MAP_BLOCK_KEYS)
        self.assertEqual(block, {
            "map_id": "example_smith", "format_version": "0.2-draft", "revision": 0,
            "sha256": hashlib.sha256(self.raw).hexdigest(), "size_bytes": len(self.raw),
            "url": "/map_file/example_smith", "map_kind": "exterior", "units_per_tile": 8.0, "tile_size_px": 48,
            "size_tiles": [6, 6], "actor_radius": 2.4, "origin": [0.0, 0.0], "primary": True})
        self.assertIsInstance(block["revision"], int)
        self.assertRegex(block["sha256"], r"^[0-9a-f]{64}$")
        spatial = body["spatial"]
        self.assertEqual((spatial["map_id"], spatial["map_revision"], spatial["units_per_tile"], spatial["actor_radius"]),
                         ("example_smith", 0, 8.0, 2.4))
        self.assertRegex(spatial["revision"], r"^[0-9a-f]{16}$")  # wall hash, not the map revision
        self.assertEqual(json.dumps(body)[:1], "{")
        self.assertNotIn(str(FIXTURES), json.dumps(body))  # no absolute paths on the wire

    async def test_view_window_carries_the_same_block(self):
        async with self.client() as client:
            boot = (await client.get("/bootstrap")).json()
            view = await self.view_window(client)
        self.assertEqual(view["maps"], boot["maps"])
        self.assertEqual(view["spatial"]["map_id"], "example_smith")

    async def test_map_file_body_is_the_exact_file_and_its_hash_matches(self):
        async with self.client() as client:
            block = (await client.get("/bootstrap")).json()["maps"][0]
            response = await client.get(block["url"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, self.raw)  # byte for byte, no re-serialisation
        self.assertEqual(hashlib.sha256(response.content).hexdigest(), block["sha256"])
        self.assertEqual(len(response.content), block["size_bytes"])
        self.assertEqual(response.headers["etag"], f'"{block["sha256"]}"')
        self.assertEqual(response.headers["content-type"], "application/json")
        self.assertEqual(json.loads(response.content)["map_id"], "example_smith")

    async def test_conditional_requests(self):
        sha = hashlib.sha256(self.raw).hexdigest()
        async with self.client() as client:
            for header in (f'"{sha}"', f'W/"{sha}"', f'"other", "{sha}"', "*"):
                with self.subTest(header=header):
                    response = await client.get("/map_file/example_smith", headers={"If-None-Match": header})
                    self.assertEqual(response.status_code, 304)
                    self.assertEqual(response.content, b"")
                    self.assertEqual(response.headers["etag"], f'"{sha}"')
            for header in ('"0000"', "", sha[:10]):
                with self.subTest(header=header):
                    response = await client.get("/map_file/example_smith", headers={"If-None-Match": header})
                    self.assertEqual((response.status_code, response.content), (200, self.raw))

    async def test_unknown_ids_are_404_without_paths(self):
        async with self.client() as client:
            for map_id in ("nope", "example_smith2", "..", "%2e%2e", "example_smith.json", "C:%5Cx"):
                with self.subTest(map_id=map_id):
                    response = await client.get(f"/map_file/{map_id}")
                    self.assertIn(response.status_code, (404, 400))
                    text = response.text
                    self.assertNotRegex(text, r"[A-Za-z]:\\\\|/Users/|fixtures")

    async def test_exact_bytes_are_served_even_with_crlf_and_odd_whitespace(self):
        text = SMITH.read_bytes().decode("utf-8")
        raw = ("\r\n".join(text.splitlines()) + "\r\n\r\n").replace('"revision": 0', '"revision":   7').encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "crlf.json"
            path.write_bytes(raw)
            register_map_file(path, name="example_smith", base_dir=FIXTURES)
        async with self.client() as client:
            block = (await client.get("/bootstrap")).json()["maps"][0]
            response = await client.get("/map_file/example_smith")
        self.assertEqual(response.content, raw)
        self.assertEqual(block["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual((block["revision"], block["size_bytes"]), (7, len(raw)))
        self.assertIn(b"\r\n", response.content)

    async def test_local_session_boundary_still_applies(self):
        async with self.client() as client:
            for host in ("example.com:8012", "localhost.example.com"):
                response = await client.get("/map_file/example_smith", headers={"Host": host})
                self.assertEqual(response.status_code, 403)
                self.assertEqual(response.json()["reason"], "local_host_required")
            for origin in ("https://example.com", "null"):
                response = await client.get("/map_file/example_smith", headers={"Origin": origin})
                self.assertEqual(response.status_code, 403)
            local = await client.get("/map_file/example_smith", headers={"Origin": "http://localhost:5173"})
            self.assertEqual(local.status_code, 200)
            for method in ("post", "put", "delete"):
                response = await getattr(client, method)("/map_file/example_smith")
                self.assertIn(response.status_code, (401, 405))  # never served, never mutates

    async def test_the_response_reflects_what_is_registered_now(self):
        async with self.client() as client:
            first = await client.get("/map_file/example_smith")
            self.assertEqual(first.status_code, 200)
            from systems.movement.map_contract import clear_map_contracts
            clear_map_contracts()
            self.assertEqual((await client.get("/map_file/example_smith")).status_code, 404)
            self.assertNotIn("maps", (await client.get("/bootstrap")).json())


if __name__ == "__main__":
    unittest.main()
