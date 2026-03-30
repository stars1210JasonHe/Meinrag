# Backend APIs for Frontend Redesign — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add backend APIs needed by the new frontend: graph visualization endpoints, chunks-by-page endpoint, session source persistence, score normalization, and query_types in responses.

**Architecture:** New `/graph` router for graph visualization data. Modify existing query endpoints to include query_types. Add `sources_json` column to chat_messages for session history. Normalize scores to 0-100% before returning to frontend.

**Tech Stack:** Python, FastAPI, SQLAlchemy, SQLite, FAISS

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `app/routers/graph.py` | Create | Graph visualization endpoints |
| `app/models/schemas.py` | Modify | Add graph response schemas, modify QueryResponse |
| `app/db/models.py` | Modify | Add sources_json to ChatMessageModel |
| `alembic/versions/xxx.py` | Create | Migration for sources_json column |
| `app/db/repositories.py` | Modify | Update add_exchange to store sources |
| `app/routers/query.py` | Modify | Add query_types to response, normalize scores |
| `app/main.py` | Modify | Register graph router |
| `tests/test_graph_api.py` | Create | Tests for graph endpoints |
| `tests/test_api_errors.py` | Modify | Add graph endpoint error tests |

---

## Task 1: Graph Visualization Schemas

**Files:**
- Modify: `app/models/schemas.py`

- [ ] **Step 1: Add graph schemas**

At the end of `app/models/schemas.py`, add:

```python
class GraphNode(BaseModel):
    doc_id: str
    chunk_index: int | None = None  # None for document-level nodes
    chunk_type: str | None = None
    label: str | None = None
    page: int | None = None
    content_preview: str = ""
    source_file: str = ""
    node_type: Literal["document", "chunk"] = "chunk"


class GraphEdge(BaseModel):
    source_doc_id: str
    source_chunk_index: int | None = None
    target_doc_id: str
    target_chunk_index: int | None = None
    relation: str
    score: float | None = None


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class ChunkDetail(BaseModel):
    doc_id: str
    chunk_index: int
    chunk_type: str | None = None
    label: str | None = None
    page: int | None = None
    content: str
    source_file: str = ""
    bbox: list[float] | None = None


class ChunkListResponse(BaseModel):
    chunks: list[ChunkDetail]
    total: int
```

- [ ] **Step 2: Modify QueryResponse to include query_types**

In `app/models/schemas.py`, update `QueryResponse`:

```python
class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
    question: str
    session_id: str | None = None
    web_search_used: bool = False
    query_types: list[str] | None = None
```

- [ ] **Step 3: Commit**

```bash
git add app/models/schemas.py
git commit -m "feat: add graph and chunk schemas, query_types in response"
```

---

## Task 2: Graph Router

**Files:**
- Create: `app/routers/graph.py`
- Modify: `app/main.py`
- Create: `tests/test_graph_api.py`

- [ ] **Step 1: Create graph router**

Create `app/routers/graph.py`:

```python
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
```

- [ ] **Step 2: Register router in main.py**

In `app/main.py`, add:

```python
from app.routers import graph
app.include_router(graph.router)
```

Find where other routers are registered and add it there.

- [ ] **Step 3: Write tests**

Create `tests/test_graph_api.py`:

```python
"""Tests for graph visualization endpoints."""
import pytest


class TestGraphDocuments:
    def test_empty_graph(self, client):
        resp = client.get("/graph/documents", headers={"X-User-Id": "testuser"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["nodes"] == []
        assert data["edges"] == []


class TestGraphNodes:
    def test_missing_doc_id(self, client):
        resp = client.get("/graph/nodes", headers={"X-User-Id": "testuser"})
        assert resp.status_code == 422  # missing required param

    def test_nonexistent_doc(self, client):
        resp = client.get("/graph/nodes?doc_id=nonexistent", headers={"X-User-Id": "testuser"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["nodes"] == []


class TestGraphNeighbors:
    def test_missing_params(self, client):
        resp = client.get("/graph/neighbors", headers={"X-User-Id": "testuser"})
        assert resp.status_code == 422
```

The tests need the same test client fixture from `test_api_errors.py`. Either import it or duplicate the fixture. Check how `test_api_errors.py` creates its client and follow the same pattern for `test_graph_api.py`.

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_graph_api.py -v
```

- [ ] **Step 5: Commit**

```bash
git add app/routers/graph.py app/main.py tests/test_graph_api.py
git commit -m "feat: add graph visualization API endpoints"
```

---

## Task 3: Chunks-by-Page Endpoint

**Files:**
- Modify: `app/routers/documents.py`

- [ ] **Step 1: Add endpoint**

In `app/routers/documents.py`, add:

```python
from app.models.schemas import ChunkDetail, ChunkListResponse


@router.get("/documents/{doc_id}/chunks", response_model=ChunkListResponse)
async def get_document_chunks(
    doc_id: str,
    page: int | None = None,
    vector_store: VectorStoreManager = Depends(get_vector_store),
    current_user: str = Depends(get_current_user),
):
    """Get chunks for a document, optionally filtered by page."""
    chunks = vector_store.get_chunks_by_doc(doc_id)

    result = []
    for chunk in chunks:
        m = chunk.metadata
        if page is not None and m.get("page") != page:
            continue

        bbox_raw = m.get("bbox")
        bbox = None
        if bbox_raw:
            import json
            try:
                bbox = json.loads(bbox_raw) if isinstance(bbox_raw, str) else bbox_raw
            except (json.JSONDecodeError, ValueError):
                pass

        result.append(ChunkDetail(
            doc_id=doc_id,
            chunk_index=m.get("chunk_index", 0),
            chunk_type=m.get("chunk_type"),
            label=m.get("label"),
            page=m.get("page"),
            content=chunk.page_content,
            source_file=m.get("source_file", ""),
            bbox=bbox,
        ))

    return ChunkListResponse(chunks=result, total=len(result))
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest tests/test_api_errors.py -v
```

- [ ] **Step 3: Commit**

```bash
git add app/routers/documents.py
git commit -m "feat: add chunks-by-page endpoint for PDF viewer"
```

---

## Task 4: Score Normalization

**Files:**
- Modify: `app/routers/query.py`

- [ ] **Step 1: Add normalization function**

In `app/routers/query.py`, add after `_apply_composite_scoring`:

```python
def _normalize_scores(retrieved: list[tuple]) -> list[tuple]:
    """Normalize scores to 0-100 range for frontend display."""
    if not retrieved:
        return retrieved
    max_score = max(score for _, score in retrieved)
    if max_score <= 0:
        return retrieved
    return [(doc, round(score / max_score * 100, 1)) for doc, score in retrieved]
```

- [ ] **Step 2: Wire into both endpoints**

In both `query_documents()` and `query_documents_stream()`, add after the final `retrieved.sort(...)` and before `_build_source_chunks`:

```python
        # Normalize scores to 0-100%
        retrieved = _normalize_scores(retrieved)
```

Note: label chunks with score=1.0 should be normalized too. The normalization runs AFTER label prepending, so label chunks (1.0) will be 100%.

- [ ] **Step 3: Add query_types to response**

In `query_documents()`, modify the return statement to include query_types:

```python
        return QueryResponse(
            answer=answer,
            sources=_build_source_chunks(retrieved),
            question=request.question,
            session_id=request.session_id,
            query_types=query_types,
        )
```

In `query_documents_stream()`, add a `query_analysis` SSE event before streaming starts:

```python
        # Send query analysis as first event
        yield sse_event("query_analysis", {"types": query_types, "label": query_label})
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest tests/test_chunk_quality.py tests/test_api_errors.py -v
```

- [ ] **Step 5: Commit**

```bash
git add app/routers/query.py
git commit -m "feat: normalize scores to 0-100% and add query_types to response"
```

---

## Task 5: Session Source Persistence

**Files:**
- Modify: `app/db/models.py`
- Create: Alembic migration
- Modify: `app/db/repositories.py`
- Modify: `app/routers/query.py`

- [ ] **Step 1: Add sources_json column**

In `app/db/models.py`, add to `ChatMessageModel`:

```python
    sources_json: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 2: Create migration**

```bash
uv run alembic revision --autogenerate -m "add sources_json to chat_messages"
uv run alembic upgrade head
```

- [ ] **Step 3: Update add_exchange to store sources**

In `app/db/repositories.py`, modify `add_exchange` signature:

```python
    async def add_exchange(
        self, session_id: str, question: str, answer: str,
        user_id: str | None = None, sources_json: str | None = None,
    ) -> None:
```

And when creating the AI message, include sources:

```python
        ai_msg = ChatMessageModel(
            session_id=session_id, role="ai", content=answer,
            sources_json=sources_json,
        )
```

- [ ] **Step 4: Update query endpoints to pass sources**

In both `query_documents()` and `query_documents_stream()`, when calling `add_exchange`, serialize sources:

```python
        if request.session_id:
            import json
            sources_data = [s.model_dump() for s in _build_source_chunks(retrieved)]
            await memory_manager.add_exchange(
                request.session_id, request.question, answer,
                user_id=current_user,
                sources_json=json.dumps(sources_data),
            )
```

- [ ] **Step 5: Update get session messages to return sources**

In `app/db/repositories.py`, modify `get_session_messages` (or wherever messages are returned for the session endpoint) to include `sources_json` in the response.

Check the sessions router to see how messages are returned and add the sources field.

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/ --ignore=tests/test_frontend_e2e.py --ignore=tests/test_api_workflow.py -v -x
```

- [ ] **Step 7: Commit**

```bash
git add app/db/models.py app/db/repositories.py app/routers/query.py alembic/
git commit -m "feat: persist source chunks in session history"
```

---

## Task 6: Full Verification

- [ ] **Step 1: Restart server**

- [ ] **Step 2: Test graph endpoints**

```bash
# Document-level graph
curl -s http://localhost:8000/graph/documents -H "X-User-Id: admin" | python -m json.tool | head -20

# Chunk-level graph for attention paper
curl -s "http://localhost:8000/graph/nodes?doc_id=<DOC_ID>" -H "X-User-Id: admin" | python -m json.tool | head -30

# Neighbors
curl -s "http://localhost:8000/graph/neighbors?doc_id=<DOC_ID>&chunk_index=0&hops=1" -H "X-User-Id: admin" | python -m json.tool | head -20

# Chunks by page
curl -s "http://localhost:8000/documents/<DOC_ID>/chunks?page=5" -H "X-User-Id: admin" | python -m json.tool | head -20
```

- [ ] **Step 3: Test query_types in response**

```bash
curl -s -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" -H "X-User-Id: admin" \
  -d '{"question": "What is attention?", "top_k": 4}' | python -m json.tool | grep query_types
```

Expected: `"query_types": ["fact"]` or similar.

- [ ] **Step 4: Verify scores are normalized 0-100**

Check that source scores in the response are 0-100, not raw 0-1 floats.

- [ ] **Step 5: Commit and push**

```bash
git push origin feature/poppler-figure-extraction
```

---

## Summary

| API | Purpose | Used by |
|-----|---------|---------|
| `GET /graph/documents` | Document-level graph (initial graph view) | Graph page |
| `GET /graph/nodes?doc_id=X` | Chunk-level graph for a document | Graph page (expanded) |
| `GET /graph/neighbors?doc_id=X&chunk_index=N` | Neighborhood subgraph | Graph page (click expand) |
| `GET /documents/{id}/chunks?page=N` | Chunks by page | PDF Viewer sidebar |
| `QueryResponse.query_types` | LLM classification result | Chat page badges |
| `SSE query_analysis event` | Streaming classification | Chat page streaming |
| Score normalization | 0-100% display | Chat source panel |
| `sources_json` in messages | Session history with sources | Chat history |

**No frontend changes in this plan.** This is pure backend — frontend plans follow separately.
