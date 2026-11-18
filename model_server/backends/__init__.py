"""Backend registry: mock | rules | recorded | openai_compat | clef."""
from .base import Backend, BackendError, CallContext
from .clef import ClefBackend
from .mock import MockBackend
from .openai_compat import OpenAICompatBackend
from .recorded import Recorder, RecordedBackend
from .rules import RulesBackend

KINDS = ("mock", "rules", "recorded", "openai_compat", "clef")


def make_backend(kind: str, options: dict | None = None) -> Backend:
    options = dict(options or {})
    if kind == "mock":
        return MockBackend(delay_ms=float(options.get("delay_ms", 0)))
    if kind == "rules":
        return RulesBackend()
    if kind == "recorded":
        return RecordedBackend(path=options.get("path"))
    if kind == "openai_compat":
        return OpenAICompatBackend(base_url=options.get("url", ""), key_env=options.get("key_env", ""), model=options.get("model", ""),
                                   timeout_s=float(options.get("timeout_s", 30)))
    if kind == "clef":
        return ClefBackend(base_url=options.get("url", ""), key_env=options.get("key_env", ""), model=options.get("model", ""))
    raise ValueError(f"unknown backend kind {kind!r}; choose one of {KINDS}")


__all__ = ["Backend", "BackendError", "CallContext", "ClefBackend", "KINDS", "MockBackend", "OpenAICompatBackend", "RecordedBackend",
           "Recorder", "RulesBackend", "make_backend"]
