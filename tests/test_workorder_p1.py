"""P1 (ops work order 2026-07-10): query-honest scoring.

The constant-score bug: RRF merges replaced cosine with a rank ladder pinned
to 1.0, graph expansion injected chunks at static edge scores, and the final
sort discarded the cross-encoder's order — the same doc scored byte-identical
values for unrelated queries. These tests pin the fixes:

- true cosine carried as metadata['_query_sim'] through both merges
- BM25-only entrants floored at the weakest vector match
- penalties scale the carried value
- composite scoring reads the carried cosine, not the rank ladder
- graph-expanded chunks are parent x decay x edge (always < parent), never
  the raw static edge score (unless graph_expansion_score_mode='legacy')
- cross-encoder order survives as the final order (rerank_final_order)
- end-to-end: the same doc's displayed score tracks the query
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from app.services.retrieval import (
    _apply_composite_scoring,
    _apply_reference_penalty,
    _expand_via_edges,
    _rrf_merge_bm25,
    _rrf_merge_dual,
    _stamp_query_sim,
)


def _doc(doc_id, idx, **meta):
    return Document(
        page_content=f"{doc_id} chunk {idx}",
        metadata={"doc_id": doc_id, "chunk_index": idx, "source_file": f"{doc_id}.txt", **meta},
    )


class TestQuerySimCarry:
    def test_stamp_overwrites_stale_value(self):
        d = _doc("a", 0)
        _stamp_query_sim(d, 0.9, "raw")
        _stamp_query_sim(d, 0.2, "raw")  # next query, same shared object
        assert d.metadata["_query_sim"] == 0.2

    def test_dual_merge_keeps_raw_cosine_on_consensus(self):
        raw_doc = _doc("a", 0)
        _stamp_query_sim(raw_doc, 0.71, "raw")  # orchestrator stamp
        summary_doc = _doc("a", 0)  # same chunk found via summary index
        merged = _rrf_merge_dual([(raw_doc, 0.71)], [(summary_doc, 0.95)])
        assert len(merged) == 1
        doc, _ = merged[0]
        assert doc is raw_doc
        assert doc.metadata["_query_sim"] == 0.71
        assert doc.metadata["_sim_source"] == "raw"

    def test_dual_merge_stamps_summary_only(self):
        raw_doc = _doc("a", 0)
        _stamp_query_sim(raw_doc, 0.71, "raw")
        summary_only = _doc("b", 3)
        merged = _rrf_merge_dual([(raw_doc, 0.71)], [(summary_only, 0.88)])
        by_id = {d.metadata["doc_id"]: d for d, _ in merged}
        assert by_id["b"].metadata["_query_sim"] == 0.88
        assert by_id["b"].metadata["_sim_source"] == "summary"

    def test_bm25_only_gets_min_vector_floor(self):
        v1, v2 = _doc("a", 0), _doc("b", 0)
        _stamp_query_sim(v1, 0.8, "raw")
        _stamp_query_sim(v2, 0.35, "raw")
        bm25_only = _doc("c", 0)
        merged = _rrf_merge_bm25([(v1, 0.8), (v2, 0.35)], [bm25_only])
        by_id = {d.metadata["doc_id"]: d for d, _ in merged}
        assert by_id["c"].metadata["_query_sim"] == 0.35
        assert by_id["c"].metadata["_sim_source"] == "bm25_floor"
        # vector-found docs keep their own stamps
        assert by_id["a"].metadata["_query_sim"] == 0.8

    def test_reference_penalty_scales_query_sim(self):
        d = _doc("a", 0, section="references")
        _stamp_query_sim(d, 0.6, "raw")
        profile = MagicMock()
        profile.reference_penalty = 0.5
        out = _apply_reference_penalty([(d, 1.0)], profile)
        assert out[0][1] == 0.5
        assert d.metadata["_query_sim"] == 0.3


@pytest.mark.asyncio
class TestCompositeReadsQuerySim:
    async def _composite(self, doc, tuple_score):
        settings = MagicMock()
        settings.query_types_file = "data/query_types.json"
        profile = MagicMock()
        profile.edge_type_weights = {}
        profile.graph_normalization_factor = 5.0
        return await _apply_composite_scoring(
            [(doc, tuple_score)], None, "exploratory", settings, profile,
        )

    async def test_prefers_carried_cosine_over_rank_ladder(self):
        d = _doc("a", 0)
        _stamp_query_sim(d, 0.4, "raw")
        # tuple score 1.0 = the RRF max-normalized top — must NOT drive the composite
        rescored_low = await self._composite(d, 1.0)
        _stamp_query_sim(d, 0.8, "raw")
        rescored_high = await self._composite(d, 1.0)
        assert rescored_high[0][1] > rescored_low[0][1]

    async def test_fallback_to_tuple_score_when_unstamped(self):
        d = _doc("a", 0)  # no _query_sim key
        rescored = await self._composite(d, 0.5)
        d2 = _doc("a", 0)
        rescored2 = await self._composite(d2, 0.9)
        assert rescored2[0][1] > rescored[0][1]


@pytest.mark.asyncio
class TestGraphExpansionScores:
    async def _expand(self, parent_score, edge_score, mode):
        parent = _doc("a", 0)
        _stamp_query_sim(parent, parent_score, "raw")
        target = _doc("b", 7)
        edge_repo = AsyncMock()
        edge_repo.get_edges_from = AsyncMock(return_value=[{
            "target_doc_id": "b", "target_chunk_index": 7, "score": edge_score,
        }])
        vector_store = MagicMock()
        vector_store.get_chunks_by_doc = MagicMock(return_value=[target])
        profile = MagicMock()
        profile.graph_expansion_score_decay = 0.8
        out = await _expand_via_edges(
            [(parent, parent_score)], edge_repo, vector_store, profile,
            relations=["describes"], score_mode=mode,
        )
        expanded = [(d, s) for d, s in out if d.metadata["doc_id"] == "b"]
        return expanded[0]

    async def test_decay_mode_is_query_linked_and_below_parent(self):
        doc, score = await self._expand(0.5, 0.9, "decay")
        assert score == pytest.approx(0.5 * 0.8 * 0.9)
        assert score < 0.5
        assert doc.metadata["_query_sim"] == pytest.approx(0.5 * 0.8 * 0.9)
        assert doc.metadata["_sim_source"] == "graph_expand"

    async def test_decay_mode_unscored_edge(self):
        _, score = await self._expand(0.5, None, "decay")
        assert score == pytest.approx(0.5 * 0.8)

    async def test_even_perfect_edge_stays_below_parent(self):
        _, score = await self._expand(0.5, 1.0, "decay")
        assert score < 0.5

    async def test_legacy_mode_restores_static_edge_score(self):
        _, score = await self._expand(0.5, 0.9, "legacy")
        assert score == 0.9  # the constant-top-3 bug, behind the escape hatch


# ---------------------------------------------------------------------------
# Orchestrator-level: final order + score-varies-with-query
# (harness mirrors tests/test_search_endpoint.py)
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
    s.rerank_final_order = True
    s.rerank_max_candidates = 80
    s.graph_expansion_score_mode = "decay"
    s.retrieval_debug_trace = False
    s.query_expansion_enabled = False
    s.visual_proximity_enabled = False
    s.web_search_enabled = False
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


def _deps(score_by_question):
    """score_by_question: dict question -> list of (doc_id, chunk_index, cosine)."""
    vector_store = MagicMock()

    def _search(question, k, doc_ids=None):
        return [
            (_doc(did, idx), cos)
            for did, idx, cos in score_by_question.get(question, [])
        ]

    vector_store.similarity_search_with_scores = MagicMock(side_effect=_search)
    vector_store.get_all_documents = MagicMock(return_value=[])
    vector_store.get_chunks_by_doc = MagicMock(return_value=[])
    llm = AsyncMock()
    llm.ainvoke = AsyncMock(
        return_value=AIMessage(content='{"types": ["exploratory"], "label": null}')
    )
    edge_repo = AsyncMock()
    edge_repo.get_edge_type_counts_batch = AsyncMock(return_value={})
    edge_repo.get_edges_from = AsyncMock(return_value=[])
    return vector_store, llm, edge_repo


async def _run(question, settings, vector_store, llm, edge_repo,
               reorder_for_attention=False):
    from app.services import retrieval as retrieval_mod
    return await retrieval_mod.retrieve_and_rank(
        question=question,
        top_k=4,
        doc_ids=None,
        user_scoped=False,
        llm=llm,
        vector_store=vector_store,
        embeddings=MagicMock(),
        edge_repo=edge_repo,
        settings=settings,
        force_corpus_only=True,
        reorder_for_attention=reorder_for_attention,
    )


@pytest.mark.asyncio
class TestScoreVariesWithQuery:
    async def test_same_doc_different_queries_different_scores(self):
        """The P1 acceptance criterion, in miniature: the SAME chunk retrieved
        for two unrelated queries must show different scores when its actual
        similarity differs."""
        scores = {
            "query about topic one": [("hub", 0, 0.82)],
            "query about topic two": [("hub", 0, 0.31)],
        }
        settings = _settings()
        vector_store, llm, edge_repo = _deps(scores)
        r1 = await _run("query about topic one", settings, vector_store, llm, edge_repo)
        r2 = await _run("query about topic two", settings, vector_store, llm, edge_repo)
        s1 = r1.sources[0].score
        s2 = r2.sources[0].score
        assert s1 != s2
        assert s1 > s2


@pytest.mark.asyncio
class TestRerankFinalOrder:
    async def _run_with_fake_rerank(self, rerank_final_order, monkeypatch):
        from app.services import retrieval as retrieval_mod

        async def fake_rerank(retrieved, question, settings, llm, top_n=4):
            # (results, ran) - the second element tells the caller whether reranking
            # actually happened, so a failed reranker is not reported as a successful one.
            return list(reversed(retrieved)), True  # cross-encoder disagrees with composite

        monkeypatch.setattr(retrieval_mod, "_rerank_results", fake_rerank)
        scores = {"q": [("a", 0, 0.9), ("b", 0, 0.5), ("c", 0, 0.2)]}
        settings = _settings(rerank_enabled=True, rerank_final_order=rerank_final_order)
        vector_store, llm, edge_repo = _deps(scores)
        return await _run("q", settings, vector_store, llm, edge_repo)

    async def test_cross_encoder_order_is_final(self, monkeypatch):
        result = await self._run_with_fake_rerank(True, monkeypatch)
        order = [s.doc_id for s in result.sources]
        # composite order is a,b,c — the (mocked) cross-encoder reversed it and
        # that order must survive to the response...
        assert order[0] == "c"
        # ...while score VALUES stay composite (c is the weakest match)
        by_id = {s.doc_id: s.score for s in result.sources}
        assert by_id["a"] > by_id["c"]

    async def test_legacy_resort_restores_composite_order(self, monkeypatch):
        result = await self._run_with_fake_rerank(False, monkeypatch)
        order = [s.doc_id for s in result.sources]
        assert order == ["a", "b", "c"]


@pytest.mark.asyncio
class TestAttentionReorder:
    async def test_retrieve_only_keeps_pure_ranking(self):
        scores = {"q": [("a", 0, 0.9), ("b", 0, 0.5), ("c", 0, 0.2)]}
        settings = _settings()
        vector_store, llm, edge_repo = _deps(scores)
        result = await _run("q", settings, vector_store, llm, edge_repo,
                            reorder_for_attention=False)
        assert [s.doc_id for s in result.sources] == ["a", "b", "c"]

    async def test_llm_path_keeps_u_shape_placement(self):
        """Default (used by /query) puts second-best LAST — U-shape attention."""
        scores = {"q": [("a", 0, 0.9), ("b", 0, 0.5), ("c", 0, 0.2)]}
        settings = _settings()
        vector_store, llm, edge_repo = _deps(scores)
        result = await _run("q", settings, vector_store, llm, edge_repo,
                            reorder_for_attention=True)
        assert [s.doc_id for s in result.sources] == ["a", "c", "b"]


@pytest.mark.asyncio
class TestMandatoryLeakCleared:
    async def test_stale_mandatory_flag_does_not_survive(self):
        """FAISS shares Document objects across queries; a _mandatory flag from
        a previous query must be cleared when the chunk re-enters."""
        stale = _doc("a", 0, _mandatory=True)
        vector_store = MagicMock()
        vector_store.similarity_search_with_scores = MagicMock(
            return_value=[(stale, 0.7)]
        )
        vector_store.get_all_documents = MagicMock(return_value=[])
        vector_store.get_chunks_by_doc = MagicMock(return_value=[])
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(
            return_value=AIMessage(content='{"types": ["exploratory"], "label": null}')
        )
        edge_repo = AsyncMock()
        edge_repo.get_edge_type_counts_batch = AsyncMock(return_value={})
        edge_repo.get_edges_from = AsyncMock(return_value=[])
        await _run("q", _settings(), vector_store, llm, edge_repo)
        assert "_mandatory" not in stale.metadata
