"""Fact-query keyword expansion — regression guard for multidoc_05-style queries.

Abstract queries like "what parameter counts?" don't lexically match concrete
answer tokens like "175B" or "13B". This test locks the expansion behavior:
  - For fact queries, _fact_keyword_expand LLM-predicts likely answer tokens
  - Augmented retrieval runs with `query + keywords`
  - Union (augmented-first, deduped) is returned — NOT RRF-merged
  - (RRF would prefer consensus chunks, demoting novel keyword hits)
"""
from __future__ import annotations

import asyncio

import pytest
from langchain_core.documents import Document


class _FakeStore:
    """Records the query passed to similarity_search and returns scripted chunks."""
    def __init__(self, augmented_hits: list[Document]):
        self._augmented_hits = augmented_hits
        self.last_query: str = ""

    def similarity_search_with_scores(self, query: str, k: int, doc_ids=None):
        self.last_query = query
        return [(d, 0.8) for d in self._augmented_hits]


def _doc(doc_id: str, chunk_index: int, content: str) -> Document:
    return Document(page_content=content, metadata={"doc_id": doc_id, "chunk_index": chunk_index})


class TestFactKeywordExpand:
    """Covers the fact-query expansion helper in isolation. Does NOT invoke a
    real LLM — uses monkeypatched prompt chain."""

    def test_augmented_chunks_take_precedence_over_original(self, monkeypatch):
        """Augmented-retrieval chunks must appear BEFORE original chunks in
        the returned list, so subsequent pipeline stages see them first."""
        from app.services import retrieval
        from app.services.retrieval import _fact_keyword_expand

        # Scripted LLM chain — generates keywords instantly
        monkeypatch.setattr(
            retrieval, "FACT_KEYWORD_EXPANSION_PROMPT", object(),
        )
        # Replace `prompt | llm | StrOutputParser()` chain construction
        # by patching the internals. We directly patch the chain invocation.
        original_fn = _fact_keyword_expand

        # Original retrieval: only "abstract" chunks (no keyword hits)
        original_chunks = [
            (_doc("d1", 0, "We discuss the architecture at length."), 0.85),
            (_doc("d1", 1, "The training loss decreased over time."), 0.80),
        ]
        # Augmented retrieval: "concrete" chunks with keyword hits
        augmented_chunks = [
            _doc("d1", 2, "The model has 175 billion parameters in the largest config."),
            _doc("d2", 0, "Llama 2 ships with 7B, 13B, and 70B parameter variants."),
        ]
        store = _FakeStore(augmented_chunks)

        async def _run():
            # Monkeypatch the chain by wrapping the | operator behavior
            # Simpler approach: patch retrieve.chain at module level to return our scripted keywords
            import app.rag.prompts as prompts_mod

            class _StubPrompt:
                def __or__(self, other):
                    return _StubPrompt()

                async def ainvoke(self, inputs):
                    return "175B 13B 70B billion parameters"

            monkeypatch.setattr(
                retrieval, "FACT_KEYWORD_EXPANSION_PROMPT", _StubPrompt(),
            )

            # Bypass the real LLM chain with a monkeypatched ainvoke
            # The function calls: chain = PROMPT | llm | StrOutputParser()
            # Then: keywords = (await chain.ainvoke({...})).strip()
            # We patch so `PROMPT | anything` → object with async ainvoke returning keywords
            class _PipedStub:
                def __or__(self, other):
                    return self

                async def ainvoke(self, inputs):
                    return "175B 13B 70B billion parameters"

            monkeypatch.setattr(
                retrieval, "FACT_KEYWORD_EXPANSION_PROMPT", _PipedStub(),
            )

            return await _fact_keyword_expand(
                question="What parameter counts?",
                retrieved=original_chunks,
                llm=None,
                vector_store=store,
                doc_ids=["d1", "d2"],
                fetch_k=10,
            )

        result = asyncio.run(_run())

        # The augmented query ran with question + predicted keywords
        assert "175B" in store.last_query or "billion" in store.last_query, (
            f"augmented query must include LLM keywords. Got: {store.last_query}"
        )

        # Augmented chunks must appear FIRST in result (their keyword hits
        # survive subsequent ranking stages)
        result_contents = [d.page_content for d, _ in result]
        aug_175b = next(
            (i for i, c in enumerate(result_contents) if "175 billion" in c),
            None,
        )
        aug_llama = next(
            (i for i, c in enumerate(result_contents) if "7B, 13B" in c),
            None,
        )
        orig_arch = next(
            (i for i, c in enumerate(result_contents) if "architecture at length" in c),
            None,
        )

        assert aug_175b is not None and aug_175b < 2, "augmented 175B chunk must be in top-2"
        assert aug_llama is not None and aug_llama < 2, "augmented llama chunk must be in top-2"
        assert orig_arch is None or orig_arch >= 2, "original abstract chunk must be demoted below augmented"

    def test_empty_keywords_fallback_to_original(self, monkeypatch):
        """If LLM returns empty, expansion is a no-op — original list is returned."""
        from app.services import retrieval
        from app.services.retrieval import _fact_keyword_expand

        class _PipedStub:
            def __or__(self, other):
                return self

            async def ainvoke(self, inputs):
                return ""  # empty keywords

        monkeypatch.setattr(
            retrieval, "FACT_KEYWORD_EXPANSION_PROMPT", _PipedStub(),
        )

        original = [(_doc("d1", 0, "abstract"), 0.9)]
        store = _FakeStore([])

        async def _run():
            return await _fact_keyword_expand(
                question="what counts?",
                retrieved=original,
                llm=None,
                vector_store=store,
                doc_ids=["d1"],
                fetch_k=10,
            )

        result = asyncio.run(_run())
        assert result == original, "empty keywords must return original unchanged"

    def test_exception_in_llm_falls_back_gracefully(self, monkeypatch):
        """LLM failure must not crash retrieval — fall back to original."""
        from app.services import retrieval
        from app.services.retrieval import _fact_keyword_expand

        class _ExplodingStub:
            def __or__(self, other):
                return self

            async def ainvoke(self, inputs):
                raise RuntimeError("simulated LLM outage")

        monkeypatch.setattr(
            retrieval, "FACT_KEYWORD_EXPANSION_PROMPT", _ExplodingStub(),
        )

        original = [(_doc("d1", 0, "abstract"), 0.9)]
        store = _FakeStore([])

        async def _run():
            return await _fact_keyword_expand(
                question="anything",
                retrieved=original,
                llm=None,
                vector_store=store,
                doc_ids=["d1"],
                fetch_k=10,
            )

        result = asyncio.run(_run())
        assert result == original, "exception must return original unchanged"

    def test_shared_chunk_keeps_augmented_score(self, monkeypatch):
        """When the same chunk appears in both lists, the augmented-retrieval
        score must be kept (augmented first, deduped). This locks in the
        score-substitution behavior so future refactors don't silently swap
        the source of the score."""
        from app.services import retrieval
        from app.services.retrieval import _fact_keyword_expand

        class _PipedStub:
            def __or__(self, other):
                return self

            async def ainvoke(self, inputs):
                return "175B parameters"

        monkeypatch.setattr(
            retrieval, "FACT_KEYWORD_EXPANSION_PROMPT", _PipedStub(),
        )

        shared = _doc("d1", 0, "175 billion parameters")
        original = [(shared, 0.55)]  # low-ish original score
        # _FakeStore returns 0.8 for every augmented hit
        store = _FakeStore([shared])

        async def _run():
            return await _fact_keyword_expand(
                question="parameter count?",
                retrieved=original,
                llm=None,
                vector_store=store,
                doc_ids=["d1"],
                fetch_k=10,
            )

        result = asyncio.run(_run())
        assert len(result) == 1, "shared chunk must not be duplicated"
        assert result[0][1] == 0.8, (
            f"shared chunk must keep augmented score (0.8), got {result[0][1]}"
        )

    def test_runaway_llm_response_rejected(self, monkeypatch):
        """LLM that ignores the prompt and returns a sentence must be rejected —
        appending a sentence to the query degrades retrieval. Guard against
        >20 words OR >200 chars."""
        from app.services import retrieval
        from app.services.retrieval import _fact_keyword_expand

        class _ChattyStub:
            def __or__(self, other):
                return self

            async def ainvoke(self, inputs):
                # 25 words — exceeds word-count guard even though under 200 chars
                return " ".join(["word"] * 25)

        monkeypatch.setattr(
            retrieval, "FACT_KEYWORD_EXPANSION_PROMPT", _ChattyStub(),
        )

        original = [(_doc("d1", 0, "abstract"), 0.9)]
        store = _FakeStore([_doc("d1", 1, "should NOT be retrieved")])

        async def _run():
            return await _fact_keyword_expand(
                question="anything",
                retrieved=original,
                llm=None,
                vector_store=store,
                doc_ids=["d1"],
                fetch_k=10,
            )

        result = asyncio.run(_run())
        assert result == original, "runaway keyword response must be rejected"
        assert store.last_query == "", (
            f"store must NOT be queried when keywords rejected. Got: {store.last_query}"
        )
