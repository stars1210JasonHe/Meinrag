"""A5: HTTP Error Handling tests - No API key required.

Uses FastAPI TestClient with mocked dependencies and in-memory SQLite DB.
"""
import io
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from app.config import Settings, LLMProvider, VectorStoreType
from app.db.models import Base, UserModel
from app.dependencies import get_settings, get_vector_store, get_db, get_llm
from app.main import create_app


@pytest.fixture
def mock_settings():
    """Minimal settings that don't need a real API key."""
    return Settings(
        openai_api_key="fake-key-for-testing",
        llm_provider=LLMProvider.OPENAI,
        vector_store=VectorStoreType.CHROMA,
    )


@pytest.fixture
def mock_vector_store():
    """Mock vector store that returns empty results."""
    store = MagicMock()
    store.similarity_search.return_value = []
    store.similarity_search_with_filter.return_value = []
    store.get_all_documents.return_value = []
    return store


@pytest.fixture
def mock_llm():
    """Mock LLM."""
    return MagicMock()


@pytest.fixture
def client(mock_settings, mock_vector_store, mock_llm):
    """FastAPI TestClient with mocked dependencies and in-memory test DB."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )

    @asynccontextmanager
    async def test_lifespan(app):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            session.add(UserModel(user_id="admin", display_name="Admin"))
            await session.commit()
        yield
        await engine.dispose()

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app = create_app()
    app.router.lifespan_context = test_lifespan

    app.dependency_overrides[get_settings] = lambda: mock_settings
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_vector_store] = lambda: mock_vector_store
    app.dependency_overrides[get_llm] = lambda: mock_llm

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    app.dependency_overrides.clear()


class TestHealthEndpoint:
    """A5.5: GET /health."""

    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "llm_provider" in data
        assert "vector_store" in data
        assert "document_count" in data


class TestUploadErrors:
    """A5.1: Upload error handling."""

    def test_unsupported_file_type(self, client):
        """A5.1: .exe file should be rejected with 400."""
        file_content = b"fake executable content"
        resp = client.post(
            "/documents/upload",
            files={"file": ("malware.exe", io.BytesIO(file_content), "application/octet-stream")},
        )
        assert resp.status_code == 400
        assert "Unsupported file type" in resp.json()["detail"]

    def test_unsupported_file_type_jpg(self, client):
        """.jpg file should be rejected."""
        resp = client.post(
            "/documents/upload",
            files={"file": ("photo.jpg", io.BytesIO(b"fake"), "image/jpeg")},
        )
        assert resp.status_code == 400


class TestDeleteErrors:
    """A5.2: Delete error handling."""

    def test_delete_nonexistent(self, client):
        """A5.2: Deleting nonexistent doc returns 404."""
        resp = client.delete("/documents/nonexistent_id_12345")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()


class TestQueryErrors:
    """A5.3 - A5.4: Query validation errors."""

    def test_empty_body(self, client):
        """A5.3: POST /query with no body returns 422."""
        resp = client.post("/query")
        assert resp.status_code == 422

    def test_empty_question(self, client):
        """A5.4: Empty question string returns 422."""
        resp = client.post("/query", json={"question": ""})
        assert resp.status_code == 422

    def test_question_too_long(self, client):
        """Question > 2000 chars returns 422."""
        resp = client.post("/query", json={"question": "x" * 2001})
        assert resp.status_code == 422

    def test_top_k_out_of_range(self, client):
        """top_k=0 returns 422."""
        resp = client.post("/query", json={"question": "test", "top_k": 0})
        assert resp.status_code == 422


class TestDocumentListEmpty:
    """A5.6: List documents when empty."""

    def test_list_empty(self, client):
        """A5.6: GET /documents with no documents returns empty list."""
        resp = client.get("/documents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["documents"] == []
        assert data["total"] == 0
