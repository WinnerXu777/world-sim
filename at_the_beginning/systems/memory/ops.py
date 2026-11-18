from __future__ import annotations

"""Stable, generation-friendly memory ops."""

from typing import Any

from .graph_sync import sync_all_residents_to_memory_graph, sync_resident_to_memory_graph
from .retrieval import build_human_memory_bundle


def sync_memory_graph(memory_rag, resident_store, *, human_id: str | None = None, save: bool = False) -> dict[str, Any]:
    if human_id:
        synced = sync_resident_to_memory_graph(memory_rag, resident_store, human_id, save=save)
        return {"synced": int(bool(synced)), "human_id": human_id}
    return sync_all_residents_to_memory_graph(memory_rag, resident_store, save=save)


def remember_resource_and_sync(
    memory_rag,
    resident_store,
    *,
    human_id: str,
    bucket: str,
    entity_id: int,
    pos: tuple[float, float],
    tick: int,
    save: bool = False,
    uid: str | None = None,
    abs_pos: dict | None = None,
) -> None:
    resident_store.remember_resource(human_id, bucket, entity_id, pos, tick, uid=uid, abs_pos=abs_pos)
    sync_resident_to_memory_graph(memory_rag, resident_store, human_id, save=save)


def remember_threat_and_sync(
    memory_rag,
    resident_store,
    *,
    human_id: str,
    kind: str,
    pos: tuple[float, float],
    tick: int,
    distance: float,
    save: bool = False,
) -> None:
    resident_store.remember_threat(human_id, kind, pos, tick, distance)
    sync_resident_to_memory_graph(memory_rag, resident_store, human_id, save=save)


def update_relationship_and_sync(
    memory_rag,
    resident_store,
    *,
    human_id: str,
    other_id: str,
    relation_kind: str,
    closeness_delta: float,
    tick: int,
    save: bool = False,
) -> None:
    resident_store.update_relationship(human_id, other_id, relation_kind, closeness_delta, tick)
    sync_resident_to_memory_graph(memory_rag, resident_store, human_id, save=False)
    sync_resident_to_memory_graph(memory_rag, resident_store, other_id, save=save)


def retrieve_memory_context(
    memory_rag,
    resident_store,
    *,
    human_id: str,
    query: str | None = None,
    case: dict[str, Any] | None = None,
    top_k_per_query: int = 6,
    traversal_depth: int = 2,
) -> dict[str, Any]:
    return build_human_memory_bundle(
        memory_rag,
        resident_store,
        human_id,
        query=query,
        case=case,
        top_k_per_query=top_k_per_query,
        traversal_depth=traversal_depth,
    )


__all__ = [
    "remember_resource_and_sync",
    "remember_threat_and_sync",
    "retrieve_memory_context",
    "sync_memory_graph",
    "update_relationship_and_sync",
]
