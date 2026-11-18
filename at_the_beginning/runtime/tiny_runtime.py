from __future__ import annotations

from copy import deepcopy
from typing import Any


TINY_OUTPUT_SCHEMA_VERSION = 1

TINY_MODE_URGENT = "urgent_react"
TINY_MODE_NORMAL = "normal_live"
TINY_MODE_TALK_REPLY = "talk_reply"
TINY_MODE_AMBIENT_NPC_TALK = "ambient_npc_talk"


def _call_tiny_model_handler(handler: Any, mode: str, cases: list[dict[str, Any]], engine: Any) -> Any:
    if callable(handler):
        try:
            return handler(mode=mode, cases=cases, engine=engine)
        except TypeError:
            try:
                return handler(mode, cases, engine)
            except TypeError:
                return handler(mode=mode, cases=cases)

    run_mode_batch = getattr(handler, "run_mode_batch", None)
    if callable(run_mode_batch):
        return run_mode_batch(mode=mode, cases=cases, engine=engine)

    infer_mode_batch = getattr(handler, "infer_mode_batch", None)
    if callable(infer_mode_batch):
        return infer_mode_batch(mode=mode, cases=cases, engine=engine)

    infer_batch = getattr(handler, "infer_batch", None)
    if callable(infer_batch):
        return infer_batch(mode=mode, cases=cases, engine=engine)

    return None


class TinyModelRuntime:
    def __init__(self) -> None:
        self.history: list[dict[str, Any]] = []
        self.batch_history: list[dict[str, Any]] = []

    def reset(self) -> None:
        self.history.clear()
        self.batch_history.clear()

    def status_snapshot(self) -> dict[str, Any]:
        return {
            "recent_outputs": self.history[-12:],
            "recent_batches": self.batch_history[-12:],
        }

    def _tiny_model_handler(self, engine: Any) -> tuple[Any | None, str]:
        engine_runner = getattr(engine, "run_tiny_model_mode_batch", None)
        if callable(engine_runner):
            return engine_runner, "engine.run_tiny_model_mode_batch"
        handler = getattr(engine, "tiny_model_handler", None)
        if handler is not None:
            return handler, "engine.tiny_model_handler"
        resident_handler = getattr(engine, "resident_model_handler", None)
        if resident_handler is not None:
            return resident_handler, "engine.resident_model_handler"
        tiny_model = getattr(engine, "tiny_model", None)
        if tiny_model is not None:
            return tiny_model, "engine.tiny_model"
        return None, "mock_tiny_model"

    def _normalize_tiny_model_response(
        self,
        response: Any,
        *,
        mode: str,
        fallback_packet: dict[str, Any],
        fallback_source: str,
    ) -> dict[str, Any]:
        packet = None
        source = str(fallback_source or "mock_tiny_model")
        if isinstance(response, dict):
            source = str(response.get("source") or response.get("model_source") or source)
            candidate_packet = response.get("packet")
            if isinstance(candidate_packet, dict):
                packet = dict(candidate_packet)
            elif mode in {TINY_MODE_URGENT, TINY_MODE_NORMAL} and (
                "intent" in response or "action" in response
            ):
                packet = dict(response)
            elif mode in {TINY_MODE_TALK_REPLY, TINY_MODE_AMBIENT_NPC_TALK} and "speech_text" in response:
                packet = dict(response)
        if packet is None:
            packet = deepcopy(dict(fallback_packet or {}))
            source = f"{source}:fallback"
        packet.setdefault("schema_version", TINY_OUTPUT_SCHEMA_VERSION)
        packet.setdefault("resident_model_mode", str(mode))
        packet["source"] = str(source)
        packet["mock"] = bool(packet.get("mock", False) or "mock" in str(source).lower())
        return {
            "packet": packet,
            "source": str(source),
            "mock": bool(packet.get("mock", False)),
        }

    def run_mode_batch(
        self,
        *,
        mode: str,
        cases: list[dict[str, Any]],
        engine: Any,
        fallback_packets: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        normalized_mode = str(mode or "").strip().lower()
        fallback_packets = [dict(packet or {}) for packet in list(fallback_packets or [])]
        while len(fallback_packets) < len(cases):
            fallback_packets.append({})

        use_mock = bool(getattr(engine, "mock_tiny_model_enabled", False))
        handler, fallback_source = self._tiny_model_handler(engine)
        responses: Any = None
        source_label = fallback_source
        if not use_mock and handler is not None:
            try:
                responses = _call_tiny_model_handler(handler, normalized_mode, cases, engine)
            except Exception as exc:  # pragma: no cover - runtime fallback
                source_label = f"{fallback_source}_error:{exc.__class__.__name__}"
                responses = None
        else:
            source_label = "mock_tiny_model"

        if isinstance(responses, dict) and isinstance(responses.get("responses"), list):
            responses = responses["responses"]
        elif isinstance(responses, dict):
            responses = [responses]
        elif not isinstance(responses, list):
            responses = []

        results: list[dict[str, Any]] = []
        for idx, case in enumerate(cases):
            response = responses[idx] if idx < len(responses) else None
            result = self._normalize_tiny_model_response(
                response,
                mode=normalized_mode,
                fallback_packet=fallback_packets[idx],
                fallback_source=source_label,
            )
            packet = dict(result.get("packet") or {})
            self.history.append(
                {
                    "mode": normalized_mode,
                    "source": str(result.get("source", "")),
                    "mock": bool(result.get("mock", False)),
                    "human_id": str(packet.get("human_id", "")),
                    "speaker_id": str(packet.get("speaker_id", "")),
                    "intent": str(packet.get("intent", "")),
                    "speech_act": str(packet.get("speech_act", "")),
                }
            )
            results.append(result)

        self.history = self.history[-30:]
        self.batch_history.append(
            {
                "mode": normalized_mode,
                "count": len(cases),
                "source": source_label,
                "mock": bool(use_mock or handler is None),
            }
        )
        self.batch_history = self.batch_history[-30:]
        return results


__all__ = [
    "TINY_MODE_AMBIENT_NPC_TALK",
    "TINY_MODE_NORMAL",
    "TINY_MODE_TALK_REPLY",
    "TINY_MODE_URGENT",
    "TINY_OUTPUT_SCHEMA_VERSION",
    "TinyModelRuntime",
]
