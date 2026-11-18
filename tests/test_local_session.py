import unittest

import httpx

from test_startup_preservation import backend


class LocalSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        backend.engine.reset_world()
        await backend.create_genesis(backend.engine, map_name="playable_village")

    def client(self, **kwargs):
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=backend.app),
                                 base_url="http://127.0.0.1", **kwargs)

    async def test_all_post_routes_require_capability_before_mutating(self):
        before = backend.engine.state.h_tensor.clone()
        epoch = backend.engine.world_epoch
        async with self.client() as client:
            for route in backend.app.routes:
                if "POST" not in getattr(route, "methods", set()):
                    continue
                path = route.path.replace("{name}", "ignored").replace("{bit}", "1")
                with self.subTest(path=path):
                    response = await client.post(path, json={"controller_id": "local_player"})
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response.json()["reason"], "session_capability_required")
        self.assertEqual(backend.engine.world_epoch, epoch)
        self.assertTrue(backend.torch.equal(before, backend.engine.state.h_tensor))
        self.assertFalse(backend.engine.player_control.has_active_sessions())

    async def test_bootstrap_capability_allows_claim_but_controller_name_alone_does_not(self):
        async with self.client() as client:
            response = await client.get("/bootstrap")
            self.assertEqual(response.status_code, 200)
            capability = response.json()["session_capability"]
            self.assertGreaterEqual(len(capability), 32)
            headers = {"X-Eden-Session": capability}
            claim = {"controller_id": "player", "target_kind": "human", "target_id": backend.engine._human_uid_by_slot[0]}
            response = await client.post("/control/claim", json=claim, headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()["ok"])
            refused = await client.post("/control/release", json={"controller_id": "player"}, headers={"X-Eden-Session": "wrong"})
            self.assertEqual(refused.status_code, 401)
            self.assertTrue(backend.engine.player_control.has_active_sessions())
            released = await client.post("/control/release", json={"controller_id": "player"}, headers=headers)
            self.assertEqual(released.status_code, 200)
            self.assertFalse(backend.engine.player_control.has_active_sessions())

    async def test_foreign_origin_and_rebinding_host_cannot_obtain_or_use_capability(self):
        async with self.client() as client:
            for origin in ("https://example.com", "null", "http://localhost.example.com"):
                with self.subTest(origin=origin):
                    self.assertEqual((await client.get("/bootstrap", headers={"Origin": origin})).status_code, 403)
                    self.assertEqual((await client.post("/control/release", json={}, headers={
                        "Origin": origin, "X-Eden-Session": backend.SESSION_CAPABILITY})).status_code, 403)
            for host in ("example.com:8012", "localhost.example.com", "[broken"):
                self.assertEqual((await client.get("/bootstrap", headers={"Host": host})).status_code, 403)
            local = await client.get("/bootstrap", headers={"Origin": "http://localhost:5173"})
            self.assertEqual(local.status_code, 200)

    async def test_development_reset_stays_disabled_with_valid_capability(self):
        async with self.client(headers={"X-Eden-Session": backend.SESSION_CAPABILITY}) as client:
            response = await client.post("/testing/render_test_village", json={})
            self.assertEqual(response.status_code, 403)

    async def test_loopback_browser_preflight_allows_capability_header(self):
        async with self.client() as client:
            for origin in ("http://localhost:5173", "http://[::1]:5173"):
                response = await client.options("/control/claim", headers={
                    "Origin": origin, "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "x-eden-session,content-type"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["access-control-allow-origin"], origin)
