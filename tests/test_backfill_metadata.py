"""P4c (ops work order 2026-07-10): POST /documents/backfill-metadata.

Bulk classification backfill writing BOTH stores — Postgres via
update_classification, vector store chunk metadata via
update_document_metadata(persist=False) + one persist() at batch end.
"""
import pytest
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from app.config import Settings, LLMProvider, VectorStoreType
from app.db.models import Base, DocumentModel, UserModel
from app.dependencies import (
    get_settings,
    get_vector_store,
    get_db,
    get_llm,
    get_embeddings,
    get_summary_store,
)
from app.main import create_app


@pytest.fixture
def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def mock_vector_store():
    return MagicMock()


@pytest.fixture
def client(session_factory, mock_vector_store):
    settings = Settings(
        openai_api_key="fake-key-for-testing",
        llm_provider=LLMProvider.OPENAI,
        vector_store=VectorStoreType.CHROMA,
    )

    @asynccontextmanager
    async def test_lifespan(app):
        async with session_factory.kw["bind"].begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            session.add(UserModel(user_id="admin", display_name="Admin"))
            session.add(DocumentModel(
                doc_id="doc-a", filename="a.txt", file_type=".txt",
                chunk_count=1, user_id="admin",
            ))
            session.add(DocumentModel(
                doc_id="doc-b", filename="b.txt", file_type=".txt",
                chunk_count=1, user_id="admin",
                primary_category="reference", subtags=["keep-me"],
            ))
            await session.commit()
        yield

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
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_vector_store] = lambda: mock_vector_store
    app.dependency_overrides[get_llm] = lambda: MagicMock()
    app.dependency_overrides[get_embeddings] = lambda: MagicMock()
    app.dependency_overrides[get_summary_store] = lambda: None

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


async def _get_doc(session_factory, doc_id):
    async with session_factory() as session:
        result = await session.execute(
            select(DocumentModel).where(DocumentModel.doc_id == doc_id)
        )
        return result.scalar_one_or_none()


@pytest.mark.anyio
async def test_backfill_updates_both_stores_and_persists_once(
    client, session_factory, mock_vector_store
):
    resp = client.post("/documents/backfill-metadata", json={
        "items": [
            {"doc_id": "doc-a", "primary_category": "legal", "subtags": ["matter-1"]},
            {"doc_id": "doc-b", "primary_category": "legal"},
        ],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["updated"] == 2
    assert body["unknown_doc_ids"] == []
    assert body["dry_run"] is False

    row_a = await _get_doc(session_factory, "doc-a")
    assert row_a.primary_category == "legal"
    assert row_a.subtags == ["matter-1"]
    # omitted subtags on doc-b keeps the existing value (PATCH semantics)
    row_b = await _get_doc(session_factory, "doc-b")
    assert row_b.primary_category == "legal"
    assert row_b.subtags == ["keep-me"]

    # chunk metadata written per doc WITHOUT per-call persist, one persist at the end
    calls = mock_vector_store.update_document_metadata.call_args_list
    assert len(calls) == 2
    for call in calls:
        assert call.kwargs.get("persist") is False
        assert call.args[1] == {"primary_category": "legal"}
    mock_vector_store.persist.assert_called_once()


@pytest.mark.anyio
async def test_backfill_dry_run_writes_nothing(client, session_factory, mock_vector_store):
    resp = client.post("/documents/backfill-metadata", json={
        "items": [{"doc_id": "doc-a", "primary_category": "legal"}],
        "dry_run": True,
    })
    assert resp.status_code == 200
    assert resp.json()["updated"] == 1
    assert resp.json()["dry_run"] is True

    row = await _get_doc(session_factory, "doc-a")
    assert row.primary_category is None
    mock_vector_store.update_document_metadata.assert_not_called()
    mock_vector_store.persist.assert_not_called()


@pytest.mark.anyio
async def test_backfill_reports_unknown_ids_without_aborting(
    client, session_factory, mock_vector_store
):
    resp = client.post("/documents/backfill-metadata", json={
        "items": [
            {"doc_id": "nope-1", "primary_category": "legal"},
            {"doc_id": "doc-a", "primary_category": "legal"},
        ],
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["updated"] == 1
    assert body["unknown_doc_ids"] == ["nope-1"]

    row = await _get_doc(session_factory, "doc-a")
    assert row.primary_category == "legal"


def test_backfill_empty_items_rejected(client):
    resp = client.post("/documents/backfill-metadata", json={"items": []})
    assert resp.status_code == 422
