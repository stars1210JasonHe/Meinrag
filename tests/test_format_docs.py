"""Unit tests for app.rag.chain.format_docs.

Focuses on the doc_summaries overview block added for B2-A multi-doc queries.
"""
from __future__ import annotations

from langchain_core.documents import Document

from app.rag.chain import format_docs


def _doc(doc_id, chunk_index, content, source_file=None, page=0, summary=None):
    meta = {
        "doc_id": doc_id,
        "chunk_index": chunk_index,
        "source_file": source_file or f"{doc_id}.pdf",
        "page": page,
    }
    if summary is not None:
        meta["summary"] = summary
    return Document(page_content=content, metadata=meta)


class TestFormatDocsOverview:
    def test_no_summaries_backwards_compat(self):
        """When doc_summaries is None, output has no overview block."""
        docs = [_doc("d1", 0, "content A"), _doc("d2", 0, "content B")]
        out = format_docs(docs)
        assert "=== Document overviews ===" not in out
        assert "content A" in out
        assert "content B" in out

    def test_empty_summaries_dict_acts_as_none(self):
        """Empty dict should not emit the overview block."""
        docs = [_doc("d1", 0, "content A")]
        out = format_docs(docs, doc_summaries={})
        # Code treats empty dict as no overview (via `if overview_lines`)
        assert "=== Document overviews ===" not in out

    def test_full_summaries_emit_overview_block(self):
        """When all docs have summaries, overview block appears at top."""
        docs = [
            _doc("d1", 0, "content A", source_file="alpha.pdf"),
            _doc("d2", 0, "content B", source_file="beta.pdf"),
        ]
        summaries = {"d1": "Alpha is about cats.", "d2": "Beta is about dogs."}
        out = format_docs(docs, doc_summaries=summaries)
        assert "=== Document overviews ===" in out
        assert "[alpha]: Alpha is about cats." in out
        assert "[beta]: Beta is about dogs." in out
        # Overview must come before retrieved chunks
        assert out.index("=== Document overviews ===") < out.index("content A")

    def test_partial_summaries_only_included_docs(self):
        """Only docs with entries in doc_summaries appear in overview block."""
        docs = [
            _doc("d1", 0, "A", source_file="alpha.pdf"),
            _doc("d2", 0, "B", source_file="beta.pdf"),
            _doc("d3", 0, "C", source_file="gamma.pdf"),
        ]
        summaries = {"d1": "cats", "d3": "birds"}  # d2 missing
        out = format_docs(docs, doc_summaries=summaries)
        assert "[alpha]: cats" in out
        assert "[gamma]: birds" in out
        assert "beta" not in out.split("=== Retrieved chunks")[0]  # not in overview block

    def test_deduplicate_overview_by_doc_id(self):
        """Multiple chunks from the same doc appear once in overview block."""
        docs = [
            _doc("d1", 0, "A1", source_file="alpha.pdf"),
            _doc("d1", 1, "A2", source_file="alpha.pdf"),
            _doc("d1", 2, "A3", source_file="alpha.pdf"),
        ]
        summaries = {"d1": "Alpha overview"}
        out = format_docs(docs, doc_summaries=summaries)
        # Overview appears exactly once
        assert out.count("[alpha]: Alpha overview") == 1

    def test_chunk_order_preserved(self):
        """U-shape ordering from _reorder_for_attention must be preserved."""
        docs = [
            _doc("d1", 0, "BEST_CHUNK"),
            _doc("d2", 0, "MIDDLE_CHUNK"),
            _doc("d3", 0, "SECOND_BEST"),  # appears last — U-shape
        ]
        out = format_docs(docs, doc_summaries={"d1": "a", "d2": "b", "d3": "c"})
        # Chunk order: BEST, MIDDLE, SECOND_BEST — as input
        a_pos = out.index("BEST_CHUNK")
        b_pos = out.index("MIDDLE_CHUNK")
        c_pos = out.index("SECOND_BEST")
        assert a_pos < b_pos < c_pos, "chunk order must be preserved"

    def test_per_chunk_summary_still_inline(self):
        """Pre-existing inline `Summary:` from chunk.metadata still appears."""
        docs = [_doc("d1", 0, "raw content", summary="one-sentence gist")]
        out = format_docs(docs, doc_summaries={"d1": "doc-level overview"})
        assert "Summary: one-sentence gist" in out  # chunk-level inline
        assert "[d1]: doc-level overview" in out  # doc-level block
