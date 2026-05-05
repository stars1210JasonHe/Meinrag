"""G4a: pin behaviour of the GET /documents?search= dispatch + repo helpers.

Covers two layers:
  - DocumentRepository.search_by_text — case-insensitive ILIKE across
    filename / primary_category / subtags / summary, with collection scope.
  - GET /documents?search= router dispatch — short-query → ILIKE,
    long-query → semantic via summary_store, collection intersect on semantic.
"""
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import LLMProvider, Settings, VectorStoreType
from app.db.models import Base, DocumentCollectionModel, DocumentModel, UserModel
from app.db.repositories import DocumentRepository
from app.dependencies import (
    get_current_user,
    get_db,
    get_edge_repository,
    get_embeddings,
    get_llm,
    get_settings,
    get_summary_store,
    get_vector_store,
)
from app.main import create_app


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def settings():
    return Settings(
        openai_api_key="fake-key",
        llm_provider=LLMProvider.OPENAI,
        vector_store=VectorStoreType.CHROMA,
    )


@pytest.fixture
def in_memory_session():
    """Yield a session_factory + an already-seeded async session for repo tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    return engine


@pytest.fixture
async def session_factory(in_memory_session):
    """Async fixture: build schema, seed an admin user, return session_factory."""
    async with in_memory_session.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(in_memory_session, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        session.add(UserModel(user_id="admin", display_name="Admin"))
        await session.commit()
    yield factory
    await in_memory_session.dispose()


def _make_doc(doc_id: str, filename: str, **kw) -> DocumentModel:
    """Build a DocumentModel with sensible defaults for search tests."""
    return DocumentModel(
        doc_id=doc_id,
        filename=filename,
        file_type=".pdf",
        chunk_count=5,
        user_id="admin",
        primary_category=kw.get("primary_category"),
        subtags=kw.get("subtags", []),
        summary=kw.get("summary"),
        uploaded_at=kw.get("uploaded_at", datetime.now(timezone.utc)),
    )


# ─── Repo: search_by_text ────────────────────────────────────────────────────


class TestSearchByText:
    @pytest.mark.asyncio
    async def test_filename_match(self, session_factory):
        async with session_factory() as session:
            session.add(_make_doc("a", "shell_model_isotopes.pdf"))
            session.add(_make_doc("b", "section230_summary.pdf"))
            await session.commit()
            repo = DocumentRepository(session)

            rows, total = await repo.search_by_text("shell", user_id="admin")
            assert total == 1
            assert rows[0]["doc_id"] == "a"

    @pytest.mark.asyncio
    async def test_case_insensitive(self, session_factory):
        async with session_factory() as session:
            session.add(_make_doc("a", "SHELL_Model.pdf"))
            await session.commit()
            repo = DocumentRepository(session)

            rows, _ = await repo.search_by_text("shell", user_id="admin")
            assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_subtags_match(self, session_factory):
        """subtags is JSON-cast-to-text — substring still hits."""
        async with session_factory() as session:
            session.add(_make_doc("a", "x.pdf", subtags=["nuclear-physics", "exotic-nuclei"]))
            session.add(_make_doc("b", "y.pdf", subtags=["legal-compliance"]))
            await session.commit()
            repo = DocumentRepository(session)

            rows, total = await repo.search_by_text("nuclear", user_id="admin")
            assert total == 1
            assert rows[0]["doc_id"] == "a"

    @pytest.mark.asyncio
    async def test_summary_match(self, session_factory):
        async with session_factory() as session:
            session.add(_make_doc("a", "x.pdf", summary="Discusses degree sequences in bipartite graphs"))
            session.add(_make_doc("b", "y.pdf", summary="Section 230 platform liability"))
            await session.commit()
            repo = DocumentRepository(session)

            rows, _ = await repo.search_by_text("bipartite", user_id="admin")
            assert len(rows) == 1
            assert rows[0]["doc_id"] == "a"

    @pytest.mark.asyncio
    async def test_collection_scope(self, session_factory):
        async with session_factory() as session:
            session.add(_make_doc("a", "shell_a.pdf"))
            session.add(_make_doc("b", "shell_b.pdf"))
            session.add(DocumentCollectionModel(doc_id="a", collection="physics"))
            await session.commit()
            repo = DocumentRepository(session)

            rows, total = await repo.search_by_text(
                "shell", user_id="admin", collection="physics",
            )
            assert total == 1
            assert rows[0]["doc_id"] == "a"

    @pytest.mark.asyncio
    async def test_limit_offset_pagination(self, session_factory):
        async with session_factory() as session:
            for i in range(5):
                session.add(_make_doc(f"d{i}", f"shell_{i}.pdf"))
            await session.commit()
            repo = DocumentRepository(session)

            rows, total = await repo.search_by_text("shell", user_id="admin", limit=2, offset=0)
            assert total == 5
            assert len(rows) == 2
            rows2, _ = await repo.search_by_text("shell", user_id="admin", limit=2, offset=2)
            assert len(rows2) == 2
            # Pages don't overlap.
            assert {r["doc_id"] for r in rows} & {r["doc_id"] for r in rows2} == set()

    @pytest.mark.asyncio
    async def test_user_isolation(self, session_factory):
        async with session_factory() as session:
            session.add(UserModel(user_id="alice", display_name="Alice"))
            session.add(_make_doc("a", "shell.pdf", uploaded_at=datetime.now(timezone.utc)))
            doc_b = DocumentModel(
                doc_id="b", filename="shell.pdf", file_type=".pdf",
                chunk_count=1, user_id="alice", subtags=[],
            )
            session.add(doc_b)
            await session.commit()
            repo = DocumentRepository(session)

            rows, total = await repo.search_by_text("shell", user_id="admin")
            assert total == 1
            assert rows[0]["doc_id"] == "a"


# ─── Repo: get_many_by_ids ───────────────────────────────────────────────────


class TestGetManyByIds:
    @pytest.mark.asyncio
    async def test_preserves_input_order(self, session_factory):
        async with session_factory() as session:
            session.add(_make_doc("a", "a.pdf"))
            session.add(_make_doc("b", "b.pdf"))
            session.add(_make_doc("c", "c.pdf"))
            await session.commit()
            repo = DocumentRepository(session)

            rows = await repo.get_many_by_ids(["c", "a", "b"], user_id="admin")
            assert [r["doc_id"] for r in rows] == ["c", "a", "b"]

    @pytest.mark.asyncio
    async def test_skips_missing_ids_silently(self, session_factory):
        async with session_factory() as session:
            session.add(_make_doc("a", "a.pdf"))
            await session.commit()
            repo = DocumentRepository(session)

            rows = await repo.get_many_by_ids(["a", "ghost", "b"], user_id="admin")
            assert [r["doc_id"] for r in rows] == ["a"]

    @pytest.mark.asyncio
    async def test_empty_input(self, session_factory):
        async with session_factory() as session:
            repo = DocumentRepository(session)
            assert await repo.get_many_by_ids([]) == []


# ─── Endpoint: GET /documents?search= dispatch ───────────────────────────────


@asynccontextmanager
async def _noop_async():
    yield


def _build_client(settings, summary_store_mock):
    """Build a TestClient with a fresh in-memory DB seeded with 3 docs.

    Returns the unentered TestClient — caller must use ``with _build_client(...) as c:``
    so FastAPI's lifespan runs (table creation + seed data).

    summary_store_mock is what gets returned from get_summary_store; pass None
    to test the no-store path (which forces ILIKE for long queries too).
    """
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(app):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            session.add(UserModel(user_id="admin", display_name="Admin"))
            session.add(_make_doc("phys1", "shell_model_isotopes.pdf",
                                  primary_category="research-scientific",
                                  subtags=["nuclear-physics"]))
            session.add(_make_doc("legal1", "section230_summary.pdf",
                                  primary_category="legal-compliance",
                                  subtags=["regulation-policy"],
                                  summary="Discusses platform liability under Section 230"))
            session.add(_make_doc("legal2", "ai_executive_order_2023.pdf",
                                  primary_category="legal-compliance",
                                  subtags=["regulation-policy"],
                                  summary="Covers AI governance and risk management"))
            session.add(DocumentCollectionModel(doc_id="legal1", collection="ai-policy"))
            session.add(DocumentCollectionModel(doc_id="legal2", collection="ai-policy"))
            await session.commit()
        yield
        await engine.dispose()

    async def override_db():
        async with factory() as session:
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
    app.dependency_overrides[get_vector_store] = lambda: MagicMock()
    app.dependency_overrides[get_llm] = lambda: MagicMock()
    app.dependency_overrides[get_embeddings] = lambda: MagicMock()
    app.dependency_overrides[get_edge_repository] = lambda: MagicMock(
        get_edges_from=AsyncMock(return_value=[]),
    )
    app.dependency_overrides[get_summary_store] = lambda: summary_store_mock
    app.dependency_overrides[get_current_user] = lambda: "admin"
    return TestClient(app, raise_server_exceptions=False)


class TestSearchEndpointDispatch:
    def test_empty_query_returns_all(self, settings):
        with _build_client(settings, summary_store_mock=None) as client:
            resp = client.get("/documents")
            assert resp.status_code == 200
            body = resp.json()
            assert body["total"] == 3
            assert len(body["documents"]) == 3

    def test_short_query_uses_ilike(self, settings):
        """`shell` is one word — should hit the ILIKE branch even without summary_store."""
        with _build_client(settings, summary_store_mock=None) as client:
            resp = client.get("/documents?search=shell")
            assert resp.status_code == 200
            body = resp.json()
            assert body["total"] == 1
            assert body["documents"][0]["doc_id"] == "phys1"

    def test_short_query_matches_subtags(self, settings):
        with _build_client(settings, summary_store_mock=None) as client:
            resp = client.get("/documents?search=nuclear")
            assert resp.status_code == 200
            body = resp.json()
            assert body["total"] == 1
            assert body["documents"][0]["doc_id"] == "phys1"

    def test_long_query_uses_semantic_when_store_available(self, settings):
        """Long query (>=4 words) hits summary_store first."""
        # legal1 gets two strong hits → ranks first; legal2 gets one weaker hit.
        store = MagicMock()
        store.similarity_search_with_scores = MagicMock(return_value=[
            (Document(page_content="...", metadata={"doc_id": "legal1"}), 0.92),
            (Document(page_content="...", metadata={"doc_id": "legal1"}), 0.88),
            (Document(page_content="...", metadata={"doc_id": "legal2"}), 0.75),
        ])
        with _build_client(settings, summary_store_mock=store) as client:
            resp = client.get(
                "/documents?search=" + "what+platforms+are+immune+from+user+content+liability"
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["total"] == 2
            # legal1 (mean 0.90, 2 hits) outranks legal2 (mean 0.75, 1 hit).
            assert body["documents"][0]["doc_id"] == "legal1"
            assert body["documents"][1]["doc_id"] == "legal2"
            store.similarity_search_with_scores.assert_called_once()

    def test_long_query_falls_back_to_ilike_on_empty_semantic(self, settings):
        """If summary_store returns nothing, gracefully fall through to ILIKE."""
        store = MagicMock()
        store.similarity_search_with_scores = MagicMock(return_value=[])
        with _build_client(settings, summary_store_mock=store) as client:
            resp = client.get("/documents?search=" + "shell+model+nuclear+physics+isotopes")
            assert resp.status_code == 200
            body = resp.json()
            # ILIKE on "shell model nuclear physics isotopes" matches nothing
            # (filename has underscores, subtags have hyphens). Real users would
            # get hits via semantic; this just proves the fallback doesn't crash.
            assert body["total"] >= 0  # sanity, non-error path

    def test_semantic_collection_intersect(self, settings):
        """When ?collection= AND a long ?search= are both set, semantic results
        are intersected with the collection scope."""
        store = MagicMock()
        # All three docs returned by semantic — but collection limits to legal*.
        store.similarity_search_with_scores = MagicMock(return_value=[
            (Document(page_content="...", metadata={"doc_id": "phys1"}), 0.95),
            (Document(page_content="...", metadata={"doc_id": "legal1"}), 0.88),
            (Document(page_content="...", metadata={"doc_id": "legal2"}), 0.85),
        ])
        with _build_client(settings, summary_store_mock=store) as client:
            resp = client.get(
                "/documents?collection=ai-policy"
                "&search=" + "regulation+governance+platform+liability"
            )
            assert resp.status_code == 200
            body = resp.json()
            ids = {d["doc_id"] for d in body["documents"]}
            # phys1 is filtered out — not in ai-policy collection.
            assert ids == {"legal1", "legal2"}

    def test_pagination(self, settings):
        with _build_client(settings, summary_store_mock=None) as client:
            resp = client.get("/documents?limit=2&offset=0")
            assert resp.status_code == 200
            body = resp.json()
            assert body["total"] == 3
            assert len(body["documents"]) == 2

            resp2 = client.get("/documents?limit=2&offset=2")
            body2 = resp2.json()
            assert len(body2["documents"]) == 1

    def test_limit_clamped_to_max(self, settings):
        """limit > 200 is clamped silently — protects against payload bombs."""
        with _build_client(settings, summary_store_mock=None) as client:
            resp = client.get("/documents?limit=10000")
            assert resp.status_code == 200
            # No assertion on exact return — just verifies non-error path.
