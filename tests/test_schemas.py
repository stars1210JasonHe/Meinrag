"""A2: Schema validation tests - No API key required."""
import pytest
from pydantic import ValidationError

from app.models.schemas import (
    QueryRequest,
    QueryResponse,
    UploadResponse,
    DocumentInfo,
    DocumentListResponse,
    DeleteResponse,
    DocumentUpdateRequest,
    DocumentUpdateResponse,
    SourceChunk,
    HealthResponse,
    UserInfo,
    UserCreateRequest,
    CollectionsResponse,
)


class TestQueryRequest:
    """A2.1 - A2.6: QueryRequest validation."""

    def test_valid_basic(self):
        """A2.1: Valid request with required fields only."""
        req = QueryRequest(question="What is RAG?")
        assert req.question == "What is RAG?"
        assert req.top_k == 4  # default
        assert req.doc_ids is None
        assert req.collection is None
        assert req.session_id is None

    def test_valid_with_all_fields(self):
        """A2.1: Valid request with all optional fields."""
        req = QueryRequest(
            question="What is RAG?",
            top_k=8,
            doc_ids=["doc1", "doc2"],
            collection="law",
            session_id="session123",
        )
        assert req.top_k == 8
        assert req.doc_ids == ["doc1", "doc2"]
        assert req.collection == "law"
        assert req.session_id == "session123"

    def test_empty_question_rejected(self):
        """A2.2: Empty question string should fail."""
        with pytest.raises(ValidationError) as exc_info:
            QueryRequest(question="")
        assert "min_length" in str(exc_info.value).lower() or "at least" in str(exc_info.value).lower()

    def test_question_too_long_rejected(self):
        """A2.3: Question exceeding 2000 chars should fail."""
        with pytest.raises(ValidationError):
            QueryRequest(question="x" * 2001)

    def test_question_at_max_length(self):
        """A2.3: Question at exactly 2000 chars should pass."""
        req = QueryRequest(question="x" * 2000)
        assert len(req.question) == 2000

    def test_top_k_zero_rejected(self):
        """A2.4: top_k=0 should fail (ge=1)."""
        with pytest.raises(ValidationError):
            QueryRequest(question="test", top_k=0)

    def test_top_k_negative_rejected(self):
        """A2.4: Negative top_k should fail."""
        with pytest.raises(ValidationError):
            QueryRequest(question="test", top_k=-1)

    def test_top_k_too_high_rejected(self):
        """A2.5: top_k=21 should fail (le=20)."""
        with pytest.raises(ValidationError):
            QueryRequest(question="test", top_k=21)

    def test_top_k_at_boundaries(self):
        """A2.4/A2.5: top_k at min=1 and max=20 should pass."""
        req_min = QueryRequest(question="test", top_k=1)
        assert req_min.top_k == 1

        req_max = QueryRequest(question="test", top_k=20)
        assert req_max.top_k == 20

    def test_optional_fields_none(self):
        """A2.6: All optional fields default to None."""
        req = QueryRequest(question="test")
        assert req.doc_ids is None
        assert req.collection is None
        assert req.session_id is None

    def test_collection_with_chinese(self):
        """QueryRequest accepts Chinese characters in collection."""
        req = QueryRequest(question="test", collection="法律文件")
        assert req.collection == "法律文件"


class TestUploadResponse:
    """A2.7: UploadResponse fields."""

    def test_all_fields(self):
        resp = UploadResponse(
            doc_id="abc123",
            filename="test.pdf",
            chunk_count=5,
            collections=["legal-compliance", "contracts-agreements"],
            suggested_collections=["legal-compliance", "contracts-agreements"],
            user_id="admin",
            message="Uploaded successfully",
        )
        assert resp.doc_id == "abc123"
        assert resp.filename == "test.pdf"
        assert resp.chunk_count == 5
        assert resp.collections == ["legal-compliance", "contracts-agreements"]
        assert resp.suggested_collections == ["legal-compliance", "contracts-agreements"]
        assert resp.user_id == "admin"
        assert resp.message == "Uploaded successfully"

    def test_optional_fields_default(self):
        resp = UploadResponse(
            doc_id="abc",
            filename="test.pdf",
            chunk_count=3,
            message="OK",
        )
        assert resp.collections == []
        assert resp.suggested_collections is None
        assert resp.user_id is None

    def test_serialization(self):
        resp = UploadResponse(
            doc_id="abc",
            filename="test.pdf",
            chunk_count=3,
            collections=["law"],
            message="OK",
        )
        data = resp.model_dump()
        assert data["doc_id"] == "abc"
        assert data["collections"] == ["law"]


class TestDocumentInfo:
    """A2.8: DocumentInfo with and without collections."""

    def test_with_collections(self):
        doc = DocumentInfo(
            doc_id="abc",
            filename="test.pdf",
            file_type=".pdf",
            chunk_count=5,
            collections=["legal-compliance", "contracts-agreements"],
            user_id="admin",
            uploaded_at="2024-02-10T00:00:00Z",
        )
        assert doc.collections == ["legal-compliance", "contracts-agreements"]
        assert doc.user_id == "admin"

    def test_without_collections(self):
        doc = DocumentInfo(
            doc_id="abc",
            filename="test.pdf",
            file_type=".pdf",
            chunk_count=5,
            uploaded_at="2024-02-10T00:00:00Z",
        )
        assert doc.collections == []
        assert doc.user_id is None

    def test_required_fields_missing(self):
        with pytest.raises(ValidationError):
            DocumentInfo(doc_id="abc")  # missing filename, file_type, etc.


class TestDocumentUpdateRequest:
    """DocumentUpdateRequest validation."""

    def test_valid(self):
        req = DocumentUpdateRequest(collections=["legal-compliance", "contracts-agreements"])
        assert req.collections == ["legal-compliance", "contracts-agreements"]

    def test_empty_collections_rejected(self):
        with pytest.raises(ValidationError):
            DocumentUpdateRequest(collections=[])


class TestDocumentUpdateResponse:
    """DocumentUpdateResponse fields."""

    def test_valid(self):
        resp = DocumentUpdateResponse(
            doc_id="abc",
            collections=["legal-compliance"],
            message="Updated",
        )
        assert resp.doc_id == "abc"
        assert resp.collections == ["legal-compliance"]


class TestQueryResponse:
    """QueryResponse structure."""

    def test_valid_response(self):
        resp = QueryResponse(
            answer="The answer is 42.",
            sources=[
                SourceChunk(content="some text", source_file="doc.pdf", chunk_index=0, doc_id="doc1"),
            ],
            question="What is the answer?",
            session_id="s1",
        )
        assert resp.answer == "The answer is 42."
        assert len(resp.sources) == 1
        assert resp.sources[0].source_file == "doc.pdf"
        assert resp.sources[0].doc_id == "doc1"
        assert resp.session_id == "s1"

    def test_empty_sources(self):
        resp = QueryResponse(
            answer="No context found.",
            sources=[],
            question="test",
        )
        assert resp.sources == []
        assert resp.session_id is None


class TestSourceChunk:
    """SourceChunk structure."""

    def test_with_all_fields(self):
        chunk = SourceChunk(content="hello", source_file="doc.pdf", chunk_index=3, doc_id="doc1")
        assert chunk.chunk_index == 3
        assert chunk.doc_id == "doc1"

    def test_without_optional_fields(self):
        chunk = SourceChunk(content="hello", source_file="doc.pdf")
        assert chunk.chunk_index is None
        assert chunk.doc_id is None


class TestUserSchemas:
    """UserInfo and UserCreateRequest validation."""

    def test_user_info(self):
        user = UserInfo(user_id="admin", display_name="Admin", created_at="2024-01-01T00:00:00Z")
        assert user.user_id == "admin"
        assert user.display_name == "Admin"

    def test_user_create_valid(self):
        req = UserCreateRequest(user_id="test-user", display_name="Test User")
        assert req.user_id == "test-user"

    def test_user_create_empty_id_rejected(self):
        with pytest.raises(ValidationError):
            UserCreateRequest(user_id="", display_name="Test")

    def test_user_create_invalid_chars_rejected(self):
        with pytest.raises(ValidationError):
            UserCreateRequest(user_id="user with spaces", display_name="Test")

    def test_user_create_valid_chars(self):
        req = UserCreateRequest(user_id="user-123_test", display_name="Test User")
        assert req.user_id == "user-123_test"


class TestCollectionsResponse:
    """CollectionsResponse fields."""

    def test_valid(self):
        resp = CollectionsResponse(
            taxonomy_categories=["legal-compliance", "finance-accounting"],
            existing_collections=["law", "medical"],
        )
        assert len(resp.taxonomy_categories) == 2
        assert len(resp.existing_collections) == 2


class TestOtherSchemas:
    """HealthResponse, DeleteResponse, DocumentListResponse."""

    def test_health_response(self):
        resp = HealthResponse(
            llm_provider="openai",
            vector_store="chroma",
            document_count=5,
        )
        assert resp.status == "ok"
        assert resp.document_count == 5

    def test_delete_response(self):
        resp = DeleteResponse(doc_id="abc", message="Deleted")
        assert resp.doc_id == "abc"

    def test_document_list_response(self):
        resp = DocumentListResponse(documents=[], total=0)
        assert resp.total == 0
        assert resp.documents == []
