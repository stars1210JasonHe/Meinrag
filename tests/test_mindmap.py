"""Tests for mindmap endpoint, service, and repository method."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, ChunkEdgeModel
from app.db.repositories import EdgeRepository


async def _make_session() -> AsyncSession:
    """Build an in-memory SQLite session for repository tests."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return factory()


@pytest.mark.asyncio
class TestEdgeRepositoryGetEdgesInDoc:
    async def test_returns_only_intra_doc_edges(self):
        session = await _make_session()
        async with session as s:
            repo = EdgeRepository(s)
            await repo.bulk_insert([
                # Intra-doc: d1 -> d1
                {"source_doc_id": "d1", "source_chunk_index": 0,
                 "target_doc_id": "d1", "target_chunk_index": 1,
                 "relation": "follows", "score": 1.0},
                {"source_doc_id": "d1", "source_chunk_index": 2,
                 "target_doc_id": "d1", "target_chunk_index": 5,
                 "relation": "describes", "score": 0.85},
                # Cross-doc: d1 -> d2 (should NOT be returned)
                {"source_doc_id": "d1", "source_chunk_index": 3,
                 "target_doc_id": "d2", "target_chunk_index": 0,
                 "relation": "similar_to", "score": 0.7},
                # Other doc entirely: d2 -> d2 (should NOT be returned)
                {"source_doc_id": "d2", "source_chunk_index": 0,
                 "target_doc_id": "d2", "target_chunk_index": 1,
                 "relation": "follows", "score": 1.0},
            ])

            rows = await repo.get_edges_in_doc("d1")

        assert len(rows) == 2
        relations = sorted(r["relation"] for r in rows)
        assert relations == ["describes", "follows"]
        # Shape check
        for r in rows:
            assert set(r.keys()) == {
                "source_chunk_index", "target_chunk_index",
                "relation", "score",
            }

    async def test_returns_empty_for_unknown_doc(self):
        session = await _make_session()
        async with session as s:
            repo = EdgeRepository(s)
            rows = await repo.get_edges_in_doc("nonexistent")
        assert rows == []

    async def test_null_score_becomes_1_0(self):
        session = await _make_session()
        async with session as s:
            repo = EdgeRepository(s)
            await repo.bulk_insert([
                {"source_doc_id": "d1", "source_chunk_index": 0,
                 "target_doc_id": "d1", "target_chunk_index": 1,
                 "relation": "follows", "score": None},
            ])
            rows = await repo.get_edges_in_doc("d1")
        assert len(rows) == 1
        assert rows[0]["score"] == 1.0
