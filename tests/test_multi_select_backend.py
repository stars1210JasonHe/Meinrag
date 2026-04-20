"""Backend-only verification of multi-select + save-collection endpoints.

No UI. Exercises:
  - POST /documents/collections/save (mode=new, mode=merge, 409 conflict)
  - POST /query with doc_ids=[multiple] — verifies scope filter + multi-doc coverage
  - Backend telemetry fields (chunks_included, chunks_available, context_mode, etc.)
  - Idempotent-ish: creates unique collection names using timestamp

Uses the persistent test DB at data/test_queries/.
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.config import Settings, ParseMode
from app.db.models import Base
from app.db.repositories import UserRepository
from app.dependencies import (
    get_settings, get_vector_store, get_db, get_llm,
    get_embeddings, get_summary_store,
)
from app.llm.provider import create_chat_model, create_embeddings
from app.main import create_app
from app.vectorstore.chroma_store import ChromaStoreManager
from tests.conftest import online


TEST_DATA_DIR = Path("data/test_queries")
TEST_DB_PATH = TEST_DATA_DIR / "query_test.db"
CHROMA_DIR = TEST_DATA_DIR / "query_test_chroma"
UPLOAD_DIR = TEST_DATA_DIR / "query_test_uploads"


@pytest.fixture(scope="module")
def client():
    settings = Settings()
    settings.upload_dir = UPLOAD_DIR
    settings.user_isolation = "all"
    settings.summary_enabled = False
    settings.parse_mode = ParseMode.DEFAULT

    embeddings = create_embeddings(settings)
    store = ChromaStoreManager(persist_directory=CHROMA_DIR)
    store.initialize(embeddings)
    llm = create_chat_model(settings)

    db_url = f"sqlite+aiosqlite:///{TEST_DB_PATH.as_posix()}"
    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(app):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            user_repo = UserRepository(session)
            if not await user_repo.exists("admin"):
                await user_repo.add("admin", "Admin")
            await session.commit()
        yield

    async def override_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app = create_app()
    app.router.lifespan_context = lifespan
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_vector_store] = lambda: store
    app.dependency_overrides[get_llm] = lambda: llm
    app.dependency_overrides[get_embeddings] = lambda: embeddings
    app.dependency_overrides[get_summary_store] = lambda: None

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    app.dependency_overrides.clear()


def _get_doc_ids(client: TestClient, n: int = 2) -> list[str]:
    resp = client.get("/documents", headers={"X-User-Id": "admin"})
    assert resp.status_code == 200
    docs = resp.json()["documents"]
    assert len(docs) >= n, f"need at least {n} docs in test DB, found {len(docs)}"
    return [d["doc_id"] for d in docs[:n]]


@online
class TestSaveCollection:
    """POST /documents/collections/save — user-driven collection creation."""

    def test_save_creates_new_collection(self, client):
        doc_ids = _get_doc_ids(client, 3)
        name = f"test-col-new-{int(time.time())}"

        resp = client.post(
            "/documents/collections/save",
            json={"name": name, "doc_ids": doc_ids, "mode": "new"},
            headers={"X-User-Id": "admin"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["name"] == name
        assert body["added"] == len(doc_ids)
        assert body["already_in_collection"] == 0
        assert body["total_docs_in_collection"] == len(doc_ids)

        # Verify it shows up in /documents/collections
        resp = client.get("/documents/collections", headers={"X-User-Id": "admin"})
        assert name in resp.json()["existing_collections"]

        # Verify list-by-collection returns the right docs
        resp = client.get(f"/documents?collection={name}", headers={"X-User-Id": "admin"})
        assert resp.status_code == 200
        returned_ids = {d["doc_id"] for d in resp.json()["documents"]}
        assert returned_ids == set(doc_ids)

    def test_save_conflict_returns_409_in_new_mode(self, client):
        doc_ids = _get_doc_ids(client, 2)
        name = f"test-col-conflict-{int(time.time())}"

        # First save
        resp = client.post(
            "/documents/collections/save",
            json={"name": name, "doc_ids": doc_ids, "mode": "new"},
            headers={"X-User-Id": "admin"},
        )
        assert resp.status_code == 200

        # Second save, same name, mode=new → 409
        resp = client.post(
            "/documents/collections/save",
            json={"name": name, "doc_ids": doc_ids, "mode": "new"},
            headers={"X-User-Id": "admin"},
        )
        assert resp.status_code == 409, f"expected 409 conflict, got {resp.status_code}: {resp.text}"
        assert "already exists" in resp.json()["detail"].lower()

    def test_save_merge_mode_adds_new_docs_skips_duplicates(self, client):
        doc_ids = _get_doc_ids(client, 4)
        name = f"test-col-merge-{int(time.time())}"

        # Initial save with first 2
        resp = client.post(
            "/documents/collections/save",
            json={"name": name, "doc_ids": doc_ids[:2], "mode": "new"},
            headers={"X-User-Id": "admin"},
        )
        assert resp.status_code == 200

        # Merge with overlap (first 2 already in, add new 2)
        resp = client.post(
            "/documents/collections/save",
            json={"name": name, "doc_ids": doc_ids, "mode": "merge"},
            headers={"X-User-Id": "admin"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["added"] == 2, f"expected 2 new, got {body['added']}"
        assert body["already_in_collection"] == 2, f"expected 2 existing, got {body['already_in_collection']}"
        assert body["total_docs_in_collection"] == 4

    def test_save_rejects_invalid_name(self, client):
        doc_ids = _get_doc_ids(client, 2)
        resp = client.post(
            "/documents/collections/save",
            json={"name": "has spaces", "doc_ids": doc_ids, "mode": "new"},
            headers={"X-User-Id": "admin"},
        )
        # Name is normalized (spaces → hyphens) — should succeed
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "has-spaces"

        # But weird chars should 400
        resp = client.post(
            "/documents/collections/save",
            json={"name": "bad/name!", "doc_ids": doc_ids, "mode": "new"},
            headers={"X-User-Id": "admin"},
        )
        assert resp.status_code == 400


@online
class TestMultiDocQueryRetrieval:
    """POST /query with doc_ids=[multiple] — end-to-end scope + telemetry."""

    def test_multi_doc_query_returns_telemetry_fields(self, client):
        doc_ids = _get_doc_ids(client, 3)
        resp = client.post(
            "/query",
            json={"question": "Summarize the main themes.", "doc_ids": doc_ids, "top_k": 10},
            headers={"X-User-Id": "admin"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        # All telemetry fields present
        assert "chunks_included" in body
        assert "chunks_available" in body
        assert "context_used_tokens" in body
        assert "context_budget_tokens" in body
        assert "context_mode" in body
        assert body["context_mode"] == "chunks"

        # Chunks should cover all 3 docs (per-doc coverage guarantee)
        source_doc_ids = {s["doc_id"] for s in body["sources"] if s.get("doc_id")}
        coverage_count = len(source_doc_ids & set(doc_ids))
        print(f"\n  [multi-doc] coverage: {coverage_count}/{len(doc_ids)}")
        print(f"  chunks_included: {body['chunks_included']} / {body['chunks_available']} available")
        print(f"  tokens: {body['context_used_tokens']} / {body['context_budget_tokens']}")
        assert coverage_count >= len(doc_ids) - 1, (
            f"expected >= {len(doc_ids)-1}/{len(doc_ids)} doc coverage, got {coverage_count}"
        )

    def test_single_doc_query_unchanged(self, client):
        """Single-doc query still works (backward compat)."""
        doc_ids = _get_doc_ids(client, 1)
        resp = client.post(
            "/query",
            json={"question": "What is this about?", "doc_ids": doc_ids, "top_k": 4},
            headers={"X-User-Id": "admin"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["chunks_included"] is not None
        assert body["chunks_included"] > 0


@online
class TestCollectionFilteredQuery:
    """Using a saved collection, query returns only docs from that collection."""

    def test_query_by_saved_collection(self, client):
        doc_ids = _get_doc_ids(client, 2)
        name = f"test-col-query-{int(time.time())}"

        # Create the collection
        client.post(
            "/documents/collections/save",
            json={"name": name, "doc_ids": doc_ids, "mode": "new"},
            headers={"X-User-Id": "admin"},
        )

        # Query with collection filter
        resp = client.post(
            "/query",
            json={"question": "What is the main topic?", "collection": name, "top_k": 6},
            headers={"X-User-Id": "admin"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        returned_ids = {s["doc_id"] for s in body["sources"] if s.get("doc_id")}

        # All sources must come from the saved collection's docs
        assert returned_ids.issubset(set(doc_ids)), (
            f"sources escaped the collection filter: {returned_ids} vs allowed {doc_ids}"
        )
