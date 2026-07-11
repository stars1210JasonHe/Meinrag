"""P2 root cause (ops work order, closed 2026-07-11): zero-chunk documents.

A file with no extractable text (scanned/no-text-layer PDF, converted docx
whose content sits in text frames) produced ZERO chunks, which travelled all
the way into faiss: replacement_add does `n, d = x.shape` and an empty batch
is a 1-D array -> `not enough values to unpack (expected 2, got 1)` -> 500.

Fixes under test:
- upload returns a diagnosable 422 at the parse stage for no-text files
- vector stores treat an empty add_documents batch as a no-op (defense in
  depth for any other caller)
"""
import io
import zipfile
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool

from app.config import Settings, LLMProvider, VectorStoreType
from app.db.models import Base, UserModel
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
from app.vectorstore.faiss_store import FAISSStoreManager
from tests.test_workorder_p3 import _HashEmbeddings, _docs


def _docx_bytes(body_xml: str) -> bytes:
    """Minimal .docx: a zip with just word/document.xml (all docx2txt reads)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(
            "word/document.xml",
            '<?xml version="1.0"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body>{body_xml}</w:body></w:document>",
        )
    return buf.getvalue()


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        openai_api_key="fake-key-for-testing",
        llm_provider=LLMProvider.OPENAI,
        vector_store=VectorStoreType.CHROMA,
        upload_dir=tmp_path,
    )

    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

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
    app.dependency_overrides[get_vector_store] = lambda: MagicMock()
    app.dependency_overrides[get_llm] = lambda: MagicMock()
    app.dependency_overrides[get_embeddings] = lambda: MagicMock()
    app.dependency_overrides[get_edge_repository] = lambda: MagicMock()
    app.dependency_overrides[get_summary_store] = lambda: None

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


class TestNoTextUpload:
    def test_docx_with_no_text_returns_422_not_500(self, client):
        """The 13 production files, in miniature: parses fine, zero text."""
        resp = client.post(
            "/documents/upload",
            files={
                "file": (
                    "frame_only.docx",
                    io.BytesIO(_docx_bytes("")),  # valid docx, empty body
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert resp.status_code == 422
        detail = resp.json()["detail"]
        assert "no extractable text" in detail
        assert "stage 'parse'" in detail

    def test_docx_with_text_still_ingests_past_parse(self, client):
        """Control: same construction WITH a text run must not trip the guard.
        (Later stages use mocks, so anything != the parse-stage 422 is fine.)"""
        body = "<w:p><w:r><w:t>合同编号 X-1 的争议解决条款内容。</w:t></w:r></w:p>"
        resp = client.post(
            "/documents/upload",
            files={
                "file": (
                    "real_text.docx",
                    io.BytesIO(_docx_bytes(body)),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
        assert not (
            resp.status_code == 422
            and "no extractable text" in str(resp.json().get("detail"))
        ), resp.json()


class TestEmptyBatchStoreGuards:
    def test_faiss_empty_add_is_noop(self, tmp_path):
        store = FAISSStoreManager(persist_directory=tmp_path)
        store.initialize(_HashEmbeddings())
        assert store.add_documents([], doc_id="ghost") == []
        assert store.get_all_documents() == []
        # and the store still works normally afterwards
        store.add_documents(_docs("real", 2), doc_id="real")
        assert len(store.get_chunks_by_doc("real")) == 2

    def test_faiss_single_chunk_doc_is_fine(self, tmp_path):
        """The other half of the production suspicion — single-chunk docs
        produce a (1, d) batch and must ingest normally."""
        store = FAISSStoreManager(persist_directory=tmp_path)
        store.initialize(_HashEmbeddings())
        store.add_documents(_docs("solo", 1), doc_id="solo")
        assert len(store.get_chunks_by_doc("solo")) == 1

    def test_chroma_empty_add_is_noop(self):
        from app.vectorstore.chroma_store import ChromaStoreManager
        store = ChromaStoreManager.__new__(ChromaStoreManager)
        store._store = MagicMock()
        assert store.add_documents([], doc_id="ghost") == []
        store._store.add_documents.assert_not_called()
