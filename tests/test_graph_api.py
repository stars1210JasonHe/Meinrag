"""Tests for graph visualization endpoints."""
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from app.config import Settings, LLMProvider, VectorStoreType
from app.db.models import Base, UserModel
from app.dependencies import get_settings, get_vector_store, get_db, get_llm, get_embeddings, get_edge_repository, get_summary_store
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
    app.dependency_overrides[get_summary_store] = lambda: None

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


class TestCrossDocEdgeAggregation:
    """Unit-level tests for EdgeRepository.get_cross_doc_edges aggregation.

    These pin G1 behavior: per-doc-pair grouping, supporting_pairs/mean_score
    fields, and the min_pairs gate that prevents the doc-graph hairball.
    """

    @pytest.mark.asyncio
    async def test_aggregates_supporting_pairs_and_mean_score(self):
        from app.db.models import ChunkEdgeModel
        from app.db.repositories import EdgeRepository

        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with Session() as session:
            # 3 supporting pairs between (A, B); 1 between (A, C); plus a same-doc
            # edge that must be ignored.
            session.add_all([
                ChunkEdgeModel(source_doc_id="A", source_chunk_index=0,
                               target_doc_id="B", target_chunk_index=0,
                               relation="similar_to", score=0.80),
                ChunkEdgeModel(source_doc_id="A", source_chunk_index=1,
                               target_doc_id="B", target_chunk_index=2,
                               relation="similar_to", score=0.90),
                # B->A direction — must group with A->B (unordered pair).
                ChunkEdgeModel(source_doc_id="B", source_chunk_index=4,
                               target_doc_id="A", target_chunk_index=3,
                               relation="similar_to", score=0.70),
                ChunkEdgeModel(source_doc_id="A", source_chunk_index=0,
                               target_doc_id="C", target_chunk_index=0,
                               relation="similar_to", score=0.85),
                # Same-doc edge — must NOT show up in cross-doc results.
                ChunkEdgeModel(source_doc_id="A", source_chunk_index=0,
                               target_doc_id="A", target_chunk_index=1,
                               relation="similar_to", score=0.99),
            ])
            await session.commit()

            repo = EdgeRepository(session)
            edges = await repo.get_cross_doc_edges(min_pairs=1)

            by_pair = {tuple(sorted([e["source_doc_id"], e["target_doc_id"]])): e
                       for e in edges}
            assert ("A", "B") in by_pair
            assert ("A", "C") in by_pair
            ab = by_pair[("A", "B")]
            assert ab["supporting_pairs"] == 3
            assert abs(ab["mean_score"] - 0.80) < 1e-3
            assert ab["score"] == ab["mean_score"]  # backward-compat alias
            ac = by_pair[("A", "C")]
            assert ac["supporting_pairs"] == 1
            assert abs(ac["mean_score"] - 0.85) < 1e-3

        await engine.dispose()

    @pytest.mark.asyncio
    async def test_min_pairs_filter_drops_under_threshold(self):
        from app.db.models import ChunkEdgeModel
        from app.db.repositories import EdgeRepository

        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with Session() as session:
            # (A, B) = 1 pair, (A, C) = 2 pairs, (B, C) = 3 pairs.
            session.add_all([
                ChunkEdgeModel(source_doc_id="A", source_chunk_index=0,
                               target_doc_id="B", target_chunk_index=0,
                               relation="similar_to", score=0.80),
                ChunkEdgeModel(source_doc_id="A", source_chunk_index=0,
                               target_doc_id="C", target_chunk_index=0,
                               relation="similar_to", score=0.80),
                ChunkEdgeModel(source_doc_id="A", source_chunk_index=1,
                               target_doc_id="C", target_chunk_index=2,
                               relation="similar_to", score=0.85),
                ChunkEdgeModel(source_doc_id="B", source_chunk_index=0,
                               target_doc_id="C", target_chunk_index=0,
                               relation="similar_to", score=0.75),
                ChunkEdgeModel(source_doc_id="B", source_chunk_index=1,
                               target_doc_id="C", target_chunk_index=1,
                               relation="similar_to", score=0.85),
                ChunkEdgeModel(source_doc_id="B", source_chunk_index=2,
                               target_doc_id="C", target_chunk_index=2,
                               relation="similar_to", score=0.90),
            ])
            await session.commit()

            repo = EdgeRepository(session)

            # min_pairs=2: drops (A,B); keeps (A,C) and (B,C).
            edges = await repo.get_cross_doc_edges(min_pairs=2)
            pairs = {tuple(sorted([e["source_doc_id"], e["target_doc_id"]]))
                     for e in edges}
            assert pairs == {("A", "C"), ("B", "C")}

            # min_pairs=3: only (B,C) survives.
            edges = await repo.get_cross_doc_edges(min_pairs=3)
            assert len(edges) == 1
            assert {edges[0]["source_doc_id"], edges[0]["target_doc_id"]} == {"B", "C"}

        await engine.dispose()
