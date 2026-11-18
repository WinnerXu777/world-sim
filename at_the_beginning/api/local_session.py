"""Local single-player capability boundary; not multi-user authentication."""
import secrets
from urllib.parse import urlsplit

from starlette.responses import JSONResponse


class LocalSessionBoundary:
    LOOPBACK = {"localhost", "127.0.0.1", "::1"}

    def __init__(self):
        self.capability = secrets.token_urlsafe(32)

    async def dispatch(self, request, call_next):
        # Host validation also closes the same-origin DNS-rebinding path.
        try:
            local_host = request.url.hostname in self.LOOPBACK
        except ValueError:
            local_host = False
        if not local_host:
            return self._reject(403, "local_host_required")
        origin = request.headers.get("origin")
        if origin is not None:
            try:
                parsed = urlsplit(origin)
                allowed = parsed.scheme in {"http", "https"} and parsed.hostname in self.LOOPBACK
            except ValueError:
                allowed = False
            if not allowed:
                return self._reject(403, "local_origin_required")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            supplied = request.headers.get("x-eden-session", "")
            if not supplied.isascii() or not secrets.compare_digest(supplied, self.capability):
                return self._reject(401, "session_capability_required")
        return await call_next(request)

    @staticmethod
    def _reject(status, reason):
        return JSONResponse({"ok": False, "reason": reason}, status_code=status)
