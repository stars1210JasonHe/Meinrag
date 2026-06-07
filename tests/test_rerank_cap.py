"""Bug 3b: the reranker must never be fed thousands of candidates (ONNX OOM).
Cap input to the top-N by score before scoring; output still comes from the
reranker. Belt-and-suspenders with Task 2's coverage bound."""
import pytest
from langchain_core.documents import Document
from app.config import Settings
from app.services import retrieval


def _pair(i):
    return (Document(page_content=f"c{i}", metadata={"doc_id": f"d{i}", "chunk_index": 0}), i / 1000.0)


@pytest.mark.asyncio
async def test_rerank_input_capped(monkeypatch):
    seen = {}

    class _FakeCompressor:
        def compress_documents(self, docs, query):
            seen["n"] = len(docs)
            return docs[:4]

    # _get_reranker is imported inside _rerank_results from app.rag.chain
    import app.rag.chain as chain
    monkeypatch.setattr(chain, "_get_reranker", lambda *a, **k: _FakeCompressor())

    settings = Settings()
    settings.rerank_max_candidates = 50
    retrieved = [_pair(i) for i in range(500)]
    out = await retrieval._rerank_results(retrieved, "q", settings, llm=None, top_n=4368)
    assert seen["n"] <= 50          # reranker never saw more than the cap
    assert len(out) >= 1
