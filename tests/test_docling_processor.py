"""Tests for docling processor — unit tests use mocks, no real docling needed."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


class TestHasDocling:
    def test_returns_bool(self):
        from app.services.docling_processor import has_docling
        assert isinstance(has_docling(), bool)

    def test_returns_true_when_installed(self):
        """Docling is installed as optional dep in this project."""
        from app.services.docling_processor import has_docling
        assert has_docling() is True


class TestBboxConversion:
    def test_top_left_origin_passthrough(self):
        """When t < b (top-left origin), pass through."""
        from app.services.docling_processor import _convert_bbox
        bbox = _convert_bbox(72.0, 100.0, 540.0, 300.0, 792.0)
        assert bbox == [72.0, 100.0, 540.0, 300.0]

    def test_bottom_left_origin_flips(self):
        """When t > b (bottom-left origin), flip y coordinates."""
        from app.services.docling_processor import _convert_bbox
        # t=700 > b=500, page_height=792
        bbox = _convert_bbox(50.0, 700.0, 500.0, 500.0, 792.0)
        assert bbox == [50.0, 92.0, 500.0, 292.0]  # 792-700=92, 792-500=292

    def test_produces_valid_coords(self):
        from app.services.docling_processor import _convert_bbox
        bbox = _convert_bbox(50.0, 600.0, 500.0, 200.0, 792.0)
        x0, y0, x1, y1 = bbox
        assert x0 < x1
        assert y0 < y1

    def test_equal_t_b(self):
        """When t == b, produces zero-height bbox."""
        from app.services.docling_processor import _convert_bbox
        bbox = _convert_bbox(50.0, 400.0, 500.0, 400.0, 792.0)
        assert bbox[1] == bbox[3]  # y0 == y1


class TestChunkHelpers:
    def test_text_chunk_metadata(self):
        from app.services.docling_processor import _make_text_chunk
        chunk = _make_text_chunk("Hello world", page=2, source_name="paper.pdf")
        assert chunk.page_content == "Hello world"
        assert chunk.metadata["chunk_type"] == "text"
        assert chunk.metadata["page"] == 2
        assert chunk.metadata["source_file"] == "paper.pdf"
        assert chunk.metadata["parse_mode"] == "docling"

    def test_table_chunk_metadata(self):
        from app.services.docling_processor import _make_table_chunk
        md = "| A | B |\n|---|---|\n| 1 | 2 |"
        chunk = _make_table_chunk(md, page=5, source_name="paper.pdf", bbox=[72, 100, 540, 300])
        assert chunk.metadata["chunk_type"] == "table"
        assert chunk.metadata["page"] == 5
        assert chunk.metadata["bbox"] == json.dumps([72, 100, 540, 300])
        assert chunk.metadata["parse_mode"] == "docling"

    def test_table_chunk_no_bbox(self):
        from app.services.docling_processor import _make_table_chunk
        chunk = _make_table_chunk("| A |\n|---|\n| 1 |", page=0, source_name="x.pdf")
        assert "bbox" not in chunk.metadata

    def test_image_chunk_metadata(self):
        from app.services.docling_processor import _make_image_chunk
        chunk = _make_image_chunk(
            caption="Figure 1: Architecture",
            page=3,
            source_name="paper.pdf",
            image_path="abc123/page3_img0.png",
            bbox=[50, 200, 500, 600],
        )
        assert chunk.metadata["chunk_type"] == "image"
        assert chunk.metadata["image_path"] == "abc123/page3_img0.png"
        assert chunk.metadata["bbox"] == json.dumps([50, 200, 500, 600])
        assert chunk.page_content == "Figure 1: Architecture"

    def test_image_chunk_no_optional_fields(self):
        from app.services.docling_processor import _make_image_chunk
        chunk = _make_image_chunk(caption="Fig 1", page=0, source_name="x.pdf")
        assert "image_path" not in chunk.metadata
        assert "bbox" not in chunk.metadata


class TestDoclingConfig:
    def test_default_settings(self):
        from app.config import Settings
        s = Settings()
        assert s.docling_ocr is False
        assert s.docling_picture_description is False
        assert s.docling_device == "auto"

    def test_parse_mode_docling_exists(self):
        from app.config import ParseMode
        assert ParseMode.DOCLING == "docling"


# ── Integration tests (require docling installed + test PDFs) ────────────

from app.services.docling_processor import has_docling

docling_installed = pytest.mark.skipif(
    not has_docling(), reason="docling not installed"
)


@docling_installed
class TestDoclingIntegration:
    """Integration tests — require docling installed + test PDFs."""

    @pytest.mark.asyncio
    async def test_process_pdf_returns_chunks(self):
        """Process a real PDF and verify chunks have correct metadata."""
        from app.services.docling_processor import process
        from app.config import Settings

        pdf = Path("test cases/attention_is_all_you_need.pdf")
        if not pdf.exists():
            pytest.skip("Test PDF not available")

        settings = Settings()
        chunks = await process(pdf, "test_int", settings, "attention.pdf")

        assert len(chunks) > 0

        for chunk in chunks:
            assert "chunk_type" in chunk.metadata
            assert chunk.metadata["chunk_type"] in ("text", "table", "image", "formula")
            assert "page" in chunk.metadata
            assert chunk.metadata["source_file"] == "attention.pdf"
            assert chunk.metadata["parse_mode"] == "docling"
            assert "chunk_index" in chunk.metadata

        types = [c.metadata["chunk_type"] for c in chunks]
        assert "image" in types, "Should extract at least one figure"
        assert "table" in types, "Should extract at least one table"

        # Image chunks exist (image_path is optional — docling's generate_picture_images
        # is off; poppler handles image saving separately in document_processor)
        image_chunks = [c for c in chunks if c.metadata["chunk_type"] == "image"]
        assert len(image_chunks) > 0

        # Table chunks should be markdown format (not triplet)
        table_chunks = [c for c in chunks if c.metadata["chunk_type"] == "table"]
        for tc in table_chunks:
            assert "|" in tc.page_content, "Tables should be markdown format"

    @pytest.mark.asyncio
    async def test_process_pdf_bbox_valid(self):
        """Verify bbox is a JSON list of 4 floats with x0<x1, y0<y1."""
        from app.services.docling_processor import process
        from app.config import Settings

        pdf = Path("test cases/attention_is_all_you_need.pdf")
        if not pdf.exists():
            pytest.skip("Test PDF not available")

        settings = Settings()
        chunks = await process(pdf, "test_bbox", settings, "attention.pdf")

        bbox_chunks = [c for c in chunks if "bbox" in c.metadata]
        assert len(bbox_chunks) > 0, "Some chunks should have bbox"

        for chunk in bbox_chunks:
            bbox = json.loads(chunk.metadata["bbox"])
            assert len(bbox) == 4
            x0, y0, x1, y1 = bbox
            assert x0 < x1, f"x0 ({x0}) should be < x1 ({x1})"
            assert y0 < y1, f"y0 ({y0}) should be < y1 ({y1})"
