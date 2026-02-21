"""Tests for SSE streaming endpoints and deep health check.

Uses FastAPI TestClient with mocked dependencies and in-memory SQLite DB.
"""
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
    return Settings(
        openai_api_key="fake-key-for-testing",
        llm_provider=LLMProvider.OPENAI,
        vector_store=VectorStoreType.CHROMA,
    )


@pytest.fixture
def mock_vector_store():
    store = MagicMock()
    store.similarity_search.return_value = []
    store.similarity_search_with_filter.return_value = []
    store.similarity_search_with_scores.return_value = []
    store.get_all_documents.return_value = []
    return store


@pytest.fixture
def mock_llm():
    return MagicMock()


@pytest.fixture
def client(mock_settings, mock_vector_store, mock_llm):
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
        # Store mock LLM on app.state for /health/deep
        app.state.llm = mock_llm
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


class TestStreamEndpoints:
    """Tests for SSE streaming endpoints."""

    def test_stream_endpoint_exists(self, client):
        """POST /query/stream returns a response (not 404)."""
        resp = client.post("/query/stream", json={"question": "test"})
        assert resp.status_code != 404

    def test_stream_content_type(self, client):
        """Streaming endpoint returns text/event-stream."""
        resp = client.post("/query/stream", json={"question": "test"})
        assert "text/event-stream" in resp.headers.get("content-type", "")

    def test_stream_validation(self, client):
        """Empty question returns 422 on stream endpoint."""
        resp = client.post("/query/stream", json={"question": ""})
        assert resp.status_code == 422

    def test_ask_ai_stream_exists(self, client):
        """POST /query/ask-ai/stream returns a response (not 404)."""
        resp = client.post("/query/ask-ai/stream", json={"question": "test"})
        assert resp.status_code != 404

    def test_ask_ai_stream_validation(self, client):
        """Empty question returns 422 on ask-ai stream endpoint."""
        resp = client.post("/query/ask-ai/stream", json={"question": ""})
        assert resp.status_code == 422


class TestDeepHealth:
    """Tests for the deep health check endpoint."""

    def test_deep_health_exists(self, client):
        resp = client.get("/health/deep")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "checks" in data

    def test_deep_health_has_checks(self, client):
        resp = client.get("/health/deep")
        data = resp.json()
        assert "database" in data["checks"]
        assert "vector_store" in data["checks"]
