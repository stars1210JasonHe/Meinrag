"""debug_target: per-stage rank of one known target (spec: Gauss 2026-10-26, "target trace").

What these tests must catch, each named by the failure it guards against:

  * the trace CHANGES what is returned (cell F) -- the diagnostic is worthless if switching
    it on alters the thing being diagnosed;
  * the trace reads a different list than the stage it claims to describe (cell E,
    reconciliation against stage_counts, an instrument this change did not write);
  * a stage silently missing from the output -- an omitted stage reads as "nothing happened
    there", which is the exact conflation the trace exists to remove;
  * "outside the scope" reported as "absent" (it is not a miss; the query could not return it);
  * an arm that never ran reported as "absent" (BM25 skipped by its gate is not BM25 missing).
"""
import copy

import pytest
from unittest.mock import AsyncMock

from langchain_core.documents import Document

from app.services.target_trace import STAGES, TargetTracer
from tests.test_stage_counts_reported import _StubLLM, _settings, _vector_store
from tests.test_search_endpoint import _upload_txt, search_app  # noqa: F401  (fixture)


def _d(doc_id, idx, score):
    return (Document(page_content="x", metadata={"doc_id": doc_id, "chunk_index": idx}), score)


# ---------------------------------------------------------------------------
# TargetTracer in isolation
# ---------------------------------------------------------------------------

class TestTracerUnit:
    def test_rank_by_score_on_a_copy(self):
        items = [_d("a", 0, 0.1), _d("t", 3, 0.9), _d("b", 0, 0.5)]
        before = list(items)
        tr = TargetTracer("t", 3)
        tr.check_scope(None)
        tr.record("arm_vector", items)
        e = tr.result()[STAGES.index("arm_vector")]
        assert (e["status"], e["rank"], e["list_len"], e["target_chunks"]) == ("present", 1, 3, 1)
        assert items == before, "record() must not reorder the pipeline's list"

    def test_list_order_rank(self):
        items = [_d("a", 0, 0.9), _d("t", 3, 0.1)]
        tr = TargetTracer("t", 3)
        tr.check_scope(None)
        tr.record("rerank_output", items, by_score=False)
        assert tr.result()[STAGES.index("rerank_output")]["rank"] == 2

    def test_bare_documents_are_accepted(self):
        """The BM25 arm returns Documents, not (Document, score) tuples."""
        tr = TargetTracer("t")
        tr.check_scope(None)
        tr.record("arm_bm25", [_d("a", 0, 0)[0], _d("t", 1, 0)[0]], by_score=False)
        assert tr.result()[STAGES.index("arm_bm25")]["rank"] == 2

    def test_document_level_counts_chunks_and_takes_best_rank(self):
        items = [_d("a", 0, 0.9), _d("t", 5, 0.8), _d("t", 2, 0.7)]
        tr = TargetTracer("t", None)
        tr.check_scope(None)
        tr.record("arm_vector", items)
        e = tr.result()[STAGES.index("arm_vector")]
        assert (e["rank"], e["target_chunks"]) == (2, 2)

    def test_chunk_level_does_not_match_a_sibling_chunk(self):
        tr = TargetTracer("t", 9)
        tr.check_scope(None)
        tr.record("arm_vector", [_d("t", 1, 0.9)])
        assert tr.result()[STAGES.index("arm_vector")]["status"] == "absent"

    def test_out_of_scope_never_says_absent(self):
        tr = TargetTracer("t")
        assert tr.check_scope(["a", "b"]) is True
        tr.record("arm_vector", [_d("a", 0, 0.9)])
        tr.skip("arm_bm25", "gate_skipped")
        out = tr.result()
        assert [e["stage"] for e in out] == list(STAGES)
        assert all(e["status"] == "out_of_scope" for e in out)

    def test_unrecorded_stage_is_visible_not_omitted(self):
        tr = TargetTracer("t")
        tr.check_scope(None)
        out = tr.result()
        assert [e["stage"] for e in out] == list(STAGES)
        assert out[1]["status"] == "not_run:untraced"

    def test_finish_fills_only_unrecorded_stages(self):
        tr = TargetTracer("t")
        tr.check_scope(None)
        tr.record("arm_vector", [_d("t", 0, 1.0)])
        tr.finish("web_search_path")
        out = {e["stage"]: e["status"] for e in tr.result()}
        assert out["arm_vector"] == "present"
        assert out["returned"] == "not_run:web_search_path"

    def test_replaced_status(self):
        tr = TargetTracer("t")
        tr.check_scope(None)
        tr.record("after_query_expansion", [_d("t", 0, 1.0)], replaced=True)
        e = tr.result()[STAGES.index("after_query_expansion")]
        assert e["status"] == "replaced" and e["rank"] == 1

    def test_never_writes_metadata(self):
        items = [_d("t", 0, 1.0)]
        items[0][0].metadata["_mandatory"] = True
        snapshot = copy.deepcopy(items[0][0].metadata)
        tr = TargetTracer("t")
        tr.check_scope(None)
        tr.record("after_coverage", items)
        assert items[0][0].metadata == snapshot
        assert "mandatory" in tr.result()[STAGES.index("after_coverage")]["note"]


# ---------------------------------------------------------------------------
# Through retrieve_and_rank
# ---------------------------------------------------------------------------

async def _run(settings=None, doc_ids=None, user_scoped=False, debug_target=None, n_docs=6,
               force_corpus_only=True, force_web_search=False, registry=None):
    from app.services import retrieval as retrieval_mod
    edge_repo = AsyncMock()
    edge_repo.get_edge_type_counts_batch = AsyncMock(return_value={})
    edge_repo.get_edges_from = AsyncMock(return_value=[])
    return await retrieval_mod.retrieve_and_rank(
        question="who is liable", top_k=4, doc_ids=doc_ids, user_scoped=user_scoped,
        llm=_StubLLM(), vector_store=_vector_store(n_docs), embeddings=AsyncMock(),
        edge_repo=edge_repo, settings=settings or _settings(),
        force_corpus_only=force_corpus_only, force_web_search=force_web_search,
        reorder_for_attention=False, enforce_token_budget=False,
        debug_target=debug_target, registry=registry,
    )


def _by_stage(result):
    return {e["stage"]: e for e in result.target_trace}


@pytest.mark.asyncio
class TestThroughPipeline:
    async def test_cell_F_results_identical_with_and_without_trace(self):
        plain = await _run()
        traced = await _run(debug_target={"doc_id": "doc-2", "chunk_index": None})
        assert plain.target_trace is None
        assert [s.model_dump() for s in traced.sources] == [s.model_dump() for s in plain.sources]
        assert traced.stage_counts == plain.stage_counts

    async def test_every_stage_once_in_order_and_none_untraced(self):
        r = await _run(debug_target={"doc_id": "doc-1", "chunk_index": None})
        assert [e["stage"] for e in r.target_trace] == list(STAGES)
        untraced = [e["stage"] for e in r.target_trace if e["status"] == "not_run:untraced"]
        assert untraced == [], "stages the main path never recorded: %s" % untraced

    async def test_cell_E_list_len_reconciles_with_stage_counts(self):
        r = await _run(debug_target={"doc_id": "doc-0", "chunk_index": None})
        t = _by_stage(r)
        pairs = {"after_composite": "after_composite", "rerank_output": "after_rerank",
                 "after_labels": "after_labels", "after_per_doc_cap": "after_per_doc_cap",
                 "after_top_k_cap": "after_top_k_cap", "after_token_budget": "after_token_budget"}
        checked = 0
        for stage, sc_key in pairs.items():
            if r.stage_counts[sc_key] is None:
                assert t[stage]["status"].startswith("not_run:"), stage
                continue
            assert t[stage]["list_len"] == r.stage_counts[sc_key], stage
            checked += 1
        assert checked >= 3, "reconciliation compared too few stages to mean anything"
        assert t["returned"]["list_len"] == r.stage_counts["returned"]

    async def test_target_that_is_returned_is_present_at_returned(self):
        r = await _run(debug_target={"doc_id": "doc-0", "chunk_index": 0})
        assert any(s.doc_id == "doc-0" for s in r.sources)
        assert _by_stage(r)["returned"]["status"] == "present"

    async def test_unknown_target_is_absent_at_every_stage_that_ran(self):
        r = await _run(debug_target={"doc_id": "no-such-doc", "chunk_index": None})
        ran = [e for e in r.target_trace[1:] if not e["status"].startswith("not_run:")]
        assert ran, "nothing ran, so this test would pass vacuously"
        assert all(e["status"] == "absent" for e in ran)

    async def test_cell_C_out_of_scope(self):
        r = await _run(doc_ids=["doc-0", "doc-1"], user_scoped=True,
                       debug_target={"doc_id": "doc-5", "chunk_index": None})
        assert all(e["status"] == "out_of_scope" for e in r.target_trace)

    async def test_zero_scope_early_return_is_out_of_scope(self):
        r = await _run(doc_ids=[], user_scoped=True,
                       debug_target={"doc_id": "doc-0", "chunk_index": None})
        assert len(r.target_trace) == len(STAGES)
        assert all(e["status"] == "out_of_scope" for e in r.target_trace)

    async def test_cell_D_bm25_gate_skip_is_not_run_not_absent(self):
        s = _settings()
        s.hybrid_search_enabled = True
        s.hybrid_max_scope_docs = 2
        ids = ["doc-%d" % i for i in range(6)]
        r = await _run(settings=s, doc_ids=ids, user_scoped=True,
                       debug_target={"doc_id": "doc-0", "chunk_index": None})
        assert _by_stage(r)["arm_bm25"]["status"] == "not_run:gate_skipped"

    async def test_bm25_unscoped_is_scope_unknown(self):
        s = _settings()
        s.hybrid_search_enabled = True
        s.hybrid_max_scope_docs = 4000
        r = await _run(settings=s, debug_target={"doc_id": "doc-0", "chunk_index": None})
        assert _by_stage(r)["arm_bm25"]["status"] == "not_run:scope_unknown"

    async def test_web_search_path_marks_the_rest_not_run(self):
        r = await _run(force_corpus_only=False, force_web_search=True,
                       debug_target={"doc_id": "doc-0", "chunk_index": None})
        t = _by_stage(r)
        assert r.web_search_needed
        assert t["web_search_gate"]["status"] == "present"
        assert t["returned"]["status"] == "not_run:web_search_path"

    async def test_rerank_stages_rank_by_list_order_and_reconcile(self, monkeypatch):
        from app.services import retrieval as retrieval_mod

        async def _reverse(retrieved, question, settings, llm=None, top_n=None):
            return list(reversed(retrieved))[:3], True

        monkeypatch.setattr(retrieval_mod, "_rerank_results", _reverse)
        s = _settings()
        s.rerank_enabled = True
        s.rerank_max_candidates = 80
        r = await _run(settings=s, debug_target={"doc_id": "doc-0", "chunk_index": None})
        t = _by_stage(r)
        assert t["rerank_input"]["status"] == "present"
        assert t["rerank_output"]["list_len"] == r.stage_counts["after_rerank"] == 3
        assert "input=" in t["rerank_output"]["note"] and "output=3" in t["rerank_output"]["note"]

    async def test_rerank_input_cap_that_cuts_the_target_reports_absent(self, monkeypatch):
        """Stage 15 exists for exactly this: present after composite, gone after the input cap.

        Added on review (Gauss): the other rerank test used rerank_max_candidates=80, so the
        target was always inside the cap and nothing could make rerank_input say absent.
        """
        from app.services import retrieval as retrieval_mod

        async def _keep(retrieved, question, settings, llm=None, top_n=None):
            return list(retrieved), True

        monkeypatch.setattr(retrieval_mod, "_rerank_results", _keep)
        s = _settings()
        s.rerank_enabled = True
        s.rerank_max_candidates = 2
        # doc-3, not the lowest-ranked doc-5: in this fixture the strategy step already cuts to
        # top_k=4, so doc-5 is gone by stage 8 and could not isolate the rerank input cap.
        r = await _run(settings=s, debug_target={"doc_id": "doc-3", "chunk_index": None})
        t = _by_stage(r)
        assert t["after_composite"]["status"] == "present"
        assert t["after_composite"]["rank"] > 2, "precondition: target must rank below the cap"
        assert t["rerank_input"]["status"] == "absent"
        assert t["rerank_input"]["list_len"] == 2

    async def test_cell_F_with_rerank_on(self, monkeypatch):
        """F again with the reranker running (a deterministic stub; the live one is an LLM)."""
        from app.services import retrieval as retrieval_mod

        async def _reverse(retrieved, question, settings, llm=None, top_n=None):
            return list(reversed(retrieved))[:3], True

        monkeypatch.setattr(retrieval_mod, "_rerank_results", _reverse)
        s = _settings()
        s.rerank_enabled = True
        s.rerank_max_candidates = 80
        plain = await _run(settings=s)
        traced = await _run(settings=s, debug_target={"doc_id": "doc-2", "chunk_index": None})
        assert [x.model_dump() for x in traced.sources] == [x.model_dump() for x in plain.sources]
        assert traced.stage_counts == plain.stage_counts

    async def test_router_removal_is_not_out_of_scope(self, monkeypatch):
        """Added on review (Gauss): stage 0 is the CALLER's scope. A target the router drops was
        removed mid-pipeline; reporting it out_of_scope would merge the two cases cell C separates."""
        import app.services.router as router_mod

        async def _drop_target(question, doc_ids, top_k, llm, registry):
            return [d for d in doc_ids if d != "doc-3"]

        monkeypatch.setattr(router_mod, "route_docs", _drop_target)
        s = _settings()
        s.router_enabled = True
        ids = ["doc-%d" % i for i in range(20)]
        r = await _run(settings=s, doc_ids=ids, user_scoped=True, registry=object(),
                       debug_target={"doc_id": "doc-3", "chunk_index": None})
        t = _by_stage(r)
        assert t["scope"]["status"] == "present"
        assert "router kept 19 of 20" in t["scope"]["note"]
        assert "REMOVED by the router" in t["scope"]["note"]
        assert not any(e["status"] == "out_of_scope" for e in r.target_trace)

    async def test_query_expansion_disabled_is_not_run(self):
        r = await _run(debug_target={"doc_id": "doc-0", "chunk_index": None})
        assert _by_stage(r)["after_query_expansion"]["status"] == "not_run:disabled"

    async def test_query_expansion_enabled_not_triggered_is_recorded(self):
        s = _settings()
        s.query_expansion_enabled = True
        s.query_expansion_score_threshold = 0.5  # stub scores are ~0.9: expansion not triggered
        r = await _run(settings=s, debug_target={"doc_id": "doc-0", "chunk_index": None})
        assert _by_stage(r)["after_query_expansion"]["status"] == "present"


# ---------------------------------------------------------------------------
# /search: the debug key appears only when asked for
# ---------------------------------------------------------------------------

class TestSearchRoute:
    def test_no_debug_target_no_key(self, search_app):  # noqa: F811
        _upload_txt(search_app, "memo.txt", "The mitochondria is the powerhouse of the cell. " * 20)
        data = search_app.post("/search", json={"query": "powerhouse of the cell"}).json()
        assert "target_trace" not in data

    def test_debug_target_returns_trace(self, search_app):  # noqa: F811
        doc = _upload_txt(search_app, "memo.txt", "The mitochondria is the powerhouse of the cell. " * 20)
        resp = search_app.post("/search", json={"query": "powerhouse of the cell",
                                                "debug_target": {"doc_id": doc}})
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert [e["stage"] for e in data["target_trace"]] == list(STAGES)
        assert "results" in data and "stage_counts" in data

    def test_debug_target_rejects_unknown_keys(self, search_app):  # noqa: F811
        resp = search_app.post("/search", json={"query": "q", "debug_target": {"doc": "x"}})
        assert resp.status_code == 422
