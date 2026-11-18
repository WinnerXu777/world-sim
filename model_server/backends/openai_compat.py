"""OpenAI-compatible chat backend (vLLM, SGLang, Ollama, hosted): config only, deliberately thin.

Configuration: base URL, the NAME of the environment variable holding the key (the key itself is never stored or logged),
and a model id. The prompt asks for a JSON object; the app validates it against the contract before it reaches the game.
"""
from __future__ import annotations

import json
import os
import re

import httpx

from ..contract import Envelope
from .base import Backend, BackendError, CallContext

SYSTEM = {
    "decide": ("You are a decision model for a village simulation. Reply with ONLY a JSON object mapping every option id to a "
               "probability (non-negative, summing to 1). Do not add or drop options."),
    "batch": ("You are a game character model. Reply with ONLY a JSON object {\"responses\": [{\"packet\": {...}}, ...]} with one "
              "entry per case, in order, following the structured packet contract for the given mode. No prose."),
}


def _extract_json(text: str):
    text = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    return json.loads(fenced.group(1) if fenced else text)


class OpenAICompatBackend(Backend):
    kind = "openai_compat"
    provider_mode = "live"

    def __init__(self, base_url: str = "", key_env: str = "", model: str = "", temperature: float = 0.2,
                 timeout_s: float = 30.0, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.key_env = key_env
        self.model_id = model or "unconfigured"
        self.temperature = temperature
        self.timeout_s = timeout_s
        self._client = client

    def ready(self):
        if not self.base_url or self.model_id == "unconfigured":
            return False, "base_url and model are required"
        if self.key_env and not os.environ.get(self.key_env):
            return False, f"environment variable {self.key_env} is not set"
        return True, "configured (not probed)"

    def _messages(self, envelope: Envelope):
        if envelope.role == "decide":
            body = {"question": envelope.payload.get("question_kind"), "resident": envelope.payload["resident_id"],
                    "trigger": envelope.payload["trigger"], "state": envelope.payload.get("state", {}),
                    "options": envelope.payload["options"]}
            return [{"role": "system", "content": SYSTEM["decide"]}, {"role": "user", "content": json.dumps(body)}]
        body = {"role": envelope.role, "mode": envelope.payload["mode"], "cases": envelope.payload["cases"]}
        return [{"role": "system", "content": SYSTEM["batch"]}, {"role": "user", "content": json.dumps(body)}]

    def handle(self, envelope: Envelope, ctx: CallContext) -> dict:
        ok, why = self.ready()
        if not ok:
            raise BackendError("backend_unavailable", why)
        headers = {"Content-Type": "application/json"}
        if self.key_env:
            headers["Authorization"] = f"Bearer {os.environ[self.key_env]}"
        body = {"model": self.model_id, "temperature": self.temperature, "messages": self._messages(envelope)}
        timeout = max(0.05, min(self.timeout_s, ctx.deadline_s))
        try:
            client = self._client or httpx.Client(timeout=timeout)
            try:
                reply = client.post(f"{self.base_url}/chat/completions", json=body, headers=headers, timeout=timeout)
            finally:
                if self._client is None:
                    client.close()
        except httpx.HTTPError as exc:
            raise BackendError("backend_unavailable", f"{type(exc).__name__}: {exc}") from exc
        if reply.status_code >= 400:
            raise BackendError("backend_unavailable", f"upstream status {reply.status_code}")
        try:
            content = reply.json()["choices"][0]["message"]["content"]
            parsed = _extract_json(content)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise BackendError("backend_error", f"upstream reply is not the expected JSON: {type(exc).__name__}") from exc
        if envelope.role == "decide":
            return {"probabilities": parsed.get("probabilities", parsed) if isinstance(parsed, dict) else parsed}
        if isinstance(parsed, dict) and "responses" in parsed:
            return {"mode": envelope.payload["mode"], "responses": parsed["responses"]}
        raise BackendError("backend_error", "upstream reply has no responses list")
