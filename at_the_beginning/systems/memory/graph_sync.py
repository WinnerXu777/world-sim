from __future__ import annotations

"""Sync resident sidecars into MemoryLightRAG."""

from pathlib import Path
from typing import Any

from .state_memoryrag import MemoryLightRAG


def sync_resident_to_memory_graph(
    memory_rag: MemoryLightRAG,
    resident_store: Any,
    human_id: str,
    *,
    save: bool = False,
) -> bool:
    resident = resident_store.get(human_id)
    if resident is None:
        return False
    memory_rag.sync_resident(human_id, resident, rebuild_index=False)
    if save:
        memory_rag.save()
    return True


def sync_all_residents_to_memory_graph(
    memory_rag: MemoryLightRAG,
    resident_store: Any,
    *,
    save: bool = False,
) -> dict[str, int]:
    synced = 0
    human_ids = {path.stem for path in Path(resident_store.root_dir).glob("*.json")}
    human_ids.update(getattr(resident_store, "_cache", {}).keys())
    for human_id in sorted(human_ids):
        resident = resident_store.get(human_id)
        if resident is None:
            continue
        memory_rag.sync_resident(human_id, resident, rebuild_index=False)
        synced += 1
    if synced:
        memory_rag.rebuild_index()
    if save:
        memory_rag.save()
    return {"synced": synced}


def sync_resident_batch_to_memory_graph(
    memory_rag: MemoryLightRAG,
    resident_store: Any,
    human_ids: list[str] | tuple[str, ...] | set[str],
    *,
    save: bool = False,
) -> dict[str, int]:
    synced = 0
    for human_id in sorted(set(str(human_id) for human_id in human_ids if human_id)):
        resident = resident_store.get(human_id)
        if resident is None:
            continue
        memory_rag.sync_resident(human_id, resident, rebuild_index=False)
        synced += 1
    if synced:
        memory_rag.rebuild_index()
    if save:
        memory_rag.save()
    return {"synced": synced}


__all__ = [
    "sync_all_residents_to_memory_graph",
    "sync_resident_batch_to_memory_graph",
    "sync_resident_to_memory_graph",
]
