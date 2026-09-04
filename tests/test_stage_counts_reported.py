"""Every /search response must say how many results each pipeline stage produced.

WHY THIS MATTERS BEYOND TELEMETRY
Measured on the live backend 2026-09-04: a request for top_k=20 came back with 5 results,
another with 10, another with 11 — from the same query. The chain is
`top_k -> fetch_k -> cap at rerank_max_candidates -> the LLM reranker returns a list of its
OWN length -> results[:top_n] -> per-doc cap -> token budget`, and none of those reductions
is visible to the caller. Nor is `total_available` the answer: it is sampled at step 13,
before the per-doc cap and the token budget run.

None of those stages is a bug. Each is deliberate. What is missing is that a caller receiving
8 results cannot tell whether the reranker dropped 3, the cap took 2, or the budget took 5.

For the lawyer using this corpus that distinction is not cosmetic. "Failed to retrieve" and
"searched and did not find" carry different evidentiary weight — the first is a limit on the
search, the second is a conclusion that can go in a filing. A silently truncated candidate
pool turns the second into the first with no signal.

WHY THE EARLY RETURNS GET THEIR OWN CASES
`retrieve_and_rank` returns in three places, and the first version of the count fields was
populated on only one of them — that is the defect the empty-scope work had to come back and
fix, one layer up, after an independent review found it. The same trap is open here, so every
case below is paired: the field must be right on the main path AND on each early return, and
it must never be absent, because an absent marker is read as "nothing was dropped".
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatResult, ChatGeneration

from app.services.retrieval import STAGE_ORDER


class _StubLLM(BaseChatModel):
    @property
    def _llm_type(self):
        return "stub"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(
            message=AIMessage(content='{"types": ["exploratory"], "label": null}'))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
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
    vs = MagicMock()
    doc = Document(page_content="a corpus chunk about liability",
                   metadata={"doc_id": "doc-1", "chunk_index": 0,
                             "source_file": "a.txt"})
    vs.similarity_search_with_scores = MagicMock(return_value=[(doc, 0.9)])
    vs.get_all_documents = MagicMock(return_value=[])
    vs.get_chunks_by_doc = MagicMock(return_value=[])
    return vs


async def _run(doc_ids, user_scoped):
    from app.services import retrieval as retrieval_mod
    edge_repo = AsyncMock()
    edge_repo.get_edge_type_counts_batch = AsyncMock(return_value={})
    edge_repo.get_edges_from = AsyncMock(return_value=[])
    return await retrieval_mod.retrieve_and_rank(
        question="who is liable",
        top_k=4,
        doc_ids=doc_ids,
        user_scoped=user_scoped,
        llm=_StubLLM(),
        vector_store=_vector_store(),
        embeddings=MagicMock(),
        edge_repo=edge_repo,
        settings=_settings(),
        force_corpus_only=True,
        reorder_for_attention=False,
    )


@pytest.mark.asyncio
class TestStageCounts:
    async def test_main_path_reports_every_stage(self):
        """The ordinary case: all stage names present, and `returned` matches the payload."""
        result = await _run(doc_ids=None, user_scoped=False)
        sc = result.stage_counts
        assert sc is not None
        for stage in STAGE_ORDER:
            assert stage in sc, "missing stage %r" % stage
        assert sc["returned"] == len(result.sources)

    async def test_counts_only_grow_where_the_pipeline_adds(self):
        """Non-increasing along the chain, except where step 13 prepends label chunks.

        Asserting a flat non-increasing chain would be wrong: `retrieved = label_results +
        retrieved` can legitimately make the count go UP at after_labels. A test that got
        that backwards would fail a correct implementation.
        """
        result = await _run(doc_ids=None, user_scoped=False)
        sc = result.stage_counts
        may_grow = {"after_labels"}
        prev_name, prev = None, None
        for stage in STAGE_ORDER:
            val = sc[stage]
            if prev is not None and stage not in may_grow:
                assert val <= prev, (
                    "%s (%s) exceeds %s (%s) and is not allowed to grow"
                    % (stage, val, prev_name, prev))
            prev_name, prev = stage, val

    async def test_empty_scope_reports_zero_not_absent(self):
        """Scope resolved to zero documents: the counts are KNOWN, so they are 0.

        Returning no field at all would be read as 'nothing was dropped', which is the
        failure this whole field exists to prevent.
        """
        result = await _run(doc_ids=[], user_scoped=True)
        sc = result.stage_counts
        assert sc is not None
        for stage in STAGE_ORDER:
            assert sc[stage] == 0, "%s should be a certain 0 on an empty scope" % stage

    async def test_every_return_path_carries_the_field(self):
        """The pairing that the first pass of the count fields missed.

        Populating only the main return leaves the early exits answering null, and null is
        indistinguishable from 'nothing was dropped'. Both scoped-to-nothing and the
        ordinary path must carry it.
        """
        for doc_ids, user_scoped in ((None, False), ([], True)):
            result = await _run(doc_ids=doc_ids, user_scoped=user_scoped)
            assert result.stage_counts is not None, (
                "stage_counts absent for doc_ids=%r user_scoped=%r" % (doc_ids, user_scoped))

    async def test_returned_is_never_null_when_the_payload_is_countable(self):
        """The returned count describes the response body, so it is knowable on EVERY path.

        Found by re-reading my own diff: the web-search early return handed back
        sources=[] while reporting returned=None. A caller would see zero results beside
        a null count -- the same conflation of "zero" and "unknown" this whole field
        exists to prevent, reproduced inside it. Stages that genuinely did not run stay
        None; the returned count does not, because the response itself demonstrates it.
        """
        for doc_ids, user_scoped in ((None, False), ([], True)):
            result = await _run(doc_ids=doc_ids, user_scoped=user_scoped)
            assert result.stage_counts["returned"] == len(result.sources), (
                "returned must match the payload for doc_ids=%r" % (doc_ids,))
            assert result.stage_counts["returned"] is not None

    async def test_counts_say_how_they_were_obtained(self):
        """A number without its provenance invites the reader to assume one.

        `basis` states whether the figures were measured, are a certain zero, or were never
        computed — so an empty or null set can never be mistaken for a clean measurement.
        """
        for doc_ids, user_scoped in ((None, False), ([], True)):
            sc = (await _run(doc_ids=doc_ids, user_scoped=user_scoped)).stage_counts
            assert isinstance(sc.get("basis"), str) and sc["basis"], (
                "no basis string for doc_ids=%r" % (doc_ids,))
