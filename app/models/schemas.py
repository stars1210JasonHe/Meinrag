from typing import Literal

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    llm_provider: str
    vector_store: str
    document_count: int


class UploadResponse(BaseModel):
    doc_id: str
    filename: str
    chunk_count: int
    primary_category: str | None = None
    subtags: list[str] = Field(default_factory=list)
    collections: list[str] = Field(default_factory=list)
    suggested_collections: list[str] | None = None
    user_id: str | None = None
    message: str


class DocumentInfo(BaseModel):
    doc_id: str
    filename: str
    file_type: str
    chunk_count: int
    primary_category: str | None = None
    subtags: list[str] = Field(default_factory=list)
    collections: list[str] = Field(default_factory=list)
    user_id: str | None = None
    uploaded_at: str


class DocumentListResponse(BaseModel):
    documents: list[DocumentInfo]
    total: int


class DeleteResponse(BaseModel):
    doc_id: str
    message: str


class DocumentUpdateRequest(BaseModel):
    """Partial update — any field omitted is left unchanged."""
    primary_category: str | None = Field(default=None, description="One of PRIMARY_CATEGORIES, or '' to clear")
    subtags: list[str] | None = Field(default=None, description="Replace subtags wholesale")
    collections: list[str] | None = Field(default=None, description="Replace user-curated collections wholesale")


class DocumentUpdateResponse(BaseModel):
    doc_id: str
    primary_category: str | None = None
    subtags: list[str] = Field(default_factory=list)
    collections: list[str] = Field(default_factory=list)
    message: str


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=4, ge=1, le=20)
    doc_ids: list[str] | None = Field(default=None, description="Filter by document IDs")
    collection: str | None = Field(default=None, description="Filter by collection name")
    session_id: str | None = Field(default=None, description="Chat session ID for memory")
    force_web_search: bool = Field(default=False, description="Skip docs, go straight to web search")


class SourceChunk(BaseModel):
    content: str
    source_file: str
    chunk_index: int | None = None
    doc_id: str | None = None
    page: int | None = None
    source_type: Literal["document", "web"] = "document"
    score: float | None = None
    url: str | None = None
    chunk_type: Literal["text", "table", "image", "formula"] | None = None
    image_path: str | None = None
    bbox: list[float] | None = None
    label: str | None = None
    headings: str | None = None
    summary: str | None = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
    question: str
    session_id: str | None = None
    web_search_used: bool = False
    query_types: list[str] | None = None
    confidence_tier: str | None = None
    # Context window telemetry (Phase 1-2)
    context_used_tokens: int | None = None
    context_budget_tokens: int | None = None
    context_mode: str | None = None  # "chunks" | "summary" (phase 3, future)
    chunks_included: int | None = None
    chunks_available: int | None = None
    fast_path: bool = False  # true when answered via pre-computed doc summary


class UserInfo(BaseModel):
    user_id: str
    display_name: str
    created_at: str


class UserCreateRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    display_name: str = Field(..., min_length=1, max_length=100)


class SessionInfo(BaseModel):
    session_id: str
    preview: str
    created_at: str
    last_access: str
    scope_type: str | None = None
    scope_value: str | None = None


class AskAIRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = Field(default=None)


class AskAIResponse(BaseModel):
    answer: str
    question: str


class ChunkContextRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    source_type: Literal["document", "web"] = "document"
    doc_id: str | None = None
    chunk_index: int | None = None
    url: str | None = None
    session_id: str | None = None


class TaxonomyResponse(BaseModel):
    """Three-layer taxonomy returned by GET /documents/taxonomy.

    primary_categories: fixed top-level types from data/taxonomy.json
    domain_options: primary -> [domain, ...] (for UI sub-tag suggestions)
    user_collections: free-form, user-curated collection names
    """
    primary_categories: list[str]
    domain_options: dict[str, list[str]]
    user_collections: list[str]


class SaveCollectionRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80, description="Collection name")
    doc_ids: list[str] = Field(..., min_length=1, description="Doc IDs to assign")
    mode: Literal["new", "merge"] = Field(
        default="new",
        description="'new' = refuse with 409 if name exists. 'merge' = add to existing collection.",
    )


class SaveCollectionResponse(BaseModel):
    name: str
    added: int
    already_in_collection: int
    total_docs_in_collection: int


# --- Graph visualization ---

class GraphNode(BaseModel):
    doc_id: str
    chunk_index: int | None = None
    chunk_type: str | None = None
    label: str | None = None
    page: int | None = None
    content_preview: str = ""
    summary_preview: str | None = None  # 1-sentence LLM summary if available
    source_file: str = ""
    node_type: Literal["document", "chunk"] = "chunk"


class GraphEdge(BaseModel):
    source_doc_id: str
    source_chunk_index: int | None = None
    target_doc_id: str
    target_chunk_index: int | None = None
    relation: str
    score: float | None = None
    # Cross-doc edge aggregation (only populated for the doc-level graph view).
    # supporting_pairs: how many distinct chunk pairs sit above the similarity floor.
    # mean_score: arithmetic mean of those pair scores. Frontend uses these for
    # link thickness/opacity so dense, high-confidence relationships read as such.
    supporting_pairs: int | None = None
    mean_score: float | None = None


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


class DocGraphNode(BaseModel):
    """One chunk rendered as a node in the per-doc force-graph."""
    id: str                           # "{doc_id}:{chunk_index}"
    chunk_index: int
    chunk_type: str                   # "text" | "table" | "image" | "formula"
    section_type: str | None = None   # e.g. "body" | "references" | "abstract"
    page: int | None = None
    label: str                        # display-truncated (<=63 chars)
    full_summary: str | None = None   # full summary for hover/detail
    content_length: int
    has_image: bool = False
    bbox: list[float] | None = None   # [x1, y1, x2, y2] for PDF highlight


class DocGraphEdge(BaseModel):
    """One edge from chunk_edges connecting two chunks in the same doc."""
    source: str          # "{doc_id}:{chunk_index}"
    target: str
    relation: str        # "follows" | "co_located" | "describes" | "references" | "similar_to"
    score: float


class DocGraphStats(BaseModel):
    """Counts for legend + filter UI without requiring another round-trip."""
    node_count: int
    edge_count: int
    edges_by_type: dict[str, int]
    chunks_by_type: dict[str, int]


class DocGraphResponse(BaseModel):
    """Full response for GET /documents/{doc_id}/graph."""
    doc_id: str
    filename: str
    doc_summary: str | None = None
    nodes: list[DocGraphNode]
    edges: list[DocGraphEdge]
    stats: DocGraphStats


class MindmapLeaf(BaseModel):
    """Leaf node in the hierarchical mind map — a concept backed by chunks."""
    name: str
    chunk_indices: list[int]  # indices of chunks that support this concept


class MindmapBranch(BaseModel):
    """Main branch in the mind map: a top-level theme with sub-concept leaves."""
    name: str
    children: list[MindmapLeaf]


class MindmapTree(BaseModel):
    """The LLM-derived hierarchical structure for one document."""
    central: str              # central theme (1-line)
    branches: list[MindmapBranch]


class MindmapTreeResponse(BaseModel):
    """Full response for GET /documents/{doc_id}/mindmap (tree mode)."""
    doc_id: str
    filename: str
    cached: bool              # True if served from data/mindmaps/ cache
    tree: MindmapTree


class CorpusStatsResponse(BaseModel):
    """Aggregate corpus stats for the chat empty state."""
    chunks: int          # total chunks across all docs visible to this user
    collections: int     # distinct collections with at least one doc
    edges: int           # total chunk_edges rows in the corpus
    documents: int       # doc count (bonus, useful for "0 docs" empty state)

