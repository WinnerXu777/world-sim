from __future__ import annotations

"""
Separate LightRAG-style memory graph for resident memories and relationships.

This is intentionally distinct from the tool/instinct LightRAG:

- tool LightRAG answers: "what abilities should the world model use?"
- memory LightRAG answers: "what personal/social context matters for this agent?"

Resident sidecars remain the source of truth. MemoryLightRAG is a derived,
retrieval-oriented layer built from those sidecars.
"""

import os
import hashlib
import pickle
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

import networkx as nx
import numpy as np


EMBED_MODEL_ID = os.getenv(
    "EDEN_MEMORY_RAG_EMBED_MODEL",
    os.getenv("EDEN_LIGHTRAG_EMBED_MODEL", "BAAI/bge-small-en-v1.5"),
)
EMBED_DIM = 384
DEFAULT_MAX_RETRIEVED = 12

_embedder = None


def _default_graph_path() -> Path:
    return Path(__file__).resolve().parents[3] / "Data_Storage" / "MemoryRAG" / "memory_graph.pkl"


def _is_active_entry(entry: dict, tick: int) -> bool:
    if bool(entry.get("archived", False)):
        return False
    if bool(entry.get("permanent", False)):
        return True
    expires_tick = entry.get("expires_tick")
    if expires_tick is None:
        return True
    return int(expires_tick) >= int(tick)


def _resident_tick(resident: dict) -> int:
    snapshot = resident.get("snapshot", {})
    runtime = resident.get("runtime", {})
    status = resident.get("status", {})
    return int(
        snapshot.get(
            "tick",
            runtime.get(
                "last_seen_tick",
                status.get("last_decision_tick", 0),
            ),
        )
    )


class _TFIDFFallback:
    def __init__(self):
        self._vocab: dict[str, int] = {}

    def encode(self, texts: list[str] | str, **kwargs) -> np.ndarray:
        if isinstance(texts, str):
            texts = [texts]
        results = []
        for text in texts:
            vec = np.zeros(EMBED_DIM, dtype=np.float32)
            for word in text.lower().split():
                bucket = int.from_bytes(hashlib.blake2s(word.encode(), digest_size=4).digest(), "little") % EMBED_DIM
                vec[bucket] += 1.0
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec /= norm
            results.append(vec)
        return np.array(results, dtype=np.float32)


def _get_embedder():
    global _embedder
    if _embedder is None and os.getenv("EDEN_EMBEDDINGS", "lexical") == "lexical":
        _embedder = _TFIDFFallback()
    if _embedder is None:
        try:
            from sentence_transformers import SentenceTransformer

            _embedder = SentenceTransformer(EMBED_MODEL_ID, local_files_only=True)
            print(f"[MemoryLightRAG] Loaded embedder: {EMBED_MODEL_ID}")
        except Exception as exc:
            print(f"[MemoryLightRAG] Falling back to TF-IDF embedder: {exc}")
            _embedder = _TFIDFFallback()
    return _embedder


def embed(texts: list[str] | str) -> np.ndarray:
    if isinstance(texts, str):
        texts = [texts]
    return _get_embedder().encode(texts, normalize_embeddings=True)


class FaissIndex:
    def __init__(self, dim: int = EMBED_DIM):
        try:
            import faiss

            self._faiss = faiss
            self._index = faiss.IndexFlatIP(dim)
            self._use_faiss = True
        except ImportError:
            print("[MemoryLightRAG] FAISS not available - using numpy brute-force search")
            self._use_faiss = False
            self._vectors: list[np.ndarray] = []
        self._id_map: list[str] = []

    def add(self, node_id: str, vector: np.ndarray) -> None:
        vec = vector.astype(np.float32).reshape(1, -1)
        if self._use_faiss:
            self._index.add(vec)
        else:
            self._vectors.append(vec.flatten())
        self._id_map.append(node_id)

    def search(self, query_vector: np.ndarray, top_k: int = 8) -> list[tuple[str, float]]:
        if len(self._id_map) == 0:
            return []
        top_k = min(top_k, len(self._id_map))
        qvec = query_vector.astype(np.float32).reshape(1, -1)
        if self._use_faiss:
            scores, indices = self._index.search(qvec, top_k)
            return [
                (self._id_map[i], float(scores[0][j]))
                for j, i in enumerate(indices[0])
                if i >= 0
            ]
        matrix = np.stack(self._vectors)
        sims = (matrix @ qvec.T).flatten()
        top_idx = np.argsort(sims)[::-1][:top_k]
        return [(self._id_map[i], float(sims[i])) for i in top_idx]


@dataclass
class ResidentNode:
    id: str
    type: str = "resident"
    resident_id: str = ""
    label: str = ""
    description: str = ""
    archetype: str = ""
    tribe: float = 0.0
    alive: bool = True
    embedding: Optional[list[float]] = None


@dataclass
class RelationshipNode:
    id: str
    type: str = "relationship"
    source_id: str = ""
    target_id: str = ""
    relation_kind: str = ""
    closeness: float = 0.0
    last_seen_tick: int = 0
    description: str = ""
    embedding: Optional[list[float]] = None


@dataclass
class EventNode:
    id: str
    type: str = "event"
    resident_id: str = ""
    kind: str = ""
    tick: int = 0
    description: str = ""
    importance: float = 0.5
    embedding: Optional[list[float]] = None


@dataclass
class PlaceNode:
    id: str
    type: str = "place"
    resident_id: str = ""
    bucket: str = ""
    entity_id: int = -1
    x: float = 0.0
    y: float = 0.0
    label: str = ""
    description: str = ""
    embedding: Optional[list[float]] = None


class MemoryLightRAG:
    def __init__(
        self,
        *,
        graph_path: str | Path | None = None,
        max_retrieved: int = DEFAULT_MAX_RETRIEVED,
    ):
        self.graph = nx.DiGraph()
        self.index = FaissIndex()
        self.nodes: dict[str, object] = {}
        self.graph_path = Path(graph_path) if graph_path is not None else _default_graph_path()
        self.max_retrieved = max_retrieved
        self._index_dirty = False

    def _embed_node(self, node: object) -> np.ndarray:
        text = getattr(node, "description", "") or getattr(node, "label", getattr(node, "id", ""))
        embedding = embed(text)[0]
        node.embedding = embedding.tolist()
        return embedding

    def _rebuild_index(self) -> None:
        self.index = FaissIndex()
        for node_id, node in self.nodes.items():
            if getattr(node, "embedding", None) is None:
                self._embed_node(node)
            self.index.add(node_id, np.array(node.embedding, dtype=np.float32))
        self._index_dirty = False

    def rebuild_index(self) -> None:
        self._rebuild_index()

    def _upsert_node_no_rebuild(self, node: object) -> None:
        node_id = getattr(node, "id")
        self._embed_node(node)
        self.graph.add_node(node_id, **asdict(node))
        self.nodes[node_id] = node
        self._index_dirty = True

    def _add_edge(self, source: str, target: str, relation: str) -> None:
        if target not in self.graph:
            self.graph.add_node(target)
        self.graph.add_edge(source, target, relation=relation)

    def _ensure_resident_placeholder(self, resident_id: str) -> None:
        node_id = f"resident:{resident_id}"
        if node_id in self.nodes:
            return
        node = ResidentNode(
            id=node_id,
            resident_id=resident_id,
            label=resident_id,
            description=f"Resident placeholder for {resident_id}",
        )
        self._upsert_node_no_rebuild(node)

    def _remove_resident_derived_nodes(self, human_id: str) -> None:
        resident_node_id = f"resident:{human_id}"
        to_remove: list[str] = []
        for node_id, node in list(self.nodes.items()):
            if node_id == resident_node_id:
                continue
            node_type = getattr(node, "type", "")
            if node_type in {"event", "place"} and getattr(node, "resident_id", None) == human_id:
                to_remove.append(node_id)
            elif node_type == "relationship" and getattr(node, "source_id", None) == human_id:
                to_remove.append(node_id)
        for node_id in to_remove:
            self.graph.remove_node(node_id)
            self.nodes.pop(node_id, None)
        if to_remove:
            self._index_dirty = True

    def sync_resident(self, human_id: str, resident: dict, *, rebuild_index: bool = True) -> None:
        self._remove_resident_derived_nodes(human_id)
        profile = resident.get("profile", {})
        personality = resident.get("personality", {})
        status = resident.get("status", {})
        snapshot = resident.get("snapshot", {})
        goals = list(resident.get("goals", []))
        primary_goal = goals[0] if goals else {}
        current_tick = _resident_tick(resident)
        label = str(profile.get("name", human_id))
        resident_node_id = f"resident:{human_id}"
        resident_desc = (
            f"{label} resident {human_id}; archetype {personality.get('archetype', profile.get('personality', {}).get('archetype', 'unknown'))}; "
            f"alive {status.get('alive', True)}; intent {status.get('current_intent', 'observe')}; "
            f"mood {snapshot.get('mood', 0)}; threat {snapshot.get('threat', 0)}; tribe {snapshot.get('tribe', 0)}; "
            f"goal {primary_goal.get('kind', 'none')}"
        )
        self._upsert_node_no_rebuild(
            ResidentNode(
                id=resident_node_id,
                resident_id=human_id,
                label=label,
                description=resident_desc,
                archetype=str(personality.get("archetype", profile.get("personality", {}).get("archetype", ""))),
                tribe=float(snapshot.get("tribe", 0.0)),
                alive=bool(status.get("alive", True)),
            )
        )

        relationships = resident.get("relationships", {})
        for other_id, relation in relationships.items():
            self._ensure_resident_placeholder(other_id)
            relation_kind = str(relation.get("kind", "known"))
            tag_meta = relation.get("tag_meta", {})
            relation_tags = []
            for tag in [str(tag) for tag in relation.get("tags", []) if str(tag).strip()] or [relation_kind]:
                if _is_active_entry(dict(tag_meta.get(tag, {})), current_tick):
                    relation_tags.append(tag)
            if not relation_tags:
                continue
            closeness = float(relation.get("closeness", 0.0))
            last_seen_tick = int(relation.get("last_seen_tick", 0))
            for relation_tag in relation_tags:
                relation_id = f"relationship:{human_id}:{other_id}:{relation_tag}"
                relation_desc = (
                    f"{label} has {relation_tag} relationship with {other_id}; "
                    f"primary kind {relation_kind}; closeness {closeness}; last seen tick {last_seen_tick}"
                )
                self._upsert_node_no_rebuild(
                    RelationshipNode(
                        id=relation_id,
                        source_id=human_id,
                        target_id=other_id,
                        relation_kind=relation_tag,
                        closeness=closeness,
                        last_seen_tick=last_seen_tick,
                        description=relation_desc,
                    )
                )
                self._add_edge(resident_node_id, relation_id, "has_relationship")
                self._add_edge(relation_id, f"resident:{other_id}", relation_tag)

        memory = resident.get("memory", {})
        self._sync_event_bucket(
            human_id,
            label,
            [entry for entry in memory.get("recent_events", []) if _is_active_entry(entry, current_tick)],
        )
        self._sync_place_bucket(
            human_id,
            label,
            "known_food_sources",
            [entry for entry in memory.get("known_food_sources", []) if _is_active_entry(entry, current_tick)],
        )
        self._sync_place_bucket(
            human_id,
            label,
            "known_water_sources",
            [entry for entry in memory.get("known_water_sources", []) if _is_active_entry(entry, current_tick)],
        )
        self._sync_threat_bucket(
            human_id,
            label,
            [entry for entry in memory.get("last_threats", []) if _is_active_entry(entry, current_tick)],
        )
        if rebuild_index:
            self._rebuild_index()

    def _sync_event_bucket(self, human_id: str, label: str, entries: list[dict]) -> None:
        resident_node_id = f"resident:{human_id}"
        for entry_idx, entry in enumerate(entries):
            tick = int(entry.get("tick", 0))
            kind = str(entry.get("kind", "event"))
            event_id = f"event:{human_id}:{tick}:{entry_idx}:{kind}"
            note = (
                str(entry.get("note", ""))
                or str(entry.get("reason", ""))
                or str(entry.get("intent", ""))
            )
            other_human_id = str(entry.get("other_human_id", "")).strip()
            if other_human_id:
                note = f"{note} related human {other_human_id}".strip()
            if entry.get("other_entity_id") is not None:
                note = f"{note} related entity {int(entry['other_entity_id'])}".strip()
            if entry.get("x") is not None and entry.get("y") is not None:
                note = f"{note} at ({round(float(entry['x']),2)}, {round(float(entry['y']),2)})".strip()
            desc = f"{label} event {kind} at tick {tick}. {note}".strip()
            importance = float(entry.get("salience", 0.8 if kind in {"death", "decision"} else 0.5))
            self._upsert_node_no_rebuild(
                EventNode(
                    id=event_id,
                    resident_id=human_id,
                    kind=kind,
                    tick=tick,
                    description=desc,
                    importance=importance,
                )
            )
            self._add_edge(resident_node_id, event_id, "remembers")
            if other_human_id:
                self._ensure_resident_placeholder(other_human_id)
                self._add_edge(event_id, f"resident:{other_human_id}", "involves")

    def _sync_place_bucket(self, human_id: str, label: str, bucket: str, entries: list[dict]) -> None:
        resident_node_id = f"resident:{human_id}"
        for entry in entries:
            entity_id = int(entry.get("entity_id", -1))
            name = entry.get("uid") or entity_id          # window mode names the source by uid: a slot is reused, a uid is not
            tick = int(entry.get("tick", 0))
            x = float(entry.get("x", 0.0))
            y = float(entry.get("y", 0.0))
            place_id = f"place:{human_id}:{bucket}:{name}"
            desc = f"{label} remembers {bucket} entity {name} at ({round(x,2)}, {round(y,2)}) from tick {tick}"
            self._upsert_node_no_rebuild(
                PlaceNode(
                    id=place_id,
                    resident_id=human_id,
                    bucket=bucket,
                    entity_id=entity_id,
                    x=x,
                    y=y,
                    label=f"{bucket}:{name}",
                    description=desc,
                )
            )
            self._add_edge(resident_node_id, place_id, "knows_place")

    def _sync_threat_bucket(self, human_id: str, label: str, entries: list[dict]) -> None:
        resident_node_id = f"resident:{human_id}"
        for entry_idx, entry in enumerate(entries):
            tick = int(entry.get("tick", 0))
            kind = str(entry.get("kind", "threat"))
            distance = float(entry.get("distance", 0.0))
            x = float(entry.get("x", 0.0))
            y = float(entry.get("y", 0.0))
            event_id = f"threat:{human_id}:{tick}:{entry_idx}:{kind}"
            desc = (
                f"{label} remembers threat {kind} at ({round(x,2)}, {round(y,2)}) "
                f"distance {round(distance,2)} from tick {tick}"
            )
            self._upsert_node_no_rebuild(
                EventNode(
                    id=event_id,
                    resident_id=human_id,
                    kind=kind,
                    tick=tick,
                    description=desc,
                    importance=float(entry.get("salience", 0.75)),
                )
            )
            self._add_edge(resident_node_id, event_id, "fears")

    def retrieve_nodes(
        self,
        query: str,
        *,
        resident_id: str | None = None,
        top_k_per_query: int = 6,
        traversal_depth: int = 2,
        type_filter: set[str] | None = None,
    ) -> list[dict[str, object]]:
        if not self.nodes:
            return []
        if self._index_dirty:
            self._rebuild_index()
        t0 = time.perf_counter()
        qvec = embed(query)[0]
        hits = self.index.search(qvec, top_k=max(top_k_per_query, self.max_retrieved))
        candidate_ids: set[str] = {node_id for node_id, score in hits if score > 0.15}

        resident_node_id = f"resident:{resident_id}" if resident_id else None
        if resident_node_id and resident_node_id in self.graph:
            candidate_ids.add(resident_node_id)
            candidate_ids.update(self._traverse(resident_node_id, depth=max(1, traversal_depth)))

        expanded: set[str] = set(candidate_ids)
        for node_id in list(candidate_ids):
            expanded.update(self._traverse(node_id, depth=traversal_depth))

        rows: list[dict[str, object]] = []
        for node_id in self._prioritize(expanded, resident_id=resident_id):
            node = self.nodes.get(node_id)
            if node is None:
                continue
            node_type = getattr(node, "type", "")
            if type_filter and node_type not in type_filter:
                continue
            rows.append(
                {
                    "id": node_id,
                    "type": node_type,
                    "label": getattr(node, "label", node_id),
                    "description": getattr(node, "description", ""),
                }
            )
            if len(rows) >= self.max_retrieved:
                break
        elapsed_ms = (time.perf_counter() - t0) * 1000
        print(f"[MemoryLightRAG] Retrieved {len(rows)} nodes in {elapsed_ms:.1f}ms")
        return rows

    def retrieve_bundle(
        self,
        query: str,
        *,
        resident_id: str | None = None,
        top_k_per_query: int = 6,
        traversal_depth: int = 2,
        type_filter: set[str] | None = None,
    ) -> dict[str, object]:
        rows = self.retrieve_nodes(
            query,
            resident_id=resident_id,
            top_k_per_query=top_k_per_query,
            traversal_depth=traversal_depth,
            type_filter=type_filter,
        )
        return {
            "query": query,
            "resident_id": resident_id,
            "node_count": len(rows),
            "nodes": rows,
            "context": self._format_context(rows),
        }

    def _format_context(self, rows: list[dict[str, object]]) -> str:
        lines = []
        for row in rows:
            lines.append(f"- [{row['type']}] {row['label']}: {row['description']}")
        return "\n".join(lines)

    def _traverse(self, start_id: str, depth: int = 2) -> set[str]:
        visited = set()
        frontier = {start_id}
        for _ in range(depth):
            next_frontier = set()
            for node_id in frontier:
                for neighbor in self.graph.successors(node_id):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_frontier.add(neighbor)
                for neighbor in self.graph.predecessors(node_id):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_frontier.add(neighbor)
            frontier = next_frontier
        return visited

    def _prioritize(self, node_ids: set[str], *, resident_id: str | None = None) -> list[str]:
        resident_node_id = f"resident:{resident_id}" if resident_id else None
        type_order = {"resident": 0, "relationship": 1, "event": 2, "place": 3}

        def _sort_key(node_id: str) -> tuple[int, int, str]:
            node = self.nodes.get(node_id)
            node_type = getattr(node, "type", "misc") if node is not None else "misc"
            focus_bonus = 0
            if resident_node_id and node_id == resident_node_id:
                focus_bonus = -2
            elif resident_id and resident_id in node_id:
                focus_bonus = -1
            return (type_order.get(node_type, 9), focus_bonus, node_id)

        return sorted(node_ids, key=_sort_key)

    def stats(self) -> dict[str, object]:
        type_counts: dict[str, int] = {}
        for node in self.nodes.values():
            node_type = getattr(node, "type", "unknown")
            type_counts[node_type] = type_counts.get(node_type, 0) + 1
        return {
            "total_nodes": len(self.nodes),
            "total_edges": self.graph.number_of_edges(),
            "type_counts": type_counts,
            "graph_path": str(self.graph_path),
            "index_dirty": self._index_dirty,
        }

    def serialize(self) -> bytes:
        """The pickled graph. Cheap (no disk), so it is taken on the tick thread and written elsewhere."""
        return pickle.dumps({"graph": self.graph, "nodes": self.nodes, "max_retrieved": self.max_retrieved})

    def save(self, path: str | Path | None = None) -> None:
        target = Path(path) if path is not None else self.graph_path
        write_graph_file(target, self.serialize(), len(self.nodes))

    def load(self, path: str | Path | None = None) -> None:
        source = Path(path) if path is not None else self.graph_path
        with source.open("rb") as handle:
            payload = pickle.load(handle)
        self.graph = payload["graph"]
        self.nodes = payload["nodes"]
        self.max_retrieved = int(payload.get("max_retrieved", self.max_retrieved))
        self._rebuild_index()
        print(f"[MemoryLightRAG] Loaded graph ({len(self.nodes)} nodes) from {source}")


def write_graph_file(target: Path, blob: bytes, node_count: int) -> None:
    """Write through a temp file and replace, so a reader (or a crash) never sees a half-written graph."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    with temp.open("wb") as handle:
        handle.write(blob)
    os.replace(temp, target)
    print(f"[MemoryLightRAG] Saved graph ({node_count} nodes) to {target}")


class BackgroundGraphWriter:
    """Writes serialized graphs on a daemon thread; only the newest pending blob is kept (a debounce by coalescing)."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._pending: Optional[tuple] = None
        self._busy = False
        self._thread: Optional[threading.Thread] = None
        self.writes = 0
        self.errors = 0
        self.last_error = ""

    def submit(self, target, blob: bytes, node_count: int) -> None:
        with self._cond:
            self._pending = (Path(target), blob, node_count)
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="eden-memory-graph-writer", daemon=True)
                self._thread.start()
            self._cond.notify_all()

    def _run(self) -> None:
        while True:
            with self._cond:
                while self._pending is None:
                    if not self._cond.wait(timeout=30.0) and self._pending is None:
                        self._thread = None  # idle for 30 s: let the thread go, submit() starts a new one
                        return
                job, self._pending, self._busy = self._pending, None, True
            try:
                write_graph_file(*job)
                self.writes += 1
            except Exception as exc:  # noqa: BLE001 - a failed derived-index write must never reach the tick loop
                self.errors += 1
                self.last_error = f"{type(exc).__name__}: {exc}"[:200]
            finally:
                with self._cond:
                    self._busy = False
                    self._cond.notify_all()

    def drain(self, timeout: float = 10.0) -> bool:
        """Wait until nothing is pending or being written."""
        deadline = time.monotonic() + timeout
        with self._cond:
            while self._pending is not None or self._busy:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self._cond.wait(timeout=remaining)
        return True

    def discard(self, timeout: float = 10.0) -> None:
        """Drop what has not started yet and wait for a write in progress (used before the file is deleted or rewritten)."""
        with self._cond:
            self._pending = None
        self.drain(timeout)

    def status(self) -> dict:
        return {"writes": self.writes, "errors": self.errors, "last_error": self.last_error, "pending": self._pending is not None}


def build_or_load_default_memory_rag(
    *,
    graph_path: str | Path | None = None,
    force_rebuild: bool = False,
    max_retrieved: int = DEFAULT_MAX_RETRIEVED,
) -> MemoryLightRAG:
    rag = MemoryLightRAG(graph_path=graph_path, max_retrieved=max_retrieved)
    target = Path(graph_path) if graph_path is not None else rag.graph_path
    if target.exists() and not force_rebuild:
        rag.load(target)
    return rag


__all__ = [
    "EventNode",
    "MemoryLightRAG",
    "PlaceNode",
    "RelationshipNode",
    "ResidentNode",
    "build_or_load_default_memory_rag",
]
