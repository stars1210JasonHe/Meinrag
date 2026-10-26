"""debug_target.rerank_variants / rerank_debug: the LLM reranker's own answer, recorded.

Runs the REAL LLMListwiseRerank (LangChain prompt, structured output, id->document mapping)
against a stub chat model that answers with a tool call, so what is tested is the path
production runs, not a re-implementation of it. Failures each test guards against:

  * the recorder changes what is returned (it is only worth anything if it does not);
  * the raw ids are lost when LangChain cannot map them (the not_run:failed cases);
  * text leaks into the record (it leaves a deployment that holds client material);
  * the shuffled variant is reported in shuffled positions, so its answers silently
    disagree with every other variant's index;
  * an ordinary request pays for any of this.
"""
import json

import pytest
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from app.services import rerank_recorder as rr

SECRET = "CONFIDENTIAL-CLIENT-TEXT"


class _ToolLLM(BaseChatModel):
    """Answers every call with RankDocuments(ranked_document_ids=<next item of answers>)."""

    answers: list = []
    calls: int = 0
    finish: str = "stop"

    @property
    def _llm_type(self):
        return "tool-stub"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        ids = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        msg = AIMessage(content="", tool_calls=[{"name": "RankDocuments", "args": {"ranked_document_ids": ids},
                                                 "id": "c%d" % self.calls}],
                        usage_metadata={"input_tokens": 100, "output_tokens": 7, "total_tokens": 107})
        return ChatResult(generations=[ChatGeneration(message=msg, generation_info={"finish_reason": self.finish})])


def _docs(n):
    return [Document(page_content="%s chunk %d" % (SECRET, i), metadata={"doc_id": "d%d" % i, "chunk_index": i})
            for i in range(n)]


def _compressor(llm, top_n=100):
    from langchain_classic.retrievers.document_compressors.listwise_rerank import LLMListwiseRerank
    return LLMListwiseRerank.from_llm(llm, top_n=top_n)


# ---------------------------------------------------------------------------
# raw id extraction
# ---------------------------------------------------------------------------

def test_ids_from_tool_call():
    assert rr._ids_from_message(AIMessage(content="", tool_calls=[
        {"name": "RankDocuments", "args": {"ranked_document_ids": [3, 1]}, "id": "x"}])) == ([3, 1], "tool_call")


def test_ids_from_json_content():
    assert rr._ids_from_message(AIMessage(content='{"ranked_document_ids": [2, 0]}')) == ([2, 0], "content_json")


def test_ids_not_found_is_not_an_empty_list():
    # "the model answered nothing" and "we could not read the answer" must stay distinguishable
    assert rr._ids_from_message(AIMessage(content="sorry")) == (None, "not_found")


# ---------------------------------------------------------------------------
# recorded_compress through the real LLMListwiseRerank
# ---------------------------------------------------------------------------

def test_records_raw_ids_out_idx_finish_and_usage():
    docs = _docs(8)
    rec = {}
    out = rr.recorded_compress(_compressor(_ToolLLM(answers=[[5, 0, 2, 7, 1]])), docs, "q",
                               provider="llm", llm=None, top_n=100, recorder=rec)
    assert [d.metadata["chunk_index"] for d in out] == [5, 0, 2, 7, 1]
    p = rec["primary"]
    assert p["raw_ids"] == [5, 0, 2, 7, 1] and p["out_idx"] == [5, 0, 2, 7, 1]
    assert p["finish_reason"] == "stop" and p["usage"] == {"input_tokens": 100, "output_tokens": 7}
    assert p["error"] is None and rec["input"][3] == ["d3", 3, len(docs[3].page_content)]


def test_out_of_range_id_keeps_raw_answer_and_still_raises():
    """The shape behind 3 not_run:failed per cohort: the model names an id LangChain cannot map."""
    rec = {}
    with pytest.raises(IndexError):
        rr.recorded_compress(_compressor(_ToolLLM(answers=[[1, 42]])), _docs(5), "q",
                             provider="llm", llm=None, top_n=100, recorder=rec)
    assert rec["primary"]["raw_ids"] == [1, 42]
    assert rec["primary"]["error"] == "IndexError" and rec["primary"]["out_idx"] is None


def test_record_contains_no_text():
    rec = {"want_variants": True}
    llm = _ToolLLM(answers=[[0, 1]])
    rr.recorded_compress(_compressor(llm), _docs(4), "query " + SECRET, provider="llm", llm=llm,
                         top_n=100, recorder=rec)
    blob = json.dumps(rec)
    assert SECRET not in blob and "query" not in blob
    assert "chunk" not in blob   # control: the text really was in the documents
    assert SECRET in _docs(1)[0].page_content


def test_variants_run_and_are_reported_on_the_original_index():
    docs = _docs(6)
    llm = _ToolLLM(answers=[[0, 1], [0, 1], list(range(6)), [0, 1]])
    rec = {"want_variants": True}
    rr.recorded_compress(_compressor(llm), docs, "q", provider="llm", llm=llm, top_n=100, recorder=rec)
    v = rec["variants"]
    assert llm.calls == 4                                   # primary + repeat + all_ids + shuffled
    assert v["repeat"]["out_idx"] == [0, 1]
    assert v["all_ids"]["out_idx"] == list(range(6))
    perm = v["shuffled"]["perm"]
    assert sorted(perm) == list(range(6)) and perm != list(range(6))   # it really was shuffled
    # the model picked shuffled positions 0 and 1 -> reported as the ORIGINAL positions there
    assert v["shuffled"]["out_idx"] == [perm[0], perm[1]]
    assert v["shuffled"]["raw_ids"] == [0, 1]               # the raw answer stays as the model wrote it


def test_variants_do_not_change_the_primary_result():
    docs = _docs(6)
    a = rr.recorded_compress(_compressor(_ToolLLM(answers=[[3, 2]])), docs, "q", provider="llm",
                             llm=None, top_n=100, recorder={})
    llm = _ToolLLM(answers=[[3, 2], [5], [0], [1]])
    b = rr.recorded_compress(_compressor(llm), docs, "q", provider="llm", llm=llm, top_n=100,
                             recorder={"want_variants": True})
    assert [id(d) for d in a] == [id(d) for d in b]


def test_variants_still_run_when_the_primary_call_fails():
    llm = _ToolLLM(answers=[[9], [0], [0], [0]])
    rec = {"want_variants": True}
    with pytest.raises(IndexError):
        rr.recorded_compress(_compressor(llm), _docs(3), "q", provider="llm", llm=llm, top_n=100, recorder=rec)
    assert rec["variants"]["repeat"]["out_idx"] == [0]


def test_variants_skipped_for_non_llm_provider():
    rec = {"want_variants": True}
    rr.recorded_compress(_compressor(_ToolLLM(answers=[[0]])), _docs(2), "q", provider="flashrank",
                         llm=_ToolLLM(answers=[[0]]), top_n=100, recorder=rec)
    assert rec["variants"] == {"skipped": "rerank_provider is not llm"}


# ---------------------------------------------------------------------------
# through _rerank_results and retrieve_and_rank
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_rerank_results_fills_recorder_and_falls_back_on_failure(monkeypatch):
    from app.rag import chain
    from app.services import retrieval
    from tests.test_stage_counts_reported import _settings
    llm = _ToolLLM(answers=[[1, 99]])
    monkeypatch.setattr(chain, "_get_reranker", lambda s, l, top_n_override=None: _compressor(llm))
    s = _settings()
    s.rerank_top_n = 4
    s.rerank_max_candidates = 80
    s.rerank_provider = "llm"
    retrieved = [(d, 1.0 - i / 10) for i, d in enumerate(_docs(4))]
    rec = {}
    out, ran = await retrieval._rerank_results(retrieved, "q", s, llm, top_n=4, recorder=rec)
    assert ran is False and out == retrieved                # unchanged fallback behaviour
    assert rec["primary"]["raw_ids"] == [1, 99] and rec["primary"]["error"] == "IndexError"


@pytest.mark.asyncio
async def test_no_debug_target_no_recorder(monkeypatch):
    from app.services import retrieval as retrieval_mod
    from tests.test_target_trace import _run
    seen = []

    async def _spy(retrieved, question, settings, llm=None, top_n=None, recorder=None):
        seen.append(recorder)
        return list(retrieved), True

    monkeypatch.setattr(retrieval_mod, "_rerank_results", _spy)
    from tests.test_stage_counts_reported import _settings
    s = _settings()
    s.rerank_enabled = True
    s.rerank_max_candidates = 80
    plain = await _run(settings=s)
    debug = await _run(settings=s, debug_target={"doc_id": "doc-0", "chunk_index": None, "rerank_variants": True})
    assert seen == [None, {"want_variants": True}]
    assert plain.rerank_debug is None and debug.rerank_debug == {"want_variants": True}
    assert plain.sources and [c.model_dump() for c in plain.sources] == [c.model_dump() for c in debug.sources]


class TestSearchRoute:
    def test_no_debug_target_no_key(self, search_app):  # noqa: F811
        from tests.test_search_endpoint import _upload_txt
        _upload_txt(search_app, "memo.txt", "The mitochondria is the powerhouse of the cell. " * 20)
        data = search_app.post("/search", json={"query": "powerhouse of the cell"}).json()
        assert "rerank_debug" not in data

    def test_debug_target_carries_rerank_debug(self, search_app):  # noqa: F811
        from tests.test_search_endpoint import _upload_txt
        doc = _upload_txt(search_app, "memo.txt", "The mitochondria is the powerhouse of the cell. " * 20)
        resp = search_app.post("/search", json={"query": "powerhouse of the cell",
                                                "debug_target": {"doc_id": doc, "rerank_variants": True}})
        assert resp.status_code == 200, resp.text
        assert resp.json()["rerank_debug"]["want_variants"] is True


from tests.test_search_endpoint import search_app  # noqa: E402,F401  (fixture)
