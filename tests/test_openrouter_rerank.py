"""rerank_provider=openrouter: request shape, result mapping, and loud failure (never a silent original order)."""
import json

import httpx
import pytest
from langchain_core.documents import Document

from app.config import Settings


def _docs(n=3, text=None):
    return [Document(page_content=text or "chunk %d" % i, metadata={"doc_id": "d%d" % i, "chunk_index": i})
            for i in range(n)]


def _compressor(handler, **kw):
    from app.rag.openrouter_rerank import OpenRouterRerank
    args = {"model": "voyageai/rerank-3", "api_key": "test-key", "top_n": 10,
            "transport": httpx.MockTransport(handler)}
    args.update(kw)
    return OpenRouterRerank(**args)


def _ok(results, **extra):
    body = {"results": results, "provider": "VoyageAI", "model": "voyageai/rerank-3",
            "usage": {"cost": 0.0001, "total_tokens": 42}}
    body.update(extra)
    return lambda request: httpx.Response(200, json=body)


class TestRequest:
    def test_payload_and_auth(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["auth"] = request.headers.get("authorization")
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 0.9}]})

        _compressor(handler, top_n=10).compress_documents(_docs(3), "q")
        assert seen["url"] == "https://openrouter.ai/api/v1/rerank"
        assert seen["auth"] == "Bearer test-key"
        assert seen["body"]["model"] == "voyageai/rerank-3"
        assert seen["body"]["query"] == "q"
        assert seen["body"]["documents"] == ["chunk 0", "chunk 1", "chunk 2"]
        assert seen["body"]["top_n"] == 3          # capped at the number of documents
        assert seen["body"]["provider"] == {"allow_fallbacks": False}

    def test_documents_cut_to_max_chars(self):
        seen = {}

        def handler(request):
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 1}]})

        _compressor(handler, max_chars=5).compress_documents(_docs(1, text="abcdefghij"), "q")
        assert seen["body"]["documents"] == ["abcde"]

    def test_max_chars_zero_means_no_cut(self):
        seen = {}

        def handler(request):
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 1}]})

        _compressor(handler, max_chars=0).compress_documents(_docs(1, text="x" * 20000), "q")
        assert len(seen["body"]["documents"][0]) == 20000

    def test_zdr_flag_sent_only_when_set(self):
        seen = {}

        def handler(request):
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"results": [{"index": 0, "relevance_score": 1}]})

        _compressor(handler, zdr=True, allow_fallbacks=True).compress_documents(_docs(1), "q")
        assert seen["body"]["provider"] == {"allow_fallbacks": True, "zdr": True}

    def test_empty_input_makes_no_call(self):
        def handler(request):
            raise AssertionError("must not call the API for an empty list")

        assert _compressor(handler).compress_documents([], "q") == []


class TestResult:
    def test_order_follows_results_and_metadata_is_kept(self):
        docs = _docs(3)
        out = _compressor(_ok([{"index": 2, "relevance_score": 0.8},
                               {"index": 0, "relevance_score": 0.5}])).compress_documents(docs, "q")
        assert [d.metadata["chunk_index"] for d in out] == [2, 0]
        assert out[0].metadata["doc_id"] == "d2" and out[0].metadata["relevance_score"] == 0.8
        assert out[0].page_content == "chunk 2"
        assert "relevance_score" not in docs[2].metadata   # input documents are not mutated

    @pytest.mark.parametrize("results", [
        [],                                                        # nothing back
        [{"index": 3, "relevance_score": 1}],                      # out of range
        [{"index": -1, "relevance_score": 1}],                     # negative
        [{"index": 0, "relevance_score": 1}, {"index": 0, "relevance_score": 1}],   # repeated
        [{"relevance_score": 1}],                                  # no index
    ])
    def test_bad_results_raise(self, results):
        with pytest.raises(ValueError):
            _compressor(_ok(results)).compress_documents(_docs(3), "q")

    def test_missing_results_key_raises(self):
        with pytest.raises(ValueError):
            _compressor(lambda r: httpx.Response(200, json={"error": "x"})).compress_documents(_docs(2), "q")

    def test_log_line_reports_provider_cost_and_cut(self, caplog):
        caplog.set_level("INFO", logger="app.rag.openrouter_rerank")
        docs = [Document(page_content="x" * 10, metadata={}), Document(page_content="y" * 3, metadata={})]
        _compressor(_ok([{"index": 0, "relevance_score": 1}]), max_chars=5).compress_documents(docs, "q")
        line = [r.getMessage() for r in caplog.records if "openrouter rerank" in r.getMessage()][0]
        assert "served_by=VoyageAI" in line and "cut=1" in line and "cost=0.0001" in line and "test-key" not in line

    def test_http_error_raises(self):
        with pytest.raises(httpx.HTTPStatusError):
            _compressor(lambda r: httpx.Response(402, json={"error": "no credits"})).compress_documents(_docs(2), "q")


class TestFactory:
    def test_needs_model(self):
        from app.rag.chain import _get_reranker
        with pytest.raises(ValueError, match="rerank_model"):
            _get_reranker(Settings(_env_file=None, rerank_provider="openrouter", openrouter_api_key="k"))

    def test_needs_key(self):
        from app.rag.chain import _get_reranker
        with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
            _get_reranker(Settings(_env_file=None, rerank_provider="openrouter", rerank_model="voyageai/rerank-3",
                                   openrouter_api_key=""))

    def test_settings_reach_the_compressor(self):
        from app.rag.chain import _get_reranker
        from app.rag.openrouter_rerank import OpenRouterRerank
        s = Settings(_env_file=None, rerank_provider="openrouter", rerank_model="cohere/rerank-4-pro",
                     openrouter_api_key="k", rerank_doc_max_chars=1234, rerank_request_timeout=7.5,
                     rerank_openrouter_zdr=True)
        c = _get_reranker(s, top_n_override=25)
        assert isinstance(c, OpenRouterRerank)
        assert (c.model, c.api_key, c.top_n, c.max_chars, c.timeout, c.zdr, c.allow_fallbacks) == \
            ("cohere/rerank-4-pro", "k", 25, 1234, 7.5, True, False)

    def test_defaults(self):
        s = Settings(_env_file=None)
        assert s.rerank_doc_max_chars == 8000 and s.rerank_openrouter_allow_fallbacks is False
        assert s.rerank_openrouter_zdr is False and s.rerank_request_timeout == 30.0


class TestPipelineFallbackIsVisible:
    """A failing provider must come back as ran=False (what the trace reports), never as a successful rerank."""

    @pytest.mark.asyncio
    async def test_failure_reports_not_ran(self, monkeypatch):
        from app.rag import chain
        from app.services import retrieval
        bad = _compressor(lambda r: httpx.Response(500, json={"error": "boom"}))
        monkeypatch.setattr(chain, "_get_reranker", lambda *a, **k: bad)
        retrieved = [(d, 1.0 - 0.1 * i) for i, d in enumerate(_docs(3))]
        out, ran = await retrieval._rerank_results(retrieved, "q", Settings(_env_file=None), top_n=10)
        assert ran is False and out == retrieved

    @pytest.mark.asyncio
    async def test_success_reports_ran_and_keeps_input_scores(self, monkeypatch):
        from app.rag import chain
        from app.services import retrieval
        good = _compressor(_ok([{"index": 2, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.1}]))
        monkeypatch.setattr(chain, "_get_reranker", lambda *a, **k: good)
        retrieved = [(d, 1.0 - 0.1 * i) for i, d in enumerate(_docs(3))]
        out, ran = await retrieval._rerank_results(retrieved, "q", Settings(_env_file=None), top_n=10)
        assert ran is True
        assert [(d.metadata["chunk_index"], s) for d, s in out] == [(2, 0.8), (0, 1.0)]
