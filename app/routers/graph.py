"""Graph visualization endpoints."""
import logging

from fastapi import APIRouter, Depends, Query

from app.config import Settings
from app.dependencies import (
    get_settings, get_vector_store, get_current_user,
    get_registry, get_edge_repository,
)
from app.db.repositories import DocumentRepository, EdgeRepository
from app.models.schemas import GraphResponse, GraphNode, GraphEdge
from app.vectorstore.base import VectorStoreManager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/graph", tags=["graph"])


def _smart_truncate(text: str, max_len: int = 100) -> str:
    """Truncate text for preview."""
    if len(text) <= max_len:
        return text
    idx = text.rfind(" ", 0, max_len)
    if idx > max_len * 0.5:
        return text[:idx] + "..."
    return text[:max_len] + "..."


@router.get("/documents", response_model=GraphResponse)
async def get_document_graph(
    registry: DocumentRepository = Depends(get_registry),
    edge_repo: EdgeRepository = Depends(get_edge_repository),
    current_user: str = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """Get document-level graph: one node per document, cross-doc edges."""
    docs = await registry.list_all(user_id=current_user)

    nodes = []
    for doc in docs:
        nodes.append(GraphNode(
            doc_id=doc["doc_id"],
            chunk_index=None,
            chunk_type=None,
            label=doc["filename"],
            content_preview=f"{doc['chunk_count']} chunks",
            source_file=doc["filename"],
            node_type="document",
        ))

    # Get cross-doc similar_to edges (distinct doc pairs)
    edges = []
    seen_pairs = set()
    for doc in docs:
        doc_edges = await edge_repo.get_edges_from(
            doc["doc_id"], 0, relations=["similar_to"]
        )
        for e in doc_edges:
            if e["target_doc_id"] != doc["doc_id"]:
                pair = tuple(sorted([doc["doc_id"], e["target_doc_id"]]))
                if pair not in seen_pairs:
                    seen_pairs.add(pair)
                    edges.append(GraphEdge(
                        source_doc_id=doc["doc_id"],
                        target_doc_id=e["target_doc_id"],
                        relation="similar_to",
                        score=e.get("score"),
                    ))

    return GraphResponse(nodes=nodes, edges=edges)


@router.get("/nodes", response_model=GraphResponse)
async def get_chunk_graph(
    doc_id: str = Query(..., description="Document ID"),
    edge_types: str = Query(
        default="follows,co_located,describes,references,similar_to",
        description="Comma-separated edge types to include",
    ),
    vector_store: VectorStoreManager = Depends(get_vector_store),
    edge_repo: EdgeRepository = Depends(get_edge_repository),
    current_user: str = Depends(get_current_user),
):
    """Get chunk-level graph for a document: all chunks as nodes, filtered edges."""
    chunks = vector_store.get_chunks_by_doc(doc_id)
    if not chunks:
        return GraphResponse(nodes=[], edges=[])

    nodes = []
    for chunk in chunks:
        m = chunk.metadata
        nodes.append(GraphNode(
            doc_id=doc_id,
            chunk_index=m.get("chunk_index"),
            chunk_type=m.get("chunk_type"),
            label=m.get("label"),
            page=m.get("page"),
            content_preview=_smart_truncate(chunk.page_content),
            source_file=m.get("source_file", ""),
            node_type="chunk",
        ))

    # Get edges for all chunks in this document
    types = [t.strip() for t in edge_types.split(",") if t.strip()]
    edges = []
    for chunk in chunks:
        cidx = chunk.metadata.get("chunk_index")
        if cidx is None:
            continue
        chunk_edges = await edge_repo.get_edges_from(doc_id, cidx, relations=types)
        for e in chunk_edges:
            edges.append(GraphEdge(
                source_doc_id=e["source_doc_id"],
                source_chunk_index=e["source_chunk_index"],
                target_doc_id=e["target_doc_id"],
                target_chunk_index=e["target_chunk_index"],
                relation=e["relation"],
                score=e.get("score"),
            ))

    return GraphResponse(nodes=nodes, edges=edges)


@router.get("/neighbors", response_model=GraphResponse)
async def get_neighbors(
    doc_id: str = Query(...),
    chunk_index: int = Query(...),
    hops: int = Query(default=1, ge=1, le=3),
    vector_store: VectorStoreManager = Depends(get_vector_store),
    edge_repo: EdgeRepository = Depends(get_edge_repository),
):
    """Get neighborhood subgraph for a specific chunk."""
    all_chunks = vector_store.get_chunks_by_doc(doc_id)
    chunk_map = {c.metadata.get("chunk_index"): c for c in all_chunks}

    # BFS to collect neighbors
    visited = set()
    frontier = [(doc_id, chunk_index)]
    visited.add((doc_id, chunk_index))
    all_edges = []

    for _ in range(hops):
        next_frontier = []
        for did, cidx in frontier:
            edges = await edge_repo.get_edges_from(did, cidx)
            for e in edges:
                target_key = (e["target_doc_id"], e["target_chunk_index"])
                all_edges.append(GraphEdge(
                    source_doc_id=e["source_doc_id"],
                    source_chunk_index=e["source_chunk_index"],
                    target_doc_id=e["target_doc_id"],
                    target_chunk_index=e["target_chunk_index"],
                    relation=e["relation"],
                    score=e.get("score"),
                ))
                if target_key not in visited:
                    visited.add(target_key)
                    next_frontier.append(target_key)
            # Also check edges pointing TO this chunk
            edges_to = await edge_repo.get_edges_to(did, cidx)
            for e in edges_to:
                source_key = (e["source_doc_id"], e["source_chunk_index"])
                all_edges.append(GraphEdge(
                    source_doc_id=e["source_doc_id"],
                    source_chunk_index=e["source_chunk_index"],
                    target_doc_id=e["target_doc_id"],
                    target_chunk_index=e["target_chunk_index"],
                    relation=e["relation"],
                    score=e.get("score"),
                ))
                if source_key not in visited:
                    visited.add(source_key)
                    next_frontier.append(source_key)
        frontier = next_frontier

    # Build nodes from visited set
    nodes = []
    for did, cidx in visited:
        if did == doc_id and cidx in chunk_map:
            c = chunk_map[cidx]
            m = c.metadata
            nodes.append(GraphNode(
                doc_id=did,
                chunk_index=cidx,
                chunk_type=m.get("chunk_type"),
                label=m.get("label"),
                page=m.get("page"),
                content_preview=_smart_truncate(c.page_content),
                source_file=m.get("source_file", ""),
            ))
        else:
            # Cross-doc node — try to load
            cross_chunks = vector_store.get_chunks_by_doc(did)
            for c in cross_chunks:
                if c.metadata.get("chunk_index") == cidx:
                    m = c.metadata
                    nodes.append(GraphNode(
                        doc_id=did,
                        chunk_index=cidx,
                        chunk_type=m.get("chunk_type"),
                        label=m.get("label"),
                        page=m.get("page"),
                        content_preview=_smart_truncate(c.page_content),
                        source_file=m.get("source_file", ""),
                    ))
                    break

    return GraphResponse(nodes=nodes, edges=all_edges)
