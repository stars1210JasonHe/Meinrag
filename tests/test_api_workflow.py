"""B5: Full API Workflow tests - Requires API key.

End-to-end tests using FastAPI TestClient with real LLM/embeddings.
"""
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.db.models import Base, UserModel
from app.dependencies import get_settings, get_vector_store, get_db, get_llm
from app.llm.provider import create_chat_model, create_embeddings
from app.main import create_app
from app.vectorstore.chroma_store import ChromaStoreManager
from tests.conftest import online, TEST_DIR, PDF_AI_SAFETY, PDF_LAW, PDF_PATTERNS


@pytest.fixture(scope="module")
def api_env():
    """Set up real app with real LLM, embeddings, and in-memory test DB."""
    settings = Settings()
    store_dir = TEST_DIR / "b5_api_store"
    store_dir.mkdir(parents=True, exist_ok=True)

    embeddings = create_embeddings(settings)
    store = ChromaStoreManager(persist_directory=store_dir)
    store.initialize(embeddings)
    llm = create_chat_model(settings)

    # Patch paths so test files go to our test dir
    settings.upload_dir = TEST_DIR / "b5_uploads"
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.user_isolation = "all"

    # Test database (in-memory SQLite)
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

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_vector_store] = lambda: store
    app.dependency_overrides[get_llm] = lambda: llm

    with TestClient(app, raise_server_exceptions=False) as client:
        yield {
            "client": client,
            "settings": settings,
            "store": store,
        }

    app.dependency_overrides.clear()
    shutil.rmtree(store_dir, ignore_errors=True)
    shutil.rmtree(settings.upload_dir, ignore_errors=True)


@online
class TestUserWorkflow:
    """User system endpoints."""

    def test_list_users_default(self, api_env):
        """Default admin user exists on startup."""
        client = api_env["client"]
        resp = client.get("/users")
        assert resp.status_code == 200
        users = resp.json()
        assert any(u["user_id"] == "admin" for u in users)

    def test_create_user(self, api_env):
        """Create a new user."""
        client = api_env["client"]
        resp = client.post("/users", json={
            "user_id": "jason",
            "display_name": "Jason",
        })
        assert resp.status_code == 201
        assert resp.json()["user_id"] == "jason"

    def test_create_duplicate_user(self, api_env):
        """Duplicate user_id returns 409."""
        client = api_env["client"]
        resp = client.post("/users", json={
            "user_id": "jason",
            "display_name": "Jason Again",
        })
        assert resp.status_code == 409

    def test_get_current_user(self, api_env):
        """Get current user from X-User-Id header."""
        client = api_env["client"]
        resp = client.get("/users/current", headers={"X-User-Id": "jason"})
        assert resp.status_code == 200
        assert resp.json()["user_id"] == "jason"

    def test_get_current_user_default(self, api_env):
        """Missing X-User-Id falls back to default user."""
        client = api_env["client"]
        resp = client.get("/users/current")
        assert resp.status_code == 200
        assert resp.json()["user_id"] == "admin"


@online
class TestUploadWorkflow:
    """B5.1 - B5.2: Upload documents with multi-collection + user."""

    def test_upload_with_collections(self, api_env):
        """B5.1: Upload PDF to multiple collections."""
        client = api_env["client"]
        with open(PDF_LAW, "rb") as f:
            resp = client.post(
                "/documents/upload?collections=legal-compliance,regulation-policy",
                files={"file": ("basic_law.pdf", f, "application/pdf")},
                headers={"X-User-Id": "admin"},
            )
        assert resp.status_code == 200, f"Upload failed: {resp.text}"
        data = resp.json()
        assert data["doc_id"]
        assert "legal-compliance" in data["collections"]
        assert "regulation-policy" in data["collections"]
        assert data["user_id"] == "admin"
        assert data["chunk_count"] > 0
        api_env["law_doc_id"] = data["doc_id"]

    def test_upload_default_collection(self, api_env):
        """Upload with no collection defaults to ['other']."""
        client = api_env["client"]
        with open(PDF_AI_SAFETY, "rb") as f:
            resp = client.post(
                "/documents/upload",
                files={"file": ("ai_safety.pdf", f, "application/pdf")},
                headers={"X-User-Id": "admin"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["collections"] == ["other"]
        api_env["ai_doc_id"] = data["doc_id"]

    def test_upload_with_auto_suggest(self, api_env):
        """B5.2: Upload with auto_suggest returns suggested collections."""
        client = api_env["client"]
        with open(PDF_PATTERNS, "rb") as f:
            resp = client.post(
                "/documents/upload?auto_suggest=true",
                files={"file": ("patterns_auto.pdf", f, "application/pdf")},
                headers={"X-User-Id": "admin"},
            )
        assert resp.status_code == 200, f"Upload failed: {resp.text}"
        data = resp.json()
        assert data["doc_id"]
        assert data["suggested_collections"] is not None
        assert len(data["suggested_collections"]) > 0
        api_env["ai_suggested_doc_id"] = data["doc_id"]


@online
class TestListWorkflow:
    """B5.3 - B5.4: List documents."""

    def test_list_all_documents(self, api_env):
        """B5.3: Uploaded docs appear in listing."""
        client = api_env["client"]
        resp = client.get("/documents", headers={"X-User-Id": "admin"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2

    def test_list_by_collection(self, api_env):
        """B5.4: Filter by collection returns matching docs (multi-collection)."""
        client = api_env["client"]
        resp = client.get("/documents", params={"collection": "legal-compliance"}, headers={"X-User-Id": "admin"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        for doc in data["documents"]:
            assert "legal-compliance" in doc["collections"]

    def test_list_collections(self, api_env):
        """Collections endpoint returns taxonomy + existing."""
        client = api_env["client"]
        resp = client.get("/documents/collections", headers={"X-User-Id": "admin"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["taxonomy_categories"]) == 11
        assert len(data["existing_collections"]) >= 1


@online
class TestUserIsolation:
    """User isolation tests."""

    def test_user_isolation_upload(self, api_env):
        """Upload as jason -- admin cannot see it."""
        client = api_env["client"]
        with open(PDF_AI_SAFETY, "rb") as f:
            resp = client.post(
                "/documents/upload?collections=research-scientific",
                files={"file": ("jason_doc.pdf", f, "application/pdf")},
                headers={"X-User-Id": "jason"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == "jason"
        api_env["jason_doc_id"] = data["doc_id"]

    def test_admin_cannot_see_jason_docs(self, api_env):
        """Admin listing doesn't include Jason's documents."""
        client = api_env["client"]
        resp = client.get("/documents", headers={"X-User-Id": "admin"})
        doc_ids = [d["doc_id"] for d in resp.json()["documents"]]
        assert api_env.get("jason_doc_id") not in doc_ids

    def test_jason_sees_own_docs(self, api_env):
        """Jason listing includes only his documents."""
        client = api_env["client"]
        resp = client.get("/documents", headers={"X-User-Id": "jason"})
        data = resp.json()
        assert data["total"] >= 1
        for doc in data["documents"]:
            assert doc["user_id"] == "jason"


@online
class TestCollectionEditing:
    """Collection editing and reclassification."""

    def test_update_collections(self, api_env):
        """PATCH updates collections on a document."""
        client = api_env["client"]
        doc_id = api_env.get("ai_doc_id")
        if not doc_id:
            pytest.skip("No ai_doc_id from upload test")

        resp = client.patch(f"/documents/{doc_id}", json={
            "collections": ["research-scientific", "computer-science-ai"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert sorted(data["collections"]) == ["computer-science-ai", "research-scientific"]

    def test_reclassify_document(self, api_env):
        """AI reclassify returns new collections."""
        client = api_env["client"]
        doc_id = api_env.get("law_doc_id")
        if not doc_id:
            pytest.skip("No law_doc_id from upload test")

        resp = client.post(f"/documents/{doc_id}/reclassify")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["collections"]) >= 1
        print(f"  Reclassified law doc to: {data['collections']}")


@online
class TestQueryWorkflow:
    """B5.5 - B5.8: Query documents."""

    def test_query_no_filter(self, api_env):
        """B5.5: Query without filters returns answer + sources."""
        client = api_env["client"]
        resp = client.post("/query", json={
            "question": "What is discussed in these documents?",
            "top_k": 4,
        }, headers={"X-User-Id": "admin"})
        assert resp.status_code == 200, f"Query failed: {resp.text}"
        data = resp.json()
        assert len(data["answer"]) > 20
        assert len(data["sources"]) > 0
        # Sources should include doc_id
        for source in data["sources"]:
            assert "doc_id" in source

    def test_query_with_collection(self, api_env):
        """B5.6: Query with collection filter."""
        client = api_env["client"]
        resp = client.post("/query", json={
            "question": "What are the fundamental rights in the Basic Law?",
            "collection": "legal-compliance",
            "top_k": 4,
        }, headers={"X-User-Id": "admin"})
        assert resp.status_code == 200, f"Query failed: {resp.text}"
        data = resp.json()
        assert len(data["answer"]) > 20

    def test_query_with_session(self, api_env):
        """B5.7: Query with session_id stores context."""
        client = api_env["client"]
        resp = client.post("/query", json={
            "question": "What is the AI safety benchmark about?",
            "session_id": "test_session_b5",
            "top_k": 4,
        }, headers={"X-User-Id": "admin"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "test_session_b5"
        assert len(data["answer"]) > 20

    def test_query_followup_with_session(self, api_env):
        """B5.8: Follow-up query with same session_id uses prior context."""
        client = api_env["client"]
        resp = client.post("/query", json={
            "question": "Can you tell me more about that?",
            "session_id": "test_session_b5",
            "top_k": 4,
        }, headers={"X-User-Id": "admin"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["answer"]) > 20


@online
class TestDownloadWorkflow:
    """File download endpoint."""

    def test_download_document(self, api_env):
        """Download returns file content."""
        client = api_env["client"]
        doc_id = api_env.get("law_doc_id")
        if not doc_id:
            pytest.skip("No law_doc_id from upload test")

        resp = client.get(f"/documents/{doc_id}/download")
        assert resp.status_code == 200
        assert len(resp.content) > 0

    def test_download_nonexistent(self, api_env):
        """Download nonexistent doc returns 404."""
        client = api_env["client"]
        resp = client.get("/documents/nonexistent/download")
        assert resp.status_code == 404


@online
class TestDeleteWorkflow:
    """B5.9 - B5.10: Delete document."""

    def test_delete_document(self, api_env):
        """B5.9: Delete removes doc from listing."""
        client = api_env["client"]
        doc_id = api_env.get("law_doc_id")
        if not doc_id:
            pytest.skip("No law_doc_id from upload test")

        resp = client.delete(f"/documents/{doc_id}")
        assert resp.status_code == 200
        assert resp.json()["doc_id"] == doc_id

        # Verify removed from listing
        list_resp = client.get("/documents", params={"collection": "legal-compliance"}, headers={"X-User-Id": "admin"})
        doc_ids = [d["doc_id"] for d in list_resp.json()["documents"]]
        assert doc_id not in doc_ids
