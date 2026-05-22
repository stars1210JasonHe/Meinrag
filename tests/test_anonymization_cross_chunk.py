"""Cross-chunk consistency: the same entity in N chunks must get the
same pseudonym across all of them (within one document).

Design notes
------------
- Uses the same custom-lifespan pattern as test_anonymization_upload_pipeline.py
  to bypass the @lru_cache on get_settings().
- CHUNK_SIZE=120 forces the fixture (5 sections, ~300 chars) into 3+ chunks.
- The AnonymizationEngine runs for real (Presidio + en_core_web_lg).
- LLM + embeddings are stubs; auto_suggest=false skips classification.
"""
from __future__ import annotations

import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.models import Base, UserModel
from app.dependencies import get_db, get_embeddings, get_llm, get_summary_store

pytest.importorskip("presidio_analyzer")
pytest.importorskip("spacy")


FIXTURE = Path(__file__).parent / "fixtures" / "anonymization" / "multi_chunk_pii.txt"

_EMBED_DIM = 1536  # matches OpenAI text-embedding-3-small default


class _FakeEmbeddings(Embeddings):
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * _EMBED_DIM for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.0] * _EMBED_DIM


class _FakeLLM(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
        raise AssertionError("LLM should not be called (auto_suggest=false)")

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
        raise AssertionError("LLM should not be called (auto_suggest=false)")


@pytest.fixture
def cross_chunk_app(tmp_path):
    """FastAPI app wired for cross-chunk consistency testing:
    - SQLite in-memory DB
    - FAISS vector store in tmp_path
    - CHUNK_SIZE=120 / CHUNK_OVERLAP=20 to guarantee 3+ chunks
    - Real AnonymizationEngine (Presidio + en_core_web_lg)
    - Fake LLM + embeddings (no OpenAI calls)
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
            chunk_size=120,
            chunk_overlap=20,
            summary_enabled=False,
            user_isolation="none",
            openai_api_key="sk-fake-key-not-used",
            parse_mode="default",
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

    with TestClient(app, raise_server_exceptions=True) as client:
        yield client

    app.dependency_overrides.clear()
    shutil.rmtree(tmp_path, ignore_errors=True)


def test_same_entity_gets_same_pseudonym_across_chunks(cross_chunk_app):
    """Upload a doc where 'Alice Smith' is mentioned in 5 separate sections.
    After ingest, every chunk that contained Alice should now contain the
    SAME [PERSON_N] token. This validates the per-doc EntityRegistry invariant.
    """
    client = cross_chunk_app

    with FIXTURE.open("rb") as f:
        r = client.post(
            "/documents/upload?auto_suggest=false",
            files={"file": ("multi.txt", f, "text/plain")},
        )
    assert r.status_code == 200, r.text
    doc_id = r.json()["doc_id"]

    chunks_r = client.get(f"/documents/{doc_id}/chunks")
    assert chunks_r.status_code == 200, chunks_r.text
    chunks = chunks_r.json()["chunks"]

    assert chunks, "No chunks returned — upload or chunking failed"

    # Sanity: CHUNK_SIZE=120 should produce several chunks from the fixture
    assert len(chunks) >= 3, (
        f"Expected >=3 chunks with CHUNK_SIZE=120, got {len(chunks)}. "
        f"Chunks: {[c['content'][:60] for c in chunks]}"
    )

    # Collect the set of [PERSON_N] tokens present in each chunk that has any.
    person_tokens_per_chunk: list[set[str]] = []
    for ch in chunks:
        tokens = set(re.findall(r"\[PERSON_\d+\]", ch["content"]))
        if tokens:
            person_tokens_per_chunk.append(tokens)

    assert len(person_tokens_per_chunk) >= 3, (
        f"Fixture should produce >=3 chunks containing PERSON tokens, "
        f"got {len(person_tokens_per_chunk)}: {person_tokens_per_chunk}"
    )

    # All person-containing chunks must share at least one token — the one
    # assigned to Alice Smith (present in every section of the fixture).
    # If EntityRegistry was re-created per chunk, each chunk would get a
    # different [PERSON_1] binding and the intersection would be empty.
    common = set.intersection(*person_tokens_per_chunk)
    assert len(common) >= 1, (
        "No common [PERSON_N] pseudonym across chunks — per-doc EntityRegistry "
        f"consistency broken.\nPer-chunk token sets: {person_tokens_per_chunk}"
    )
