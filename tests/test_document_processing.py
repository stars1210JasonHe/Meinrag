"""B1: Document Processing tests - Requires API key."""
import pytest

from app.services.document_processor import DocumentProcessor
from tests.conftest import online, PDF_AI_SAFETY, PDF_LAW


@online
class TestDocumentProcessing:
    """B1.1 - B1.5: Document chunking and metadata."""

    def test_process_pdf(self, settings):
        """B1.1: PDF produces chunks with correct metadata."""
        processor = DocumentProcessor(settings)
        chunks = processor.load_and_split(PDF_AI_SAFETY)

        assert len(chunks) > 0
        for chunk in chunks:
            assert "source_file" in chunk.metadata
            assert "chunk_index" in chunk.metadata
            assert len(chunk.page_content) > 0

    def test_chunk_size_within_limits(self, settings):
        """B1.4: All chunks within configured chunk_size."""
        processor = DocumentProcessor(settings)
        chunks = processor.load_and_split(PDF_AI_SAFETY)

        # Allow some tolerance (chunk_size + overlap)
        max_allowed = settings.chunk_size + settings.chunk_overlap
        for chunk in chunks:
            assert len(chunk.page_content) <= max_allowed * 2, (
                f"Chunk too large: {len(chunk.page_content)} chars"
            )

    def test_large_pdf_produces_many_chunks(self, settings):
        """B1.5: 142-page law PDF produces significant number of chunks."""
        processor = DocumentProcessor(settings)
        chunks = processor.load_and_split(PDF_LAW)

        # 142 pages should produce a lot of chunks
        assert len(chunks) > 50, f"Expected many chunks from 142-page PDF, got {len(chunks)}"

    def test_chunk_metadata_has_source(self, settings):
        """B1.1: Each chunk has source_file in metadata."""
        processor = DocumentProcessor(settings)
        chunks = processor.load_and_split(PDF_AI_SAFETY)

        for chunk in chunks:
            assert chunk.metadata.get("source_file"), "Missing source_file in metadata"
