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
    collections: list[str] = Field(default_factory=list)
    suggested_collections: list[str] | None = None
    user_id: str | None = None
    message: str


class DocumentInfo(BaseModel):
    doc_id: str
    filename: str
    file_type: str
    chunk_count: int
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
    collections: list[str] = Field(..., min_length=1)


class DocumentUpdateResponse(BaseModel):
    doc_id: str
    collections: list[str]
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


class CollectionsResponse(BaseModel):
    taxonomy_categories: list[str]
    existing_collections: list[str]


# --- Graph visualization ---

class GraphNode(BaseModel):
    doc_id: str
    chunk_index: int | None = None
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
