"""Mindmap data assembly — builds node + edge + stats payload from
existing FAISS chunks and chunk_edges table rows. Zero LLM cost.

Consumed by the per-doc mindmap endpoint in app/routers/documents.py.
Design: see docs/plans/2026-04-22-mindmap-v0.md
"""
from __future__ import annotations

import json
from collections import Counter

from langchain_core.documents import Document

from app.models.schemas import (
    MindmapNode, MindmapEdge, MindmapStats, MindmapResponse,
)


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


def _chunk_to_node(chunk: Document) -> MindmapNode:
    """Convert a FAISS chunk Document to a MindmapNode.

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

    return MindmapNode(
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
) -> tuple[list[MindmapEdge], MindmapStats]:
    """Assemble edge list + stats block from raw edges and chunks."""
    edges = [
        MindmapEdge(
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

    stats = MindmapStats(
        node_count=len(chunks),
        edge_count=len(edges),
        edges_by_type=dict(edges_by_type),
        chunks_by_type=dict(chunks_by_type),
    )
    return edges, stats


async def build_mindmap(
    doc_id: str,
    doc: dict,
    vector_store,
    edge_repo,
) -> MindmapResponse:
    """Assemble the full mindmap payload for one document.

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

    return MindmapResponse(
        doc_id=doc_id,
        filename=doc.get("filename", "unknown"),
        doc_summary=doc.get("summary"),
        nodes=nodes,
        edges=edges,
        stats=stats,
    )
