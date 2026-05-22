"""Phase 5: every query that triggers deanonymization writes an audit
entry (action='deanonymize', entity_count=N).
"""
from __future__ import annotations

import shutil
from contextlib import asynccontextmanager

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel
from langchain_core.embeddings import Embeddings
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import AnonymizationAuditEntryModel, Base, UserModel
from app.dependencies import get_db, get_embeddings, get_llm, get_summary_store

pytest.importorskip("presidio_analyzer")
pytest.importorskip("spacy")

PII_TEXT = "Alice Smith filed a complaint on 2026-04-15. Bob Jones at 555-123-4567."

_EMBED_DIM = 1536


class _FakeEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * _EMBED_DIM for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.0] * _EMBED_DIM


class _FakeLLM(BaseChatModel):
    """Fake LLM: returns valid query-analysis JSON and a fixed answer."""

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
        text = " ".join(
            (m.content if hasattr(m, "content") else str(m))
            for m in (messages if isinstance(messages, list) else [messages])
        )
        if "valid JSON" in text or "query_type" in text.lower() or '"types"' in text:
            return '{"types": ["fact"], "label": null}'
        if "json array" in text.lower() or "return a json" in text.lower():
            return "[]"
        return "This is a test answer."


@pytest.fixture
def anon_audit_app(tmp_path):
    """TestClient-ready app with anonymization enabled + mocked LLM/embeddings."""
    fernet_key = Fernet.generate_key().decode()
    upload_dir = tmp_path / "uploads"
    vs_dir = tmp_path / "vs"
    upload_dir.mkdir()
    vs_dir.mkdir()

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/db.sqlite")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

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
            database_url=f"sqlite+aiosqlite:///{tmp_path}/db.sqlite",
            upload_dir=upload_dir,
            vectorstore_dir=vs_dir,
            summary_enabled=False,
            user_isolation="none",
            openai_api_key="sk-fake-key-not-used",
            hybrid_search_enabled=False,
            rerank_enabled=False,
            query_expansion_enabled=False,
            router_enabled=False,
        )

        from app.vectorstore.faiss_store import FAISSStoreManager
        fake_emb = _FakeEmbeddings()
        vector_store = FAISSStoreManager(vs_dir)
        vector_store.initialize(fake_emb)

        from app.anonymization import AnonymizationEngine, MappingCrypto
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

    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, app, session_factory

    app.dependency_overrides.clear()
    shutil.rmtree(tmp_path, ignore_errors=True)


@pytest.mark.asyncio
async def test_query_writes_deanonymize_audit_entry(anon_audit_app, tmp_path):
    """After running a query against an anonymized doc, the audit log
    must have BOTH an `anonymize` entry (from upload) AND a
    `deanonymize` entry (from query)."""
    import tempfile, os

    client, app, session_factory = anon_audit_app

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
        assert r.status_code == 200, r.text
        doc_id = r.json()["doc_id"]

        # Run a query — LLM call is mocked, full retrieval pipeline runs
        client.post("/query", json={"question": "Who filed?", "doc_ids": [doc_id]})
    finally:
        os.unlink(fixture_path)

    # Verify audit log has both anonymize + deanonymize entries
    async with session_factory() as s:
        rows = (await s.execute(
            select(AnonymizationAuditEntryModel)
            .where(AnonymizationAuditEntryModel.document_id == doc_id)
            .order_by(AnonymizationAuditEntryModel.timestamp)
        )).scalars().all()

    actions = [r.action for r in rows]
    assert "anonymize" in actions, f"No 'anonymize' entry found. Actions: {actions}"
    assert "deanonymize" in actions, f"No 'deanonymize' entry found. Actions: {actions}"
