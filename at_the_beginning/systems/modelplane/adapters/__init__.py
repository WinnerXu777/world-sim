"""Adapters between the model plane and the legacy hooks / the held Clef API."""
from .legacy import LegacyModelHandler, install, sync_installation

__all__ = ["LegacyModelHandler", "install", "sync_installation"]
