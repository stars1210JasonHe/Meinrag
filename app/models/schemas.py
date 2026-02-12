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


class SourceChunk(BaseModel):
    content: str
    source_file: str
    chunk_index: int | None = None
    doc_id: str | None = None


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
    question: str
    session_id: str | None = None


class UserInfo(BaseModel):
    user_id: str
    display_name: str
    created_at: str


class UserCreateRequest(BaseModel):
    user_id: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    display_name: str = Field(..., min_length=1, max_length=100)


class CollectionsResponse(BaseModel):
    taxonomy_categories: list[str]
    existing_collections: list[str]
