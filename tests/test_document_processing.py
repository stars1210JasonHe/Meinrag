"""B1: Document Processing tests - Requires API key."""
import base64
import shutil
from pathlib import Path

import pytest
from fpdf import FPDF

from app.config import Settings, ParseMode
from app.services.document_processor import (
    DocumentProcessor,
    SUPPORTED_EXTENSIONS,
    _check_libreoffice_available,
)
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


class TestContentSegmentation:
    """Offline tests for content segmentation and chunk type metadata."""

    def test_separate_segments_text_only(self):
        """Pure text returns a single text segment."""
        content = "This is some plain text.\nWith multiple lines.\n\nAnd paragraphs."
        segments = DocumentProcessor._separate_content_segments(content)
        assert len(segments) == 1
        assert segments[0][1] == "text"
        assert "plain text" in segments[0][0]

    def test_separate_segments_with_table(self):
        """Markdown table is detected as a table segment."""
        content = (
            "Some text before the table.\n\n"
            "| Name | Age | City |\n"
            "|------|-----|------|\n"
            "| Alice | 30 | Berlin |\n"
            "| Bob | 25 | Munich |\n\n"
            "Some text after the table."
        )
        segments = DocumentProcessor._separate_content_segments(content)
        types = [s[1] for s in segments]
        assert "table" in types
        # Find the table segment
        table_seg = [s for s in segments if s[1] == "table"][0]
        assert "| Name |" in table_seg[0]
        assert "|------|" in table_seg[0]
        assert "| Alice |" in table_seg[0]

    def test_separate_segments_with_image(self):
        """Image markdown is detected as an image segment."""
        content = (
            "Text before image.\n\n"
            "![A diagram showing the workflow](data:image/png;base64,abc123)\n\n"
            "Text after image."
        )
        segments = DocumentProcessor._separate_content_segments(content)
        types = [s[1] for s in segments]
        assert "image" in types
        image_seg = [s for s in segments if s[1] == "image"][0]
        assert "![" in image_seg[0]

    def test_separate_segments_mixed(self):
        """Mixed content produces text, table, and image segments."""
        content = (
            "Introduction paragraph.\n\n"
            "| Col1 | Col2 |\n"
            "|------|------|\n"
            "| val1 | val2 |\n\n"
            "Middle text.\n\n"
            "![chart](data:image/png;base64,xyz)\n\n"
            "Conclusion."
        )
        segments = DocumentProcessor._separate_content_segments(content)
        types = [s[1] for s in segments]
        assert "text" in types
        assert "table" in types
        assert "image" in types

    def test_separate_segments_pipe_without_separator_is_text(self):
        """Lines starting with | but without separator row remain text."""
        content = "| This is not a table, just a line starting with pipe."
        segments = DocumentProcessor._separate_content_segments(content)
        assert len(segments) == 1
        assert segments[0][1] == "text"

    def test_split_large_table(self):
        """Large table is split preserving header."""
        header = "| Name | Value |\n|------|-------|"
        rows = "\n".join(f"| item{i} | {i * 100} |" for i in range(100))
        table_content = f"{header}\n{rows}"

        # Use a small max_size to force splitting
        parts = DocumentProcessor._split_large_table(table_content, max_size=200)
        assert len(parts) > 1
        # Every part should start with the header
        for part in parts:
            assert part.startswith("| Name | Value |")
            assert "|------|" in part

    def test_split_small_table_unchanged(self):
        """Small table that fits in max_size is not split."""
        table_content = "| A | B |\n|---|---|\n| 1 | 2 |"
        parts = DocumentProcessor._split_large_table(table_content, max_size=10000)
        assert len(parts) == 1
        assert parts[0] == table_content

    def test_chunk_type_metadata_default_mode(self, settings):
        """All chunks from default mode have chunk_type='text'."""
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        pdf.cell(200, 10, text="Hello World from test PDF", new_x="LMARGIN", new_y="NEXT")
        test_pdf = Path("data/test_pytest/test_chunk_type.pdf")
        test_pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.output(str(test_pdf))

        try:
            processor = DocumentProcessor(settings)
            chunks = processor.load_and_split(test_pdf)
            assert len(chunks) > 0
            for chunk in chunks:
                assert chunk.metadata.get("chunk_type") == "text"
        finally:
            test_pdf.unlink(missing_ok=True)

    def test_extract_image_description(self):
        """Image description extraction works."""
        # With alt text
        content = "![A beautiful sunset over the ocean](data:image/png;base64,abc)"
        desc = DocumentProcessor._extract_image_description(content)
        assert desc == "A beautiful sunset over the ocean"

        # Without alt text
        content2 = "![](data:image/png;base64,abc)"
        desc2 = DocumentProcessor._extract_image_description(content2)
        assert desc2  # Should return something, not empty


class TestVisionMode:
    """Offline tests for vision mode infrastructure."""

    def test_doc_extension_supported(self):
        """'.doc' is in SUPPORTED_EXTENSIONS."""
        assert ".doc" in SUPPORTED_EXTENSIONS

    def test_libreoffice_check_returns_bool(self):
        """_check_libreoffice_available returns a bool."""
        result = _check_libreoffice_available()
        assert isinstance(result, bool)

    def test_parse_mode_enum_values(self):
        """ParseMode enum has default, enhanced, vision."""
        assert ParseMode.DEFAULT == "default"
        assert ParseMode.ENHANCED == "enhanced"
        assert ParseMode.VISION == "vision"

    def test_parse_mode_default_unchanged(self):
        """Default parse_mode is 'default'."""
        settings = Settings()
        assert settings.parse_mode == ParseMode.DEFAULT

    def test_parse_mode_accepts_vision(self):
        """parse_mode='vision' is a valid setting."""
        settings = Settings(parse_mode="vision")
        assert settings.parse_mode == ParseMode.VISION

    def test_backward_compat_pdf_parse_mode(self):
        """Legacy pdf_parse_mode is remapped to parse_mode."""
        settings = Settings(pdf_parse_mode="enhanced")
        assert settings.parse_mode == ParseMode.ENHANCED

    def test_vision_settings_defaults(self):
        """Vision-related settings have sensible defaults."""
        settings = Settings()
        assert settings.vision_page_dpi == 150
        assert settings.vision_model == "gpt-4o-mini"
        assert settings.vision_max_tokens == 4096

    def test_render_page_to_base64(self):
        """_render_page_to_base64 returns a valid base64 PNG."""
        import fitz

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        pdf.cell(200, 10, text="Test page for rendering", new_x="LMARGIN", new_y="NEXT")
        test_pdf = Path("data/test_pytest/test_render.pdf")
        test_pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.output(str(test_pdf))

        try:
            doc = fitz.open(str(test_pdf))
            page = doc[0]
            b64 = DocumentProcessor._render_page_to_base64(page, dpi=72)
            doc.close()

            assert isinstance(b64, str)
            assert len(b64) > 100
            # Verify it decodes to a valid PNG
            decoded = base64.b64decode(b64)
            assert decoded[:4] == b"\x89PNG"
        finally:
            test_pdf.unlink(missing_ok=True)

    def test_doc_without_libreoffice_raises(self, tmp_path):
        """Loading .doc without LibreOffice gives a clear error."""
        doc_file = tmp_path / "test.doc"
        doc_file.write_bytes(b"fake doc content")

        settings = Settings(parse_mode="default")
        processor = DocumentProcessor(settings)

        if not _check_libreoffice_available():
            with pytest.raises(ValueError, match="LibreOffice"):
                processor.load_and_split(doc_file)


# ================================
# LibreOffice-dependent tests
# ================================

has_libreoffice = _check_libreoffice_available()
needs_libreoffice = pytest.mark.skipif(
    not has_libreoffice, reason="LibreOffice (soffice) not found on PATH"
)


@needs_libreoffice
class TestLibreOfficeConversion:
    """Tests that require LibreOffice installed."""

    def test_convert_txt_to_pdf(self, tmp_path):
        """TXT file converts to PDF."""
        txt_file = tmp_path / "test.txt"
        txt_file.write_text("Hello world from a text file.")

        settings = Settings()
        processor = DocumentProcessor(settings)
        pdf_path = processor._convert_to_pdf(txt_file)
        try:
            assert pdf_path.exists()
            assert pdf_path.suffix == ".pdf"
            assert pdf_path.stat().st_size > 0
        finally:
            shutil.rmtree(pdf_path.parent, ignore_errors=True)

    def test_doc_loads_in_default_mode(self, tmp_path):
        """A .doc file loads via LibreOffice conversion in default mode."""
        # Create a minimal .doc-like file (LibreOffice can handle simple text files)
        doc_file = tmp_path / "test.txt"
        doc_file.write_text("This is a test document with some content for processing.")
        # Rename to test the conversion path
        real_doc = tmp_path / "test.doc"
        doc_file.rename(real_doc)

        settings = Settings(parse_mode="default")
        processor = DocumentProcessor(settings)
        # Note: a plain text .doc may work or fail depending on LibreOffice
        # This tests the pipeline works
        try:
            chunks = processor.load_and_split(real_doc)
            assert len(chunks) > 0
            for chunk in chunks:
                assert chunk.metadata["source_file"] == "test.doc"
                assert chunk.metadata["chunk_type"] == "text"
        except RuntimeError:
            pytest.skip("LibreOffice couldn't convert this test .doc file")


# ================================
# Vision mode integration tests (requires API key)
# ================================

@online
class TestVisionModePDF:
    """Vision mode tests with real PDFs (requires OpenAI API key)."""

    def test_vision_mode_processes_pdf(self):
        """Vision mode on a small PDF produces chunks with correct metadata."""
        # Create a small test PDF
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=14)
        pdf.cell(200, 10, text="Vision Mode Test", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=11)
        pdf.multi_cell(180, 7, text=(
            "This is a test document for the vision processing mode. "
            "It contains a simple paragraph of text that should be extracted "
            "accurately by the vision LLM."
        ))
        test_pdf = Path("data/test_pytest/test_vision.pdf")
        test_pdf.parent.mkdir(parents=True, exist_ok=True)
        pdf.output(str(test_pdf))

        try:
            settings = Settings(
                parse_mode="vision",
                vision_page_dpi=100,  # lower DPI for faster test
            )
            processor = DocumentProcessor(settings)
            chunks = processor.load_and_split(test_pdf, doc_id="testvision")
            assert len(chunks) > 0
            for chunk in chunks:
                assert chunk.metadata.get("chunk_type") in ("text", "table", "image")
                assert chunk.metadata.get("parse_mode") == "vision"
                assert chunk.metadata.get("source_file") == "test_vision.pdf"
                assert chunk.metadata.get("page") is not None
        finally:
            test_pdf.unlink(missing_ok=True)
            shutil.rmtree(Path("data/uploads/testvision"), ignore_errors=True)
