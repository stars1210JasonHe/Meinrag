"""Reranker model cache (P6 latency follow-up, 2026-07-11).

_get_reranker built a fresh FlashrankRerank per query, whose validator loads
the ONNX model from scratch — with ms-marco-MultiBERT-L-12 (~98MB) that took
collection searches from 8-9s to 26-53s. The heavy backend (flashrank Ranker /
HF cross-encoder) is now cached process-wide keyed by (provider, model); the
cheap pydantic wrapper is still built per call so top_n (which varies per
query) never shares mutable state and never duplicates a model load.
"""
import pytest

import flashrank
# Import BEFORE the Ranker monkeypatch: this module snapshots `Ranker` into
# its own namespace on first import — importing it while the fake is patched
# in would bake the fake into sys.modules and break later real-Ranker tests.
import langchain_community.document_compressors.flashrank_rerank  # noqa: F401

from app.config import Settings
from app.rag import chain as chain_mod


class _CountingRanker(flashrank.Ranker):
    """Real-Ranker subclass (satisfies FlashrankRerank's isinstance check)
    that skips the model download/load and counts constructions."""

    constructed: list = []

    def __init__(self, model_name: str = "", **kwargs):  # no super().__init__
        type(self).constructed.append(model_name)
        self.model_name = model_name


@pytest.fixture(autouse=True)
def _clean_cache_and_fake_ranker(monkeypatch):
    monkeypatch.setattr(chain_mod, "_reranker_client_cache", {})
    monkeypatch.setattr(flashrank, "Ranker", _CountingRanker)
    _CountingRanker.constructed = []
    yield


def _settings(model="", top_n=4):
    return Settings(
        openai_api_key="fake-key-for-testing",
        rerank_provider="flashrank",
        rerank_model=model,
        rerank_top_n=top_n,
    )


class TestRerankerModelCache:
    def test_same_model_loads_once_across_calls(self):
        c1 = chain_mod._get_reranker(_settings(model="ms-marco-MultiBERT-L-12"))
        c2 = chain_mod._get_reranker(_settings(model="ms-marco-MultiBERT-L-12"), top_n_override=10)
        assert _CountingRanker.constructed == ["ms-marco-MultiBERT-L-12"]
        assert c1.client is c2.client  # shared heavy backend

    def test_per_call_wrapper_keeps_independent_top_n(self):
        """top_n varies per query (multi-doc scope passes n_docs*3) — wrappers
        must not share it, and it must not fragment the model cache."""
        c1 = chain_mod._get_reranker(_settings(top_n=4))
        c2 = chain_mod._get_reranker(_settings(), top_n_override=6750)
        assert c1 is not c2
        assert c1.top_n == 4
        assert c2.top_n == 6750
        assert len(_CountingRanker.constructed) == 1

    def test_different_models_load_separately(self):
        chain_mod._get_reranker(_settings(model="ms-marco-MiniLM-L-12-v2"))
        chain_mod._get_reranker(_settings(model="ms-marco-MultiBERT-L-12"))
        assert _CountingRanker.constructed == [
            "ms-marco-MiniLM-L-12-v2",
            "ms-marco-MultiBERT-L-12",
        ]

    def test_default_model_resolution_unchanged(self):
        compressor = chain_mod._get_reranker(_settings())
        assert compressor.model == "ms-marco-MiniLM-L-12-v2"
        assert _CountingRanker.constructed == ["ms-marco-MiniLM-L-12-v2"]
