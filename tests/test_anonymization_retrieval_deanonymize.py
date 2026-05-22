"""Phase 5: retrieved chunks are deanonymized before reaching the LLM
or the API response. FAISS still holds pseudonymized chunks.

Design
------
- Real AnonymizationEngine (Presidio + en_core_web_lg) runs on upload.
- A FakeLLM is used: returns valid JSON for _analyze_query so the
  retrieval pipeline does not crash, and returns a fixed answer string
  for the actual RAG chain invocation.
- After the query the /query response's `sources` list should contain
  the real names (deanonymized). The /documents/:id/chunks endpoint
  (which reads from the vector store directly) should still show
  pseudonyms only.
"""
from __future__ import annotations

import shutil
import tempfile
import os
from contextlib import asynccontextmanager

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult, ChatGeneration
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.db.models import Base, UserModel
from app.dependencies import get_db, get_embeddings, get_llm, get_summary_store

pytest.importorskip("presidio_analyzer")
pytest.importorskip("spacy")


PII_TEXT = (
    "Alice Smith filed a complaint on 2026-04-15. "
    "Bob Jones can be reached at 555-123-4567."
)

_EMBED_DIM = 1536


class _FakeEmbeddings(Embeddings):
    """Fixed zero vectors so FAISS accepts them."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * _EMBED_DIM for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.0] * _EMBED_DIM


class _FakeLLM(BaseChatModel):
    """Fake LLM that:
    - Returns a valid query-analysis JSON response for _analyze_query calls
    - Returns a fixed short answer for all other calls
    """

    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        content = self._pick_response(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        content = self._pick_response(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])

    @staticmethod
    def _pick_response(messages) -> str:
        """Return JSON for analyze-query calls, otherwise a fixed answer."""
        # Convert messages to text for inspection
        text = " ".join(
            (m.content if hasattr(m, "content") else str(m))
            for m in (messages if isinstance(messages, list) else [messages])
        )
        # _analyze_query prompt contains "output ONLY valid JSON"
        if "valid JSON" in text or "query_type" in text.lower() or '"types"' in text:
            return '{"types": ["fact"], "label": null}'
        # Router prefix prompt contains "Return a JSON array"
        if "json array" in text.lower() or "return a json" in text.lower():
            import json
            # Return all doc IDs mentioned — we can't know them, so return empty
            # which causes the router to fall back to full scope.
            return "[]"
        # Everything else: synthesized RAG answer
        return "This is a test answer."


@pytest.fixture
def anon_query_app(tmp_path):
    """Build a TestClient-ready app with the same pattern as the upload
    pipeline test but also ready to serve /query requests.
    """
    fernet_key = Fernet.generate_key().decode()
    upload_dir = tmp_path / "uploads"
    vs_dir = tmp_path / "vs"
    upload_dir.mkdir()
    vs_dir.mkdir()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    @asynccontextmanager
    async def _lifespan(app):
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with session_factory() as s:
            s.add(UserModel(user_id="admin", display_name="Admin"))
            await s.commit()

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
            # Disable optional pipeline features that require extra infra
            hybrid_search_enabled=False,
            rerank_enabled=False,
            query_expansion_enabled=False,
            visual_proximity_enabled=False,
            web_search_enabled=False,
            router_enabled=False,
        )

        from app.vectorstore.faiss_store import FAISSStoreManager
        from app.anonymization import AnonymizationEngine, MappingCrypto

        fake_emb = _FakeEmbeddings()
        vector_store = FAISSStoreManager(vs_dir)
        vector_store.initialize(fake_emb)

        mapping_crypto = MappingCrypto(fernet_key)
        anon_engine = AnonymizationEngine(settings)

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


def test_retrieved_chunks_are_deanonymized(anon_query_app, tmp_path):
    """Upload a PII doc, then query it.

    Assertions:
    1. Vector store (FAISS) still contains pseudonymized text — no raw PII.
    2. /query response sources contain deanonymized real names.
    """
    client = anon_query_app

    # Write fixture to a temp file
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".txt", delete=False, encoding="utf-8"
    ) as f:
        f.write(PII_TEXT)
        fixture_path = f.name

    try:
        with open(fixture_path, "rb") as fh:
            r = client.post(
                "/documents/upload?auto_suggest=false",
                files={"file": ("memo.txt", fh, "text/plain")},
            )
        assert r.status_code == 200, f"Upload failed: {r.text}"
        doc_id = r.json()["doc_id"]
    finally:
        os.unlink(fixture_path)

    # ── Regression check: FAISS still has pseudonymized chunks ───────────
    chunks_resp = client.get(f"/documents/{doc_id}/chunks")
    assert chunks_resp.status_code == 200, chunks_resp.text
    joined_raw = " ".join(ch["content"] for ch in chunks_resp.json()["chunks"])
    assert joined_raw, "No chunks found after upload"
    assert "Alice Smith" not in joined_raw, (
        f"FAISS still has raw PII 'Alice Smith': {joined_raw!r}"
    )
    assert "Bob Jones" not in joined_raw, (
        f"FAISS still has raw PII 'Bob Jones': {joined_raw!r}"
    )
    assert "[PERSON_" in joined_raw, (
        f"Expected [PERSON_N] placeholder in FAISS chunks: {joined_raw!r}"
    )

    # ── Query: sources should be deanonymized ────────────────────────────
    query_resp = client.post(
        "/query",
        json={
            "question": "What happened with the complaint?",
            "doc_ids": [doc_id],
            "top_k": 5,
        },
    )
    assert query_resp.status_code == 200, f"Query failed: {query_resp.text}"

    sources = query_resp.json().get("sources", [])
    assert sources, "Query returned no sources — retrieval returned nothing"

    joined_sources = " ".join(s["content"] for s in sources)

    # The deanonymize step must have replaced placeholders with real names
    assert "Alice Smith" in joined_sources or "Bob Jones" in joined_sources, (
        f"Expected real names in query sources after deanonymization.\n"
        f"Sources content: {joined_sources!r}\n"
        f"Raw FAISS chunks: {joined_raw!r}"
    )
    # Pseudonyms should NOT appear in sources anymore (they were replaced)
    assert "[PERSON_" not in joined_sources, (
        f"Pseudonym still present in query sources (deanonymize did not run):\n"
        f"{joined_sources!r}"
    )
