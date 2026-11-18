"""Which matrix weights Tier 1 uses: the rules prior (``MatrixPolicy.initial()``, weights v1) unless ``EDEN_MATRIX_WEIGHTS=<version>`` names a shipped file that loads and verifies
(format, schema, menu, content hash); any failure falls back to the rules prior and is recorded in ``STATUS``. Trained files come from ``model_server/train_matrix.py`` (imitation of
the rules prior; deterministic; the provenance sits beside the file).
"""
from __future__ import annotations

import os

ENV = "EDEN_MATRIX_WEIGHTS"
STATUS: dict = {"requested": None, "version": 1, "fallback": False, "reason": ""}


def default_policy():
    """The policy an agent driver or the Tier 3 escalator builds when none is injected."""
    from systems.decision import matrix
    requested = os.environ.get(ENV, "").strip()
    STATUS.update(requested=requested or None, version=1, fallback=False, reason="")
    if requested.isdigit() and int(requested) > 1:
        try:
            policy = matrix.MatrixPolicy.load(matrix.default_weights_path(int(requested)))
            STATUS["version"] = policy.version
            return policy
        except Exception as error:            # a missing, tampered or stale file must never stop the village: the rules prior stands
            STATUS.update(fallback=True, reason=f"{type(error).__name__}: {error}")
    elif requested and requested != "1":
        STATUS.update(fallback=True, reason=f"unrecognised version {requested!r}")
    return matrix.MatrixPolicy.initial()
