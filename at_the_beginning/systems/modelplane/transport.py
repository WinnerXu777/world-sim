"""HTTP transport (httpx) behind a tiny interface so tests and the Gate A harness can swap it. Nothing here runs unless a job is
sent: the plane builds the transport lazily, so ``off`` never opens a socket."""
from __future__ import annotations

import threading
from dataclasses import dataclass


class TransportTimeout(Exception):
    pass


class TransportError(Exception):
    pass


@dataclass
class TransportReply:
    status: int
    text: str


class Transport:
    def post(self, url: str, body: bytes, headers: dict, timeout_s: float) -> TransportReply:
        raise NotImplementedError

    def close(self) -> None:
        pass


class HttpxTransport(Transport):
    """One shared ``httpx.Client`` (keep-alive). Proxy environment variables are ignored: model endpoints are explicit config."""

    def __init__(self):
        self._client = None
        self._lock = threading.Lock()

    def _get(self):
        with self._lock:
            if self._client is None:
                import httpx
                self._client = httpx.Client(trust_env=False, limits=httpx.Limits(max_connections=8, max_keepalive_connections=4))
            return self._client

    def post(self, url, body, headers, timeout_s):
        import httpx
        try:
            reply = self._get().post(url, content=body, headers=headers, timeout=httpx.Timeout(timeout_s))
        except httpx.TimeoutException as exc:
            raise TransportTimeout(str(exc) or "timeout") from exc
        except httpx.HTTPError as exc:
            raise TransportError(f"{type(exc).__name__}: {exc}") from exc
        return TransportReply(reply.status_code, reply.text)

    def close(self):
        with self._lock:
            if self._client is not None:
                self._client.close()
                self._client = None
