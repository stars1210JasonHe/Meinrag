"""Unit tests for app/services/retrieval.py.

Covers _rrf_merge_dual, _normalize_scores, _section_aware_sample,
_lookup_by_label, _analyze_query, and _apply_composite_scoring.

Functions already covered in test_chunk_quality.py are NOT duplicated:
  _apply_reference_penalty, _apply_section_weights.
"""
from __future__ import annotations

import json
import pytest
from langchain_core.documents import Document

from app.services.retrieval import (
    _rrf_merge_dual,
    _normalize_scores,
    _section_aware_sample,
    _lookup_by_label,
    _analyze_query,
    _apply_composite_scoring,
    _rrf_merge_bm25,
    _ensure_per_doc_coverage,
    _apply_token_budget,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _doc(doc_id="d1", chunk_index=0, section="methods", content="text", **extra_meta):
    meta = {"doc_id": doc_id, "chunk_index": chunk_index, "section_type": section}
    meta.update(extra_meta)
    return Document(page_content=content, metadata=meta)


# ---------------------------------------------------------------------------
# 1. _rrf_merge_dual
# ---------------------------------------------------------------------------

class TestRRFMergeDual:
    """RRF fuses raw-chunk and summary-chunk rankings. Scale-agnostic — cosine
    scores are ignored; only ranks matter. Output is re-normalized to 0-1."""

    def test_empty_inputs(self):
        assert _rrf_merge_dual([], []) == []

    def test_only_raw_results(self):
        """Summary empty → each raw chunk gets a single 1/(k+rank) contribution."""
        raw = [
            (_doc(chunk_index=0), 0.9),
            (_doc(chunk_index=1), 0.7),
            (_doc(chunk_index=2), 0.5),
        ]
        result = _rrf_merge_dual(raw, [], k=60)
        assert len(result) == 3
        # After normalization, rank-1 chunk gets 1.0; rank-2 and rank-3 strictly less
        score_map = {doc.metadata["chunk_index"]: s for doc, s in result}
        assert score_map[0] == pytest.approx(1.0)
        assert score_map[0] > score_map[1] > score_map[2]

    def test_only_summary_results(self):
        """Raw empty → each summary chunk contributes alone."""
        summary = [
            (_doc(chunk_index=5), 0.9),
            (_doc(chunk_index=6), 0.3),
        ]
        result = _rrf_merge_dual([], summary, k=60)
        assert len(result) == 2
        score_map = {doc.metadata["chunk_index"]: s for doc, s in result}
        assert score_map[5] == pytest.approx(1.0)
        assert score_map[5] > score_map[6]

    def test_consensus_outranks_solo(self):
        """Key RRF property: a chunk found by BOTH retrievers outscores a
        chunk found by only one, even when the solo match was at rank 1."""
        raw = [
            (_doc(chunk_index=0, content="solo-raw"), 0.95),   # rank 1 in raw only
            (_doc(chunk_index=1, content="both-chunk"), 0.50),  # rank 2 in raw
        ]
        summary = [
            (_doc(chunk_index=1, content="both-sum"), 0.40),    # rank 1 in summary
            (_doc(chunk_index=2, content="solo-sum"), 0.30),    # rank 2 in summary
        ]
        result = _rrf_merge_dual(raw, summary, k=60)
        score_map = {doc.metadata["chunk_index"]: s for doc, s in result}
        # chunk_index=1 was found in both → consensus bonus → should score highest
        assert score_map[1] > score_map[0]
        assert score_map[1] > score_map[2]

    def test_raw_doc_preferred_on_overlap(self):
        """When both retrievers find the same chunk, the raw Document object is
        kept (has full content), not the summary one."""
        raw_doc = _doc(chunk_index=0, content="full raw content")
        summary_doc = _doc(chunk_index=0, content="summary snippet")
        raw = [(raw_doc, 0.6)]
        summary = [(summary_doc, 0.9)]
        result = _rrf_merge_dual(raw, summary, k=60)
        assert len(result) == 1
        doc, _ = result[0]
        assert doc.page_content == "full raw content"

    def test_normalization_to_unit_scale(self):
        """After RRF, top chunk is exactly 1.0; all scores in [0, 1]."""
        raw = [(_doc(chunk_index=i), 0.5) for i in range(5)]
        summary = [(_doc(chunk_index=i), 0.5) for i in range(2, 7)]  # 2,3,4 overlap
        result = _rrf_merge_dual(raw, summary, k=60)
        scores = [s for _, s in result]
        assert max(scores) == pytest.approx(1.0)
        assert all(0.0 <= s <= 1.0 for s in scores)

    def test_later_rank_contributes_less(self):
        """A chunk at raw-rank 1 beats one at raw-rank 10 when neither appears
        in summary."""
        raw = [(_doc(chunk_index=i), 0.9 - i * 0.05) for i in range(10)]
        result = _rrf_merge_dual(raw, [], k=60)
        score_map = {doc.metadata["chunk_index"]: s for doc, s in result}
        # rank 1 (chunk 0) > rank 2 (chunk 1) > ... > rank 10 (chunk 9)
        for i in range(9):
            assert score_map[i] > score_map[i + 1]

    def test_output_sorted_desc(self):
        """Downstream pipeline (_section_aware_sample, _reorder_for_attention)
        requires the returned list to be sorted by score descending."""
        raw = [
            (_doc(chunk_index=2), 0.5),
            (_doc(chunk_index=0), 0.5),
            (_doc(chunk_index=4), 0.5),
        ]
        summary = [
            (_doc(chunk_index=0), 0.5),  # consensus bump on chunk 0
        ]
        result = _rrf_merge_dual(raw, summary, k=60)
        scores = [s for _, s in result]
        assert scores == sorted(scores, reverse=True), (
            f"RRF output must be sorted desc, got {scores}"
        )


# ---------------------------------------------------------------------------
# 2. _normalize_scores
# ---------------------------------------------------------------------------

class TestNormalizeScoresAbsolute:
    """Default mode: score * 100. Honest — top not pinned to 100."""

    def test_score_multiplied_by_100(self):
        """Display = raw * 100, preserved as-is."""
        results = [
            (_doc(chunk_index=0), 0.8),
            (_doc(chunk_index=1), 0.4),
            (_doc(chunk_index=2), 0.6),
        ]
        normed = _normalize_scores(results)
        score_map = {doc.metadata["chunk_index"]: s for doc, s in normed}
        assert score_map[0] == pytest.approx(80.0)
        assert score_map[1] == pytest.approx(40.0)
        assert score_map[2] == pytest.approx(60.0)

    def test_perfect_score_hits_100(self):
        """Raw 1.0 → exactly 100."""
        results = [(_doc(), 1.0)]
        normed = _normalize_scores(results)
        assert normed[0][1] == pytest.approx(100.0)

    def test_top_not_always_100(self):
        """A mediocre top stays mediocre — no max-scale trick."""
        results = [(_doc(), 0.73)]
        normed = _normalize_scores(results)
        assert normed[0][1] == pytest.approx(73.0)

    def test_empty(self):
        assert _normalize_scores([]) == []

    def test_all_zero(self):
        results = [
            (_doc(chunk_index=0), 0.0),
            (_doc(chunk_index=1), 0.0),
        ]
        normed = _normalize_scores(results)
        assert [s for _, s in normed] == [0.0, 0.0]

    def test_negative_clamped_to_zero(self):
        """Rare negative composite scores → display 0, not negative percent."""
        results = [(_doc(), -0.1)]
        normed = _normalize_scores(results)
        assert normed[0][1] == pytest.approx(0.0)

    def test_above_one_clamped_to_100(self):
        """Score > 1.0 (shouldn't happen but defensive) → 100."""
        results = [(_doc(), 1.5)]
        normed = _normalize_scores(results)
        assert normed[0][1] == pytest.approx(100.0)


class TestNormalizeScoresMaxScale:
    """Legacy mode: divide by max, top always = 100. Kept for rollback."""

    class _Profile:
        normalization = "max_scale"
        normalization_k = 1.5

    def test_normalizes_max_to_100(self):
        results = [
            (_doc(chunk_index=0), 0.8),
            (_doc(chunk_index=1), 0.4),
            (_doc(chunk_index=2), 0.6),
        ]
        normed = _normalize_scores(results, self._Profile())
        assert max(s for _, s in normed) == pytest.approx(100.0)

    def test_proportional_scaling(self):
        results = [
            (_doc(chunk_index=0), 1.0),
            (_doc(chunk_index=1), 0.5),
        ]
        normed = _normalize_scores(results, self._Profile())
        score_map = {doc.metadata["chunk_index"]: s for doc, s in normed}
        assert score_map[0] == pytest.approx(100.0)
        assert score_map[1] == pytest.approx(50.0)

    def test_all_zero_unchanged(self):
        results = [(_doc(chunk_index=0), 0.0), (_doc(chunk_index=1), 0.0)]
        normed = _normalize_scores(results, self._Profile())
        assert [s for _, s in normed] == [0.0, 0.0]


class TestNormalizeScoresTanh:
    """Tanh normalization: absolute, honest, no relative-max trick."""

    class _MockProfile:
        normalization = "tanh"
        normalization_k = 1.5

    def test_monotonic(self):
        """Higher raw score → higher display score."""
        results = [
            (_doc(chunk_index=0), 0.25),
            (_doc(chunk_index=1), 0.50),
            (_doc(chunk_index=2), 0.85),
        ]
        normed = _normalize_scores(results, self._MockProfile())
        score_map = {doc.metadata["chunk_index"]: s for doc, s in normed}
        assert score_map[0] < score_map[1] < score_map[2]

    def test_no_relative_max_trick(self):
        """Top result should NOT always be 100 — a weak query stays weak."""
        weak_results = [
            (_doc(chunk_index=0), 0.25),
            (_doc(chunk_index=1), 0.20),
            (_doc(chunk_index=2), 0.15),
        ]
        normed = _normalize_scores(weak_results, self._MockProfile())
        top = max(s for _, s in normed)
        # With tanh(k=1.5), raw 0.25 → ~30%, definitely not 100
        assert top < 50.0, f"Weak top should stay weak, got {top}"

    def test_perfect_score_hits_100(self):
        """Raw 1.0 → exactly 100 (by construction: tanh(k)/tanh(k) = 1)."""
        results = [(_doc(), 1.0)]
        normed = _normalize_scores(results, self._MockProfile())
        assert normed[0][1] == pytest.approx(100.0)

    def test_known_values(self):
        """Sanity check against computed tanh values (k=1.5)."""
        import math
        k = 1.5
        denom = math.tanh(k)
        results = [
            (_doc(chunk_index=0), 0.50),
            (_doc(chunk_index=1), 0.85),
        ]
        normed = _normalize_scores(results, self._MockProfile())
        score_map = {doc.metadata["chunk_index"]: s for doc, s in normed}
        expected_50 = round(math.tanh(k * 0.50) / denom * 100, 1)
        expected_85 = round(math.tanh(k * 0.85) / denom * 100, 1)
        assert score_map[0] == pytest.approx(expected_50)
        assert score_map[1] == pytest.approx(expected_85)
        # The two must differ — subtle gap preserved
        assert score_map[0] != score_map[1]

    def test_empty(self):
        assert _normalize_scores([], self._MockProfile()) == []

    def test_negative_raw_clamped_to_zero(self):
        """Graph expansion can produce slightly negative composite scores; clamp to 0."""
        results = [(_doc(), -0.1)]
        normed = _normalize_scores(results, self._MockProfile())
        assert normed[0][1] == pytest.approx(0.0)


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
    async def test_graph_score_soft_saturation(self):
        """Graph score uses Michaelis-Menten: x / (x + norm_factor), never hits 1.0."""
        doc = _doc(doc_id="d1", chunk_index=0)
        edge_repo = FakeEdgeRepo({("d1", 0): 999})
        settings = FakeSettings()
        scoring = _general_scoring()
        result = await _apply_composite_scoring([(doc, 0.5)], edge_repo, "fact", settings, scoring)
        _, score = result[0]
        # 999 edges, norm_factor=10: graph_score = 999/(999+10) = 0.9901
        # Composite = 0.85*0.5 + 0.15*0.9901 = 0.425 + 0.1485 = 0.5735
        expected_graph = 999 / (999 + 10)
        assert score == pytest.approx(0.85 * 0.5 + 0.15 * expected_graph)
        # Graph contribution is below the naive 0.15 ceiling
        assert score < 0.85 * 0.5 + 0.15 * 1.0

    @pytest.mark.asyncio
    async def test_graph_score_discriminates(self):
        """Different edge counts give different graph scores (no saturation)."""
        docA = _doc(doc_id="d1", chunk_index=0, content="low edges")
        docB = _doc(doc_id="d1", chunk_index=1, content="many edges")
        edge_repo = FakeEdgeRepo({("d1", 0): 5, ("d1", 1): 50})
        settings = FakeSettings()
        scoring = _general_scoring()
        result = await _apply_composite_scoring(
            [(docA, 0.5), (docB, 0.5)], edge_repo, "fact", settings, scoring
        )
        score_map = {doc.metadata["chunk_index"]: s for doc, s in result}
        # Before fix, both would saturate at graph=1.0 → identical scores.
        # After fix, 50 edges gives higher graph score than 5.
        assert score_map[1] > score_map[0]

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
        # Use 30 edges so graph_score = 30/40 = 0.75, distinct from similarity
        edge_repo = FakeEdgeRepo({("d1", 0): 30})
        settings = FakeSettings()
        scoring = _general_scoring()

        fact_result = await _apply_composite_scoring([(doc, 0.5)], edge_repo, "fact", settings, scoring)
        overview_result = await _apply_composite_scoring([(doc, 0.5)], edge_repo, "overview", settings, scoring)

        _, fact_score = fact_result[0]
        _, overview_score = overview_result[0]
        # fact weights: [0.85, 0.15, 0.0, 0.0]; overview: [0.6, 0.4, 0.0, 0.0]
        # With similarity=0.5, 30 edges → graph_score = 30/(30+10) = 0.75:
        # fact:     0.85*0.5 + 0.15*0.75 = 0.425 + 0.1125 = 0.5375
        # overview: 0.6*0.5 + 0.4*0.75 = 0.3 + 0.30 = 0.60
        assert fact_score != pytest.approx(overview_score)
        assert overview_score > fact_score  # overview weights graph higher


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

    def test_output_sorted_desc(self):
        """Downstream pipeline invariant: output must be sorted score desc."""
        vector = [(_doc(chunk_index=i), 0.5) for i in range(5)]
        bm25 = [_doc(chunk_index=i) for i in [2, 0]]  # consensus on 0, 2
        result = _rrf_merge_bm25(vector, bm25, k=60)
        scores = [s for _, s in result]
        assert scores == sorted(scores, reverse=True), (
            f"output must be sorted desc, got {scores}"
        )


# ---------------------------------------------------------------------------
# Mandatory coverage — B2-A
# ---------------------------------------------------------------------------

class TestEnsurePerDocCoverageMandatory:
    """_ensure_per_doc_coverage marks highest-scored chunk per scope doc as
    _mandatory, and backfills absent docs with mandatory-flagged chunks."""

    def test_highest_scored_per_doc_marked_mandatory(self):
        """When scope doc has multiple chunks, only the highest-scored is mandatory."""
        retrieved = [
            (_doc(doc_id="d1", chunk_index=0, content="a"), 0.9),
            (_doc(doc_id="d1", chunk_index=1, content="b"), 0.5),
            (_doc(doc_id="d2", chunk_index=0, content="c"), 0.7),
            (_doc(doc_id="d3", chunk_index=0, content="d"), 0.3),
        ]
        result = _ensure_per_doc_coverage(retrieved, [], ["d1", "d2", "d3"], question="", vector_store=None)
        mandatory_keys = {
            (d.metadata.get("doc_id"), d.metadata.get("chunk_index"))
            for d, _ in result if d.metadata.get("_mandatory")
        }
        assert mandatory_keys == {("d1", 0), ("d2", 0), ("d3", 0)}

    def test_missing_doc_backfilled_and_mandatory(self):
        """Doc not in retrieved is backfilled from candidate pool with mandatory flag."""
        retrieved = [(_doc(doc_id="d1", chunk_index=0), 0.8)]
        all_candidates = [
            (_doc(doc_id="d2", chunk_index=0, content="backfill"), 0.2),
        ]
        result = _ensure_per_doc_coverage(retrieved, all_candidates, ["d1", "d2"], question="", vector_store=None)
        d2_chunks = [(d, s) for d, s in result if d.metadata.get("doc_id") == "d2"]
        assert len(d2_chunks) == 1
        assert d2_chunks[0][0].metadata.get("_mandatory") is True

    def test_single_doc_scope_no_mandatory(self):
        """Single-doc scope returns early without marking anything."""
        retrieved = [(_doc(doc_id="d1", chunk_index=0), 0.5)]
        result = _ensure_per_doc_coverage(retrieved, [], ["d1"], question="", vector_store=None)
        assert not any(d.metadata.get("_mandatory") for d, _ in result)


class TestApplyTokenBudgetMandatory:
    """_apply_token_budget guarantees mandatory chunks survive even under
    budget pressure."""

    def test_mandatory_survives_tight_budget(self):
        """8 mandatory chunks fit regardless of non-mandatory pressure."""
        # Each chunk ~ 20 tokens (content "word " * 20 ≈ 20 tokens)
        mandatory_docs = [
            _doc(doc_id=f"m{i}", chunk_index=0, content="word " * 20) for i in range(8)
        ]
        for d in mandatory_docs:
            d.metadata["_mandatory"] = True
        ordinary_docs = [
            _doc(doc_id=f"o{i}", chunk_index=0, content="word " * 20) for i in range(20)
        ]

        retrieved = [(d, 0.1) for d in mandatory_docs] + [(d, 0.9) for d in ordinary_docs]
        # budget = 300 tokens — fits all 8 mandatory + ~7 ordinary
        kept, used = _apply_token_budget(retrieved, chunk_budget=300)
        kept_mandatory = [d for d, _ in kept if d.metadata.get("_mandatory")]
        assert len(kept_mandatory) == 8, (
            f"expected all 8 mandatory kept, got {len(kept_mandatory)}"
        )

    def test_mandatory_overflow_kept_anyway(self):
        """When mandatory chunks alone exceed budget, all are kept with warning."""
        # 10 mandatory × ~40 tokens = 400 tokens, budget 100 → overflow
        mandatory = []
        for i in range(10):
            d = _doc(doc_id=f"m{i}", chunk_index=0, content="word " * 40)
            d.metadata["_mandatory"] = True
            mandatory.append((d, 0.5))
        kept, used = _apply_token_budget(mandatory, chunk_budget=100)
        kept_mandatory = [d for d, _ in kept if d.metadata.get("_mandatory")]
        assert len(kept_mandatory) == 10, "all mandatory must survive overflow"
        assert used > 100, "used tokens should exceed budget (mandatory overflow)"

    def test_mandatory_and_non_mandatory_pass_2_fills(self):
        """After mandatory, Pass 2 fills remaining budget with top-scored non-mandatory."""
        m = _doc(doc_id="m1", chunk_index=0, content="word " * 20)
        m.metadata["_mandatory"] = True
        high = _doc(doc_id="o1", chunk_index=0, content="word " * 20)
        low = _doc(doc_id="o2", chunk_index=0, content="word " * 20)
        retrieved = [(m, 0.1), (high, 0.9), (low, 0.3)]
        kept, used = _apply_token_budget(retrieved, chunk_budget=200)
        kept_ids = {d.metadata.get("doc_id") for d, _ in kept}
        assert "m1" in kept_ids, "mandatory must be kept"
        assert "o1" in kept_ids, "high-scored non-mandatory must be kept"


# ---------------------------------------------------------------------------
# Router hook in retrieve_and_rank
# ---------------------------------------------------------------------------

from unittest.mock import AsyncMock, MagicMock
from langchain_core.messages import AIMessage


class _FakeRegistry2:
    def __init__(self, docs):
        self._docs = docs
    async def get(self, doc_id):
        return self._docs.get(doc_id)


@pytest.mark.asyncio
class TestRouterHookInRetrieval:
    """When router_enabled=True and scope >= threshold, retrieve_and_rank
    narrows doc_ids via router before vector search."""

    async def test_router_narrows_scope_when_above_threshold(self, monkeypatch):
        from app.services import retrieval as retrieval_mod

        # Capture the doc_ids passed to similarity_search_with_scores
        captured = {}
        def fake_search(question, k, doc_ids=None):
            captured["doc_ids"] = doc_ids
            return []
        vector_store = MagicMock()
        vector_store.similarity_search_with_scores = fake_search
        vector_store.get_all_documents = MagicMock(return_value=[])
        vector_store.get_chunks_by_doc = MagicMock(return_value=[])

        # Registry with 20 docs
        docs = {f"d{i}": {"doc_id": f"d{i}", "source_file": f"f{i}.pdf",
                          "summary": f"doc {i}"} for i in range(20)}
        registry = _FakeRegistry2(docs)

        # LLM: analyze returns "fact"; router returns a subset of 5
        llm = AsyncMock()
        async def fake_ainvoke(messages):
            content = messages[0].content if messages else ""
            if "document router" in content.lower():
                return AIMessage(content='{"doc_ids": ["d0","d1","d2","d3","d4"]}')
            # analyze_query response
            return AIMessage(content='{"types": ["fact"], "label": null}')
        llm.ainvoke = fake_ainvoke

        settings = MagicMock()
        settings.router_enabled = True
        settings.router_min_scope = 15
        settings.router_top_k = 8
        settings.per_doc_coverage_max_backfill = 30
        settings.rerank_max_candidates = 80
        settings.router_model = "gpt-4o-mini"
        settings.hybrid_search_enabled = False
        settings.rerank_enabled = False
        settings.query_expansion_enabled = False
        settings.visual_proximity_enabled = False
        settings.web_search_enabled = False
        settings.query_types_file = "data/query_types.json"
        settings.scoring_profile = "general"
        settings.context_budget_ratio = 0.6
        settings.reserved_output_tokens = 2048
        settings.reserved_prompt_overhead_tokens = 512
        settings.max_context_tokens = None
        settings.history_min_reserve_ratio = 0.2
        settings.history_max_budget_ratio = 0.4
        settings.openai_model = "gpt-4o-mini"
        settings.llm_provider = MagicMock()
        settings.llm_provider.value = "openai"

        edge_repo = AsyncMock()
        edge_repo.get_edge_type_counts_batch = AsyncMock(return_value={})
        edge_repo.get_edges_from = AsyncMock(return_value=[])

        scope = [f"d{i}" for i in range(20)]
        await retrieval_mod.retrieve_and_rank(
            question="What is the param count of d0?",
            top_k=4,
            doc_ids=scope,
            user_scoped=True,
            llm=llm,
            vector_store=vector_store,
            embeddings=MagicMock(),
            edge_repo=edge_repo,
            settings=settings,
            registry=registry,
        )
        # After router, doc_ids passed to vector search is the 5-item subset
        assert captured["doc_ids"] == ["d0", "d1", "d2", "d3", "d4"]

    async def test_router_bypassed_when_below_threshold(self, monkeypatch):
        """Scope below router_min_scope -> router not called, full scope used."""
        from app.services import retrieval as retrieval_mod

        captured = {}
        def fake_search(question, k, doc_ids=None):
            captured["doc_ids"] = doc_ids
            return []
        vector_store = MagicMock()
        vector_store.similarity_search_with_scores = fake_search
        vector_store.get_all_documents = MagicMock(return_value=[])
        vector_store.get_chunks_by_doc = MagicMock(return_value=[])

        registry = _FakeRegistry2({})  # shouldn't be touched

        llm = AsyncMock()
        # Only analyze_query is called — router is skipped
        llm.ainvoke = AsyncMock(
            return_value=AIMessage(content='{"types": ["fact"], "label": null}'),
        )

        settings = MagicMock()
        settings.router_enabled = True
        settings.router_min_scope = 15
        settings.router_top_k = 8
        settings.per_doc_coverage_max_backfill = 30
        settings.rerank_max_candidates = 80
        settings.hybrid_search_enabled = False
        settings.rerank_enabled = False
        settings.query_expansion_enabled = False
        settings.visual_proximity_enabled = False
        settings.web_search_enabled = False
        settings.query_types_file = "data/query_types.json"
        settings.scoring_profile = "general"
        settings.context_budget_ratio = 0.6
        settings.reserved_output_tokens = 2048
        settings.reserved_prompt_overhead_tokens = 512
        settings.max_context_tokens = None
        settings.history_min_reserve_ratio = 0.2
        settings.history_max_budget_ratio = 0.4
        settings.openai_model = "gpt-4o-mini"
        settings.llm_provider = MagicMock()
        settings.llm_provider.value = "openai"

        edge_repo = AsyncMock()
        edge_repo.get_edge_type_counts_batch = AsyncMock(return_value={})
        edge_repo.get_edges_from = AsyncMock(return_value=[])

        small_scope = ["d0", "d1", "d2"]
        await retrieval_mod.retrieve_and_rank(
            question="q",
            top_k=4,
            doc_ids=small_scope,
            user_scoped=True,
            llm=llm,
            vector_store=vector_store,
            embeddings=MagicMock(),
            edge_repo=edge_repo,
            settings=settings,
            registry=registry,
        )
        assert captured["doc_ids"] == small_scope
        # Only analyze_query was invoked, no router call
        assert llm.ainvoke.await_count == 1

    async def test_router_disabled_by_flag(self):
        """Even with scope >= threshold, router_enabled=False skips it."""
        from app.services import retrieval as retrieval_mod

        captured = {}
        def fake_search(question, k, doc_ids=None):
            captured["doc_ids"] = doc_ids
            return []
        vector_store = MagicMock()
        vector_store.similarity_search_with_scores = fake_search
        vector_store.get_all_documents = MagicMock(return_value=[])
        vector_store.get_chunks_by_doc = MagicMock(return_value=[])

        registry = _FakeRegistry2({})
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(
            return_value=AIMessage(content='{"types": ["fact"], "label": null}'),
        )

        settings = MagicMock()
        settings.router_enabled = False  # off
        settings.router_min_scope = 15
        settings.router_top_k = 8
        settings.per_doc_coverage_max_backfill = 30
        settings.rerank_max_candidates = 80
        settings.hybrid_search_enabled = False
        settings.rerank_enabled = False
        settings.query_expansion_enabled = False
        settings.visual_proximity_enabled = False
        settings.web_search_enabled = False
        settings.query_types_file = "data/query_types.json"
        settings.scoring_profile = "general"
        settings.context_budget_ratio = 0.6
        settings.reserved_output_tokens = 2048
        settings.reserved_prompt_overhead_tokens = 512
        settings.max_context_tokens = None
        settings.history_min_reserve_ratio = 0.2
        settings.history_max_budget_ratio = 0.4
        settings.openai_model = "gpt-4o-mini"
        settings.llm_provider = MagicMock()
        settings.llm_provider.value = "openai"

        edge_repo = AsyncMock()
        edge_repo.get_edge_type_counts_batch = AsyncMock(return_value={})
        edge_repo.get_edges_from = AsyncMock(return_value=[])

        big_scope = [f"d{i}" for i in range(20)]
        await retrieval_mod.retrieve_and_rank(
            question="q",
            top_k=4,
            doc_ids=big_scope,
            user_scoped=True,
            llm=llm,
            vector_store=vector_store,
            embeddings=MagicMock(),
            edge_repo=edge_repo,
            settings=settings,
            registry=registry,
        )
        assert captured["doc_ids"] == big_scope
        assert llm.ainvoke.await_count == 1  # only analyze_query
