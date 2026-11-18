"""Test and harness helpers: an ephemeral-port model server thread and a scripted transport. Not used by the running game."""
from __future__ import annotations

import json
import threading
import time

from .transport import Transport, TransportReply


class ServerThread:
    """Run a FastAPI app on an ephemeral loopback port (never a fixed port). ``with ServerThread(app) as srv: srv.url``."""

    def __init__(self, app):
        import uvicorn
        self.config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", lifespan="on")
        self.server = uvicorn.Server(self.config)
        self.thread = threading.Thread(target=self.server.run, name="model-server-test", daemon=True)
        self.url = ""

    def __enter__(self):
        self.thread.start()
        deadline = time.monotonic() + 10.0
        while not self.server.started:
            if time.monotonic() > deadline or not self.thread.is_alive():
                raise RuntimeError("model server did not start")
            time.sleep(0.01)
        port = self.server.servers[0].sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=10.0)


class ScriptedTransport(Transport):
    """``handler(url, body: dict) -> (status, text)``; it may raise TransportTimeout / TransportError. Counts calls."""

    def __init__(self, handler):
        self.handler = handler
        self.calls = []
        self._lock = threading.Lock()

    def post(self, url, body, headers, timeout_s):
        data = json.loads(body)
        with self._lock:
            self.calls.append((url, data, dict(headers), timeout_s))
        status, text = self.handler(url, data)
        return TransportReply(status, text)


class NoNetworkTransport(Transport):
    """Fails the test if anything tries to send."""

    def post(self, url, body, headers, timeout_s):
        raise AssertionError(f"network call attempted to {url}")
