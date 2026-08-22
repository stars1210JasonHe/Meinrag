"""An explicitly scoped query whose scope resolves to zero documents must return zero results.

Regression for a defect measured on the live backend 2026-08-22: a nonexistent collection,
a nonexistent subtag, an AND of two subtags with an empty intersection, and an explicit list
of non-existent doc_ids each returned five unrelated documents instead of none.

`_resolve_doc_ids` was correct — it produced `[]` and set `user_scoped=True`. The loss
happened downstream, where `if not doc_ids` cannot tell "scoped to zero documents" from
"not scoped at all", so the query was answered from the whole corpus. The response was well
formed and carried no signal that the scope had been dropped, so a caller could not detect it.

The original review missed this because it only exercised scopes that MATCH something. Every
assertion below therefore comes in a pair: the guard must fire when the scope is empty, and
must NOT fire when it isn't. A test that only proves the first half is the test that let this
through.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult, ChatGeneration


class _CountingLLM(BaseChatModel):
    """Records whether the pipeline reached the LLM at all.

    The guard sits ahead of query analysis, so an empty scope must cost zero LLM calls —
    that is both the correctness signal and a real saving: the old path paid for an
    analysis call before searching a corpus it had been told not to search.
    """
    calls: int = 0

    @property
    def _llm_type(self):
        return "counting"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(
            message=AIMessage(content='{"types": ["exploratory"], "label": null}'))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(
            message=AIMessage(content='{"types": ["exploratory"], "label": null}'))])


def _settings():
    s = MagicMock()
    s.router_enabled = False
    s.router_min_scope = 15
    s.router_max_scope = 300
    s.router_top_k = 8
    s.hybrid_search_enabled = False
    s.hyde_enabled = False
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


def _vector_store():
    """Returns a corpus hit for ANY search, so a dropped scope is loudly visible:
    if the guard fails, results come back and the call counter is non-zero."""
    vs = MagicMock()
    doc = Document(page_content="unrelated corpus chunk",
                   metadata={"doc_id": "other-matter", "chunk_index": 0,
                             "source_file": "other.txt"})
    vs.similarity_search_with_scores = MagicMock(return_value=[(doc, 0.9)])
    vs.get_all_documents = MagicMock(return_value=[])
    vs.get_chunks_by_doc = MagicMock(return_value=[])
    return vs


async def _run(doc_ids, user_scoped, vs, llm):
    from app.services import retrieval as retrieval_mod
    edge_repo = AsyncMock()
    edge_repo.get_edge_type_counts_batch = AsyncMock(return_value={})
    edge_repo.get_edges_from = AsyncMock(return_value=[])
    return await retrieval_mod.retrieve_and_rank(
        question="who is liable",
        top_k=4,
        doc_ids=doc_ids,
        user_scoped=user_scoped,
        llm=llm,
        vector_store=vs,
        embeddings=MagicMock(),
        edge_repo=edge_repo,
        settings=_settings(),
        force_corpus_only=True,
        reorder_for_attention=False,
    )


@pytest.mark.asyncio
class TestEmptyScope:
    async def test_empty_scope_returns_nothing(self):
        """The failing case: scope requested, resolved to zero documents."""
        vs, llm = _vector_store(), _CountingLLM()
        result = await _run(doc_ids=[], user_scoped=True, vs=vs, llm=llm)
        assert result.sources == []
        assert result.retrieved == []

    async def test_empty_scope_never_searches_the_corpus(self):
        """Returning nothing is not enough — it must not have LOOKED either.

        A corpus-wide search that happens to be discarded still burns the query and
        would still leak through any future code path that reads `retrieved`.
        """
        vs, llm = _vector_store(), _CountingLLM()
        await _run(doc_ids=[], user_scoped=True, vs=vs, llm=llm)
        assert vs.similarity_search_with_scores.call_count == 0
        assert llm.calls == 0

    async def test_unscoped_query_still_runs(self):
        """Positive control: doc_ids=None means NO scope was requested, not an empty one.

        Without this the guard could be written as `if not doc_ids` and pass the two tests
        above while silently killing every unscoped query in the product.
        """
        vs, llm = _vector_store(), _CountingLLM()
        await _run(doc_ids=None, user_scoped=False, vs=vs, llm=llm)
        assert vs.similarity_search_with_scores.call_count > 0

    async def test_scoped_query_with_matches_still_runs(self):
        """Positive control: a scope that resolves to real documents must be unaffected."""
        vs, llm = _vector_store(), _CountingLLM()
        await _run(doc_ids=["other-matter"], user_scoped=True, vs=vs, llm=llm)
        assert vs.similarity_search_with_scores.call_count > 0

    async def test_none_doc_ids_with_user_scoped_still_runs(self):
        """The awkward cell: scope flag set but doc_ids is None.

        Reachable when user isolation is off and no collection was given. It means
        "unrestricted", so it must fall through — distinguishing None from [] is the
        whole point of the guard.
        """
        vs, llm = _vector_store(), _CountingLLM()
        await _run(doc_ids=None, user_scoped=True, vs=vs, llm=llm)
        assert vs.similarity_search_with_scores.call_count > 0


class _Req:
    """Minimal stand-in for QueryRequest/SearchRequest — only the scoping fields matter."""
    def __init__(self, doc_ids=None, collection=None, subtags=None):
        self.doc_ids = doc_ids
        self.collection = collection
        self.subtags = subtags or []


@pytest.mark.asyncio
class TestResolveDocIdsEmptyList:
    """The sibling defect, one layer up from the guard.

    `_resolve_doc_ids` used `elif doc_ids:` to decide whether the caller supplied ids.
    An explicitly supplied EMPTY list is falsy, so it fell to the else branch and was
    REPLACED with the user's entire corpus — the caller asked for no documents and the
    scope came back as everything. The guard in retrieve_and_rank cannot catch this
    because by then doc_ids is no longer empty.

    Found by the end-to-end acceptance suite AFTER the guard shipped: seven of eight
    cases passed and this one did not. Worth recording — the patch author (me) had
    already convinced himself the fix was complete.
    """

    async def _resolve(self, request, user_isolation="documents", user_docs=("a", "b", "c")):
        from app.routers import query as query_mod
        settings = MagicMock()
        settings.user_isolation = user_isolation
        registry = AsyncMock()
        registry.list_all = AsyncMock(return_value=[{"doc_id": d} for d in user_docs])
        registry.list_by_collection = AsyncMock(return_value=[{"doc_id": d} for d in user_docs])
        registry.list_by_subtag = AsyncMock(return_value=[])
        return await query_mod._resolve_doc_ids(request, settings, registry, "admin")

    async def test_explicit_empty_doc_ids_stays_empty(self):
        doc_ids, user_scoped = await self._resolve(_Req(doc_ids=[]))
        assert doc_ids == [], "an explicit empty scope must not be widened to the corpus"
        assert user_scoped is True

    async def test_explicit_empty_doc_ids_with_collection_stays_empty(self):
        doc_ids, _ = await self._resolve(_Req(doc_ids=[], collection="legal"))
        assert doc_ids == []

    async def test_none_doc_ids_still_means_whole_user_corpus(self):
        """Positive control: None is not [] — it must still widen to the user's documents."""
        doc_ids, _ = await self._resolve(_Req(doc_ids=None))
        assert sorted(doc_ids) == ["a", "b", "c"]

    async def test_nonempty_doc_ids_still_filtered_not_replaced(self):
        """Positive control: a real list is still intersected with the user's documents."""
        doc_ids, _ = await self._resolve(_Req(doc_ids=["a", "zzz-not-mine"]))
        assert doc_ids == ["a"]
