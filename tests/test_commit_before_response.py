"""P5 (ops work order 2026-07-10): mutating handlers must commit BEFORE responding.

Under FastAPI >=0.106 the get_db finalizer (which holds the only commit) runs
AFTER the response is sent, so a client's immediate read-after-write races the
commit — observed in production as "12 DELETEs return 200, COUNT still shows 1
row for a few seconds".

These tests make the race deterministic: the get_db override ROLLS BACK in its
finalizer instead of committing. If a handler relies on the finalizer commit,
its write is discarded and the fresh-session assertion fails; with the explicit
in-handler commit the write is durable regardless of the finalizer.
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
    get_edge_repository,
    get_summary_store,
)
from app.main import create_app


DOC_ID = "p5-test-doc"


@pytest.fixture
def session_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def client(session_factory, tmp_path):
    settings = Settings(
        openai_api_key="fake-key-for-testing",
        llm_provider=LLMProvider.OPENAI,
        vector_store=VectorStoreType.CHROMA,
        upload_dir=tmp_path,
    )

    mock_vector_store = MagicMock()
    mock_vector_store.delete_document.return_value = None
    mock_vector_store.update_document_metadata.return_value = None

    @asynccontextmanager
    async def test_lifespan(app):
        async with session_factory.kw["bind"].begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            session.add(UserModel(user_id="admin", display_name="Admin"))
            session.add(
                DocumentModel(
                    doc_id=DOC_ID,
                    filename="p5.txt",
                    file_type=".txt",
                    chunk_count=1,
                    user_id="admin",
                )
            )
            await session.commit()
        yield

    async def override_get_db_no_finalizer_commit():
        # Deliberately NEVER commits on exit — simulates the client reading
        # before the real finalizer commit lands. Handlers must have committed
        # themselves for their writes to survive.
        async with session_factory() as session:
            try:
                yield session
            finally:
                await session.rollback()

    app = create_app()
    app.router.lifespan_context = test_lifespan
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_db] = override_get_db_no_finalizer_commit
    app.dependency_overrides[get_vector_store] = lambda: mock_vector_store
    app.dependency_overrides[get_llm] = lambda: MagicMock()
    app.dependency_overrides[get_embeddings] = lambda: MagicMock()
    app.dependency_overrides[get_edge_repository] = lambda: MagicMock()
    app.dependency_overrides[get_summary_store] = lambda: None

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


async def _fetch_doc(session_factory):
    async with session_factory() as session:
        result = await session.execute(
            select(DocumentModel).where(DocumentModel.doc_id == DOC_ID)
        )
        return result.scalar_one_or_none()


@pytest.mark.anyio
async def test_delete_is_durable_before_response(client, session_factory):
    resp = client.delete(f"/documents/{DOC_ID}")
    assert resp.status_code == 200

    row = await _fetch_doc(session_factory)
    assert row is None, "registry row survived the 200 — delete relied on the post-response finalizer commit"


@pytest.mark.anyio
async def test_patch_is_durable_before_response(client, session_factory):
    resp = client.patch(
        f"/documents/{DOC_ID}",
        json={"primary_category": "reference", "subtags": ["p5"]},
    )
    assert resp.status_code == 200

    row = await _fetch_doc(session_factory)
    assert row is not None
    assert row.primary_category == "reference", (
        "PATCH result invisible to a fresh session — update relied on the post-response finalizer commit"
    )
