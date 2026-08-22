"""A5: HTTP Error Handling tests - No API key required.

Uses FastAPI TestClient with mocked dependencies and in-memory SQLite DB.
"""
import io
import re
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from app.config import Settings, LLMProvider, VectorStoreType
from app.db.models import Base, UserModel
from app.dependencies import get_settings, get_vector_store, get_db, get_llm, get_embeddings, get_edge_repository, get_summary_store, get_registry, get_current_user
from app.main import create_app


@pytest.fixture
def mock_settings(tmp_path):
    """Minimal settings that don't need a real API key.

    upload_dir/vectorstore_dir point at tmp_path, matching what the anonymization
    tests already do. Two reasons, and the first one was actively breaking a test:

    The app creates these directories in its lifespan (app/main.py), but the client
    fixture below substitutes its own lifespan for the DB setup and does not recreate
    that step. With the default `data/uploads`, any test that gets far enough to write
    an uploaded file died with FileNotFoundError and a 500 — including
    test_corrupt_docx_returns_422_with_stage, which then never reached the parse stage
    it exists to check. It looked like the 422 handling was broken; it was not.

    Second, tests should not write into the working tree at all.
    """
    upload_dir = tmp_path / "uploads"
    vs_dir = tmp_path / "vs"
    upload_dir.mkdir()
    vs_dir.mkdir()
    return Settings(
        openai_api_key="fake-key-for-testing",
        llm_provider=LLMProvider.OPENAI,
        vector_store=VectorStoreType.CHROMA,
        upload_dir=upload_dir,
        vectorstore_dir=vs_dir,
    )


@pytest.fixture
def mock_vector_store():
    """Mock vector store that returns empty results."""
    store = MagicMock()
    store.similarity_search.return_value = []
    store.similarity_search_with_filter.return_value = []
    store.similarity_search_with_scores.return_value = []
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

    async def mock_get_edges_from(*args, **kwargs):
        return []

    mock_edge_repo = MagicMock()
    mock_edge_repo.get_edges_from = mock_get_edges_from

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

    def test_corrupt_docx_returns_422_with_stage(self, client):
        """P2 (ops work order): a file the parser can't ingest must yield a
        diagnosable 422 naming the stage + error + frame, not an opaque 500."""
        resp = client.post(
            "/documents/upload",
            files={
                "file": (
                    "broken.docx",
                    io.BytesIO(b"this is not a zip archive"),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "Ingest failed at stage 'parse'" in detail
        # innermost frame is included, e.g. [zipfile.py:1379]
        assert re.search(r"\[\w+.*\.py:\d+\]", detail), detail


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


class TestSessionEndpoints:
    """A5.7: Session API endpoint tests."""

    def test_list_sessions_empty(self, client):
        """GET /sessions with no sessions returns empty list."""
        resp = client.get("/sessions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_delete_nonexistent_session(self, client):
        """DELETE /sessions/nonexistent returns 404."""
        resp = client.delete("/sessions/nonexistent_session_id")
        assert resp.status_code == 404

    def test_get_nonexistent_session_messages(self, client):
        """GET /sessions/nonexistent/messages returns 404."""
        resp = client.get("/sessions/nonexistent_session_id/messages")
        assert resp.status_code == 404


class TestAskAIEndpoint:
    """Ask AI general knowledge endpoint tests."""

    def test_ask_ai_empty_body(self, client):
        """POST /query/ask-ai with no body returns 422."""
        resp = client.post("/query/ask-ai")
        assert resp.status_code == 422

    def test_ask_ai_empty_question(self, client):
        """Empty question returns 422."""
        resp = client.post("/query/ask-ai", json={"question": ""})
        assert resp.status_code == 422

    def test_ask_ai_question_too_long(self, client):
        """Question > 2000 chars returns 422."""
        resp = client.post("/query/ask-ai", json={"question": "x" * 2001})
        assert resp.status_code == 422


class TestDownloadDirectoryCollision:
    """Regression: download endpoint must skip the figure-extraction directory.

    Every PDF that goes through figure extraction creates upload_dir/{doc_id}/
    next to upload_dir/{doc_id}_{filename}.pdf. Before the fix, the download
    endpoint matched on `name.startswith(doc_id)` with no is_file() guard, so
    when iterdir() yielded the directory FileResponse choked → HTTP 500.
    """

    def _build_client(self, mock_settings, tmp_path, doc_id, filename):
        """Build a TestClient with get_registry mocked, upload_dir at tmp_path."""
        mock_settings.upload_dir = tmp_path

        registry = MagicMock()
        registry.get = AsyncMock(return_value={
            "doc_id": doc_id,
            "filename": filename,
            "user_id": "admin",
        })

        app = create_app()
        # No DB / lifespan needed — every dep used by /download is overridden.
        app.dependency_overrides[get_settings] = lambda: mock_settings
        app.dependency_overrides[get_registry] = lambda: registry
        app.dependency_overrides[get_current_user] = lambda: "admin"
        return TestClient(app, raise_server_exceptions=False)

    def test_returns_file_when_dir_collision_exists(self, mock_settings, tmp_path):
        """Both `{doc_id}/` dir AND `{doc_id}_*.pdf` exist → return the file."""
        doc_id = "abcdef123456"
        filename = "report.pdf"
        file_bytes = b"%PDF-1.4 fake content for regression test"

        # Recreate the on-disk shape that figure extraction produces
        (tmp_path / doc_id / "images").mkdir(parents=True)
        (tmp_path / f"{doc_id}_{filename}").write_bytes(file_bytes)

        client = self._build_client(mock_settings, tmp_path, doc_id, filename)
        resp = client.get(f"/documents/{doc_id}/download")

        assert resp.status_code == 200, (
            f"Expected 200 (file), got {resp.status_code}: {resp.text[:200]}"
        )
        assert resp.content == file_bytes

    def test_prefix_collision_with_underscore_separator(self, mock_settings, tmp_path):
        """doc_id `abc123` must NOT match a sibling file `abc1234_other.pdf`."""
        target_id = "abc123"
        sibling_id = "abc1234"  # shares the `abc123` prefix
        filename = "ours.pdf"
        target_bytes = b"%PDF target"

        (tmp_path / f"{target_id}_{filename}").write_bytes(target_bytes)
        (tmp_path / f"{sibling_id}_other.pdf").write_bytes(b"%PDF sibling")

        client = self._build_client(mock_settings, tmp_path, target_id, filename)
        resp = client.get(f"/documents/{target_id}/download")

        assert resp.status_code == 200
        assert resp.content == target_bytes  # not the sibling

    def test_returns_404_when_only_directory_exists(self, mock_settings, tmp_path):
        """If only the figure-extraction dir is on disk (file lost), return 404 not 500."""
        doc_id = "deadbeef0123"
        filename = "missing.pdf"
        (tmp_path / doc_id / "images").mkdir(parents=True)

        client = self._build_client(mock_settings, tmp_path, doc_id, filename)
        resp = client.get(f"/documents/{doc_id}/download")

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()
