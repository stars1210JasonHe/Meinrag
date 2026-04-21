"""E1 regression test — DOCX via Docling produces structured table chunks.

Before this fix, DOCX files went through Docx2txtLoader which flattens tables
to plain text. Docling preserves table structure as a separate chunk_type=table
chunk with markdown-rendered rows/columns.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.config import Settings
from app.services.docling_processor import process, has_docling


FIXTURES = Path(__file__).parent / "fixtures"
DOCX_FIXTURE = FIXTURES / "test_docling.docx"


@pytest.mark.skipif(not DOCX_FIXTURE.exists(), reason="DOCX fixture missing")
@pytest.mark.skipif(not has_docling(), reason="docling not installed")
def test_docx_extracts_table_as_structured_chunk():
    """DOCX with a table should produce a chunk_type='table' chunk whose
    content preserves the row/column structure as markdown."""
    settings = Settings()

    chunks = asyncio.run(process(
        DOCX_FIXTURE,
        doc_id="test_docx_fixture",
        settings=settings,
        source_name="test_docling.docx",
    ))

    assert len(chunks) >= 2, f"expected text + table chunks, got {len(chunks)}"

    # At least one chunk must be a structured table
    table_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "table"]
    assert len(table_chunks) >= 1, (
        f"DOCX via Docling must produce at least one chunk_type=table; got types: "
        f"{[c.metadata.get('chunk_type') for c in chunks]}"
    )

    # Table content must preserve cells — not flatten to plain prose
    table_text = table_chunks[0].page_content
    for expected_cell in ("Quarter", "Revenue", "Q1 2025", "125.3", "Q2 2025", "142.7"):
        assert expected_cell in table_text, (
            f"table chunk missing cell '{expected_cell}'. Got:\n{table_text}"
        )

    # At least one text chunk contains the narrative paragraph
    text_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "text"]
    assert any("test document" in c.page_content.lower() for c in text_chunks), (
        "expected narrative paragraph in a text chunk"
    )


@pytest.mark.skipif(not has_docling(), reason="docling not installed")
def test_docling_converter_accepts_docx_format():
    """Regression guard: DocumentConverter must be configured with DOCX in
    allowed_formats. A common mistake is to limit to PDF-only format_options,
    which silently breaks DOCX and falls back to Docx2txtLoader."""
    from app.services.docling_processor import _get_converter
    from docling.datamodel.base_models import InputFormat

    settings = Settings()
    converter = _get_converter(settings)

    # docling's DocumentConverter exposes allowed_formats via its
    # internal attribute. We check both possible attr names to survive
    # minor lib version changes.
    allowed = getattr(converter, "allowed_formats", None) or getattr(converter, "_allowed_formats", None)
    assert allowed is not None, "cannot introspect converter's allowed_formats"
    assert InputFormat.DOCX in allowed, (
        f"DOCX must be in allowed_formats. Got: {allowed}"
    )
    assert InputFormat.PDF in allowed, "PDF must remain in allowed_formats"
