"""
eden_lightrag.py
================
LightRAG implementation for Eden's tool registry.

Architecture:
  Layer 1 — FAISS vector index  : semantic similarity search
  Layer 2 — NetworkX graph       : structural traversal + dependency expansion

Retrieval pipeline:
  1. Decompose god command into sub-queries (map / human / event intents)
  2. FAISS similarity search per sub-query → candidate node ids
  3. NetworkX traversal from each candidate → expand to related tools
  4. Union + deduplicate + always append Tier A primitives + propose_*
  5. Format as compact tool registry string for world agent prompt injection

Node types:
  tool        — Tier A/B/C tools and instincts
  tensor_col  — h_tensor and m_tensor column definitions
  map_entity  — M_LAKE, M_FOREST etc + dynamically spawned types
  concept     — game events / phenomena (plague, famine, drought...)
  asset       — sprite library entries

Usage:
  from eden_lightrag import EdenLightRAG
  rag = EdenLightRAG()
  rag.load("eden_graph.pkl")          # load persisted graph
  tools_context = rag.retrieve("Send a plague and make survivors flee")
  # inject tools_context into world agent system prompt
"""

import json
import os
import hashlib
import pickle
import time
import numpy as np
import networkx as nx
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional

# =============================================================================
# EMBEDDING — lightweight, CPU-friendly
# Using sentence-transformers bge-small-en-v1.5 (33M params, ~2ms per query)
# Falls back to a simple TF-IDF bag-of-words if transformers not available
# so the graph is testable without GPU dependencies
# =============================================================================

EMBED_MODEL_ID = os.getenv("EDEN_LIGHTRAG_EMBED_MODEL", "BAAI/bge-small-en-v1.5")
EMBED_DIM      = 384   # bge-small output dimension

_embedder = None

def _get_embedder():
    global _embedder
    if _embedder is None and os.getenv("EDEN_EMBEDDINGS", "lexical") == "lexical":
        _embedder = _TFIDFFallback()
    if _embedder is None:
        try:
            from sentence_transformers import SentenceTransformer
            _embedder = SentenceTransformer(EMBED_MODEL_ID)
            print(f"[EdenLightRAG] Loaded embedder: {EMBED_MODEL_ID}")
        except ImportError:
            print("[EdenLightRAG] sentence-transformers not available — using TF-IDF fallback")
            _embedder = _TFIDFFallback()
    return _embedder


class _TFIDFFallback:
    """
    Minimal bag-of-words fallback when sentence-transformers is unavailable.
    Produces 384-dim vectors from word overlap. Sufficient for testing.
    """
    def __init__(self):
        self._vocab: dict[str, int] = {}

    def encode(self, texts: list[str] | str, **kwargs) -> np.ndarray:
        if isinstance(texts, str):
            texts = [texts]
        results = []
        for text in texts:
            vec = np.zeros(EMBED_DIM, dtype=np.float32)
            words = text.lower().split()
            for word in words:
                bucket = int.from_bytes(hashlib.blake2s(word.encode(), digest_size=4).digest(), "little") % EMBED_DIM
                vec[bucket] += 1.0
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec /= norm
            results.append(vec)
        return np.array(results, dtype=np.float32)


def embed(texts: list[str] | str) -> np.ndarray:
    """Embed one or more strings. Returns float32 array shape (N, EMBED_DIM)."""
    if isinstance(texts, str):
        texts = [texts]
    return _get_embedder().encode(texts, normalize_embeddings=True)


# =============================================================================
# NODE SCHEMA
# =============================================================================

@dataclass
class ToolNode:
    id:               str
    type:             str = "tool"
    tier:             str = "A"          # A / B / C
    label:            str = ""           # display name
    description:      str = ""           # natural language, used for embedding
    handles_events:   list[str] = field(default_factory=list)
    signature:        str = ""           # e.g. "tool_plague(mask)"
    embedding:        Optional[list[float]] = None

@dataclass
class TensorColNode:
    id:               str
    type:             str = "tensor_col"
    tensor:           str = ""           # "h_tensor" | "m_tensor"
    col:              int = 0
    name:             str = ""
    description:      str = ""
    embedding:        Optional[list[float]] = None

@dataclass
class MapEntityNode:
    id:               str
    type:             str = "map_entity"
    type_id:          int = 0
    label:            str = ""
    description:      str = ""
    special_cols:     dict = field(default_factory=dict)  # {col_int: "name"}
    sprite_exists:    bool = False
    sprite_id:        Optional[int] = None
    sprite_desc:      Optional[str] = None
    style_family:     Optional[str] = None
    embedding:        Optional[list[float]] = None

@dataclass
class ConceptNode:
    id:               str
    type:             str = "concept"
    label:            str = ""
    description:      str = ""           # synonyms / related terms
    embedding:        Optional[list[float]] = None

@dataclass
class AssetNode:
    id:               str
    type:             str = "asset"
    sprite_id:        int = 0
    label:            str = ""
    description:      str = ""
    style_family:     str = ""
    embedding:        Optional[list[float]] = None


# =============================================================================
# EDGE TYPES
# Used as the 'relation' attribute on NetworkX edges.
# =============================================================================
EDGE_TYPES = {
    "composes",          # tool → tool: tool_plague composes tool_epidemic
    "modifies_col",      # tool → tensor_col: set_attr modifies HUNGER col14
    "reads_col",         # tool → tensor_col: instinct_flee reads THREAT col15
    "targets",           # tool → map_entity: tool_drought targets M_LAKE
    "handles_event",     # tool → concept: tool_plague handles_event plague
    "triggers",          # tool → tool: escalation triggers propose_new_instinct
    "sets_bit",          # instinct → tensor_col: instinct_fish sets_bit col19
    "blocks",            # instinct → tool: instinct_immunity blocks tool_epidemic
    "requires",          # tool → tool: tool_reproduce requires instinct_search
    "has_sprite",        # map_entity → asset: M_VOLCANO has_sprite sprite_23
    "style_family",      # asset/entity → concept: M_VOLCANO style_family volcanic
    "related_concept",   # concept → concept: plague related_concept disease
}


# =============================================================================
# FAISS INDEX WRAPPER
# Thin wrapper so we can swap to a different ANN library later if needed.
# =============================================================================

class FaissIndex:
    def __init__(self, dim: int = EMBED_DIM):
        try:
            import faiss
            self._faiss = faiss
            self._index = faiss.IndexFlatIP(dim)   # inner product = cosine on normalized vecs
            self._use_faiss = True
        except ImportError:
            print("[EdenLightRAG] FAISS not available — using numpy brute-force search")
            self._use_faiss = False
            self._vectors: list[np.ndarray] = []

        self._id_map: list[str] = []   # position → node_id
        self.dim = dim

    def add(self, node_id: str, vector: np.ndarray) -> None:
        vec = vector.astype(np.float32).reshape(1, -1)
        if self._use_faiss:
            self._index.add(vec)
        else:
            self._vectors.append(vec.flatten())
        self._id_map.append(node_id)

    def search(self, query_vector: np.ndarray, top_k: int = 8) -> list[tuple[str, float]]:
        """Returns list of (node_id, score) sorted by descending score."""
        if len(self._id_map) == 0:
            return []
        top_k = min(top_k, len(self._id_map))
        qvec = query_vector.astype(np.float32).reshape(1, -1)

        if self._use_faiss:
            scores, indices = self._index.search(qvec, top_k)
            return [(self._id_map[i], float(scores[0][j]))
                    for j, i in enumerate(indices[0]) if i >= 0]
        else:
            matrix = np.stack(self._vectors)
            sims = (matrix @ qvec.T).flatten()
            top_idx = np.argsort(sims)[::-1][:top_k]
            return [(self._id_map[i], float(sims[i])) for i in top_idx]

    def __len__(self) -> int:
        return len(self._id_map)


# =============================================================================
# MAIN CLASS
# =============================================================================

class EdenLightRAG:
    """
    Two-layer RAG for Eden's tool registry.

    graph  : NetworkX DiGraph — structural relationships
    index  : FaissIndex       — semantic similarity
    nodes  : dict[id → dataclass] — full node data
    """

    # Tier A tools always injected regardless of retrieval score
    ALWAYS_INCLUDE = {
        "instinct_born", "instinct_die", "instinct_move", "instinct_flee",
        "set_attr", "geo_mutate",
        "propose_new_tool", "propose_new_instinct",
    }

    # Max tools to inject into world agent prompt (context budget)
    DEFAULT_MAX_RETRIEVED = 20

    def __init__(self, max_retrieved: int | None = None):
        self.graph  = nx.DiGraph()
        self.index  = FaissIndex()
        self.nodes: dict[str, object] = {}
        self.max_retrieved = max_retrieved or self.DEFAULT_MAX_RETRIEVED

    # -------------------------------------------------------------------------
    # NODE ADDITION
    # -------------------------------------------------------------------------

    def add_node(self, node: object, edges: list[dict] = None) -> None:
        """
        Add any node dataclass to the graph and vector index.
        edges format: [{"relation": "composes", "target": "tool_epidemic"}, ...]

        Called by handyman agent after executing world agent packet.
        Pure Python, no reasoning needed.
        """
        node_id = node.id

        # Compute embedding from description field
        desc = getattr(node, "description", "") or getattr(node, "label", node_id)
        embedding = embed(desc)[0]
        node.embedding = embedding.tolist()

        # Add to graph
        self.graph.add_node(node_id, **asdict(node))
        self.nodes[node_id] = node

        # Add to FAISS index
        self.index.add(node_id, embedding)

        # Add edges
        if edges:
            for edge in edges:
                relation = edge.get("relation", "related")
                target   = edge.get("target")
                if target and target in self.graph:
                    self.graph.add_edge(node_id, target, relation=relation)
                elif target:
                    # Target not yet in graph — store as pending
                    # Will be resolved on next add_node call for that target
                    self.graph.add_node(target)   # placeholder
                    self.graph.add_edge(node_id, target, relation=relation)

        print(f"[EdenLightRAG] Added node: {node_id} ({node.type})")

    def _embed_node(self, node: object) -> np.ndarray:
        desc = getattr(node, "description", "") or getattr(node, "label", node.id)
        embedding = embed(desc)[0]
        node.embedding = embedding.tolist()
        return embedding

    def _rebuild_index(self) -> None:
        self.index = FaissIndex()
        for node_id, node in self.nodes.items():
            if getattr(node, "embedding", None) is None:
                self._embed_node(node)
            self.index.add(node_id, np.array(node.embedding, dtype=np.float32))

    def upsert_tool(
        self,
        *,
        name: str,
        tier: str,
        signature: str,
        description: str,
        handles_events: list[str] | None = None,
        edges: list[dict] | None = None,
    ) -> None:
        """
        Add or update a tool node and rebuild the vector index.
        This is intended for newly generated tools/instincts after they pass validation.
        """
        node = ToolNode(
            id=name,
            tier=tier,
            label=name,
            signature=signature,
            description=description,
            handles_events=handles_events or [],
        )
        self._embed_node(node)
        self.graph.add_node(name, **asdict(node))
        self.nodes[name] = node

        if edges:
            for edge in edges:
                relation = edge.get("relation", "related")
                target = edge.get("target")
                if not target:
                    continue
                if target not in self.graph:
                    self.graph.add_node(target)
                self.graph.add_edge(name, target, relation=relation)

        self._rebuild_index()
        print(f"[EdenLightRAG] Upserted tool: {name} ({tier})")

    # -------------------------------------------------------------------------
    # RETRIEVAL — two-layer pipeline
    # -------------------------------------------------------------------------

    def _retrieve_tool_ids(
        self,
        god_command: str,
        sub_queries: list[str] = None,
        top_k_per_query: int = 5,
        traversal_depth: int = 2,
    ) -> list[str]:
        """
        Core retrieval entry point. Returns prioritized tool ids.

        Args:
            god_command:    original player input
            sub_queries:    pre-decomposed queries from handyman decomposer LoRA
                            if None, uses god_command as single query
            top_k_per_query: FAISS hits per sub-query before graph expansion
            traversal_depth: how many hops to traverse from each FAISS hit
        """
        t0 = time.perf_counter()

        # Layer 1: semantic search
        queries = sub_queries if sub_queries else [god_command]
        candidate_ids: set[str] = set()
        scored_hits: dict[str, float] = {}

        semantic_top_k = max(top_k_per_query, min(self.max_retrieved, 10))
        for query in queries:
            qvec = embed(query)[0]
            hits = self.index.search(qvec, top_k=semantic_top_k)
            for node_id, score in hits:
                scored_hits[node_id] = max(score, scored_hits.get(node_id, float("-inf")))
                if score > 0.25:   # minimum similarity threshold
                    candidate_ids.add(node_id)

        # Layer 2: graph traversal from candidates
        expanded_ids: set[str] = set(candidate_ids)
        for node_id in candidate_ids:
            neighbors = self._traverse(node_id, depth=traversal_depth)
            expanded_ids.update(neighbors)

        # Always include Tier A primitives + propose_*
        expanded_ids.update(self.ALWAYS_INCLUDE & set(self.nodes.keys()))

        # Filter to only actual tool/instinct nodes for prompt injection
        # (tensor_col and concept nodes are used for traversal but not injected)
        tool_ids = {
            nid for nid in expanded_ids
            if nid in self.nodes
            and getattr(self.nodes[nid], "type", "") == "tool"
        }

        if len(tool_ids) < self.max_retrieved:
            fallback_ranked = sorted(
                (
                    (node_id, score)
                    for node_id, score in scored_hits.items()
                    if node_id in self.nodes
                    and getattr(self.nodes[node_id], "type", "") == "tool"
                ),
                key=lambda item: item[1],
                reverse=True,
            )
            for node_id, _ in fallback_ranked:
                tool_ids.add(node_id)
                if len(tool_ids) >= self.max_retrieved:
                    break

        # Cap at MAX_RETRIEVED — prioritize by tier (A first, then B, then C)
        tool_ids = self._prioritize(tool_ids)

        elapsed_ms = (time.perf_counter() - t0) * 1000
        print(f"[EdenLightRAG] Retrieved {len(tool_ids)} tools in {elapsed_ms:.1f}ms")

        return tool_ids

    def retrieve(
        self,
        god_command: str,
        sub_queries: list[str] = None,
        top_k_per_query: int = 5,
        traversal_depth: int = 2,
    ) -> str:
        """
        Return compact prompt-ready tool context for world-model injection.
        """
        tool_ids = self._retrieve_tool_ids(
            god_command,
            sub_queries=sub_queries,
            top_k_per_query=top_k_per_query,
            traversal_depth=traversal_depth,
        )
        return self._format_context(tool_ids)

    def retrieve_nodes(
        self,
        god_command: str,
        sub_queries: list[str] = None,
        top_k_per_query: int = 5,
        traversal_depth: int = 2,
    ) -> list[dict[str, object]]:
        """
        Return structured retrieved tool metadata for debugging or prompt builders.
        """
        tool_ids = self._retrieve_tool_ids(
            god_command,
            sub_queries=sub_queries,
            top_k_per_query=top_k_per_query,
            traversal_depth=traversal_depth,
        )
        rows: list[dict[str, object]] = []
        for tool_id in tool_ids:
            node = self.nodes.get(tool_id)
            if node is None:
                continue
            rows.append(
                {
                    "id": tool_id,
                    "tier": getattr(node, "tier", "B"),
                    "label": getattr(node, "label", tool_id),
                    "signature": getattr(node, "signature", tool_id),
                    "description": getattr(node, "description", ""),
                    "handles_events": list(getattr(node, "handles_events", [])),
                }
            )
        return rows

    def retrieve_bundle(
        self,
        god_command: str,
        sub_queries: list[str] = None,
        top_k_per_query: int = 5,
        traversal_depth: int = 2,
    ) -> dict[str, object]:
        """
        Return both the structured rows and formatted prompt context.
        """
        tool_rows = self.retrieve_nodes(
            god_command,
            sub_queries=sub_queries,
            top_k_per_query=top_k_per_query,
            traversal_depth=traversal_depth,
        )
        return {
            "query": god_command,
            "tool_count": len(tool_rows),
            "tools": tool_rows,
            "context": self._format_context([row["id"] for row in tool_rows]),
        }

    def _traverse(self, start_id: str, depth: int = 2) -> set[str]:
        """BFS traversal from start_id up to given depth. Returns neighbor ids."""
        visited = set()
        frontier = {start_id}
        for _ in range(depth):
            next_frontier = set()
            for node_id in frontier:
                for neighbor in self.graph.successors(node_id):
                    if neighbor not in visited:
                        next_frontier.add(neighbor)
                        visited.add(neighbor)
            frontier = next_frontier
        return visited

    def _prioritize(self, tool_ids: set[str]) -> list[str]:
        """Sort by tier A → B → C, cap at max_retrieved."""
        tier_order = {"A": 0, "B": 1, "C": 2}
        always = [t for t in tool_ids if t in self.ALWAYS_INCLUDE]
        others = [t for t in tool_ids if t not in self.ALWAYS_INCLUDE]
        others.sort(key=lambda t: tier_order.get(
            getattr(self.nodes.get(t), "tier", "B"), 1
        ))
        combined = always + others
        return combined[:self.max_retrieved]

    def _format_context(self, tool_ids: list[str]) -> str:
        """
        Format retrieved tools as compact registry string for prompt injection.
        Groups by tier so world agent sees clear priority ordering.
        """
        tiers: dict[str, list[str]] = {"A": [], "B": [], "C": []}
        for tool_id in tool_ids:
            node = self.nodes.get(tool_id)
            if node is None:
                continue
            tier = getattr(node, "tier", "B")
            sig  = getattr(node, "signature", tool_id)
            desc = getattr(node, "description", "")
            tiers[tier].append(f"  {sig}  # {desc}" if desc else f"  {sig}")

        lines = ["### RETRIEVED TOOLS (use in priority order A → B → C)"]
        for tier, entries in tiers.items():
            if entries:
                label = {
                    "A": "TIER A — core (use first)",
                    "B": "TIER B — extended",
                    "C": "TIER C — propose (last resort, needs why_existing_tools_insufficient)",
                }[tier]
                lines.append(label)
                lines.extend(entries)

        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # SPRITE / ASSET QUERIES
    # Used by world agent when building new_entities field of output packet
    # -------------------------------------------------------------------------

    def get_sprite(self, entity_type_id: int) -> dict:
        """
        Returns sprite metadata for an entity type.
        World agent calls this to decide whether to request diffusion generation.
        """
        for node in self.nodes.values():
            if (getattr(node, "type", "") == "map_entity"
                    and getattr(node, "type_id", -1) == entity_type_id):
                return {
                    "exists":      node.sprite_exists,
                    "sprite_id":   node.sprite_id,
                    "description": node.sprite_desc,
                    "style_family": node.style_family,
                }
        return {"exists": False, "sprite_id": None,
                "description": None, "style_family": None}

    def get_style_reference(self, style_family: str) -> Optional[int]:
        """
        Returns sprite_id of an existing sprite in the given style family.
        Used as style_ref_sprite_id in diffusion prompts.
        """
        for node in self.nodes.values():
            if (getattr(node, "type", "") == "asset"
                    and getattr(node, "style_family", "") == style_family
                    and getattr(node, "sprite_id", None) is not None):
                return node.sprite_id
        return None

    # -------------------------------------------------------------------------
    # PERSISTENCE
    # -------------------------------------------------------------------------

    def save(self, path: str = "eden_graph.pkl") -> None:
        """Atomic save — write to temp file then rename."""
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:
            pickle.dump({
                "graph":       self.graph,
                "nodes":       self.nodes,
                "index_map":   self.index._id_map,
                "index_vecs":  self._collect_vectors(),
            }, f)
        Path(tmp).replace(path)
        print(f"[EdenLightRAG] Saved graph ({len(self.nodes)} nodes) to {path}")

    def load(self, path: str = "eden_graph.pkl") -> None:
        with open(path, "rb") as f:
            data = pickle.load(f)
        self.graph = data["graph"]
        self.nodes = data["nodes"]
        # Rebuild FAISS index from saved vectors
        self.index = FaissIndex()
        for node_id, vec in zip(data["index_map"], data["index_vecs"]):
            self.index.add(node_id, np.array(vec, dtype=np.float32))
        print(f"[EdenLightRAG] Loaded graph ({len(self.nodes)} nodes) from {path}")

    def _collect_vectors(self) -> list[list[float]]:
        return [
            self.nodes[nid].embedding
            for nid in self.index._id_map
            if nid in self.nodes and self.nodes[nid].embedding is not None
        ]

    def stats(self) -> dict:
        type_counts: dict[str, int] = {}
        for node in self.nodes.values():
            t = getattr(node, "type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1
        return {
            "total_nodes": len(self.nodes),
            "total_edges": self.graph.number_of_edges(),
            "index_size":  len(self.index),
            "by_type":     type_counts,
        }


# =============================================================================
# SEED DATA — full registry seeded at startup
# =============================================================================

def build_seed_graph(max_retrieved: int = 20) -> EdenLightRAG:
    """
    Build and return a fully seeded EdenLightRAG instance.
    Call once at simulation startup and persist with rag.save().
    """
    rag = EdenLightRAG(max_retrieved=max_retrieved)

    # ── TENSOR COLUMN NODES ────────────────────────────────────────────────

    h_cols = [
        (0,  "X",                    "h_tensor", "agent position x pixel"),
        (1,  "Y",                    "h_tensor", "agent position y pixel"),
        (2,  "TYPE",                 "h_tensor", "entity type integer"),
        (3,  "HP",                   "h_tensor", "health points"),
        (10, "H_SEX",                "h_tensor", "sex 0=male 1=female"),
        (11, "H_AGE",                "h_tensor", "age in float years"),
        (12, "H_LIFE_EXP",           "h_tensor", "life expectancy float years"),
        (13, "H_COOLDOWN",           "h_tensor", "mating recovery timer"),
        (14, "HUNGER",               "h_tensor", "hunger level float"),
        (15, "THREAT",               "h_tensor", "threat perception float"),
        (16, "MOOD",                 "h_tensor", "mood float"),
        (17, "CRITICAL_HEALTH",      "h_tensor", "critical health flag"),
        (18, "ESCALATION_FLAG",      "h_tensor", "escalation flag for human agent"),
        (19, "ACQUIRED_INSTINCT_MASK","h_tensor","bitmask of acquired instincts"),
    ]
    for col, name, tensor, desc in h_cols:
        node = TensorColNode(
            id=f"col_{tensor}_{col}_{name}",
            tensor=tensor, col=col, name=name, description=desc
        )
        rag.add_node(node)

    m_cols = [
        (0,  "CX",       "m_tensor", "map entity centre x pixel"),
        (1,  "CY",       "m_tensor", "map entity centre y pixel"),
        (2,  "M_TYPE",   "m_tensor", "entity type integer"),
        (3,  "M_HP",     "m_tensor", "entity health 0=destroyed"),
        (4,  "SCALE",    "m_tensor", "render scale"),
        (5,  "SPRITE_ID","m_tensor", "sprite index for rendering"),
        (10, "SPECIAL_COL10", "m_tensor", "special attr col 10 typed by M_TYPE"),
        (11, "SPECIAL_COL11", "m_tensor", "special attr col 11 typed by M_TYPE"),
        (12, "SPECIAL_COL12", "m_tensor", "special attr col 12 typed by M_TYPE"),
    ]
    for col, name, tensor, desc in m_cols:
        node = TensorColNode(
            id=f"col_{tensor}_{col}_{name}",
            tensor=tensor, col=col, name=name, description=desc
        )
        rag.add_node(node)

    # ── CONCEPT NODES (game events / phenomena) ────────────────────────────

    concepts = [
        ("concept_plague",     "plague",      "plague disease epidemic infection sickness contagion"),
        ("concept_famine",     "famine",      "famine starvation food shortage hunger crisis"),
        ("concept_drought",    "drought",     "drought water shortage lake dry depletion"),
        ("concept_flood",      "flood",       "flood rising water sea encroachment"),
        ("concept_wildfire",   "wildfire",    "wildfire fire forest burning spread"),
        ("concept_earthquake", "earthquake",  "earthquake tremor shake ground collapse"),
        ("concept_volcano",    "volcano",     "volcano eruption lava magma explosion"),
        ("concept_storm",      "storm",       "storm tempest weather hp decay"),
        ("concept_fertility",  "fertility",   "fertility reproduction birth mating cooldown"),
        ("concept_death",      "death",       "death die kill mortality"),
        ("concept_movement",   "movement",    "move flee flee repulsion attraction seek"),
        ("concept_mood",       "mood",        "mood emotion happiness sadness grief mourning"),
        ("concept_threat",     "threat",      "threat danger predator fear panic"),
        ("concept_instinct",   "instinct",    "instinct behavior learned skill inherited"),
        ("concept_terrain",    "terrain",     "terrain map entity biome geography"),
        ("style_water",        "water_entities",    "water lake sea river deep shallow"),
        ("style_fire",         "fire_entities",     "fire lava volcano eruption flame"),
        ("style_nature",       "nature_entities",   "forest tree grass beach mountain"),
        ("style_human",        "human_entities",    "human person figure agent"),
        ("style_disaster",     "disaster_entities", "crater meteorite disaster destruction"),
    ]
    for cid, label, desc in concepts:
        rag.add_node(ConceptNode(id=cid, label=label, description=desc))

    # ── MAP ENTITY NODES ───────────────────────────────────────────────────

    map_entities = [
        ("M_LAKE",     1, {"10":"has_water","11":"depth","12":"fish_count"},
         "lake body of water fishing resource",     True,  1, "top-down pixel lake blue water",     "style_water"),
        ("M_FOREST",   2, {"10":"tree_density","11":"is_burning"},
         "forest trees woodland biome",             True,  2, "top-down pixel forest green trees",   "style_nature"),
        ("M_SEA",      3, {"10":"depth","11":"wave_intensity"},
         "sea ocean deep water coastal",            True,  3, "top-down pixel sea dark blue waves",  "style_water"),
        ("M_MOUNTAIN", 4, {"10":"elevation","11":"is_snow_capped"},
         "mountain peak highland rocky terrain",   True,  4, "top-down pixel mountain grey rocky",  "style_nature"),
        ("M_BEACH",    5, {"10":"sand_density"},
         "beach sand coastal shoreline",            True,  5, "top-down pixel beach sandy shore",    "style_nature"),
        ("M_GRASS",    6, {"10":"fertility_level"},
         "grass grassland open plain fertile",      True,  6, "top-down pixel grassland green open","style_nature"),
    ]
    for label, type_id, scols, desc, sp_exists, sp_id, sp_desc, style in map_entities:
        node = MapEntityNode(
            id=label, label=label, type_id=type_id,
            description=desc, special_cols=scols,
            sprite_exists=sp_exists, sprite_id=sp_id,
            sprite_desc=sp_desc, style_family=style
        )
        edges = [{"relation": "style_family", "target": style}]
        rag.add_node(node, edges)

    # ── TIER A TOOL NODES ──────────────────────────────────────────────────

    tier_a = [
        ("instinct_born",    "instinct_born(x, y, type_id)",
         "spawn new agent into free tensor slot increment population count",
         ["birth", "spawn", "new agent", "creation"],
         [("modifies_col","col_h_tensor_0_X"), ("modifies_col","col_h_tensor_1_Y")]),

        ("instinct_die",     "instinct_die(mask)",
         "remove agent from simulation zero tensor row decrement population",
         ["death", "kill", "die", "remove agent", "mortality"],
         [("modifies_col","col_h_tensor_3_HP")]),

        ("instinct_age",     "instinct_age(mask)",
         "increment agent age by one tick advance time aging",
         ["age", "aging", "time", "older"],
         [("modifies_col","col_h_tensor_11_H_AGE")]),

        ("instinct_move",    "instinct_move(mask, attraction_target=None)",
         "brownian walk plus attraction bias toward target movement navigation",
         ["move", "walk", "navigate", "seek", "approach", "wander"],
         [("modifies_col","col_h_tensor_0_X"), ("modifies_col","col_h_tensor_1_Y")]),

        ("instinct_flee",    "instinct_flee(mask, threat_pos)",
         "repulsion vector away from threat position flee escape retreat",
         ["flee", "escape", "run away", "retreat", "repel", "avoid"],
         [("modifies_col","col_h_tensor_0_X"), ("reads_col","col_h_tensor_15_THREAT")]),

        ("instinct_cooldown","instinct_cooldown(mask, col)",
         "decay timer column toward zero cooldown recovery mating timer",
         ["cooldown", "recovery", "timer", "decay", "mating"],
         [("modifies_col","col_h_tensor_13_H_COOLDOWN")]),

        ("instinct_search",  "instinct_search(mask)",
         "compute seek mask mature agents with cooldown zero ready to mate",
         ["search", "seek", "mate", "fertile", "ready"],
         [("reads_col","col_h_tensor_13_H_COOLDOWN"),
          ("reads_col","col_h_tensor_11_H_AGE")]),

        ("tool_reproduce",   "tool_reproduce(mask)",
         "search proximity instinct_born cooldown chain reproduction birth population growth",
         ["reproduce", "birth", "baby", "population growth", "multiply", "fertile"],
         [("requires","instinct_search"), ("requires","instinct_born"),
          ("modifies_col","col_h_tensor_13_H_COOLDOWN")]),

        ("tool_area_attack", "tool_area_attack(center_x, center_y, radius)",
         "proximity kill instinct_die flee in radius area of effect damage",
         ["attack", "kill", "damage", "destroy", "area", "radius", "explosion"],
         [("composes","instinct_die"), ("composes","instinct_flee")]),

        ("tool_epidemic",    "tool_epidemic(mask, decay_rate)",
         "proximity HP decay per tick disease sickness health reduction spread",
         ["epidemic", "disease", "HP decay", "sickness", "health loss", "contagion"],
         [("modifies_col","col_h_tensor_3_HP"), ("handles_event","concept_plague")]),

        ("tool_drought",     "tool_drought(entity_mask)",
         "drain lake has_water col write geo_mutate dry water shortage",
         ["drought", "drain", "dry", "water shortage", "lake empty"],
         [("targets","M_LAKE"), ("handles_event","concept_drought")]),

        ("geo_mutate",       "geo_mutate(mask, new_shape)",
         "atomically update MAP_GEO shape bump geo_version tile_mask recompute",
         ["shape change", "geometry", "expand", "shrink", "terrain mutate"],
         [("modifies_col","col_m_tensor_0_CX")]),

        ("set_attr",         "set_attr(mask, col, value, mode)",
         "write tensor column value for masked agents mode set add multiply or",
         ["set attribute", "modify stat", "update column", "change value"],
         []),
    ]

    for tid, sig, desc, events, edge_defs in tier_a:
        edges = [{"relation": rel, "target": tgt} for rel, tgt in edge_defs]
        edges += [{"relation": "handles_event", "target": f"concept_{e.split()[0]}"}
                  for e in events if f"concept_{e.split()[0]}" in
                  [n.id for n in rag.nodes.values()]]
        node = ToolNode(id=tid, tier="A", label=tid, signature=sig, description=desc,
                        handles_events=events)
        rag.add_node(node, edges)

    # ── TIER B TOOL NODES ──────────────────────────────────────────────────

    tier_b = [
        ("tool_flood",        "tool_flood(direction, distance_px)",
         "raise sea boundary inland flood water encroachment terrain",
         ["flood", "rising water", "sea advance", "inundation"],
         [("targets","M_SEA"), ("handles_event","concept_flood"),
          ("composes","geo_mutate")]),

        ("tool_wildfire",     "tool_wildfire(mask, spread_rate)",
         "spread fire flag across forest tiles per tick burning",
         ["wildfire", "fire", "burning", "forest fire", "spread flame"],
         [("targets","M_FOREST"), ("handles_event","concept_wildfire"),
          ("modifies_col","col_m_tensor_10_SPECIAL_COL10")]),

        ("tool_earthquake",   "tool_earthquake(center_x, center_y, radius, magnitude)",
         "apply random force all agents in radius shake ground tremor",
         ["earthquake", "tremor", "shake", "seismic"],
         [("handles_event","concept_earthquake"), ("composes","instinct_flee")]),

        ("tool_storm",        "tool_storm(x, y, radius, hp_decay)",
         "spawn storm entity area HP decay flee coastal weather",
         ["storm", "tempest", "weather", "rain", "wind"],
         [("handles_event","concept_storm"), ("composes","tool_epidemic")]),

        ("tool_volcanic_eruption","tool_volcanic_eruption(x, y, kill_radius, flee_radius)",
         "spawn lava entity kill core radius flee outer ring volcano",
         ["volcano", "eruption", "lava", "magma", "explosion"],
         [("handles_event","concept_volcano"), ("composes","tool_area_attack"),
          ("composes","instinct_flee")]),

        ("tool_spawn_resource","tool_spawn_resource(x, y, resource_type, quantity)",
         "place food water material resource entity on tile supply",
         ["resource", "food", "spawn supply", "item", "material"],
         [("composes","instinct_born")]),

        ("tool_deplete_resource","tool_deplete_resource(mask, col, amount)",
         "reduce fish_count has_water resource depletion consumption",
         ["deplete", "consume", "reduce resource", "fish count"],
         [("modifies_col","col_m_tensor_10_SPECIAL_COL10")]),

        ("tool_regrow_forest","tool_regrow_forest(mask, expansion_px)",
         "geo_mutate forest outward expand tree density growth",
         ["forest grow", "regrow", "expand forest", "tree spread"],
         [("targets","M_FOREST"), ("composes","geo_mutate")]),

        ("tool_set_mood",     "tool_set_mood(mask, value, mode)",
         "set MOOD column for masked agents emotion happiness sadness",
         ["mood", "emotion", "happiness", "sadness", "morale"],
         [("modifies_col","col_h_tensor_16_MOOD")]),

        ("tool_set_threat",   "tool_set_threat(mask, value, mode)",
         "set THREAT column for masked agents danger fear panic level",
         ["threat", "danger", "fear", "panic", "alert"],
         [("modifies_col","col_h_tensor_15_THREAT")]),

        ("tool_reset_cooldown","tool_reset_cooldown(mask)",
         "zero H_COOLDOWN for masked agents maximum fertility mating burst",
         ["cooldown reset", "fertility", "mating ready", "reproduce now"],
         [("modifies_col","col_h_tensor_13_H_COOLDOWN")]),

        ("tool_age_shift",    "tool_age_shift(mask, years)",
         "add subtract years to H_AGE for masked agents time skip",
         ["age shift", "add years", "grow old", "time skip"],
         [("modifies_col","col_h_tensor_11_H_AGE")]),

        ("tool_life_exp_modify","tool_life_exp_modify(mask, value, mode)",
         "multiply H_LIFE_EXP for masked agents bless curse lifespan",
         ["life expectancy", "lifespan", "longevity", "bless age"],
         [("modifies_col","col_h_tensor_12_H_LIFE_EXP")]),

        ("tool_cull",         "tool_cull(target_population)",
         "kill lowest HP agents until population reaches target reduce",
         ["cull", "reduce population", "kill weakest", "thin herd"],
         [("composes","instinct_die"), ("reads_col","col_h_tensor_3_HP")]),

        ("tool_baby_boom",    "tool_baby_boom(count, biome)",
         "spawn N new agents at random biome tiles population increase",
         ["baby boom", "spawn population", "new humans", "population growth"],
         [("composes","instinct_born")]),

        ("tool_plague",       "tool_plague(mask)",
         "chain epidemic HP decay plus threat raise plus mood lower disease",
         ["plague", "disease", "epidemic", "sickness", "contagion outbreak"],
         [("composes","tool_epidemic"), ("composes","tool_set_threat"),
          ("composes","tool_set_mood"), ("handles_event","concept_plague")]),

        ("tool_bless",        "tool_bless(mask)",
         "chain HP restore plus mood raise plus cooldown reset divine blessing",
         ["bless", "heal", "restore HP", "divine", "blessing", "cure"],
         [("composes","tool_reset_cooldown"), ("composes","tool_set_mood"),
          ("modifies_col","col_h_tensor_3_HP")]),

        ("tool_grant_instinct","tool_grant_instinct(mask, instinct_name, heritable)",
         "set bit in ACQUIRED_INSTINCT_MASK grant skill learned behavior inherit",
         ["grant instinct", "teach skill", "learn", "acquire ability", "inherit"],
         [("modifies_col","col_h_tensor_19_ACQUIRED_INSTINCT_MASK"),
          ("sets_bit","col_h_tensor_19_ACQUIRED_INSTINCT_MASK")]),

        ("tool_revoke_instinct","tool_revoke_instinct(mask, instinct_name)",
         "clear bit in ACQUIRED_INSTINCT_MASK remove skill unlearn",
         ["revoke instinct", "remove skill", "unlearn", "forget ability"],
         [("modifies_col","col_h_tensor_19_ACQUIRED_INSTINCT_MASK")]),

        ("tool_inherit_instinct","tool_inherit_instinct(parent_mask, child_mask, instinct_name)",
         "copy instinct bitmask bits from parent to children inheritance hereditary",
         ["inherit", "pass to children", "hereditary", "genetic", "offspring"],
         [("modifies_col","col_h_tensor_19_ACQUIRED_INSTINCT_MASK")]),
    ]

    for tid, sig, desc, events, edge_defs in tier_b:
        edges = [{"relation": rel, "target": tgt} for rel, tgt in edge_defs]
        node = ToolNode(id=tid, tier="B", label=tid, signature=sig,
                        description=desc, handles_events=events)
        rag.add_node(node, edges)

    # ── TIER C TOOL NODES ──────────────────────────────────────────────────

    tier_c = [
        ("propose_new_tool",
         "propose_new_tool(name, description, why_existing_tools_insufficient)",
         "propose request new composite tool from Coder LoRA when Tier A and B insufficient",
         ["propose tool", "new tool", "custom tool", "registry miss", "code generation"],
         [("triggers","concept_instinct")]),

        ("propose_new_instinct",
         "propose_new_instinct(name, description, heritable, mask, why_existing_tools_insufficient)",
         "propose new acquired instinct tick-registered behavior past state memory persistent cross-tick",
         ["propose instinct", "new behavior", "persistent behavior", "memory",
          "cross tick", "heritable", "trauma", "immunity", "rivalry"],
         [("modifies_col","col_h_tensor_19_ACQUIRED_INSTINCT_MASK"),
          ("triggers","concept_instinct")]),
    ]

    for tid, sig, desc, events, edge_defs in tier_c:
        edges = [{"relation": rel, "target": tgt} for rel, tgt in edge_defs]
        node = ToolNode(id=tid, tier="C", label=tid, signature=sig,
                        description=desc, handles_events=events)
        rag.add_node(node, edges)

    print(f"\n[EdenLightRAG] Seed graph built: {rag.stats()}")
    return rag


def build_or_load_default(
    graph_path: str | Path | None = None,
    *,
    force_rebuild: bool = False,
    max_retrieved: int = 20,
) -> EdenLightRAG:
    """
    Load a persisted graph when available, otherwise build and persist one.
    """
    if graph_path is None:
        graph_path = Path(__file__).resolve().with_name("eden_graph.pkl")
    graph_path = Path(graph_path)

    if graph_path.exists() and not force_rebuild:
        rag = EdenLightRAG(max_retrieved=max_retrieved)
        rag.load(str(graph_path))
        rag.max_retrieved = max_retrieved
        return rag

    rag = build_seed_graph(max_retrieved=max_retrieved)
    rag.save(str(graph_path))
    return rag


# =============================================================================
# QUICK TEST
# =============================================================================

if __name__ == "__main__":
    print("Building seed graph...")
    rag = build_seed_graph()
    rag.save("eden_graph.pkl")

    print("\n" + "="*60)
    print("RETRIEVAL TESTS")
    print("="*60)

    test_commands = [
        ("Send a plague near the sea",
         ["plague epidemic disease HP decay", "sea coastal M_SEA"]),

        ("Drain the lake and make humans seek water",
         ["lake drain has_water drought", "human seek water movement"]),

        ("Wildfire in the forest — everyone flees",
         ["forest fire burning wildfire", "flee escape movement humans"]),

        ("Humans who survive plague become immune — pass to children",
         ["plague immunity survivor HP recovery", "inherited instinct children bitmask"]),

        ("Spawn a volcano and kill everyone nearby",
         ["volcano eruption spawn new entity", "kill area attack radius"]),
    ]

    for command, sub_queries in test_commands:
        print(f"\nCommand: '{command}'")
        result = rag.retrieve(command, sub_queries=sub_queries)
        print(result)
        print()
