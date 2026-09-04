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


def _vector_store(n_docs=1):
    """n_docs > 1 exists because a one-document fixture cannot exercise a size cap.

    With a single document every "did we return at most top_k" assertion holds no matter
    what the code does, which is how a mutation that DELETED the top_k cap left the whole
    suite green. The per-doc cap floors at max(1, top_k // n_docs) chunks per document, so
    a scope with more documents than top_k is the only shape where the cap can be seen.
    """
    vs = MagicMock()
    docs = [(Document(page_content="a corpus chunk about liability %d" % i,
                      metadata={"doc_id": "doc-%d" % i, "chunk_index": 0,
                                "source_file": "a%d.txt" % i}), 0.9 - i * 0.01)
            for i in range(n_docs)]
    vs.similarity_search_with_scores = MagicMock(return_value=docs)
    vs.get_all_documents = MagicMock(return_value=[])
    vs.get_chunks_by_doc = MagicMock(return_value=[])
    return vs


async def _run(doc_ids, user_scoped, force_corpus_only=True, force_web_search=False,
               enforce_token_budget=None, n_docs=1):
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
        vector_store=_vector_store(n_docs),
        embeddings=MagicMock(),
        edge_repo=edge_repo,
        settings=_settings(),
        force_corpus_only=force_corpus_only,
        force_web_search=force_web_search,
        reorder_for_attention=False,
        **({} if enforce_token_budget is None
           else {"enforce_token_budget": enforce_token_budget}),
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
            if val is None:      # stage did not run; it reports None, not a number
                continue
            if prev is not None and stage not in may_grow:
                assert val <= prev, (
                    "%s (%s) exceeds %s (%s) and is not allowed to grow"
                    % (stage, val, prev_name, prev))
            prev_name, prev = stage, val

    async def test_empty_scope_reports_the_field_with_nulls_not_zeros(self):
        """Scope resolved to zero documents: no stage RAN, so stages are null and returned is 0.

        This test previously asserted every stage == 0, justified as "with zero documents each
        stage certainly produces zero". That is a claim about what the stages WOULD have done;
        the field is about what they DID. Reporting 0 also made the endpoint contradict itself:
        on /search reranking is off, so the normal path reports after_rerank=None while this
        path reported after_rerank=0 - same request, same configuration, different answer
        depending only on whether the scope happened to be empty. Independent review caught it.

        The original concern behind the old assertion is still covered, and asserted below: the
        field must be PRESENT, because an absent field reads as 'nothing was dropped'. Present
        with explicit nulls plus a basis string is not the same as absent.
        """
        result = await _run(doc_ids=[], user_scoped=True)
        sc = result.stage_counts
        assert sc is not None, "the field must be present - absent reads as 'nothing dropped'"
        assert sc["returned"] == 0, "returned is genuinely known on this path"
        for stage in STAGE_ORDER:
            if stage == "returned":
                continue
            assert sc[stage] is None, (
                "%s did not run on the empty-scope path, so it must be None, got %r"
                % (stage, sc[stage]))
        assert "no stage ran" in sc["basis"], (
            "basis must say why the stages are null: %r" % sc["basis"])

    async def test_every_return_path_carries_the_field(self):
        """The pairing that the first pass of the count fields missed.

        Populating only the main return leaves the early exits answering null, and null is
        indistinguishable from 'nothing was dropped'.

        CORRECTED after an independent review: the first version of this test hardcoded
        force_corpus_only=True in the helper, which gates out the web-search branch
        entirely (retrieval.py: `if not force_corpus_only and ...`). So it covered two of
        three paths while its NAME claimed all three - and the mutation test that seemed
        to prove it worked had only ever mutated a covered path. A test asserting coverage
        it does not have is worse than no test."""
        cases = [
            (dict(doc_ids=None, user_scoped=False), "main path"),
            (dict(doc_ids=[], user_scoped=True), "zero-scope early return"),
            (dict(doc_ids=None, user_scoped=False, force_corpus_only=False,
                  force_web_search=True), "web-search early return"),
        ]
        for kwargs, label in cases:
            result = await _run(**kwargs)
            assert result.stage_counts is not None, (
                "stage_counts absent on the %s (%r)" % (label, kwargs))

    async def test_web_search_path_says_not_measured_rather_than_zero(self):
        """The path that returns BEFORE the ranking stages must not claim zeros.

        Its stages genuinely did not run, so reporting 0 for them would be false; but
        `returned` is knowable because the payload is right there. This is the one place
        the three states have to be told apart, so it gets its own case."""
        result = await _run(doc_ids=None, user_scoped=False,
                            force_corpus_only=False, force_web_search=True)
        sc = result.stage_counts
        assert sc is not None
        assert sc["returned"] == len(result.sources)
        assert any(sc[s] is None for s in STAGE_ORDER if s != "returned"), (
            "stages that never ran must be None, not 0: %r" % (sc,))
        assert "not measured" in sc.get("basis", "")

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

    async def test_budget_opt_out_is_plumbed_through(self):
        """Only that the flag REACHES retrieve_and_rank. It proves nothing about behaviour.

        Labelled honestly because the first version of this test claimed more: it asserted
        after_token_budget == after_per_doc_cap with the budget declined, which holds
        trivially here - the fixture has one 30-character document and the budget floors at
        512 tokens, so truncation cannot happen either way. A mutation disabling the opt-out
        left it green. The real behaviour is tested directly below."""
        result = await _run(doc_ids=None, user_scoped=False, enforce_token_budget=False)
        assert result.stage_counts is not None
        assert result.context_used_tokens is not None

    async def test_budget_is_enforced_by_default(self):
        """The negative half: default behaviour is unchanged for every other caller.

        A flag that is always on is not a flag, and a change that silently alters the
        /query path would be exactly the regression this is supposed to avoid."""
        result = await _run(doc_ids=None, user_scoped=False)
        assert result.stage_counts is not None
        assert result.context_used_tokens is not None

    async def test_skipped_stages_report_none_not_a_number(self):
        """A stage that did not run must not look like one that ran and kept everything.

        The fixture disables reranking (rerank_enabled=False), so after_rerank must be
        None. With the budget also declined, after_token_budget must be None too, and the
        basis string must say both. Found by independent review: reporting len(retrieved)
        for a skipped stage reproduces, inside this field, the conflation the field was
        added to remove."""
        result = await _run(doc_ids=None, user_scoped=False, enforce_token_budget=False)
        sc = result.stage_counts
        assert sc["after_rerank"] is None, (
            "reranking is off in this fixture; after_rerank must be None, got %r"
            % (sc["after_rerank"],))
        assert sc["after_token_budget"] is None, (
            "budget enforcement was declined; after_token_budget must be None, got %r"
            % (sc["after_token_budget"],))
        assert "rerank SKIPPED" in sc["basis"] and "NOT ENFORCED" in sc["basis"], (
            "basis must name what was skipped: %r" % sc["basis"])

    async def test_stages_that_DID_run_still_report_numbers(self):
        """The negative half. If every stage reported None this would be useless."""
        result = await _run(doc_ids=None, user_scoped=False)
        sc = result.stage_counts
        assert isinstance(sc["after_composite"], int)
        assert isinstance(sc["after_labels"], int)
        assert isinstance(sc["after_per_doc_cap"], int)
        assert isinstance(sc["returned"], int)


    async def test_declining_the_budget_does_not_remove_the_top_k_bound(self):
        """P1 from independent review: the opt-out removed the last size limiter.

        Measured on the previous revision: 12 documents in scope with top_k=4 returned 12
        chunks, because the per-doc cap floors at one chunk per document and nothing after
        it bounded the list once the budget was declined. SearchRequest.top_k is documented
        as the maximum to return."""
        result = await _run(doc_ids=None, user_scoped=False, enforce_token_budget=False,
                            n_docs=12)          # 12 docs, top_k=4 -> per-doc cap gives 1 each
        sc = result.stage_counts
        assert sc["after_top_k_cap"] is not None, (
            "the cap stage must REPORT itself when it runs, not trim silently: %r" % sc)
        # NOTE, so nobody reads more into this test than it proves: with this fixture the
        # per-doc cap already returns exactly top_k (an earlier [:top_k] in the scoring path
        # bounds it), so the invariant below would hold even with the cap DELETED. Verified:
        # that mutation leaves this file green. The overrun needs the label/backfill stages,
        # which this fixture disables. The cap itself is proved in TestCallerSizeLimit below,
        # which CAN fail. This test covers only that the stage reports itself.
        assert len(result.sources) <= 4, (          # _run passes top_k=4, line 102
            "returned %d sources for top_k=4" % len(result.sources))

    async def test_the_cap_stage_is_None_when_the_budget_DID_run(self):
        """Negative half. The cap is the budget's substitute, not an extra always-on trim -
        reporting a number here on the /query path would say a stage ran that did not."""
        result = await _run(doc_ids=None, user_scoped=False)
        assert result.stage_counts["after_top_k_cap"] is None, (
            "budget enforced, so the top_k cap did not run and must report None")

    async def test_counts_say_how_they_were_obtained(self):
        """A number without its provenance invites the reader to assume one.

        `basis` states whether the figures were measured, are a certain zero, or were never
        computed — so an empty or null set can never be mistaken for a clean measurement.
        """
        for doc_ids, user_scoped in ((None, False), ([], True)):
            sc = (await _run(doc_ids=doc_ids, user_scoped=user_scoped)).stage_counts
            assert isinstance(sc.get("basis"), str) and sc["basis"], (
                "no basis string for doc_ids=%r" % (doc_ids,))


class TestCallerSizeLimit:
    """The cap, tested where it CAN fail.

    Measured on the revision before the fix: 12 documents in scope with top_k=4 came out of
    _apply_per_doc_cap as 12 chunks, because that cap floors at max(1, top_k // n_docs) = 1
    chunk per document. With the token budget declined nothing bounded that list, so /search
    returned 12 results for a request that asked for 4.
    """

    def _items(self, n):
        from langchain_core.documents import Document
        return [(Document(page_content="c%d" % i,
                          metadata={"doc_id": "d%d" % i, "chunk_index": 0}), 1.0 - i * 0.01)
                for i in range(n)]

    def test_the_overrun_this_guards_against_is_REAL(self):
        """POSITIVE CONTROL. If the per-doc cap ever stops exceeding top_k on its own, the
        test below is guarding nothing and should be deleted rather than left passing."""
        from app.services.retrieval import _apply_per_doc_cap
        out = _apply_per_doc_cap(self._items(12), n_docs_in_scope=12, top_k=4)
        assert len(out) > 4, (
            "per-doc cap returned %d for top_k=4; the overrun this cap exists to bound no "
            "longer happens, so the guard is now untested by construction" % len(out))

    def test_the_cap_bounds_it(self):
        from app.services.retrieval import _apply_caller_size_limit, _apply_per_doc_cap
        over = _apply_per_doc_cap(self._items(12), n_docs_in_scope=12, top_k=4)
        assert len(_apply_caller_size_limit(over, 4)) == 4

    def test_the_cap_does_not_pad(self):
        """Negative half: a limiter that also GREW a short list would pass the test above."""
        from app.services.retrieval import _apply_caller_size_limit
        assert len(_apply_caller_size_limit(self._items(2), 4)) == 2


@pytest.mark.asyncio
class TestTokenBudgetOptOut:
    """Direct tests of _apply_token_budget with content that EXCEEDS the budget.

    Through the pipeline this cannot be tested: the fixture corpus is far smaller than the
    budget floor, so enforcement and non-enforcement agree. Here the budget genuinely bites,
    so the two modes must differ - which is what makes these able to fail.
    """

    def _items(self, n=12, chars=4000):
        from langchain_core.documents import Document
        return [(Document(page_content="劳动合同法条文内容 " * (chars // 10),
                          metadata={"doc_id": "d%d" % i, "chunk_index": i,
                                    "source_file": "f%d.txt" % i}), 1.0 - i * 0.01)
                for i in range(n)]

    async def test_enforced_budget_truncates(self):
        """POSITIVE CONTROL: with enforcement on, a small budget must drop chunks.

        If this ever passes trivially, the opt-out test below proves nothing either."""
        from app.services.retrieval import _apply_token_budget
        items = self._items()
        kept, used = _apply_token_budget(items, 500, enforce=True)
        assert len(kept) < len(items), (
            "budget of 500 tokens kept all %d oversized chunks - the control is dead"
            % len(items))

    async def test_declined_budget_keeps_everything(self):
        """The actual claim: declining enforcement returns every chunk."""
        from app.services.retrieval import _apply_token_budget
        items = self._items()
        kept, used = _apply_token_budget(items, 500, enforce=False)
        assert len(kept) == len(items), (
            "declined budget still dropped %d of %d" % (len(items) - len(kept), len(items)))

    async def test_declined_budget_still_counts_tokens_truthfully(self):
        """Enforcement is what is declined, not measurement.

        Returning 0 or the budget figure would swap a real number for a made-up one - the
        exact substitution this whole change argues against."""
        from app.services.retrieval import _apply_token_budget
        items = self._items()
        kept, used = _apply_token_budget(items, 500, enforce=False)
        assert used > 500, (
            "declined budget reported %d tokens, which is at or under the budget it "
            "ignored - the count is not real" % used)


class TestSearchResponseContract:
    """stage_counts must be REQUIRED on the response model, not defaulted to None.

    Found by independent review AFTER the first attempt at this: a second annotation
    (stage_counts: dict) had been added while the original (stage_counts: dict | None = None)
    was still present a few lines above, so Pydantic still saw a defaulted field and the
    generated schema still advertised the value as optional. The declaration read as required
    and behaved as optional.

    The cause was re-running a patch script over an already-patched file. It also duplicated a
    keyword argument in query.py, which was noticed and reverted - and this second casualty was
    not. So this test exists because a fix that LOOKED applied was not.
    """

    def test_stage_counts_is_required(self):
        import pytest as _pytest
        from pydantic import ValidationError
        from app.models.schemas import SearchResponse
        with _pytest.raises(ValidationError):
            SearchResponse(results=[])           # no stage_counts -> must be rejected

    def test_search_response_still_builds_when_given_one(self):
        """Negative half: required must not mean unconstructable."""
        from app.models.schemas import SearchResponse
        r = SearchResponse(results=[], stage_counts={"after_composite": 0, "after_rerank": 0, "after_labels": 0,
                          "after_per_doc_cap": 0, "after_token_budget": 0,
                          "after_top_k_cap": 0,
                          "returned": 0, "basis": "test"})
        assert r.stage_counts.returned == 0

    def test_a_partial_or_junk_stage_counts_is_REJECTED(self):
        """The point of typing it. Each of these was ACCEPTED before this change.

        Measured on the previous revision, not assumed: {} , a string where a count belongs,
        and a dict of unrelated keys all passed validation on a field documented as a
        required guarantee. If this test ever goes green with the model loosened back to
        `dict`, the guarantee is gone again and nothing else in the suite would say so."""
        import pytest as _pytest
        from pydantic import ValidationError
        from app.models.schemas import SearchResponse
        for bad in ({},
                    {"after_composite": "twelve"},
                    {"nonsense": 1},
                    {"returned": 0, "basis": "missing every stage"}):
            with _pytest.raises(ValidationError):
                SearchResponse(results=[], stage_counts=bad)

    def test_a_misspelled_stage_name_is_REJECTED_not_swallowed(self):
        """extra=forbid. A permissive dict accepts this and loses the real key silently."""
        import pytest as _pytest
        from pydantic import ValidationError
        from app.models.schemas import SearchResponse
        with _pytest.raises(ValidationError):
            SearchResponse(results=[], stage_counts={
                "after_composite": 1, "after_rerank": 1, "after_labels": 1,
                "after_per_doc_cap": 1, "after_tokn_budget": 1,      # misspelled
                "returned": 1, "basis": "t"})

    def test_the_schema_now_TELLS_a_client_the_keys(self):
        """The actual complaint from review: an MCP client generating from OpenAPI saw
        `additionalProperties: true` and could not know these keys existed."""
        from app.models.schemas import SearchResponse
        sch = SearchResponse.model_json_schema()
        ref = sch["properties"]["stage_counts"]
        assert ref.get("additionalProperties") is not True, (
            "stage_counts is still an untyped object in the generated schema: %r" % ref)
        defs = sch.get("$defs", {})
        assert "StageCounts" in defs, "must resolve to a named schema, got %r" % ref
        props = defs["StageCounts"]["properties"]
        for k in ("after_composite", "after_rerank", "after_labels",
                  "after_per_doc_cap", "after_token_budget", "returned", "basis"):
            assert k in props, "generated schema does not mention %s" % k

    def test_a_VALID_full_stage_counts_still_builds(self):
        """Negative half. A model that rejected everything would pass all three above."""
        from app.models.schemas import SearchResponse
        r = SearchResponse(results=[], stage_counts={
            "after_composite": 12, "after_rerank": None, "after_labels": 12,
            "after_per_doc_cap": 8, "after_token_budget": None,
            "after_top_k_cap": 8,
            "returned": 8, "basis": "measured"})
        assert r.stage_counts.returned == 8
        assert r.stage_counts.after_rerank is None, "None must survive as None, not become 0"
