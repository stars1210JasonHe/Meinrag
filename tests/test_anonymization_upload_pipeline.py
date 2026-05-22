"""Integration test: upload a doc with anonymization enabled and verify
the chunks reaching the vector store contain no raw PII.

Design notes
------------
- Uses a custom lifespan so we never call the OpenAI API (no key needed).
- The AnonymizationEngine runs for real (Presidio + en_core_web_lg).
- LLM + embeddings are stub objects; auto_suggest=false skips the
  classifier so the LLM stub is never invoked.
- Fake embeddings return a fixed-size zero vector so FAISS/Chroma won't
  complain about dimension mismatches.
- `get_anonymization_engine` returns app.state.anonymization_engine via
  dependency injection — no override needed, the real DI factory reads it.
"""
from __future__ import annotations

import shutil
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.db.models import Base, UserModel
from app.dependencies import get_db, get_embeddings, get_llm, get_summary_store

pytest.importorskip("presidio_analyzer")
pytest.importorskip("spacy")


PII_FIXTURE_TEXT = (
    "On 2026-04-15, Alice Smith (alice.smith@example.com) filed a complaint "
    "against Acme Corp on behalf of her client Bob Jones. Bob's phone is "
    "555-123-4567. The case docket is 24-CV-9981."
)

_EMBED_DIM = 1536  # same default as OpenAI text-embedding-3-small


class _FakeEmbeddings(Embeddings):
    """Returns zero vectors so FAISS/Chroma index accepts them."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * _EMBED_DIM for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.0] * _EMBED_DIM


class _FakeLLM(BaseChatModel):
    """Stub LLM — must never be invoked during this test."""

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
        raise AssertionError("LLM should not be called (auto_suggest=false)")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
        raise AssertionError("LLM should not be called (auto_suggest=false)")


@pytest.fixture
def anon_upload_app(tmp_path):
    """Build a TestClient-ready FastAPI app with:
    - SQLite in-memory DB
    - FAISS vector store in tmp_path
    - Real AnonymizationEngine (Presidio + en_core_web_lg)
    - Fake LLM + embeddings via dependency_overrides
    - anonymization_enabled=true, anonymization_languages=['en']
    """
    import os
    fernet_key = Fernet.generate_key().decode()

    upload_dir = tmp_path / "uploads"
    vs_dir = tmp_path / "vs"
    upload_dir.mkdir()
    vs_dir.mkdir()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def _lifespan(app):
        # DB setup
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with session_factory() as s:
            s.add(UserModel(user_id="admin", display_name="Admin"))
            await s.commit()

        # Settings (ANONYMIZATION_LANGUAGES=en to skip zh_core_web_trf load)
        from app.config import Settings
        settings = Settings(
            _env_file=None,
            anonymization_enabled=True,
            anonymization_encryption_key=fernet_key,
            anonymization_languages=["en"],
            database_url="sqlite+aiosqlite:///:memory:",
            upload_dir=upload_dir,
            vectorstore_dir=vs_dir,
            summary_enabled=False,
            user_isolation="none",
            openai_api_key="sk-fake-key-not-used",
        )

        # Vector store (FAISS with fake embeddings)
        from app.vectorstore.faiss_store import FAISSStoreManager
        fake_emb = _FakeEmbeddings()
        vector_store = FAISSStoreManager(vs_dir)
        vector_store.initialize(fake_emb)

        # Anonymization plugin
        from app.anonymization import AnonymizationEngine, MappingCrypto
        mapping_crypto = MappingCrypto(fernet_key)
        anon_engine = AnonymizationEngine(settings)

        # Publish on app.state
        app.state.settings = settings
        app.state.db_engine = engine
        app.state.db_session_factory = session_factory
        app.state.vector_store = vector_store
        app.state.summary_store = None
        app.state.llm = _FakeLLM()
        app.state.embeddings = fake_emb
        app.state.mapping_crypto = mapping_crypto
        app.state.anonymization_engine = anon_engine

        yield

        vector_store.persist()
        await engine.dispose()

    async def _override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    from app.main import create_app
    app = create_app()
    app.router.lifespan_context = _lifespan
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_llm] = lambda: _FakeLLM()
    app.dependency_overrides[get_embeddings] = lambda: _FakeEmbeddings()
    app.dependency_overrides[get_summary_store] = lambda: None

    with TestClient(app, raise_server_exceptions=True) as client:
        yield client

    app.dependency_overrides.clear()
    shutil.rmtree(tmp_path, ignore_errors=True)


def test_upload_anonymizes_pii_before_vector_store(anon_upload_app, tmp_path):
    """Upload a TXT file with clear PII and verify:
    1. Upload succeeds (200)
    2. Chunks in the vector store contain NO raw PII strings
    3. Typed placeholders [PERSON_N] / [EMAIL_*] / [PHONE_*] ARE present
    """
    client = anon_upload_app

    # Write the PII fixture to a temp file the TestClient can open
    # Note: tmp_path here is a new pytest tmp_path for THIS test, not the
    # fixture's — use a sibling directory to avoid conflicts.
    import tempfile, os
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write(PII_FIXTURE_TEXT)
        fixture_path = f.name

    try:
        with open(fixture_path, "rb") as fh:
            r = client.post(
                "/documents/upload?auto_suggest=false",
                files={"file": ("pii_memo.txt", fh, "text/plain")},
            )
        assert r.status_code == 200, r.text
        doc_id = r.json()["doc_id"]

        # Inspect what reached the vector store via the chunk listing endpoint
        chunks_resp = client.get(f"/documents/{doc_id}/chunks")
        assert chunks_resp.status_code == 200, chunks_resp.text
        chunk_texts = [ch["content"] for ch in chunks_resp.json()["chunks"]]
    finally:
        os.unlink(fixture_path)

    assert chunk_texts, "No chunks returned — upload or chunking failed"

    joined = " ".join(chunk_texts)

    # ── PII must NOT appear in the stored chunks ──────────────────────
    assert "Alice Smith" not in joined, "PERSON 'Alice Smith' leaked into chunk text"
    assert "Bob Jones" not in joined, "PERSON 'Bob Jones' leaked into chunk text"
    assert "alice.smith@example.com" not in joined, "EMAIL leaked into chunk text"
    assert "555-123-4567" not in joined, "PHONE leaked into chunk text"

    # ── Typed placeholders SHOULD appear ─────────────────────────────
    assert "[PERSON_" in joined, f"No [PERSON_N] placeholder found. Chunks: {joined!r}"
    assert (
        "[EMAIL_ADDRESS_" in joined or "[EMAIL_" in joined
    ), f"No email placeholder found. Chunks: {joined!r}"
    assert (
        "[PHONE_NUMBER_" in joined or "[PHONE_" in joined
    ), f"No phone placeholder found. Chunks: {joined!r}"
