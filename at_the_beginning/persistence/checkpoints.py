"""Atomic manifest commits referencing immutable, checksummed world generations."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import time
import uuid
from pathlib import Path

from .codec import MAX_BYTES


class CheckpointError(ValueError):
    pass


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


class CheckpointStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def directory(self, save_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", save_id):
            raise CheckpointError("Invalid save ID")
        result = (self.root / save_id).resolve()
        if not result.is_relative_to(self.root):
            raise CheckpointError("Save path leaves storage root")
        return result

    def manifest(self, save_id: str) -> dict:
        path = self.directory(save_id) / "manifest.json"
        if path.stat().st_size > 1024 * 1024:
            raise CheckpointError("Invalid checkpoint manifest size")
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if manifest.get("schema") != 1 or manifest.get("save_id") != save_id:
            raise CheckpointError("Unsupported checkpoint manifest")
        return manifest

    def commit(self, save_id: str, name: str, tick: int, payload: bytes, world_format: int = 1) -> dict:
        directory = self.directory(save_id)
        if len(payload) > MAX_BYTES:
            raise CheckpointError("World snapshot too large")
        old = self.manifest(save_id) if (directory / "manifest.json").exists() else None
        generation = uuid.uuid4().hex
        compressed = gzip.compress(payload, mtime=0)
        atomic_write(directory / f"{generation}.json.gz", compressed)
        # A crash before this replace leaves an orphan file; it is not a committed save.
        entry = {"id": generation, "sha256": hashlib.sha256(compressed).hexdigest(),
                 "tick": tick, "saved_at": time.time()}
        if world_format != 1:  # format-1 manifests stay byte-identical; entries without the key count as format 1
            entry["world_format"] = world_format
        manifest = {"schema": 1, "save_id": save_id, "name": name,
                    "generations": [entry, *(old["generations"] if old else [])][:8]}
        atomic_write(directory / "manifest.json", json.dumps(manifest).encode("utf-8"))
        return entry

    def read(self, save_id: str) -> tuple[bytes, dict]:
        manifest = self.manifest(save_id)
        errors = []
        for index, entry in enumerate(manifest["generations"]):
            try:
                generation = entry["id"]
                if not re.fullmatch(r"[0-9a-f]{32}", generation):
                    raise CheckpointError("Invalid generation ID")
                path = self.directory(save_id) / f"{generation}.json.gz"
                if path.stat().st_size > MAX_BYTES:
                    raise CheckpointError("Compressed snapshot too large")
                compressed = path.read_bytes()
                if hashlib.sha256(compressed).hexdigest() != entry["sha256"]:
                    raise CheckpointError("Snapshot checksum mismatch")
                with gzip.open(path, "rb") as handle:
                    data = handle.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES:
                    raise CheckpointError("Expanded snapshot too large")
                return data, {**entry, "save_id": save_id, "name": manifest["name"],
                              "recovered_previous": index > 0}
            except (OSError, ValueError, KeyError, EOFError) as exc:
                errors.append(str(exc))
        raise CheckpointError("No complete checkpoint: " + "; ".join(errors))

    def list_saves(self) -> list[dict]:
        saves = []
        for path in self.root.iterdir():
            if not path.is_dir() or not re.fullmatch(r"[0-9a-f]{32}", path.name):
                continue
            try:
                manifest = self.manifest(path.name)
                newest = manifest["generations"][0]
                save = {"save_id": path.name, "name": manifest["name"], **newest}
                from .world_snapshot import current_format
                fmt = save.get("world_format", 1)
                if fmt != 1 or current_format() != 1:  # additive: flag-off listings of format-1 saves keep their exact keys
                    save["compatible"] = fmt == current_format()
                saves.append(save)
            except (OSError, ValueError, KeyError, IndexError):
                continue
        return sorted(saves, key=lambda save: save["saved_at"], reverse=True)
