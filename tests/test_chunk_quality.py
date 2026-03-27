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
    classify_section_type,
    classify_section_from_headings,
    enrich_section_metadata,
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


# ── Task 8: Section type classifier ──────────────────────────────────────


class TestSectionClassifier:
    def test_abstract(self):
        assert classify_section_type("Abstract") == "abstract"
        assert classify_section_type("ABSTRACT") == "abstract"

    def test_introduction(self):
        assert classify_section_type("1 Introduction") == "introduction"
        assert classify_section_type("Introduction") == "introduction"

    def test_methods(self):
        assert classify_section_type("3 Model Architecture") == "methods"
        assert classify_section_type("Methodology") == "methods"
        assert classify_section_type("Proposed Approach") == "methods"
        assert classify_section_type("3.1 Model Design") == "methods"

    def test_methods_subsection_via_heading_chain(self):
        """Subsections without keywords are resolved via the parent heading chain."""
        assert classify_section_from_headings("3 Model Architecture > 3.1 Encoder and Decoder Stacks") == "methods"

    def test_results(self):
        assert classify_section_type("6 Results") == "results"
        assert classify_section_type("Experiments") == "results"

    def test_discussion(self):
        assert classify_section_type("7 Conclusion") == "discussion"
        assert classify_section_type("Discussion") == "discussion"
        assert classify_section_type("Future Work") == "discussion"

    def test_references(self):
        assert classify_section_type("References") == "references"
        assert classify_section_type("Bibliography") == "references"

    def test_appendix(self):
        assert classify_section_type("Appendix A") == "appendix"
        assert classify_section_type("Supplementary Material") == "appendix"

    def test_training(self):
        assert classify_section_type("5 Training") == "training"
        assert classify_section_type("Training Details") == "training"

    def test_unknown_defaults_to_body(self):
        assert classify_section_type("Some Random Heading") == "body"
        assert classify_section_type("") == "body"
        assert classify_section_type(None) == "body"

    def test_heading_chain(self):
        assert classify_section_from_headings("3 Model Architecture > 3.1 Attention") == "methods"
        assert classify_section_from_headings("References") == "references"
        assert classify_section_from_headings(None) == "body"
        assert classify_section_from_headings("") == "body"


# ── Task 9: Section metadata enrichment ──────────────────────────────────


class TestSectionMetadata:
    def test_text_chunk_gets_section(self):
        chunks = [
            Document(page_content="We propose a model...", metadata={"headings": "3 Model Architecture", "chunk_type": "text", "page": 3}),
            Document(page_content="Results show...", metadata={"headings": "6 Results > 6.1 Translation", "chunk_type": "text", "page": 7}),
            Document(page_content="[1] Author et al.", metadata={"headings": "References", "chunk_type": "text", "page": 12}),
        ]
        enrich_section_metadata(chunks)
        assert chunks[0].metadata["section_type"] == "methods"
        assert chunks[1].metadata["section_type"] == "results"
        assert chunks[2].metadata["section_type"] == "references"

    def test_text_chunk_no_headings_gets_body(self):
        """A chunk with no headings and no nearby classified chunks gets 'body'."""
        chunks = [
            Document(page_content="Some content", metadata={"chunk_type": "text"}),
        ]
        enrich_section_metadata(chunks)
        assert chunks[0].metadata["section_type"] == "body"

    def test_table_inherits_nearest_section(self):
        chunks = [
            Document(page_content="Training details...", metadata={"headings": "5 Training", "chunk_type": "text", "page": 6}),
            Document(page_content="|Model|BLEU|", metadata={"chunk_type": "table", "page": 7}),
            Document(page_content="Results...", metadata={"headings": "6 Results", "chunk_type": "text", "page": 7}),
        ]
        enrich_section_metadata(chunks)
        assert chunks[0].metadata["section_type"] == "training"
        assert chunks[1].metadata["section_type"] in ("training", "results")
        assert chunks[2].metadata["section_type"] == "results"

    def test_empty_chunks(self):
        enrich_section_metadata([])  # should not crash

    def test_reference_section_tag_inherited(self):
        chunks = [
            Document(page_content="[1] Author et al.", metadata={"section": "references", "chunk_type": "text"}),
        ]
        enrich_section_metadata(chunks)
        assert chunks[0].metadata["section_type"] == "references"

    def test_image_inherits_from_nearest_page(self):
        chunks = [
            Document(page_content="Introduction text", metadata={"headings": "1 Introduction", "chunk_type": "text", "page": 1}),
            Document(page_content="Figure 1", metadata={"chunk_type": "image", "page": 2}),
        ]
        enrich_section_metadata(chunks)
        assert chunks[1].metadata["section_type"] == "introduction"


# ── Task 10: Section-based score weighting ────────────────────────────────


class TestSectionScoreWeighting:
    def test_acknowledgment_penalized(self):
        from app.routers.query import _apply_section_weights
        results = [
            (Document(page_content="Thanks to...", metadata={"section_type": "acknowledgment"}), 0.5),
        ]
        weighted = _apply_section_weights(results)
        assert weighted[0][1] == pytest.approx(0.5 * 0.4)

    def test_appendix_penalized(self):
        from app.routers.query import _apply_section_weights
        results = [
            (Document(page_content="Appendix content", metadata={"section_type": "appendix"}), 0.5),
        ]
        weighted = _apply_section_weights(results)
        assert weighted[0][1] == pytest.approx(0.5 * 0.7)

    def test_body_sections_unchanged(self):
        from app.routers.query import _apply_section_weights
        results = [
            (Document(page_content="Methods", metadata={"section_type": "methods"}), 0.7),
            (Document(page_content="Results", metadata={"section_type": "results"}), 0.6),
            (Document(page_content="Intro", metadata={"section_type": "introduction"}), 0.5),
        ]
        weighted = _apply_section_weights(results)
        assert weighted[0][1] == 0.7
        assert weighted[1][1] == 0.6
        assert weighted[2][1] == 0.5

    def test_references_not_double_penalized(self):
        from app.routers.query import _apply_section_weights
        results = [
            (Document(page_content="[1] Author", metadata={"section_type": "references", "section": "references"}), 0.15),
        ]
        weighted = _apply_section_weights(results)
        assert weighted[0][1] == 0.15  # unchanged — handled by reference penalty


# ── Task 1 (bbox plan): Bbox merging ──────────────────────────────────────


class TestBboxMerging:
    def test_single_element_bbox(self):
        from app.services.docling_processor import _merge_element_bboxes
        elements = [{"page": 1, "bbox": [100, 200, 400, 250]}]
        result = _merge_element_bboxes(elements, target_page=1)
        assert result == [100, 200, 400, 250]

    def test_multiple_elements_merged(self):
        from app.services.docling_processor import _merge_element_bboxes
        elements = [
            {"page": 1, "bbox": [100, 200, 400, 250]},
            {"page": 1, "bbox": [100, 260, 400, 310]},
            {"page": 1, "bbox": [80, 320, 420, 370]},
        ]
        result = _merge_element_bboxes(elements, target_page=1)
        assert result == [80, 200, 420, 370]

    def test_multi_page_uses_target_page(self):
        from app.services.docling_processor import _merge_element_bboxes
        elements = [
            {"page": 2, "bbox": [100, 500, 400, 600]},
            {"page": 2, "bbox": [100, 610, 400, 700]},
            {"page": 3, "bbox": [100, 50, 400, 100]},
        ]
        result = _merge_element_bboxes(elements, target_page=2)
        assert result == [100, 500, 400, 700]

    def test_no_elements_on_target_page(self):
        from app.services.docling_processor import _merge_element_bboxes
        elements = [{"page": 3, "bbox": [100, 200, 400, 250]}]
        result = _merge_element_bboxes(elements, target_page=1)
        assert result is None

    def test_empty_elements(self):
        from app.services.docling_processor import _merge_element_bboxes
        assert _merge_element_bboxes([], target_page=1) is None


# ── Open/Closed question classification ──────────────────────────────────


class TestQuestionClassification:
    """Test _classify_question() with mock LLM."""

    @pytest.mark.asyncio
    async def test_open_question(self):
        from app.routers.query import _classify_question

        class MockLLM:
            async def ainvoke(self, input):
                class Resp:
                    content = "open"
                return Resp()

        result = await _classify_question("Summarize this paper", MockLLM())
        assert result == "open"

    @pytest.mark.asyncio
    async def test_closed_question(self):
        from app.routers.query import _classify_question

        class MockLLM:
            async def ainvoke(self, input):
                class Resp:
                    content = "closed"
                return Resp()

        result = await _classify_question("What BLEU score did the model achieve?", MockLLM())
        assert result == "closed"

    @pytest.mark.asyncio
    async def test_llm_failure_defaults_to_closed(self):
        from app.routers.query import _classify_question

        class MockLLM:
            async def ainvoke(self, input):
                raise RuntimeError("LLM error")

        result = await _classify_question("Some question", MockLLM())
        assert result == "closed"

    @pytest.mark.asyncio
    async def test_unexpected_response_defaults_to_closed(self):
        from app.routers.query import _classify_question

        class MockLLM:
            async def ainvoke(self, input):
                class Resp:
                    content = "maybe open maybe not"
                return Resp()

        result = await _classify_question("Some question", MockLLM())
        assert result == "closed"


# ── Section-aware sampling ───────────────────────────────────────────────


class TestSectionAwareSampling:
    """Test _section_aware_sample() picks best chunk per section."""

    def test_one_per_section(self):
        from app.routers.query import _section_aware_sample
        results = [
            (Document(page_content="Intro text 1", metadata={"section_type": "introduction"}), 0.8),
            (Document(page_content="Intro text 2", metadata={"section_type": "introduction"}), 0.6),
            (Document(page_content="Methods text", metadata={"section_type": "methods"}), 0.7),
            (Document(page_content="Results text", metadata={"section_type": "results"}), 0.5),
            (Document(page_content="Conclusion", metadata={"section_type": "discussion"}), 0.4),
        ]
        sampled = _section_aware_sample(results)
        # Should pick best from each section: intro(0.8), methods(0.7), results(0.5), discussion(0.4)
        assert len(sampled) == 4
        contents = [doc.page_content for doc, _ in sampled]
        assert "Intro text 1" in contents
        assert "Intro text 2" not in contents
        assert "Methods text" in contents

    def test_sorted_by_score_descending(self):
        from app.routers.query import _section_aware_sample
        results = [
            (Document(page_content="A", metadata={"section_type": "introduction"}), 0.3),
            (Document(page_content="B", metadata={"section_type": "methods"}), 0.9),
            (Document(page_content="C", metadata={"section_type": "results"}), 0.6),
        ]
        sampled = _section_aware_sample(results)
        scores = [score for _, score in sampled]
        assert scores == sorted(scores, reverse=True)

    def test_missing_section_type_uses_body(self):
        from app.routers.query import _section_aware_sample
        results = [
            (Document(page_content="No section", metadata={}), 0.5),
            (Document(page_content="Has section", metadata={"section_type": "methods"}), 0.6),
        ]
        sampled = _section_aware_sample(results)
        assert len(sampled) == 2

    def test_empty_results(self):
        from app.routers.query import _section_aware_sample
        assert _section_aware_sample([]) == []

    def test_single_section_returns_one(self):
        from app.routers.query import _section_aware_sample
        results = [
            (Document(page_content="A", metadata={"section_type": "introduction"}), 0.8),
            (Document(page_content="B", metadata={"section_type": "introduction"}), 0.6),
            (Document(page_content="C", metadata={"section_type": "introduction"}), 0.4),
        ]
        sampled = _section_aware_sample(results)
        assert len(sampled) == 1
        assert sampled[0][0].page_content == "A"


# ── Visual proximity linking ─────────────────────────────────────────────


class TestVisualProximityLinking:
    """Test _link_nearby_visuals() pulls in visual chunks from adjacent pages."""

    def _make_store(self, chunks_by_doc):
        """Create a mock vector store with get_chunks_by_doc."""
        class MockStore:
            def __init__(self, data):
                self._data = data
            def get_chunks_by_doc(self, doc_id):
                return self._data.get(doc_id, [])
        return MockStore(chunks_by_doc)

    def test_links_table_on_same_page(self):
        from app.routers.query import _link_nearby_visuals

        text_chunk = Document(
            page_content="As shown in Table 1...",
            metadata={"doc_id": "doc1", "page": 5, "chunk_type": "text", "chunk_index": 0},
        )
        table_chunk = Document(
            page_content="|Model|BLEU|\n|---|---|\n|Transformer|28.4|",
            metadata={"doc_id": "doc1", "page": 5, "chunk_type": "table", "chunk_index": 1},
        )
        store = self._make_store({"doc1": [text_chunk, table_chunk]})
        retrieved = [(text_chunk, 0.8)]

        result = _link_nearby_visuals(retrieved, store, ["doc1"], proximity_pages=1)
        assert len(result) == 2
        assert result[1][0].page_content == table_chunk.page_content

    def test_links_image_on_adjacent_page(self):
        from app.routers.query import _link_nearby_visuals

        text_chunk = Document(
            page_content="See Figure 1...",
            metadata={"doc_id": "doc1", "page": 3, "chunk_type": "text", "chunk_index": 0},
        )
        image_chunk = Document(
            page_content="Figure 1. Architecture diagram",
            metadata={"doc_id": "doc1", "page": 4, "chunk_type": "image", "chunk_index": 1, "image_path": "/img.png"},
        )
        store = self._make_store({"doc1": [text_chunk, image_chunk]})
        retrieved = [(text_chunk, 0.7)]

        result = _link_nearby_visuals(retrieved, store, ["doc1"], proximity_pages=1)
        assert len(result) == 2

    def test_skips_distant_page(self):
        from app.routers.query import _link_nearby_visuals

        text_chunk = Document(
            page_content="Some text",
            metadata={"doc_id": "doc1", "page": 2, "chunk_type": "text", "chunk_index": 0},
        )
        far_table = Document(
            page_content="|A|B|\n|---|---|\n|1|2|",
            metadata={"doc_id": "doc1", "page": 10, "chunk_type": "table", "chunk_index": 1},
        )
        store = self._make_store({"doc1": [text_chunk, far_table]})
        retrieved = [(text_chunk, 0.6)]

        result = _link_nearby_visuals(retrieved, store, ["doc1"], proximity_pages=1)
        assert len(result) == 1  # no visuals linked

    def test_skips_already_retrieved(self):
        from app.routers.query import _link_nearby_visuals

        text_chunk = Document(
            page_content="Text",
            metadata={"doc_id": "doc1", "page": 5, "chunk_type": "text", "chunk_index": 0},
        )
        table_chunk = Document(
            page_content="|A|B|",
            metadata={"doc_id": "doc1", "page": 5, "chunk_type": "table", "chunk_index": 1},
        )
        store = self._make_store({"doc1": [text_chunk, table_chunk]})
        # table already in retrieved
        retrieved = [(text_chunk, 0.8), (table_chunk, 0.5)]

        result = _link_nearby_visuals(retrieved, store, ["doc1"], proximity_pages=1)
        assert len(result) == 2  # no duplicates added

    def test_skips_image_without_image_path(self):
        from app.routers.query import _link_nearby_visuals

        text_chunk = Document(
            page_content="Text",
            metadata={"doc_id": "doc1", "page": 5, "chunk_type": "text", "chunk_index": 0},
        )
        bad_image = Document(
            page_content="Figure caption",
            metadata={"doc_id": "doc1", "page": 5, "chunk_type": "image", "chunk_index": 1},
        )
        store = self._make_store({"doc1": [text_chunk, bad_image]})
        retrieved = [(text_chunk, 0.7)]

        result = _link_nearby_visuals(retrieved, store, ["doc1"], proximity_pages=1)
        assert len(result) == 1  # image without image_path skipped

    def test_filters_garbage_tables(self):
        from app.routers.query import _link_nearby_visuals

        text_chunk = Document(
            page_content="Text",
            metadata={"doc_id": "doc1", "page": 5, "chunk_type": "text", "chunk_index": 0},
        )
        garbage = Document(
            page_content="|Col1|Col2|Col3|Col4|Col5|\n|---|---|---|---|---|\n|a|b|c|d|e|",
            metadata={"doc_id": "doc1", "page": 5, "chunk_type": "table", "chunk_index": 1},
        )
        store = self._make_store({"doc1": [text_chunk, garbage]})
        retrieved = [(text_chunk, 0.7)]

        result = _link_nearby_visuals(retrieved, store, ["doc1"], proximity_pages=1)
        assert len(result) == 1  # garbage table filtered

    def test_no_doc_ids_returns_unchanged(self):
        from app.routers.query import _link_nearby_visuals

        text_chunk = Document(
            page_content="Text",
            metadata={"doc_id": "doc1", "page": 5, "chunk_type": "text", "chunk_index": 0},
        )
        retrieved = [(text_chunk, 0.7)]
        result = _link_nearby_visuals(retrieved, None, None, proximity_pages=1)
        assert len(result) == 1

    def test_empty_retrieved(self):
        from app.routers.query import _link_nearby_visuals

        class MockStore:
            def get_chunks_by_doc(self, doc_id):
                return []
        result = _link_nearby_visuals([], MockStore(), ["doc1"], proximity_pages=1)
        assert result == []


# ── LLM label extraction during ingestion ────────────────────────────────


class TestLLMLabelExtraction:
    """Test _extract_label_llm() extracts and normalizes labels via LLM."""

    @pytest.mark.asyncio
    async def test_table_label(self):
        from app.services.docling_processor import _extract_label_llm

        class MockLLM:
            async def ainvoke(self, input):
                class R:
                    content = "Table 1"
                return R()

        result = await _extract_label_llm("Table 1: Maximum path lengths", MockLLM())
        assert result == "Table 1"

    @pytest.mark.asyncio
    async def test_no_label(self):
        from app.services.docling_processor import _extract_label_llm

        class MockLLM:
            async def ainvoke(self, input):
                class R:
                    content = "none"
                return R()

        result = await _extract_label_llm("| Col1 | Col2 |", MockLLM())
        assert result is None

    @pytest.mark.asyncio
    async def test_llm_failure(self):
        from app.services.docling_processor import _extract_label_llm

        class MockLLM:
            async def ainvoke(self, input):
                raise RuntimeError("fail")

        result = await _extract_label_llm("Figure 1: arch", MockLLM())
        assert result is None

    @pytest.mark.asyncio
    async def test_long_response_rejected(self):
        from app.services.docling_processor import _extract_label_llm

        class MockLLM:
            async def ainvoke(self, input):
                class R:
                    content = "This is a very long response that is not a label"
                return R()

        result = await _extract_label_llm("some text", MockLLM())
        assert result is None

    @pytest.mark.asyncio
    async def test_short_content_skipped(self):
        from app.services.docling_processor import _extract_label_llm

        class MockLLM:
            async def ainvoke(self, input):
                class R:
                    content = "Table 1"
                return R()

        result = await _extract_label_llm("ab", MockLLM())
        assert result is None


# ── Query label detection ────────────────────────────────────────────────


class TestQueryLabelDetection:
    """Test _extract_query_label() detects label references in queries."""

    @pytest.mark.asyncio
    async def test_table_reference(self):
        from app.routers.query import _extract_query_label

        class MockLLM:
            async def ainvoke(self, input):
                class R:
                    content = "Table 1"
                return R()

        result = await _extract_query_label("Show me table 1", MockLLM())
        assert result == "Table 1"

    @pytest.mark.asyncio
    async def test_no_reference(self):
        from app.routers.query import _extract_query_label

        class MockLLM:
            async def ainvoke(self, input):
                class R:
                    content = "none"
                return R()

        result = await _extract_query_label("What is attention?", MockLLM())
        assert result is None

    @pytest.mark.asyncio
    async def test_llm_failure(self):
        from app.routers.query import _extract_query_label

        class MockLLM:
            async def ainvoke(self, input):
                raise RuntimeError("fail")

        result = await _extract_query_label("Table 1", MockLLM())
        assert result is None


# ── Label lookup ─────────────────────────────────────────────────────────


class TestLabelLookup:
    """Test _lookup_by_label() finds chunks by label metadata."""

    def _make_store(self, chunks_by_doc):
        class MockStore:
            def __init__(self, data):
                self._data = data
            def get_chunks_by_doc(self, doc_id):
                return self._data.get(doc_id, [])
        return MockStore(chunks_by_doc)

    def test_finds_table_by_label(self):
        from app.routers.query import _lookup_by_label

        table = Document(
            page_content="Table 1: Max path lengths",
            metadata={"doc_id": "doc1", "chunk_type": "table", "label": "Table 1", "page": 5},
        )
        other = Document(
            page_content="Table 2: BLEU scores",
            metadata={"doc_id": "doc1", "chunk_type": "table", "label": "Table 2", "page": 7},
        )
        store = self._make_store({"doc1": [table, other]})
        result = _lookup_by_label("Table 1", store, ["doc1"])
        assert len(result) == 1
        assert result[0].page_content == "Table 1: Max path lengths"

    def test_case_insensitive(self):
        from app.routers.query import _lookup_by_label

        table = Document(
            page_content="Table 1: data",
            metadata={"doc_id": "doc1", "label": "Table 1", "page": 5},
        )
        store = self._make_store({"doc1": [table]})
        result = _lookup_by_label("table 1", store, ["doc1"])
        assert len(result) == 1

    def test_no_match(self):
        from app.routers.query import _lookup_by_label

        table = Document(
            page_content="Table 2: data",
            metadata={"doc_id": "doc1", "label": "Table 2", "page": 5},
        )
        store = self._make_store({"doc1": [table]})
        result = _lookup_by_label("Table 99", store, ["doc1"])
        assert len(result) == 0

    def test_no_doc_ids(self):
        from app.routers.query import _lookup_by_label

        class MockStore:
            def get_chunks_by_doc(self, doc_id):
                return []

        result = _lookup_by_label("Table 1", MockStore(), None)
        assert len(result) == 0
