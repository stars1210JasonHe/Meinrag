"""Tests for graph visualization endpoints."""
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from app.config import Settings, LLMProvider, VectorStoreType
from app.db.models import Base, UserModel
from app.dependencies import get_settings, get_vector_store, get_db, get_llm, get_embeddings, get_edge_repository
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
    store.similarity_search_with_scores.return_value = []
    store.get_all_documents.return_value = []
    store.get_chunks_by_doc.return_value = []
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

    async def mock_get_edges_from(*args, **kwargs):
        return []

    async def mock_get_edges_to(*args, **kwargs):
        return []

    async def mock_get_cross_doc_edges(*args, **kwargs):
        return []

    mock_edge_repo = MagicMock()
    mock_edge_repo.get_edges_from = mock_get_edges_from
    mock_edge_repo.get_edges_to = mock_get_edges_to
    mock_edge_repo.get_cross_doc_edges = mock_get_cross_doc_edges

    app.dependency_overrides[get_settings] = lambda: mock_settings
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_vector_store] = lambda: mock_vector_store
    app.dependency_overrides[get_llm] = lambda: mock_llm
    app.dependency_overrides[get_embeddings] = lambda: MagicMock()
    app.dependency_overrides[get_edge_repository] = lambda: mock_edge_repo

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    app.dependency_overrides.clear()


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
