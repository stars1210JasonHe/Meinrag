"""P3 (ops work order 2026-07-10): O(N)-latency fixes.

Covers: FAISS doc_id index correctness across mutations, BM25 scope-cache
skipping the corpus fetch on hit, per-doc coverage skip for retrieve-only
callers, and the router scope upper bound.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.messages import AIMessage

from app.vectorstore.faiss_store import FAISSStoreManager


class _HashEmbeddings(Embeddings):
    """Deterministic, text-dependent vectors — offline, no API."""

    def _vec(self, text: str) -> list[float]:
        h = abs(hash(text))
        return [((h >> (i * 2)) % 7) / 7.0 for i in range(16)]

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


@pytest.fixture
def faiss_store(tmp_path):
    store = FAISSStoreManager(persist_directory=tmp_path)
    store.initialize(_HashEmbeddings())
    return store


def _docs(doc_id, n):
    return [
        Document(page_content=f"{doc_id} chunk {i}", metadata={"chunk_index": i})
        for i in range(n)
    ]


class TestFaissDocIdIndex:
    """get_chunks_by_doc goes through the lazy doc_id index — must stay correct
    across add / delete / re-add / metadata update."""

    def test_add_then_get(self, faiss_store):
        faiss_store.add_documents(_docs("a", 3), doc_id="a")
        faiss_store.add_documents(_docs("b", 2), doc_id="b")
        chunks = faiss_store.get_chunks_by_doc("a")
        assert [c.metadata["chunk_index"] for c in chunks] == [0, 1, 2]
        assert all(c.metadata["doc_id"] == "a" for c in chunks)

    def test_chunk_indices_filter(self, faiss_store):
        faiss_store.add_documents(_docs("a", 4), doc_id="a")
        chunks = faiss_store.get_chunks_by_doc("a", chunk_indices=[1, 3])
        assert [c.metadata["chunk_index"] for c in chunks] == [1, 3]

    def test_delete_invalidates(self, faiss_store):
        faiss_store.add_documents(_docs("a", 3), doc_id="a")
        faiss_store.add_documents(_docs("b", 2), doc_id="b")
        faiss_store.get_chunks_by_doc("a")  # build the index
        faiss_store.delete_document("a")
        assert faiss_store.get_chunks_by_doc("a") == []
        assert len(faiss_store.get_chunks_by_doc("b")) == 2

    def test_readd_after_delete(self, faiss_store):
        faiss_store.add_documents(_docs("a", 2), doc_id="a")
        faiss_store.get_chunks_by_doc("a")
        faiss_store.delete_document("a")
        faiss_store.add_documents(_docs("a", 5), doc_id="a")
        assert len(faiss_store.get_chunks_by_doc("a")) == 5

    def test_metadata_update_via_index(self, faiss_store):
        faiss_store.add_documents(_docs("a", 2), doc_id="a")
        faiss_store.get_chunks_by_doc("a")  # index built before the update
        faiss_store.update_document_metadata("a", {"primary_category": "legal"})
        chunks = faiss_store.get_chunks_by_doc("a")
        assert all(c.metadata["primary_category"] == "legal" for c in chunks)


# ---------------------------------------------------------------------------
# retrieve_and_rank harness (offline, mirrors tests/test_search_endpoint.py)
# ---------------------------------------------------------------------------

def _settings(**overrides):
    s = MagicMock()
    s.router_enabled = False
    s.router_min_scope = 15
    s.router_max_scope = 300
    s.router_top_k = 8
    s.hybrid_search_enabled = False
    s.rrf_k = 60
    s.rerank_enabled = False
    s.query_expansion_enabled = False
    s.visual_proximity_enabled = False
    s.web_search_enabled = True
    s.web_search_score_threshold = 0.0
    s.anonymization_enabled = False
    s.per_doc_coverage_max_backfill = 30
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
    for key, value in overrides.items():
        setattr(s, key, value)
    return s


def _deps(search_results, all_docs=None):
    vector_store = MagicMock()
    vector_store.similarity_search_with_scores = MagicMock(
        side_effect=lambda question, k, doc_ids=None: list(search_results)
    )
    vector_store.get_all_documents = MagicMock(return_value=list(all_docs or []))
    vector_store.get_chunks_by_doc = MagicMock(return_value=[])
    llm = AsyncMock()
    llm.ainvoke = AsyncMock(
        return_value=AIMessage(content='{"types": ["exploratory"], "label": null}')
    )
    edge_repo = AsyncMock()
    edge_repo.get_edge_type_counts_batch = AsyncMock(return_value={})
    edge_repo.get_edges_from = AsyncMock(return_value=[])
    return vector_store, llm, edge_repo


def _chunk(doc_id, idx, text=None):
    return Document(
        page_content=text or f"{doc_id} chunk {idx}",
        metadata={"doc_id": doc_id, "chunk_index": idx, "source_file": f"{doc_id}.txt"},
    )


async def _run(settings, vector_store, llm, edge_repo, *, doc_ids=None,
               user_scoped=False, registry=None, ensure_coverage=True):
    from app.services import retrieval as retrieval_mod
    return await retrieval_mod.retrieve_and_rank(
        question="what does the corpus say about topic x",
        top_k=4,
        doc_ids=doc_ids,
        user_scoped=user_scoped,
        llm=llm,
        vector_store=vector_store,
        embeddings=MagicMock(),
        edge_repo=edge_repo,
        settings=settings,
        force_corpus_only=True,
        registry=registry,
        ensure_coverage=ensure_coverage,
    )


@pytest.mark.asyncio
class TestBM25ScopeCache:
    async def test_cache_hit_skips_corpus_fetch(self):
        from app.rag.chain import invalidate_bm25_cache
        invalidate_bm25_cache()

        scope = ["d1", "d2"]
        corpus = [_chunk("d1", 0), _chunk("d1", 1), _chunk("d2", 0), _chunk("d3", 0)]
        settings = _settings(hybrid_search_enabled=True)
        vector_store, llm, edge_repo = _deps([( _chunk("d1", 0), 0.8)], all_docs=corpus)

        await _run(settings, vector_store, llm, edge_repo, doc_ids=scope)
        assert vector_store.get_all_documents.call_count == 1

        # same scope again -> cache hit, corpus NOT re-materialized
        await _run(settings, vector_store, llm, edge_repo, doc_ids=scope)
        assert vector_store.get_all_documents.call_count == 1

        # different scope -> rebuild
        await _run(settings, vector_store, llm, edge_repo, doc_ids=["d1"])
        assert vector_store.get_all_documents.call_count == 2

        invalidate_bm25_cache()

    async def test_invalidation_forces_rebuild(self):
        from app.rag.chain import invalidate_bm25_cache
        invalidate_bm25_cache()

        scope = ["d1"]
        corpus = [_chunk("d1", 0)]
        settings = _settings(hybrid_search_enabled=True)
        vector_store, llm, edge_repo = _deps([(_chunk("d1", 0), 0.8)], all_docs=corpus)

        await _run(settings, vector_store, llm, edge_repo, doc_ids=scope)
        invalidate_bm25_cache()  # what documents.py calls on add/delete
        await _run(settings, vector_store, llm, edge_repo, doc_ids=scope)
        assert vector_store.get_all_documents.call_count == 2

        invalidate_bm25_cache()


@pytest.mark.asyncio
class TestSearchCoverageSkip:
    async def test_ensure_coverage_false_skips_backfill(self):
        settings = _settings()
        vector_store, llm, edge_repo = _deps([(_chunk("d1", 0), 0.9)])
        result = await _run(
            settings, vector_store, llm, edge_repo,
            doc_ids=["d1", "d2"], user_scoped=True, ensure_coverage=False,
        )
        vector_store.get_chunks_by_doc.assert_not_called()
        assert {s.doc_id for s in result.sources} == {"d1"}

    async def test_ensure_coverage_true_backfills_missing_doc(self):
        settings = _settings()
        vector_store, llm, edge_repo = _deps([(_chunk("d1", 0), 0.9)])
        vector_store.get_chunks_by_doc = MagicMock(return_value=[_chunk("d2", 0)])
        result = await _run(
            settings, vector_store, llm, edge_repo,
            doc_ids=["d1", "d2"], user_scoped=True, ensure_coverage=True,
        )
        vector_store.get_chunks_by_doc.assert_called_with("d2")
        assert {s.doc_id for s in result.sources} == {"d1", "d2"}


@pytest.mark.asyncio
class TestRouterMaxScope:
    async def test_scope_above_cap_skips_router(self, monkeypatch):
        import app.services.router as router_mod
        route_mock = AsyncMock(return_value=["d1"])
        monkeypatch.setattr(router_mod, "route_docs", route_mock)

        settings = _settings(router_enabled=True, router_max_scope=300)
        big_scope = [f"d{i}" for i in range(400)]
        vector_store, llm, edge_repo = _deps([(_chunk("d1", 0), 0.9)])
        await _run(
            settings, vector_store, llm, edge_repo,
            doc_ids=big_scope, registry=AsyncMock(),
        )
        route_mock.assert_not_called()

    async def test_scope_within_range_uses_router(self, monkeypatch):
        import app.services.router as router_mod
        route_mock = AsyncMock(return_value=["d1"])
        monkeypatch.setattr(router_mod, "route_docs", route_mock)

        settings = _settings(router_enabled=True, router_max_scope=300)
        scope = [f"d{i}" for i in range(20)]
        vector_store, llm, edge_repo = _deps([(_chunk("d1", 0), 0.9)])
        await _run(
            settings, vector_store, llm, edge_repo,
            doc_ids=scope, registry=AsyncMock(),
        )
        route_mock.assert_called_once()
