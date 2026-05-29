"""Tests for the retrieve-only POST /search endpoint.

Layers:
  - Unit: SearchRequest/SearchResponse models, _build_source_chunks truncation,
    retrieve_and_rank force_corpus_only flag (no API key needed).
  - Integration: TestClient + real FAISS + fake embeddings/LLM, hitting /search
    end-to-end, including the deanonymize path.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.schemas import SearchRequest, SearchResponse, SourceChunk


class TestSearchModels:
    def test_request_defaults(self):
        req = SearchRequest(query="hello")
        assert req.query == "hello"
        assert req.top_k is None          # resolved to settings.retrieval_top_k in the endpoint
        assert req.doc_ids is None
        assert req.collection is None

    def test_request_rejects_empty_query(self):
        with pytest.raises(ValidationError):
            SearchRequest(query="")

    def test_request_rejects_too_long_query(self):
        with pytest.raises(ValidationError):
            SearchRequest(query="x" * 2001)

    def test_request_top_k_bounds(self):
        with pytest.raises(ValidationError):
            SearchRequest(query="q", top_k=0)
        with pytest.raises(ValidationError):
            SearchRequest(query="q", top_k=51)

    def test_response_has_no_answer_field(self):
        resp = SearchResponse(
            results=[SourceChunk(content="c", source_file="f.pdf")],
            confidence_tier="high",
            total_available=1,
            query_types=["fact"],
        )
        assert not hasattr(resp, "answer")
        assert resp.results[0].content == "c"
        assert resp.total_available == 1


from langchain_core.documents import Document
from app.services.retrieval import _build_source_chunks


class TestBuildSourceChunksTruncation:
    """§4b: /search returns FULL text; /query keeps the 500-char preview."""

    def _long_pair(self):
        text = "word " * 400  # 2000 chars, well over 500
        doc = Document(page_content=text, metadata={"doc_id": "d1", "chunk_index": 0, "source_file": "f.pdf"})
        return [(doc, 0.5)], text

    def test_default_truncates_to_preview(self):
        pairs, full = self._long_pair()
        out = _build_source_chunks(pairs)            # default 500
        assert len(out) == 1
        assert len(out[0].content) < len(full)
        assert out[0].content != full

    def test_none_returns_full_text(self):
        pairs, full = self._long_pair()
        out = _build_source_chunks(pairs, truncate_chars=None)
        assert out[0].content == full               # complete, untruncated

    def test_short_chunk_unaffected(self):
        doc = Document(page_content="short", metadata={"doc_id": "d1", "chunk_index": 0, "source_file": "f.pdf"})
        assert _build_source_chunks([(doc, 0.5)])[0].content == "short"
        assert _build_source_chunks([(doc, 0.5)], truncate_chars=None)[0].content == "short"


from unittest.mock import AsyncMock, MagicMock
from langchain_core.messages import AIMessage


def _retrieval_settings(web_threshold: float):
    """MagicMock Settings with every flag retrieve_and_rank reads set explicitly.

    All optional pipeline stages off; web search ON so the gate is reachable.
    """
    s = MagicMock()
    s.router_enabled = False
    s.router_min_scope = 15
    s.router_top_k = 8
    s.hybrid_search_enabled = False
    s.rerank_enabled = False
    s.query_expansion_enabled = False
    s.visual_proximity_enabled = False
    s.web_search_enabled = True
    s.web_search_score_threshold = web_threshold
    s.anonymization_enabled = False
    s.query_types_file = "data/query_types.json"
    s.scoring_profile = "general"
    s.context_budget_ratio = 0.6
    s.reserved_output_tokens = 2048
    s.reserved_prompt_overhead_tokens = 512
    s.max_context_tokens = None
    s.history_min_reserve_ratio = 0.2
    s.history_max_budget_ratio = 0.4
    s.openai_model = "gpt-4o-mini"
    s.llm_provider = MagicMock()
    s.llm_provider.value = "openai"
    return s


def _retrieval_deps(search_results):
    """vector_store / llm / edge_repo mocks. search_results is what
    similarity_search_with_scores returns (list of (Document, score))."""
    vector_store = MagicMock()
    vector_store.similarity_search_with_scores = lambda question, k, doc_ids=None: list(search_results)
    vector_store.get_all_documents = MagicMock(return_value=[])
    vector_store.get_chunks_by_doc = MagicMock(return_value=[])
    llm = AsyncMock()
    # _analyze_query -> exploratory (avoids the fact-keyword-expansion branch)
    llm.ainvoke = AsyncMock(return_value=AIMessage(content='{"types": ["exploratory"], "label": null}'))
    edge_repo = AsyncMock()
    edge_repo.get_edge_type_counts_batch = AsyncMock(return_value={})
    edge_repo.get_edges_from = AsyncMock(return_value=[])
    return vector_store, llm, edge_repo


@pytest.mark.asyncio
class TestForceCorpusOnly:
    async def _run(self, search_results, web_threshold, force_corpus_only):
        from app.services import retrieval as retrieval_mod
        vector_store, llm, edge_repo = _retrieval_deps(search_results)
        return await retrieval_mod.retrieve_and_rank(
            question="an unscoped query with no good match",
            top_k=4,
            doc_ids=None,
            user_scoped=False,
            llm=llm,
            vector_store=vector_store,
            embeddings=MagicMock(),
            edge_repo=edge_repo,
            settings=_retrieval_settings(web_threshold),
            force_corpus_only=force_corpus_only,
        )

    async def test_default_false_empty_triggers_web_gate(self):
        """Empty retrieval, default flag: gate fires (regression guard for /query)."""
        result = await self._run([], web_threshold=0.0, force_corpus_only=False)
        assert result.web_search_needed is True
        assert result.sources == []

    async def test_force_corpus_only_empty_skips_gate(self):
        """Empty retrieval + force_corpus_only: no web flag, truthful empty result."""
        result = await self._run([], web_threshold=0.0, force_corpus_only=True)
        assert result.web_search_needed is False
        assert result.sources == []
        assert result.chunks_available == 0

    async def test_force_corpus_only_preserves_below_threshold_chunks(self):
        """Below-threshold non-empty (raised threshold): default discards via the
        gate; force_corpus_only keeps the best-effort chunk."""
        doc = Document(
            page_content="weakly relevant content",
            metadata={"doc_id": "d1", "chunk_index": 0, "section_type": "methods",
                      "chunk_type": "text", "source_file": "f.pdf"},
        )
        results = [(doc, 0.1)]  # below the raised 0.99 threshold

        gated = await self._run(results, web_threshold=0.99, force_corpus_only=False)
        assert gated.web_search_needed is True
        assert gated.sources == []

        kept = await self._run(results, web_threshold=0.99, force_corpus_only=True)
        assert kept.web_search_needed is False
        assert len(kept.sources) >= 1
        assert kept.sources[0].content  # the discarded-by-gate chunk survived


# ---------------------------------------------------------------------------
# Integration: TestClient + real FAISS + fake embeddings/LLM, hitting /search
# ---------------------------------------------------------------------------

import os
import shutil
import tempfile
from contextlib import asynccontextmanager

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from langchain_core.embeddings import Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.outputs import ChatResult, ChatGeneration
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.db.models import Base, UserModel
from app.dependencies import get_db, get_embeddings, get_llm, get_summary_store

_EMBED_DIM = 1536


class _FakeEmbeddings(Embeddings):
    def embed_documents(self, texts):
        return [[0.0] * _EMBED_DIM for _ in texts]

    def embed_query(self, text):
        return [0.0] * _EMBED_DIM


class _FakeLLM(BaseChatModel):
    @property
    def _llm_type(self):
        return "fake"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self._pick(messages)))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self._pick(messages)))])

    @staticmethod
    def _pick(messages):
        text = " ".join(
            (m.content if hasattr(m, "content") else str(m))
            for m in (messages if isinstance(messages, list) else [messages])
        )
        if "valid JSON" in text or "query_type" in text.lower() or '"types"' in text:
            return '{"types": ["exploratory"], "label": null}'
        if "json array" in text.lower() or "return a json" in text.lower():
            return "[]"
        return "unused — /search never synthesizes an answer"


def _make_search_app(tmp_path, *, anonymization_enabled=False, fernet_key=None):
    upload_dir = tmp_path / "uploads"
    vs_dir = tmp_path / "vs"
    upload_dir.mkdir(exist_ok=True)
    vs_dir.mkdir(exist_ok=True)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
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
            anonymization_enabled=anonymization_enabled,
            anonymization_encryption_key=fernet_key,
            anonymization_languages=["en"],
            database_url="sqlite+aiosqlite:///:memory:",
            upload_dir=upload_dir,
            vectorstore_dir=vs_dir,
            summary_enabled=False,
            user_isolation="none",
            openai_api_key="sk-fake-key-not-used",
            hybrid_search_enabled=False,
            rerank_enabled=False,
            query_expansion_enabled=False,
            visual_proximity_enabled=False,
            web_search_enabled=True,      # ON — proves /search still never web-falls-back
            router_enabled=False,
        )

        from app.vectorstore.faiss_store import FAISSStoreManager

        fake_emb = _FakeEmbeddings()
        vector_store = FAISSStoreManager(vs_dir)
        vector_store.initialize(fake_emb)

        app.state.settings = settings
        app.state.db_engine = engine
        app.state.db_session_factory = session_factory
        app.state.vector_store = vector_store
        app.state.summary_store = None
        app.state.llm = _FakeLLM()
        app.state.embeddings = fake_emb

        if anonymization_enabled:
            from app.anonymization import AnonymizationEngine, MappingCrypto
            app.state.mapping_crypto = MappingCrypto(fernet_key)
            app.state.anonymization_engine = AnonymizationEngine(settings)

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
    return app


def _upload_txt(client, filename, text):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(text)
        path = f.name
    try:
        with open(path, "rb") as fh:
            r = client.post(
                "/documents/upload?auto_suggest=false",
                files={"file": (filename, fh, "text/plain")},
            )
        assert r.status_code == 200, f"Upload failed: {r.text}"
        return r.json()["doc_id"]
    finally:
        os.unlink(path)


@pytest.fixture
def search_app(tmp_path):
    app = _make_search_app(tmp_path)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client
    app.dependency_overrides.clear()
    shutil.rmtree(tmp_path, ignore_errors=True)


class TestSearchEndpoint:
    def test_empty_body_returns_422(self, search_app):
        assert search_app.post("/search").status_code == 422

    def test_empty_query_returns_422(self, search_app):
        assert search_app.post("/search", json={"query": ""}).status_code == 422

    def test_returns_results_no_answer_field(self, search_app):
        _upload_txt(search_app, "memo.txt", "The mitochondria is the powerhouse of the cell. " * 20)
        resp = search_app.post("/search", json={"query": "what is the powerhouse of the cell?"})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "answer" not in data
        assert "results" in data and isinstance(data["results"], list)
        assert "confidence_tier" in data
        assert "total_available" in data
        assert len(data["results"]) >= 1

    def test_scope_filtering_by_doc_ids(self, search_app):
        doc_a = _upload_txt(search_app, "alpha.txt", "Alpha document about quantum entanglement. " * 20)
        _upload_txt(search_app, "beta.txt", "Beta document about marine biology. " * 20)
        resp = search_app.post("/search", json={"query": "anything", "doc_ids": [doc_a]})
        assert resp.status_code == 200, resp.text
        results = resp.json()["results"]
        assert results, "scoped search returned nothing"
        assert all(r["doc_id"] == doc_a for r in results)

    def test_unscoped_whole_corpus(self, search_app):
        _upload_txt(search_app, "a.txt", "Alpha content here. " * 20)
        _upload_txt(search_app, "b.txt", "Beta content here. " * 20)
        resp = search_app.post("/search", json={"query": "content"})
        assert resp.status_code == 200, resp.text
        # No web fallback (web_search_enabled=True but force_corpus_only suppresses it)
        results = resp.json()["results"]
        assert all(r["source_type"] == "document" for r in results)

    def test_total_available_is_pre_cap_count(self, search_app):
        """total_available = chunks_available, snapshotted BEFORE per-doc-cap /
        token-budget trimming, so it is always >= the returned count.

        NOTE: top_k is a retrieval-breadth target, NOT a hard output cap —
        _apply_per_doc_cap is a no-op for single/unscoped docs (retrieval.py
        :1004-1005), and final count is governed by strategy sampling + token
        budget. So we assert the guaranteed invariant, not len <= top_k."""
        _upload_txt(search_app, "long.txt", "Sentence about the topic. " * 800)
        resp = search_app.post("/search", json={"query": "topic", "top_k": 2})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert len(data["results"]) >= 1
        assert data["total_available"] is not None
        assert data["total_available"] >= len(data["results"])

    def test_top_k_influences_breadth(self, search_app):
        """Directional check that top_k is plumbed through: a tiny top_k never
        returns MORE chunks than a large one (it may tie when budget binds)."""
        _upload_txt(search_app, "long.txt", "Sentence about the topic. " * 800)
        small = search_app.post("/search", json={"query": "topic", "top_k": 1}).json()
        large = search_app.post("/search", json={"query": "topic", "top_k": 10}).json()
        assert len(small["results"]) <= len(large["results"])


class TestSearchDeanonymization:
    """With anonymization ON, /search must return deanonymized chunks (real
    names), never the [PERSON_N] placeholders the vector store holds."""

    def test_search_returns_deanonymized_chunks(self, tmp_path):
        pytest.importorskip("presidio_analyzer")
        pytest.importorskip("spacy")

        fernet_key = Fernet.generate_key().decode()
        app = _make_search_app(tmp_path, anonymization_enabled=True, fernet_key=fernet_key)
        with TestClient(app, raise_server_exceptions=True) as client:
            doc_id = _upload_txt(
                client, "memo.txt",
                "Alice Smith filed a complaint on 2026-04-15. "
                "Bob Jones can be reached at 555-123-4567.",
            )

            # Vector store still holds pseudonyms
            chunks = client.get(f"/documents/{doc_id}/chunks").json()["chunks"]
            joined_raw = " ".join(c["content"] for c in chunks)
            assert "[PERSON_" in joined_raw
            assert "Alice Smith" not in joined_raw

            # /search returns deanonymized real names
            resp = client.post("/search", json={"query": "complaint", "doc_ids": [doc_id]})
            assert resp.status_code == 200, resp.text
            joined = " ".join(r["content"] for r in resp.json()["results"])
            assert joined, "no results returned"
            assert "Alice Smith" in joined or "Bob Jones" in joined
            assert "[PERSON_" not in joined

        app.dependency_overrides.clear()
        shutil.rmtree(tmp_path, ignore_errors=True)
