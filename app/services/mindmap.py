"""Document force-graph assembly — builds node + edge + stats payload
from existing FAISS chunks and chunk_edges table rows. Zero LLM cost.

Each chunk becomes a graph node and each row in the chunk_edges table
becomes an edge. This is the data backing the per-doc force-graph
visualization (not a hierarchical mind map — see the tree-based mindmap
service for that).

Consumed by the per-doc graph endpoint in app/routers/documents.py.
Design: see docs/plans/2026-04-22-mindmap-v0.md
"""
from __future__ import annotations

import json
import re
from collections import Counter

from langchain_core.documents import Document

from app.models.schemas import (
    DocGraphNode, DocGraphEdge, DocGraphStats, DocGraphResponse,
)

import logging
from pathlib import Path

from langchain_core.language_models import BaseChatModel

from app.models.schemas import (
    MindmapNode, MindmapPalette, MindmapTree, MindmapTreeResponse,
)


MINDMAP_MAX_DEPTH = 4  # central=0, branches=1, children=2, grandchildren=3
from app.rag.prompts import MINDMAP_TREE_PROMPT

logger = logging.getLogger(__name__)

# Cache directory — override in tests via monkeypatch
MINDMAPS_CACHE_DIR = Path("data/mindmaps")


def _parse_bbox(raw) -> list[float] | None:
    """Parse bbox which may be a JSON string, a list, or None.

    Matches the contract in app/services/retrieval.py:_parse_bbox.
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return None
    if isinstance(raw, list):
        return raw
    return None


def _chunk_to_node(chunk: Document) -> DocGraphNode:
    """Convert a FAISS chunk Document to a DocGraphNode.

    Label preference: truncated summary -> truncated content -> `Chunk N`.
    """
    meta = chunk.metadata or {}
    doc_id = meta.get("doc_id", "?")
    chunk_index = meta.get("chunk_index", 0)
    summary = meta.get("summary") or ""
    content = chunk.page_content or ""

    if summary:
        label = summary[:60] + ("..." if len(summary) > 60 else "")
    elif content:
        label = content[:60] + ("..." if len(content) > 60 else "")
    else:
        label = f"Chunk {chunk_index}"

    return DocGraphNode(
        id=f"{doc_id}:{chunk_index}",
        chunk_index=chunk_index,
        chunk_type=meta.get("chunk_type") or "text",
        section_type=meta.get("section_type"),
        page=meta.get("page"),
        label=label,
        full_summary=summary or None,
        content_length=len(content),
        has_image=bool(meta.get("image_path")),
        bbox=_parse_bbox(meta.get("bbox")),
    )


def _build_edges_and_stats(
    doc_id: str,
    chunks: list[Document],
    edge_rows: list[dict],
) -> tuple[list[DocGraphEdge], DocGraphStats]:
    """Assemble edge list + stats block from raw edges and chunks."""
    edges = [
        DocGraphEdge(
            source=f"{doc_id}:{row['source_chunk_index']}",
            target=f"{doc_id}:{row['target_chunk_index']}",
            relation=row["relation"],
            score=row["score"],
        )
        for row in edge_rows
    ]

    edges_by_type: Counter = Counter(e.relation for e in edges)
    chunks_by_type: Counter = Counter(
        (c.metadata or {}).get("chunk_type") or "text" for c in chunks
    )

    stats = DocGraphStats(
        node_count=len(chunks),
        edge_count=len(edges),
        edges_by_type=dict(edges_by_type),
        chunks_by_type=dict(chunks_by_type),
    )
    return edges, stats


async def build_doc_graph(
    doc_id: str,
    doc: dict,
    vector_store,
    edge_repo,
) -> DocGraphResponse:
    """Assemble the full doc-graph payload for one document.

    Precondition: caller has verified the user owns this doc.

    Args:
        doc_id: the document id
        doc: the registry dict (has keys: filename, summary, user_id)
        vector_store: VectorStoreManager with get_chunks_by_doc()
        edge_repo: EdgeRepository with get_edges_in_doc()
    """
    chunks = vector_store.get_chunks_by_doc(doc_id)
    edge_rows = await edge_repo.get_edges_in_doc(doc_id)

    nodes = [_chunk_to_node(c) for c in chunks]
    edges, stats = _build_edges_and_stats(doc_id, chunks, edge_rows)

    return DocGraphResponse(
        doc_id=doc_id,
        filename=doc.get("filename", "unknown"),
        doc_summary=doc.get("summary"),
        nodes=nodes,
        edges=edges,
        stats=stats,
    )


def _format_chunks_for_prompt(chunks: list[Document]) -> str:
    """Render chunks as numbered summaries for the mind-map LLM prompt."""
    lines = []
    for chunk in chunks:
        meta = chunk.metadata or {}
        idx = meta.get("chunk_index", "?")
        summary = (meta.get("summary") or chunk.page_content or "").strip()
        if not summary:
            summary = "(no summary)"
        if len(summary) > 200:
            summary = summary[:197] + "..."
        lines.append(f"[{idx}] {summary}")
    return "\n".join(lines)


def _parse_node(node, valid_indices: set[int], depth: int) -> MindmapNode | None:
    """Recursively parse one mind-map node. Returns None if the node is
    malformed (no name, etc.) so the caller can drop it.

    Depth contract: central=0, branches=1, leaves typically at 2 or 3.
    At depth >= MINDMAP_MAX_DEPTH - 1 the node is forced to be a leaf
    (its children are dropped) so a runaway LLM can't produce 5+ levels.
    """
    if not isinstance(node, dict):
        return None
    name = str(node.get("name", "")).strip()
    if not name:
        return None

    raw_children = node.get("children")
    can_recurse = depth < MINDMAP_MAX_DEPTH - 1
    if can_recurse and isinstance(raw_children, list) and raw_children:
        parsed_children = [
            _parse_node(c, valid_indices, depth + 1)
            for c in raw_children
        ]
        parsed_children = [p for p in parsed_children if p is not None]
        if parsed_children:
            return MindmapNode(name=name, chunk_indices=None, children=parsed_children)

    raw_indices = node.get("chunk_indices", []) or []
    validated = [
        i for i in raw_indices
        if isinstance(i, int) and i in valid_indices
    ]
    return MindmapNode(name=name, chunk_indices=validated, children=None)


_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _validate_palette(raw, branch_count: int) -> MindmapPalette | None:
    """Validate the LLM's palette block. Returns None if missing or malformed
    so the renderer can fall back to its default palette. Requires every hex
    value to be a 6-character #rrggbb string and the branches list to match
    the actual branch count (truncate or pad as needed)."""
    if not isinstance(raw, dict):
        return None
    central = raw.get("central")
    if not isinstance(central, str) or not _HEX_RE.match(central):
        return None
    raw_branches = raw.get("branches", [])
    if not isinstance(raw_branches, list):
        raw_branches = []
    branches = [b for b in raw_branches if isinstance(b, str) and _HEX_RE.match(b)]
    # Align branch palette length to actual branch count: if LLM gave fewer,
    # pad by repeating central; if more, truncate.
    if len(branches) < branch_count:
        branches = branches + [central] * (branch_count - len(branches))
    branches = branches[:branch_count]
    return MindmapPalette(central=central, branches=branches)


def _parse_tree_response(text: str, valid_indices: set[int]) -> MindmapTree:
    """Parse LLM output into a MindmapTree. Strips markdown fences,
    validates chunk_indices against the known set, recursively descends
    children (capped at MINDMAP_MAX_DEPTH). Returns an empty tree if
    parsing fails — caller decides whether to cache."""
    import json as _json

    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    try:
        parsed = _json.loads(text)
    except (ValueError, _json.JSONDecodeError) as e:
        logger.warning("Mindmap LLM returned invalid JSON: %s", e)
        return MindmapTree(central="", branches=[])

    central = parsed.get("central", "")
    if not isinstance(central, str):
        return MindmapTree(central="", branches=[])

    branches: list[MindmapNode] = []
    for b in parsed.get("branches", []):
        node = _parse_node(b, valid_indices, depth=1)
        if node is not None:
            branches.append(node)

    palette = _validate_palette(parsed.get("palette"), len(branches))

    return MindmapTree(central=central, branches=branches, palette=palette)


def _load_cached_tree(doc_id: str) -> MindmapTree | None:
    """Return cached tree for this doc, or None if absent/unreadable."""
    import json as _json
    path = MINDMAPS_CACHE_DIR / f"{doc_id}.json"
    if not path.exists():
        return None
    try:
        data = _json.loads(path.read_text(encoding="utf-8"))
        return MindmapTree.model_validate(data)
    except Exception as e:
        logger.warning("Failed to read mindmap cache for %s: %s", doc_id, e)
        return None


def _save_cached_tree(doc_id: str, tree: MindmapTree) -> None:
    """Persist the tree to the cache file."""
    MINDMAPS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = MINDMAPS_CACHE_DIR / f"{doc_id}.json"
    path.write_text(tree.model_dump_json(), encoding="utf-8")


async def build_mindmap_tree(
    doc_id: str,
    doc: dict,
    vector_store,
    llm: BaseChatModel,
) -> MindmapTreeResponse:
    """Return the hierarchical mind map for a doc.

    Cache-first: reads `data/mindmaps/{doc_id}.json` if present; else calls
    the LLM to derive a concept hierarchy from chunk summaries, writes the
    cache, returns the fresh result.

    Fail-safe: empty chunks -> empty tree (no LLM call). LLM failure -> empty
    tree, no cache write (retry on next request).

    Precondition: caller has verified the user owns this doc.
    """
    cached = _load_cached_tree(doc_id)
    if cached is not None:
        return MindmapTreeResponse(
            doc_id=doc_id,
            filename=doc.get("filename", "unknown"),
            cached=True,
            tree=cached,
        )

    chunks = vector_store.get_chunks_by_doc(doc_id)
    if not chunks:
        return MindmapTreeResponse(
            doc_id=doc_id,
            filename=doc.get("filename", "unknown"),
            cached=False,
            tree=MindmapTree(central="", branches=[]),
        )

    valid_indices = {
        (c.metadata or {}).get("chunk_index") for c in chunks
        if (c.metadata or {}).get("chunk_index") is not None
    }

    try:
        messages = MINDMAP_TREE_PROMPT.format_messages(
            filename=doc.get("filename", "unknown"),
            chunks=_format_chunks_for_prompt(chunks),
        )
        response = await llm.ainvoke(messages)
        text = response.content if hasattr(response, "content") else str(response)
        tree = _parse_tree_response(text, valid_indices)
    except Exception as e:
        logger.warning("Mindmap LLM call failed: %s", e)
        tree = MindmapTree(central="", branches=[])

    if tree.branches:
        try:
            _save_cached_tree(doc_id, tree)
        except Exception as e:
            logger.warning("Failed to cache mindmap for %s: %s", doc_id, e)

    return MindmapTreeResponse(
        doc_id=doc_id,
        filename=doc.get("filename", "unknown"),
        cached=False,
        tree=tree,
    )
