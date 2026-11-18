"""Model plane server side: wire contract v1 (shared with the game), mock/rules/recorded/openai_compat/clef backends, FastAPI app.

``contract`` and ``schema`` are stdlib only. ``app``/``backends`` need fastapi. Nothing here hosts, trains or imports a model.
"""
from .contract import SCHEMA_VERSION  # noqa: F401
