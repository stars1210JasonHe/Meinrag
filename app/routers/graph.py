"""Graph visualization endpoints."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.config import Settings
from app.dependencies import (
    get_settings, get_vector_store, get_current_user, get_llm,
    get_registry, get_edge_repository,
)
from app.db.repositories import DocumentRepository, EdgeRepository
from app.models.schemas import GraphResponse, GraphNode, GraphEdge, MultiMindmapResponse
from app.services.multi_mindmap import build_multi_mindmap
from app.vectorstore.base import VectorStoreManager
from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/graph", tags=["graph"])

# Hard cap on number of docs that can be visualised at once in the chunk-
# level multi-doc view. 10 docs × ~50 chunks each ≈ 500 nodes, which
# force-graph-2d handles smoothly. Above that the layout starts to crawl.
MULTI_DOC_MAX = 10


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

    # Get cross-doc similar_to edges, aggregated and gated by min_pairs.
    cross_edges = await edge_repo.get_cross_doc_edges(
        relation="similar_to",
        min_pairs=settings.graph_similar_min_pairs,
    )
    edges = [
        GraphEdge(
            source_doc_id=e["source_doc_id"],
            target_doc_id=e["target_doc_id"],
            relation=e["relation"],
            score=e.get("score"),
            supporting_pairs=e.get("supporting_pairs"),
            mean_score=e.get("mean_score"),
        )
        for e in cross_edges
    ]

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
            summary_preview=m.get("summary"),
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


@router.get("/nodes-multi", response_model=GraphResponse)
async def get_chunk_graph_multi(
    doc_ids: str = Query(..., description="Comma-separated document IDs (max 10)"),
    edge_types: str = Query(
        default="similar_to",
        description="Comma-separated edge types to include",
    ),
    include_intra_doc: bool = Query(
        default=False,
        description="Include edges where source and target are in the same doc",
    ),
    settings: Settings = Depends(get_settings),
    registry: DocumentRepository = Depends(get_registry),
    vector_store: VectorStoreManager = Depends(get_vector_store),
    edge_repo: EdgeRepository = Depends(get_edge_repository),
    current_user: str = Depends(get_current_user),
):
    """Multi-doc chunk-level graph: chunks from N docs + edges among them.

    Backs the dashboard multi-select → graph "chunk view" experience. Each
    chunk becomes a graph node tagged with its doc_id; the client maps
    doc_id → colour (typically pulled from the doc's mindmap palette).

    Authorization: docs the current user doesn't own are silently dropped.
    If the user owns none of the requested docs, returns an empty graph
    rather than 403 — the caller can render an empty-state banner.

    Performance: enforces MULTI_DOC_MAX=10 to keep force-graph-2d happy.
    """
    doc_id_list = [d.strip() for d in doc_ids.split(",") if d.strip()]
    if not doc_id_list:
        return GraphResponse(nodes=[], edges=[])
    if len(doc_id_list) > MULTI_DOC_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"Too many documents — max {MULTI_DOC_MAX} per request",
        )

    user_filter = current_user if settings.user_isolation != "none" else None
    owned_docs = await registry.get_many_by_ids(doc_id_list, user_id=user_filter)
    allowed_doc_ids = [d["doc_id"] for d in owned_docs]

    if not allowed_doc_ids:
        return GraphResponse(nodes=[], edges=[])

    # Build nodes — chunks from each authorised doc. Each node carries its
    # doc_id so the client can colour and filter without a separate lookup.
    nodes: list[GraphNode] = []
    for doc_id in allowed_doc_ids:
        chunks = vector_store.get_chunks_by_doc(doc_id)
        for chunk in chunks:
            m = chunk.metadata or {}
            nodes.append(GraphNode(
                doc_id=doc_id,
                chunk_index=m.get("chunk_index"),
                chunk_type=m.get("chunk_type"),
                label=m.get("label"),
                page=m.get("page"),
                content_preview=_smart_truncate(chunk.page_content),
                summary_preview=m.get("summary"),
                source_file=m.get("source_file", ""),
                node_type="chunk",
            ))

    # One SQL roundtrip for all edges among the requested doc set.
    types = [t.strip() for t in edge_types.split(",") if t.strip()]
    edge_rows = await edge_repo.get_edges_among_docs(
        doc_ids=allowed_doc_ids,
        relations=types or None,
        include_intra_doc=include_intra_doc,
    )
    edges = [
        GraphEdge(
            source_doc_id=e["source_doc_id"],
            source_chunk_index=e["source_chunk_index"],
            target_doc_id=e["target_doc_id"],
            target_chunk_index=e["target_chunk_index"],
            relation=e["relation"],
            score=e.get("score"),
        )
        for e in edge_rows
    ]

    return GraphResponse(nodes=nodes, edges=edges)


@router.get("/mindmap-multi", response_model=MultiMindmapResponse)
async def get_mindmap_multi(
    doc_ids: str = Query(..., description="Comma-separated document IDs (2-10)"),
    settings: Settings = Depends(get_settings),
    registry: DocumentRepository = Depends(get_registry),
    vector_store: VectorStoreManager = Depends(get_vector_store),
    llm: BaseChatModel = Depends(get_llm),
    current_user: str = Depends(get_current_user),
):
    """Synthesised mindmap across N documents.

    LLM generates one shared concept tree; leaves cite chunks via
    ``chunks_by_doc: {doc_id: [chunk_indices]}`` so the frontend can
    render coverage colour blocks (visualising "do all N docs cover
    this concept?").

    Cache-first: same doc set returns instantly. Single-doc deletion
    invalidates any multi-doc cache that included that doc.

    Authorisation: docs the user doesn't own are silently dropped. A
    single-doc request → 400 ("use /documents/{id}/mindmap for one
    doc"). 0 owned docs → empty tree, no 403.
    """
    doc_id_list = [d.strip() for d in doc_ids.split(",") if d.strip()]
    if not doc_id_list:
        raise HTTPException(status_code=400, detail="doc_ids cannot be empty")
    if len(doc_id_list) > MULTI_DOC_MAX:
        raise HTTPException(
            status_code=400,
            detail=f"Too many documents — max {MULTI_DOC_MAX} per request",
        )

    user_filter = current_user if settings.user_isolation != "none" else None
    owned_docs = await registry.get_many_by_ids(doc_id_list, user_id=user_filter)
    if len(owned_docs) < 2:
        # 1 doc (or zero owned) → not a "multi" view. Steer the caller to
        # the right endpoint instead of silently degrading.
        raise HTTPException(
            status_code=400,
            detail=(
                "Multi-doc mindmap requires at least 2 owned documents. "
                "Use /documents/{doc_id}/mindmap for single-doc."
            ),
        )

    docs_by_id = {d["doc_id"]: d for d in owned_docs}
    allowed_ids = [d["doc_id"] for d in owned_docs]

    return await build_multi_mindmap(
        doc_ids=allowed_ids,
        docs_by_id=docs_by_id,
        vector_store=vector_store,
        llm=llm,
    )


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
                summary_preview=m.get("summary"),
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
                        summary_preview=m.get("summary"),
                        source_file=m.get("source_file", ""),
                    ))
                    break

    return GraphResponse(nodes=nodes, edges=all_edges)
