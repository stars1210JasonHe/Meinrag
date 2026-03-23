"""Tests for chunk quality helpers.

Covers garbage table filtering, deduplication, reference section tagging,
and retrieval-time quality fixes.
"""
import pytest
from langchain_core.documents import Document

from app.services.chunk_utils import (
    is_garbage_table as _is_garbage_table,
    deduplicate_chunks as _deduplicate_chunks,
    tag_reference_chunks as _tag_reference_chunks,
)


# ── Task 2: Garbage table filter ────────────────────────────────────────


class TestGarbageTableFilter:
    def test_generic_column_headers_detected(self):
        md = "|Col1|Col2|Col3|Col4|Col5|\n|---|---|---|---|---|\n|a|b|c|d|e|"
        assert _is_garbage_table(md) is True

    def test_single_char_cells_detected(self):
        md = "|It|is|in|is|rit|at|a|ty|of|n|ts|e|d|w|s|e|"
        assert _is_garbage_table(md) is True

    def test_meaningful_table_kept(self):
        md = "|Parser|Training|WSJ 23 F1|\n|---|---|---|\n|Vinyals (2014)|WSJ|88.3|"
        assert _is_garbage_table(md) is False

    def test_data_table_kept(self):
        md = "|Model|BLEU|PPL|Parameters|\n|---|---|---|---|\n|Transformer|28.4|4.92|65M|"
        assert _is_garbage_table(md) is False

    def test_empty_table_is_garbage(self):
        assert _is_garbage_table("") is True
        assert _is_garbage_table("||\n||") is True

    def test_whitespace_only_is_garbage(self):
        assert _is_garbage_table("   \n  \t  ") is True

    def test_two_generic_headers_not_enough(self):
        md = "|Col1|Col2|Score|\n|---|---|---|\n|a|b|0.9|"
        assert _is_garbage_table(md) is False


# ── Task 3: Deduplication ────────────────────────────────────────────────


class TestDeduplication:
    def test_identical_chunks_removed(self):
        chunks = [
            Document(page_content="Hello world", metadata={"chunk_index": 0}),
            Document(page_content="Hello world", metadata={"chunk_index": 1}),
            Document(page_content="Different text", metadata={"chunk_index": 2}),
        ]
        result = _deduplicate_chunks(chunks)
        assert len(result) == 2
        assert result[0].page_content == "Hello world"
        assert result[1].page_content == "Different text"

    def test_near_duplicate_kept(self):
        chunks = [
            Document(page_content="Hello world", metadata={"chunk_index": 0}),
            Document(page_content="Hello world!", metadata={"chunk_index": 1}),
        ]
        result = _deduplicate_chunks(chunks)
        assert len(result) == 2

    def test_whitespace_normalization(self):
        chunks = [
            Document(page_content="Hello  world\n", metadata={"chunk_index": 0}),
            Document(page_content="Hello world", metadata={"chunk_index": 1}),
        ]
        result = _deduplicate_chunks(chunks)
        assert len(result) == 1

    def test_empty_input(self):
        assert _deduplicate_chunks([]) == []

    def test_preserves_order(self):
        chunks = [
            Document(page_content="AAA", metadata={"pos": 1}),
            Document(page_content="BBB", metadata={"pos": 2}),
            Document(page_content="AAA", metadata={"pos": 3}),
            Document(page_content="CCC", metadata={"pos": 4}),
        ]
        result = _deduplicate_chunks(chunks)
        assert [c.metadata["pos"] for c in result] == [1, 2, 4]


# ── Task 4: Reference section tagging ───────────────────────────────────


class TestReferenceTagging:
    def test_heading_based_detection(self):
        chunks = [
            Document(page_content="The model uses attention.", metadata={"headings": "3 Model Architecture"}),
            Document(page_content="[1] Author et al. Title.", metadata={"headings": "References"}),
            Document(page_content="[2] Another reference.", metadata={"headings": "References"}),
        ]
        _tag_reference_chunks(chunks)
        assert chunks[0].metadata.get("section") is None
        assert chunks[1].metadata.get("section") == "references"
        assert chunks[2].metadata.get("section") == "references"

    def test_bibliography_heading(self):
        chunks = [
            Document(page_content="[1] Some reference.", metadata={"headings": "Bibliography"}),
        ]
        _tag_reference_chunks(chunks)
        assert chunks[0].metadata.get("section") == "references"

    def test_works_cited_heading(self):
        chunks = [
            Document(page_content="[1] Some reference.", metadata={"headings": "Works Cited"}),
        ]
        _tag_reference_chunks(chunks)
        assert chunks[0].metadata.get("section") == "references"

    def test_no_headings_fallback_to_text(self):
        chunks = [
            Document(page_content="[1] Author, Title. In Proceedings of NeurIPS, 2020.", metadata={}),
        ]
        _tag_reference_chunks(chunks)
        assert chunks[0].metadata.get("section") == "references"

    def test_normal_text_not_tagged(self):
        chunks = [
            Document(page_content="We use a transformer architecture with multi-head attention.", metadata={}),
        ]
        _tag_reference_chunks(chunks)
        assert chunks[0].metadata.get("section") is None

    def test_case_insensitive_heading(self):
        chunks = [
            Document(page_content="[1] Some ref.", metadata={"headings": "REFERENCES"}),
        ]
        _tag_reference_chunks(chunks)
        assert chunks[0].metadata.get("section") == "references"


# ── Task 5: Reference score penalty ──────────────────────────────────


class TestReferenceScorePenalty:
    def test_reference_chunk_penalized(self):
        from app.routers.query import _apply_reference_penalty
        results = [
            (Document(page_content="Real content", metadata={}), 0.6),
            (Document(page_content="[1] Author et al.", metadata={"section": "references"}), 0.5),
        ]
        penalized = _apply_reference_penalty(results)
        assert penalized[0][1] == 0.6
        assert penalized[1][1] == pytest.approx(0.5 * 0.3)

    def test_non_reference_unchanged(self):
        from app.routers.query import _apply_reference_penalty
        results = [
            (Document(page_content="Normal text", metadata={}), 0.8),
            (Document(page_content="Another chunk", metadata={"section": "introduction"}), 0.7),
        ]
        penalized = _apply_reference_penalty(results)
        assert penalized[0][1] == 0.8
        assert penalized[1][1] == 0.7

    def test_empty_results(self):
        from app.routers.query import _apply_reference_penalty
        assert _apply_reference_penalty([]) == []
