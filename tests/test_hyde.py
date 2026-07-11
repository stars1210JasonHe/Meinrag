"""HyDE retrieval probe (P6 recall lever, 2026-07-11).

Colloquial/narrative queries (case descriptions) sit far from formal corpus
text in embedding space — target docs never reach the candidate pool. HyDE
embeds an LLM-written hypothetical answer document as a SECOND retrieval
probe, RRF-fused with the direct results so a bad hypothesis can only add
candidates, never evict direct hits. Off by default (HYDE_ENABLED).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult, ChatGeneration


HYPO_TEXT = (
    "本院经审理查明：涉案房屋因市政建设需要被征收，行政机关作出补偿决定，"
    "当事人对补偿标准与安置方式提出异议,遂提起行政诉讼。"
)


def _doc(doc_id, idx):
    return Document(
        page_content=f"{doc_id} chunk {idx}",
        metadata={"doc_id": doc_id, "chunk_index": idx, "source_file": f"{doc_id}.txt"},
    )


def _settings(hyde_enabled):
    s = MagicMock()
    s.router_enabled = False
    s.router_min_scope = 15
    s.router_max_scope = 300
    s.router_top_k = 8
    s.hybrid_search_enabled = False
    s.hyde_enabled = hyde_enabled
    s.rrf_k = 60
    s.rerank_enabled = False
    s.rerank_final_order = True
    s.graph_expansion_score_mode = "decay"
    s.retrieval_debug_trace = False
    s.query_expansion_enabled = False
    s.visual_proximity_enabled = False
    s.web_search_enabled = False
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
    return s


class _FakeLLM(BaseChatModel):
    """Real BaseChatModel (LCEL chains need a Runnable, not a mock): the HyDE
    prompt gets the hypo passage, everything else gets query-analysis JSON."""
    hyde_response: str = HYPO_TEXT
    hyde_error: bool = False

    @property
    def _llm_type(self):
        return "fake"

    def _pick(self, messages):
        text = " ".join(
            (m.content if hasattr(m, "content") else str(m))
            for m in (messages if isinstance(messages, list) else [messages])
        )
        if "HYPOTHETICAL" in text:
            if self.hyde_error:
                raise RuntimeError("llm down")
            return self.hyde_response
        return '{"types": ["exploratory"], "label": null}'

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self._pick(messages)))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self._pick(messages)))])


def _llm(hyde_response=HYPO_TEXT, hyde_error=False):
    return _FakeLLM(hyde_response=hyde_response, hyde_error=hyde_error)


def _vector_store(direct_hits, hyde_hits):
    """Direct query returns direct_hits; the hypo-passage probe returns hyde_hits."""
    vector_store = MagicMock()

    def _search(question, k, doc_ids=None):
        if question == HYPO_TEXT:
            return list(hyde_hits)
        return list(direct_hits)

    vector_store.similarity_search_with_scores = MagicMock(side_effect=_search)
    vector_store.get_all_documents = MagicMock(return_value=[])
    vector_store.get_chunks_by_doc = MagicMock(return_value=[])
    return vector_store


async def _run(settings, vector_store, llm):
    from app.services import retrieval as retrieval_mod
    edge_repo = AsyncMock()
    edge_repo.get_edge_type_counts_batch = AsyncMock(return_value={})
    edge_repo.get_edges_from = AsyncMock(return_value=[])
    return await retrieval_mod.retrieve_and_rank(
        question="房子被征收了补偿太低怎么起诉",
        top_k=4,
        doc_ids=None,
        user_scoped=False,
        llm=llm,
        vector_store=vector_store,
        embeddings=MagicMock(),
        edge_repo=edge_repo,
        settings=settings,
        force_corpus_only=True,
        reorder_for_attention=False,
    )


@pytest.mark.asyncio
class TestHyde:
    async def test_disabled_by_default_single_search(self):
        vs = _vector_store([(_doc("direct", 0), 0.6)], [(_doc("hyde-found", 0), 0.8)])
        result = await _run(_settings(hyde_enabled=False), vs, _llm())
        assert vs.similarity_search_with_scores.call_count == 1
        assert {s.doc_id for s in result.sources} == {"direct"}

    async def test_enabled_probe_adds_recall_misses(self):
        """The P6 Q1/Q3 shape: the target doc only surfaces via the hypo probe."""
        hyde_only = _doc("hyde-found", 0)
        vs = _vector_store([(_doc("direct", 0), 0.6)], [(hyde_only, 0.8)])
        result = await _run(_settings(hyde_enabled=True), vs, _llm())
        assert vs.similarity_search_with_scores.call_count == 2
        # second search used the hypothetical passage, not the raw query
        assert vs.similarity_search_with_scores.call_args_list[1].args[0] == HYPO_TEXT
        assert {s.doc_id for s in result.sources} == {"direct", "hyde-found"}
        # provenance: probe-found chunk carries its probe cosine, labeled hyde
        assert hyde_only.metadata["_sim_source"] == "hyde"
        assert hyde_only.metadata["_query_sim"] == 0.8

    async def test_consensus_keeps_direct_hit_identity(self):
        """Doc found by BOTH probes: direct object (and its raw stamp) wins."""
        direct = _doc("both", 0)
        via_hyde = _doc("both", 0)
        vs = _vector_store([(direct, 0.55)], [(via_hyde, 0.9)])
        result = await _run(_settings(hyde_enabled=True), vs, _llm())
        assert [s.doc_id for s in result.sources] == ["both"]
        assert direct.metadata["_sim_source"] == "raw"
        assert direct.metadata["_query_sim"] == 0.55

    async def test_degenerate_hypothesis_skips_probe(self):
        vs = _vector_store([(_doc("direct", 0), 0.6)], [(_doc("hyde-found", 0), 0.8)])
        result = await _run(_settings(hyde_enabled=True), vs, _llm(hyde_response="嗯。"))
        assert vs.similarity_search_with_scores.call_count == 1
        assert {s.doc_id for s in result.sources} == {"direct"}

    async def test_llm_failure_is_nonfatal(self):
        vs = _vector_store([(_doc("direct", 0), 0.6)], [])
        result = await _run(_settings(hyde_enabled=True), vs, _llm(hyde_error=True))
        assert {s.doc_id for s in result.sources} == {"direct"}
