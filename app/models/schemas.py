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
    collection: str | None = None
    suggested_collection: str | None = None
    message: str


class DocumentInfo(BaseModel):
    doc_id: str
    filename: str
    file_type: str
    chunk_count: int
    collection: str | None = None
    uploaded_at: str


class DocumentListResponse(BaseModel):
    documents: list[DocumentInfo]
    total: int


class DeleteResponse(BaseModel):
    doc_id: str
    message: str


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=4, ge=1, le=20)
    doc_ids: list[str] | None = Field(default=None, description="Filter by document IDs")
    collection: str | None = Field(default=None, description="Filter by collection name")
    session_id: str | None = Field(default=None, description="Chat session ID for memory")


class SourceChunk(BaseModel):
    content: str
    source_file: str
    chunk_index: int | None = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
    question: str
    session_id: str | None = None
