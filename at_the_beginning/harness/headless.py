"""Boot the real legacy Engine headlessly and deterministically, in a fresh process.

This is the shared setup for ``tools/golden_trace.py`` and ``tools/profile_tick.py``. It must run in a process that has
not yet imported ``map_test`` (``map_test`` reads its configuration from the environment at import time and owns a
module-level ``engine`` singleton), so callers use it from a ``__main__`` script or a subprocess, never from a unit test
that already imported the backend.

Nothing here changes behaviour: it sets the environment the way ``tools/soak_headless.py`` does, seeds the three global
RNGs, and runs ``create_genesis``.
"""
from __future__ import annotations

import json
import os
import random
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAP_NAMES = ("starter_village", "smith_interior", "village_lodge_interior", "west_cottage_interior")
MAP_ORIGINS = {"smith_interior": [620, 0], "village_lodge_interior": [620, 400], "west_cottage_interior": [960, 160]}


def configure_environment(data_root: Path | None = None) -> Path:
    """Set the EDEN_* environment for an isolated authored-village world; returns the data root used."""
    if data_root is None:
        runtime = ROOT / ".runtime"
        data_root = Path(tempfile.mkdtemp(prefix="eden-harness-", dir=str(runtime) if runtime.exists() else None))
    os.environ.update(
        EDEN_PROFILE="gameplay", EDEN_DATA_ROOT=str(data_root), EDEN_MAP="starter_village", EDEN_EMBEDDINGS="lexical",
        EDEN_MAP_FILES=os.pathsep.join(str(ROOT / "world_data" / "maps2d" / f"{name}.json") for name in MAP_NAMES),
        EDEN_MAP_ORIGINS=json.dumps(MAP_ORIGINS))
    legacy_dir = str(ROOT / "at_the_beginning")
    if legacy_dir not in sys.path:
        sys.path.insert(0, legacy_dir)
    return Path(data_root)


def seed_globals(seed: int) -> None:
    """Seed every process-global generator the legacy code uses (python, numpy, torch)."""
    import numpy as np
    import torch
    random.seed(seed)
    np.random.seed(seed % (2 ** 32))
    torch.manual_seed(seed)


async def boot_engine(seed: int):
    """Reset the backend singleton, seed the RNGs and create the starter village. Returns ``(backend_module, engine)``."""
    import map_test as backend  # noqa: PLC0415 - must come after configure_environment
    engine = backend.engine
    engine.reset_world()
    seed_globals(seed)
    await backend.create_genesis(engine, map_name="starter_village")
    return backend, engine
