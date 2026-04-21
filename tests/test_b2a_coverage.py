"""B2-A regression guard — per-doc coverage must survive the full retrieval
pipeline.

Focused integration tests that exercise the interaction between the pipeline
stages that can drop mandatory chunks:

  - `_ensure_per_doc_coverage` (adds + flags)
  - `_apply_per_doc_cap` (can evict on low cap)
  - `_apply_token_budget` (can evict on overflow)

These complement the unit tests in `test_retrieval.py` (which exercise each
function in isolation). The goal here is to catch INTERACTION bugs where a
single change to one stage silently breaks coverage in another.
"""
from __future__ import annotations

import pytest
from langchain_core.documents import Document

from app.services.retrieval import (
    _ensure_per_doc_coverage,
    _apply_per_doc_cap,
    _apply_token_budget,
)


def _doc(doc_id: str, chunk_index: int = 0, content: str = "content", **meta) -> Document:
    m = {"doc_id": doc_id, "chunk_index": chunk_index}
    m.update(meta)
    return Document(page_content=content, metadata=m)


class _FakeVectorStoreWithBrokenFilter:
    """Simulates the pre-existing FAISS bug: similarity_search_with_scores(
    k, doc_ids=[one_doc]) returns empty because the over-fetch multiplier
    doesn't reach the target doc's chunks. Meanwhile get_chunks_by_doc works
    correctly because it reads the docstore directly.

    The B2-A fix is that _ensure_per_doc_coverage Step 2 must bypass the
    broken filter path and use get_chunks_by_doc. This fake exposes exactly
    that bug to verify the fix.
    """

    def __init__(self, chunks_by_doc: dict[str, list[Document]]):
        self._chunks = chunks_by_doc

    def get_chunks_by_doc(self, doc_id: str, chunk_indices=None) -> list[Document]:
        chunks = self._chunks.get(doc_id, [])
        if chunk_indices is not None:
            chunks = [c for c in chunks if c.metadata.get("chunk_index") in chunk_indices]
        return chunks

    def similarity_search_with_scores(self, query: str, k: int, doc_ids=None):
        # Deliberately broken: returns empty whenever a specific doc_ids filter
        # is applied — mirrors the real FAISS bug with narrow filters.
        if doc_ids and len(doc_ids) <= 3:
            return []
        # Unfiltered path would normally return top-K from the global pool
        return []


# ---------------------------------------------------------------------------
# Coverage-specific regression tests
# ---------------------------------------------------------------------------

class TestEnsureCoverageFAISSBypass:
    """B2-A: _ensure_per_doc_coverage Step 2 uses get_chunks_by_doc, not the
    broken similarity_search_with_scores path."""

    def test_missing_doc_is_backfilled_via_get_chunks_by_doc(self):
        # Scenario: 2 scope docs have natural hits, 1 does not.
        # The vector store's similarity_search_with_scores is broken (returns []
        # on narrow doc_ids filters — mirrors FAISS bug). get_chunks_by_doc works.
        natural_hits = [
            (_doc(doc_id="d1", content="natural d1"), 0.9),
            (_doc(doc_id="d2", content="natural d2"), 0.7),
        ]
        fake_store = _FakeVectorStoreWithBrokenFilter({
            "d3": [_doc(doc_id="d3", chunk_index=0, content="d3 intro chunk")],
        })
        result = _ensure_per_doc_coverage(
            natural_hits,
            all_candidates=[],  # Step 1 empty, forces Step 2 fallback
            scope_doc_ids=["d1", "d2", "d3"],
            question="any query",
            vector_store=fake_store,
        )
        doc_ids_present = {d.metadata.get("doc_id") for d, _ in result}
        assert doc_ids_present == {"d1", "d2", "d3"}, (
            f"FAISS-bypass fallback failed to backfill d3. Got docs: {doc_ids_present}"
        )
        # The backfilled d3 chunk must be marked mandatory
        d3_mandatory = any(
            d.metadata.get("doc_id") == "d3" and d.metadata.get("_mandatory")
            for d, _ in result
        )
        assert d3_mandatory, "backfilled chunk must carry _mandatory=True"


class TestPerDocCapPreservesMandatory:
    """_apply_per_doc_cap must preserve at least the highest-scored chunk per
    doc. Mandatory chunks are the highest-scored by construction of
    _ensure_per_doc_coverage, so this is load-bearing when cap == 1."""

    def test_cap_one_keeps_one_per_doc(self):
        """With cap=1 forced (top_k=3, n_docs=6 → cap=1), each doc retains one chunk."""
        retrieved = [
            (_doc(doc_id=f"d{i}", chunk_index=0, content=f"d{i} chunk 0"), 0.9 - i * 0.05)
            for i in range(1, 7)
        ]
        # Mark 3 of them mandatory (simulating post-coverage state)
        for i in [0, 2, 4]:
            retrieved[i][0].metadata["_mandatory"] = True

        result = _apply_per_doc_cap(retrieved, n_docs_in_scope=6, top_k=3)
        doc_ids_kept = {d.metadata.get("doc_id") for d, _ in result}
        assert doc_ids_kept == {"d1", "d2", "d3", "d4", "d5", "d6"}, (
            f"per-doc cap dropped docs with cap=1: {doc_ids_kept}"
        )

    def test_multiple_chunks_per_doc_with_mandatory_low_scored(self):
        """When a doc has a high-scored chunk AND a low-scored mandatory chunk,
        the cap keeps the high-scored one (the high-scored one IS mandatory by
        construction of _ensure_per_doc_coverage, but this test uses a contrived
        case to verify the cap doesn't silently lose the mandatory flag's intent).
        """
        high = _doc(doc_id="d1", chunk_index=0, content="high")
        low = _doc(doc_id="d1", chunk_index=1, content="low")
        low.metadata["_mandatory"] = True  # contrived — normally the high one would be mandatory
        other = _doc(doc_id="d2", chunk_index=0, content="other")

        retrieved = [(high, 0.9), (other, 0.5), (low, 0.1)]
        result = _apply_per_doc_cap(retrieved, n_docs_in_scope=2, top_k=2)
        doc_ids_kept = {d.metadata.get("doc_id") for d, _ in result}
        # At minimum d1 (via high) and d2 must be kept
        assert "d1" in doc_ids_kept and "d2" in doc_ids_kept


class TestTokenBudgetGuaranteesCoverage:
    """_apply_token_budget Pass 0 always includes mandatory, even under budget
    pressure from many high-scored non-mandatory chunks."""

    def test_tight_budget_with_10_mandatory_and_50_ordinary(self):
        """10 scope docs each with 1 mandatory chunk, plus 50 high-scored non-mandatory
        chunks trying to flood the budget. All 10 mandatory must survive."""
        mandatory = []
        for i in range(10):
            d = _doc(doc_id=f"m{i}", chunk_index=0, content="word " * 30)
            d.metadata["_mandatory"] = True
            mandatory.append((d, 0.1))  # low score

        ordinary = [
            (_doc(doc_id=f"o{i}", chunk_index=0, content="word " * 30), 0.95)
            for i in range(50)
        ]

        retrieved = mandatory + ordinary
        # budget = 600 tokens → ~20 chunks fit at ~30 tokens each.
        kept, _ = _apply_token_budget(retrieved, chunk_budget=600)
        kept_mandatory = [d for d, _ in kept if d.metadata.get("_mandatory")]
        assert len(kept_mandatory) == 10, (
            f"expected all 10 mandatory kept, got {len(kept_mandatory)}"
        )
        kept_doc_ids = {d.metadata.get("doc_id") for d, _ in kept}
        # All 10 mandatory docs must be represented
        for i in range(10):
            assert f"m{i}" in kept_doc_ids, f"scope doc m{i} lost by budget"

    def test_catastrophic_overflow_still_includes_mandatory(self):
        """When mandatory alone far exceeds budget, they're still all kept."""
        mandatory = []
        for i in range(20):
            d = _doc(doc_id=f"m{i}", chunk_index=0, content="word " * 50)
            d.metadata["_mandatory"] = True
            mandatory.append((d, 0.5))

        # 20 × ~50 tokens = 1000 tokens, budget 100 → 10× overflow
        kept, used = _apply_token_budget(mandatory, chunk_budget=100)
        kept_doc_ids = {d.metadata.get("doc_id") for d, _ in kept}
        for i in range(20):
            assert f"m{i}" in kept_doc_ids, f"overflow dropped mandatory doc m{i}"
        assert used > 100, "used tokens should exceed budget (documented overflow)"


class TestEndToEndB2ACoverage:
    """Integration test: coverage + cap + budget in sequence, mimicking the
    full pipeline order. Every scope doc must be represented at the end."""

    def test_6_doc_scope_3_need_backfill_all_survive(self):
        """The exact scenario the user reported: select 6 docs, 3 have natural
        hits (high score), 3 need backfill (low score). All 6 must be in the
        final output after cap + budget."""
        # Natural hits for 3 docs
        natural = []
        for i in range(1, 4):
            # 3 chunks per natural-hit doc to trigger per-doc cap stress
            for ci in range(3):
                d = _doc(doc_id=f"d{i}", chunk_index=ci, content=f"d{i}_c{ci} " + "word " * 20)
                natural.append((d, 0.9 - ci * 0.05))

        # Backfill the 3 missing docs via _ensure_per_doc_coverage fallback
        fake_store = _FakeVectorStoreWithBrokenFilter({
            f"d{i}": [_doc(doc_id=f"d{i}", chunk_index=0, content=f"d{i} intro " + "word " * 20)]
            for i in [4, 5, 6]
        })
        retrieved = _ensure_per_doc_coverage(
            natural, all_candidates=[], scope_doc_ids=[f"d{i}" for i in range(1, 7)],
            question="test", vector_store=fake_store,
        )
        # Should now have 9 natural + 3 backfill = 12 chunks
        assert len(retrieved) == 12

        # Simulate post-scoring sort (highest first)
        retrieved.sort(key=lambda x: x[1], reverse=True)

        # Per-doc cap: top_k=6, 6 unique docs → cap=1
        retrieved = _apply_per_doc_cap(retrieved, n_docs_in_scope=6, top_k=6)
        assert {d.metadata.get("doc_id") for d, _ in retrieved} == {f"d{i}" for i in range(1, 7)}

        # Token budget: tight — 600 tokens, each chunk ~20 tokens, 6 chunks ~120 tokens
        kept, used = _apply_token_budget(retrieved, chunk_budget=600)
        final_doc_ids = {d.metadata.get("doc_id") for d, _ in kept}
        assert final_doc_ids == {f"d{i}" for i in range(1, 7)}, (
            f"B2-A regression: final result missing docs. Got {final_doc_ids}"
        )
