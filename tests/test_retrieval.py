"""Unit tests for app/services/retrieval.py.

Covers _merge_dual_results, _normalize_scores, _section_aware_sample,
_lookup_by_label, _analyze_query, and _apply_composite_scoring.

Functions already covered in test_chunk_quality.py are NOT duplicated:
  _apply_reference_penalty, _apply_section_weights.
"""
from __future__ import annotations

import json
import pytest
from langchain_core.documents import Document

from app.services.retrieval import (
    _merge_dual_results,
    _normalize_scores,
    _section_aware_sample,
    _lookup_by_label,
    _analyze_query,
    _apply_composite_scoring,
    _rrf_merge_bm25,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _doc(doc_id="d1", chunk_index=0, section="methods", content="text", **extra_meta):
    meta = {"doc_id": doc_id, "chunk_index": chunk_index, "section_type": section}
    meta.update(extra_meta)
    return Document(page_content=content, metadata=meta)


# ---------------------------------------------------------------------------
# 1. _merge_dual_results
# ---------------------------------------------------------------------------

class TestMergeDualResults:
    def test_merge_keeps_best_score(self):
        """Same chunk in both lists — keep the higher score."""
        doc = _doc(doc_id="d1", chunk_index=0, content="chunk A")
        raw = [(doc, 0.6)]
        summary = [(doc, 0.85)]
        result = _merge_dual_results(raw, summary)
        assert len(result) == 1
        _, score = result[0]
        assert score == pytest.approx(0.85)

    def test_merge_keeps_best_score_raw_wins(self):
        """Same chunk, raw score is higher — keep raw score."""
        doc = _doc(doc_id="d1", chunk_index=0, content="chunk A")
        raw = [(doc, 0.9)]
        summary = [(doc, 0.5)]
        result = _merge_dual_results(raw, summary)
        assert len(result) == 1
        _, score = result[0]
        assert score == pytest.approx(0.9)

    def test_merge_combines_unique(self):
        """Distinct chunks from each list are all kept."""
        raw = [(_doc(doc_id="d1", chunk_index=0, content="A"), 0.7)]
        summary = [(_doc(doc_id="d1", chunk_index=1, content="B"), 0.6)]
        result = _merge_dual_results(raw, summary)
        assert len(result) == 2

    def test_raw_doc_preferred_over_summary(self):
        """When summary has higher score, raw doc object is kept (full content),
        but the score is updated to the higher summary score."""
        raw_doc = _doc(doc_id="d1", chunk_index=0, content="full raw content")
        summary_doc = _doc(doc_id="d1", chunk_index=0, content="summary snippet")
        raw = [(raw_doc, 0.5)]
        summary = [(summary_doc, 0.9)]
        result = _merge_dual_results(raw, summary)
        assert len(result) == 1
        doc, score = result[0]
        # Raw doc object preserved (has full content)
        assert doc.page_content == "full raw content"
        # But score is updated to the higher value from summary
        assert score == pytest.approx(0.9)

    def test_empty_inputs(self):
        """Both empty."""
        assert _merge_dual_results([], []) == []

    def test_one_empty(self):
        """Only raw list has data."""
        raw = [(_doc(doc_id="d1", chunk_index=0), 0.7)]
        result = _merge_dual_results(raw, [])
        assert len(result) == 1

        result2 = _merge_dual_results([], raw)
        assert len(result2) == 1

    def test_multiple_chunks_mixed(self):
        """Three chunks: two unique and one overlap; overlap keeps max score."""
        raw = [
            (_doc(doc_id="d1", chunk_index=0, content="A"), 0.8),
            (_doc(doc_id="d1", chunk_index=1, content="B"), 0.6),
        ]
        summary = [
            (_doc(doc_id="d1", chunk_index=1, content="B-sum"), 0.75),  # overlap, higher
            (_doc(doc_id="d1", chunk_index=2, content="C"), 0.5),
        ]
        result = _merge_dual_results(raw, summary)
        assert len(result) == 3
        score_map = {doc.metadata["chunk_index"]: score for doc, score in result}
        assert score_map[0] == pytest.approx(0.8)
        assert score_map[1] == pytest.approx(0.75)  # summary was higher
        assert score_map[2] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# 2. _normalize_scores
# ---------------------------------------------------------------------------

class TestNormalizeScores:
    def test_normalizes_max_to_100(self):
        """Highest score should become exactly 100."""
        results = [
            (_doc(chunk_index=0), 0.8),
            (_doc(chunk_index=1), 0.4),
            (_doc(chunk_index=2), 0.6),
        ]
        normed = _normalize_scores(results)
        scores = [s for _, s in normed]
        assert max(scores) == pytest.approx(100.0)

    def test_proportional_scaling(self):
        """Scores should scale proportionally relative to the max."""
        results = [
            (_doc(chunk_index=0), 1.0),
            (_doc(chunk_index=1), 0.5),
        ]
        normed = _normalize_scores(results)
        score_map = {doc.metadata["chunk_index"]: score for doc, score in normed}
        assert score_map[0] == pytest.approx(100.0)
        assert score_map[1] == pytest.approx(50.0)

    def test_empty(self):
        assert _normalize_scores([]) == []

    def test_all_zero(self):
        """When all scores are zero, return unchanged (no division)."""
        results = [
            (_doc(chunk_index=0), 0.0),
            (_doc(chunk_index=1), 0.0),
        ]
        normed = _normalize_scores(results)
        # max_score <= 0 path: return unchanged
        assert [s for _, s in normed] == [0.0, 0.0]

    def test_single_item(self):
        results = [(_doc(), 0.73)]
        normed = _normalize_scores(results)
        assert normed[0][1] == pytest.approx(100.0)

    def test_scores_rounded_to_one_decimal(self):
        results = [
            (_doc(chunk_index=0), 0.3),
            (_doc(chunk_index=1), 0.7),
        ]
        normed = _normalize_scores(results)
        for _, s in normed:
            # round() to 1dp means at most one digit after decimal point
            assert s == round(s, 1)


# ---------------------------------------------------------------------------
# 3. _section_aware_sample
# ---------------------------------------------------------------------------

class TestSectionAwareSample:
    def test_round_robin_across_sections(self):
        """Chunks are sampled round-robin across sections up to top_k."""
        results = [
            (_doc(chunk_index=0, section="methods", content="M1"), 0.9),
            (_doc(chunk_index=1, section="methods", content="M2"), 0.6),
            (_doc(chunk_index=2, section="results", content="R1"), 0.7),
        ]
        # Default top_k=8, so all 3 are returned
        sampled = _section_aware_sample(results)
        assert len(sampled) == 3
        # With top_k=2, round-robin picks best from each section first
        sampled2 = _section_aware_sample(results, top_k=2)
        assert len(sampled2) == 2
        sections = {doc.metadata["section_type"] for doc, _ in sampled2}
        assert sections == {"methods", "results"}

    def test_highest_score_first_per_section(self):
        """Within a section, highest-scoring chunk is picked first."""
        results = [
            (_doc(chunk_index=0, section="methods", content="M-low"), 0.4),
            (_doc(chunk_index=1, section="methods", content="M-high"), 0.9),
        ]
        sampled = _section_aware_sample(results)
        assert len(sampled) == 2
        assert sampled[0][0].page_content == "M-high"
        assert sampled[0][1] == pytest.approx(0.9)

    def test_sorted_by_score_descending(self):
        """Output is sorted by score descending."""
        results = [
            (_doc(chunk_index=0, section="methods"), 0.5),
            (_doc(chunk_index=1, section="abstract"), 0.9),
            (_doc(chunk_index=2, section="results"), 0.7),
        ]
        sampled = _section_aware_sample(results)
        scores = [s for _, s in sampled]
        assert scores == sorted(scores, reverse=True)

    def test_empty(self):
        assert _section_aware_sample([]) == []

    def test_missing_section_type_uses_body_key(self):
        """Chunks without section_type are grouped under 'body'."""
        results = [
            (Document(page_content="A", metadata={"doc_id": "d1", "chunk_index": 0}), 0.8),
            (Document(page_content="B", metadata={"doc_id": "d1", "chunk_index": 1}), 0.6),
        ]
        sampled = _section_aware_sample(results)
        # Both map to 'body' section, with top_k=8 both returned
        assert len(sampled) == 2


# ---------------------------------------------------------------------------
# 4. _lookup_by_label
# ---------------------------------------------------------------------------

class FakeVectorStore:
    """Minimal VectorStoreManager stub for label lookup tests."""
    def __init__(self, chunks_by_doc: dict):
        self._chunks = chunks_by_doc

    def get_chunks_by_doc(self, doc_id):
        return self._chunks.get(doc_id, [])


class TestLookupByLabel:
    def _make_chunk(self, doc_id, chunk_index, chunk_type, label=None):
        meta = {"doc_id": doc_id, "chunk_index": chunk_index, "chunk_type": chunk_type}
        if label:
            meta["label"] = label
        return Document(page_content=f"{chunk_type} {chunk_index}", metadata=meta)

    def test_exact_label_match(self):
        chunks = [
            self._make_chunk("d1", 0, "table", label="Table 1"),
            self._make_chunk("d1", 1, "image", label="Figure 2"),
        ]
        vs = FakeVectorStore({"d1": chunks})
        result = _lookup_by_label("Table 1", vs, doc_ids=["d1"])
        assert len(result) == 1
        assert result[0].metadata["label"] == "Table 1"

    def test_exact_label_case_insensitive(self):
        chunks = [self._make_chunk("d1", 0, "table", label="Table 1")]
        vs = FakeVectorStore({"d1": chunks})
        result = _lookup_by_label("table 1", vs, doc_ids=["d1"])
        assert len(result) == 1

    def test_fallback_nth_table(self):
        """No label metadata but 'Table 2' should return the 2nd table chunk."""
        chunks = [
            self._make_chunk("d1", 0, "table"),   # 1st table
            self._make_chunk("d1", 1, "text"),
            self._make_chunk("d1", 2, "table"),   # 2nd table
        ]
        vs = FakeVectorStore({"d1": chunks})
        result = _lookup_by_label("Table 2", vs, doc_ids=["d1"])
        assert len(result) == 1
        assert result[0].metadata["chunk_index"] == 2

    def test_fallback_nth_figure(self):
        """'Figure 1' fallback maps to first image chunk."""
        chunks = [
            self._make_chunk("d1", 0, "text"),
            self._make_chunk("d1", 1, "image"),
        ]
        vs = FakeVectorStore({"d1": chunks})
        result = _lookup_by_label("Figure 1", vs, doc_ids=["d1"])
        assert len(result) == 1
        assert result[0].metadata["chunk_type"] == "image"

    def test_fallback_nth_equation(self):
        """'Equation 1' fallback maps to first formula chunk."""
        chunks = [
            self._make_chunk("d1", 0, "formula"),
            self._make_chunk("d1", 1, "formula"),
        ]
        vs = FakeVectorStore({"d1": chunks})
        result = _lookup_by_label("Equation 2", vs, doc_ids=["d1"])
        assert len(result) == 1
        assert result[0].metadata["chunk_index"] == 1

    def test_fallback_out_of_range(self):
        """Nth chunk doesn't exist — return empty."""
        chunks = [self._make_chunk("d1", 0, "table")]
        vs = FakeVectorStore({"d1": chunks})
        result = _lookup_by_label("Table 5", vs, doc_ids=["d1"])
        assert result == []

    def test_no_match(self):
        chunks = [self._make_chunk("d1", 0, "text")]
        vs = FakeVectorStore({"d1": chunks})
        result = _lookup_by_label("Table 1", vs, doc_ids=["d1"])
        assert result == []

    def test_no_doc_ids(self):
        vs = FakeVectorStore({})
        result = _lookup_by_label("Table 1", vs, doc_ids=None)
        assert result == []

    def test_empty_label(self):
        vs = FakeVectorStore({"d1": []})
        result = _lookup_by_label("", vs, doc_ids=["d1"])
        assert result == []

    def test_unrecognized_label_type(self):
        """'Section 2' doesn't match table/figure/equation — return empty."""
        chunks = [self._make_chunk("d1", 0, "text")]
        vs = FakeVectorStore({"d1": chunks})
        result = _lookup_by_label("Section 2", vs, doc_ids=["d1"])
        assert result == []


# ---------------------------------------------------------------------------
# 5. _analyze_query
# ---------------------------------------------------------------------------

class FakeLLMResponse:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    def __init__(self, response_content):
        self._content = response_content

    async def ainvoke(self, messages):
        return FakeLLMResponse(self._content)


class TestAnalyzeQuery:
    @pytest.mark.asyncio
    async def test_fact_query(self):
        """LLM returns valid JSON with 'fact' type."""
        payload = json.dumps({"types": ["fact"], "label": None})
        llm = FakeLLM(payload)
        result = await _analyze_query("What is the BLEU score?", llm)
        assert "fact" in result["types"]
        assert result["label"] is None

    @pytest.mark.asyncio
    async def test_reference_query_with_label(self):
        """LLM returns reference type with a label."""
        payload = json.dumps({"types": ["reference"], "label": "Table 2"})
        llm = FakeLLM(payload)
        result = await _analyze_query("What does Table 2 show?", llm)
        assert "reference" in result["types"]
        assert result["label"] == "Table 2"

    @pytest.mark.asyncio
    async def test_multi_type(self):
        """Multiple types are all returned."""
        payload = json.dumps({"types": ["fact", "exploratory"], "label": None})
        llm = FakeLLM(payload)
        result = await _analyze_query("Compare and list the exact numbers", llm)
        assert set(result["types"]) >= {"fact", "exploratory"}

    @pytest.mark.asyncio
    async def test_failure_defaults_to_exploratory(self):
        """When LLM returns invalid JSON, default to ['exploratory']."""
        llm = FakeLLM("not valid json at all")
        result = await _analyze_query("some question", llm)
        assert result["types"] == ["exploratory"]
        assert result["label"] is None

    @pytest.mark.asyncio
    async def test_markdown_code_block_unwrapped(self):
        """LLM wraps JSON in markdown code block — should still parse."""
        payload = "```json\n" + json.dumps({"types": ["overview"], "label": None}) + "\n```"
        llm = FakeLLM(payload)
        result = await _analyze_query("Summarize the paper", llm)
        assert "overview" in result["types"]

    @pytest.mark.asyncio
    async def test_unknown_types_filtered(self):
        """Types not in the valid set are filtered out; falls back to last valid type."""
        payload = json.dumps({"types": ["nonexistent_type"], "label": None})
        llm = FakeLLM(payload)
        result = await _analyze_query("some question", llm)
        # Should fall back to the last configured type (exploratory)
        assert len(result["types"]) > 0

    @pytest.mark.asyncio
    async def test_long_label_truncated_to_none(self):
        """Labels longer than 30 chars are rejected (set to None)."""
        long_label = "A" * 31
        payload = json.dumps({"types": ["reference"], "label": long_label})
        llm = FakeLLM(payload)
        result = await _analyze_query("some question", llm)
        assert result["label"] is None


# ---------------------------------------------------------------------------
# 6. _apply_composite_scoring
# ---------------------------------------------------------------------------

class FakeSettings:
    query_types_file: str = "data/query_types.json"


class FakeEdgeRepo:
    """Returns configurable edge counts per (doc_id, [chunk_indices]).

    Accepts flat counts {(doc_id, chunk_index): total} and converts to
    typed format {chunk_index: {"follows": total}} for the typed API.
    """
    def __init__(self, counts: dict | None = None):
        self._counts = counts or {}

    async def get_edge_counts_batch(self, doc_id, chunk_indices):
        return {
            cidx: self._counts.get((doc_id, cidx), 0)
            for cidx in chunk_indices
        }

    async def get_edge_type_counts_batch(self, doc_id, chunk_indices):
        result = {}
        for cidx in chunk_indices:
            total = self._counts.get((doc_id, cidx), 0)
            if total > 0:
                result[cidx] = {"follows": total}
        return result


def _general_scoring():
    from app.services.scoring_profile import load_scoring_profile
    return load_scoring_profile("general").for_query_type()


class TestCompositeScoring:
    @pytest.mark.asyncio
    async def test_scores_change_with_edges(self):
        """A chunk with edges should get a higher composite score than one without."""
        doc_with_edges = _doc(doc_id="d1", chunk_index=0, content="has edges")
        doc_no_edges = _doc(doc_id="d1", chunk_index=1, content="no edges")
        retrieved = [(doc_with_edges, 0.5), (doc_no_edges, 0.5)]
        edge_repo = FakeEdgeRepo({("d1", 0): 10})
        settings = FakeSettings()
        scoring = _general_scoring()
        result = await _apply_composite_scoring(retrieved, edge_repo, "fact", settings, scoring)
        score_map = {doc.metadata["chunk_index"]: score for doc, score in result}
        assert score_map[0] > score_map[1]

    @pytest.mark.asyncio
    async def test_graph_score_capped_at_1(self):
        """Edge count > normalization_factor should still cap graph_score at 1.0."""
        doc = _doc(doc_id="d1", chunk_index=0)
        edge_repo = FakeEdgeRepo({("d1", 0): 999})
        settings = FakeSettings()
        scoring = _general_scoring()
        result = await _apply_composite_scoring([(doc, 0.5)], edge_repo, "fact", settings, scoring)
        _, score = result[0]
        # With fact weights [0.85, 0.15, 0.0, 0.0]: 0.85*0.5 + 0.15*1.0 + 0.0*1.0 + 0.0*1.0
        assert score == pytest.approx(0.85 * 0.5 + 0.15 * 1.0 + 0.0 * 1.0 + 0.0 * 1.0)

    @pytest.mark.asyncio
    async def test_no_edge_repo(self):
        """With edge_repo=None, graph_score=0; scoring still works."""
        doc = _doc(doc_id="d1", chunk_index=0)
        settings = FakeSettings()
        scoring = _general_scoring()
        result = await _apply_composite_scoring([(doc, 0.6)], None, "fact", settings, scoring)
        assert len(result) == 1
        _, score = result[0]
        # fact weights [0.85, 0.15, 0.0, 0.0]: 0.85*0.6 + 0.15*0 + 0.0*1.0 + 0.0*1.0
        assert score == pytest.approx(0.85 * 0.6 + 0.0 + 0.0 * 1.0 + 0.0 * 1.0)

    @pytest.mark.asyncio
    async def test_empty_input(self):
        """Empty retrieved list returns empty."""
        settings = FakeSettings()
        scoring = _general_scoring()
        result = await _apply_composite_scoring([], FakeEdgeRepo(), "fact", settings, scoring)
        assert result == []

    @pytest.mark.asyncio
    async def test_missing_doc_id_still_scores(self):
        """Chunks without doc_id/chunk_index get graph_score=0 but are still scored."""
        doc = Document(page_content="no metadata", metadata={})
        settings = FakeSettings()
        scoring = _general_scoring()
        result = await _apply_composite_scoring([(doc, 0.5)], FakeEdgeRepo(), "exploratory", settings, scoring)
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_per_query_type_weights(self):
        """Different query types produce different scores for the same input."""
        doc = _doc(doc_id="d1", chunk_index=0)
        edge_repo = FakeEdgeRepo({("d1", 0): 10})
        settings = FakeSettings()
        scoring = _general_scoring()

        fact_result = await _apply_composite_scoring([(doc, 0.5)], edge_repo, "fact", settings, scoring)
        overview_result = await _apply_composite_scoring([(doc, 0.5)], edge_repo, "overview", settings, scoring)

        _, fact_score = fact_result[0]
        _, overview_score = overview_result[0]
        # fact weights: [0.85, 0.15, 0.0, 0.0]; overview: [0.6, 0.4, 0.0, 0.0]
        # With similarity=0.5 and graph=1.0:
        # fact:     0.85*0.5 + 0.15*1.0 + 0.0*1.0 + 0.0*1.0 = 0.575
        # overview: 0.6*0.5 + 0.4*1.0 + 0.0*1.0 + 0.0*1.0 = 0.70
        assert fact_score != pytest.approx(overview_score)


class TestRRFMerge:
    def test_vector_only(self):
        """With no BM25 results, vector ranking is preserved."""
        docs = [_doc(chunk_index=i) for i in range(3)]
        vector = [(docs[0], 0.9), (docs[1], 0.7), (docs[2], 0.5)]
        result = _rrf_merge_bm25(vector, [], k=60)
        assert len(result) == 3
        scores = [s for _, s in result]
        assert scores[0] > scores[1] > scores[2]
        assert scores[0] == pytest.approx(1.0)

    def test_bm25_only(self):
        """With no vector results, BM25 ranking is preserved."""
        docs = [_doc(chunk_index=i) for i in range(3)]
        result = _rrf_merge_bm25([], docs, k=60)
        assert len(result) == 3
        scores = [s for _, s in result]
        assert scores[0] > scores[1] > scores[2]
        assert scores[0] == pytest.approx(1.0)

    def test_both_found_sums(self):
        """Chunks found by both retrievers get higher RRF scores."""
        shared = _doc(chunk_index=0)
        vec_only = _doc(chunk_index=1)
        bm25_only = _doc(chunk_index=2)

        vector = [(shared, 0.9), (vec_only, 0.8)]
        bm25_docs = [shared, bm25_only]

        result = _rrf_merge_bm25(vector, bm25_docs, k=60)
        score_map = {doc.metadata["chunk_index"]: score for doc, score in result}
        assert score_map[0] > score_map[1]
        assert score_map[0] > score_map[2]

    def test_empty_inputs(self):
        """Both empty returns empty."""
        assert _rrf_merge_bm25([], [], k=60) == []

    def test_normalized_to_0_1(self):
        """Output scores are in [0, 1] range."""
        docs = [_doc(chunk_index=i) for i in range(5)]
        vector = [(d, 0.5) for d in docs[:3]]
        bm25 = docs[2:]
        result = _rrf_merge_bm25(vector, bm25, k=60)
        for _, score in result:
            assert 0.0 <= score <= 1.0

    def test_k_parameter_affects_scores(self):
        """Larger k compresses rank differences; smaller k amplifies them."""
        docs = [_doc(chunk_index=i) for i in range(3)]
        vector = [(docs[0], 0.9), (docs[1], 0.7), (docs[2], 0.5)]

        result_k10 = _rrf_merge_bm25(vector, [], k=10)
        result_k100 = _rrf_merge_bm25(vector, [], k=100)

        spread_k10 = result_k10[0][1] - result_k10[-1][1]
        spread_k100 = result_k100[0][1] - result_k100[-1][1]
        assert spread_k10 > spread_k100
