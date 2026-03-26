"""Docling-based document processor for PARSE_MODE=docling.

Requires optional dependency: uv sync --extra docling
"""
import json
import logging
import re
from pathlib import Path

from langchain_core.documents import Document

from app.config import Settings

logger = logging.getLogger(__name__)


# ── Chunk quality helpers (shared with document_processor) ───────────────
from app.services.chunk_utils import (
    is_garbage_table as _is_garbage_table,
    deduplicate_chunks as _deduplicate_chunks,
    tag_reference_chunks as _tag_reference_chunks,
    enrich_section_metadata as _enrich_section_metadata,
)


def has_docling() -> bool:
    """Return True if docling is installed."""
    try:
        import docling  # noqa: F401
        return True
    except ImportError:
        return False


def _convert_bbox(
    l: float, t: float, r: float, b: float, page_height: float
) -> list[float]:
    """Convert docling bbox to [x0, y0, x1, y1] with top-left origin.

    Docling bbox has (l, t, r, b). If origin is bottom-left (t > b),
    flip y coordinates. Otherwise pass through ensuring y0 < y1.
    """
    if t > b:
        # bottom-left origin: flip y
        y0 = page_height - t
        y1 = page_height - b
    else:
        y0 = t
        y1 = b
    return [l, y0, r, y1]


def _make_text_chunk(text: str, page: int, source_name: str) -> Document:
    """Create a text chunk with standard metadata."""
    return Document(
        page_content=text,
        metadata={
            "chunk_type": "text",
            "page": page,
            "source_file": source_name,
            "parse_mode": "docling",
        },
    )


def _make_table_chunk(
    markdown: str, page: int, source_name: str, bbox: list[float] | None = None
) -> Document:
    """Create a table chunk with standard metadata."""
    meta = {
        "chunk_type": "table",
        "page": page,
        "source_file": source_name,
        "parse_mode": "docling",
    }
    if bbox:
        meta["bbox"] = json.dumps(bbox)
    return Document(page_content=markdown, metadata=meta)


def _make_image_chunk(
    caption: str, page: int, source_name: str,
    image_path: str | None = None, bbox: list[float] | None = None
) -> Document:
    """Create an image chunk with standard metadata."""
    meta = {
        "chunk_type": "image",
        "page": page,
        "source_file": source_name,
        "parse_mode": "docling",
    }
    if image_path:
        meta["image_path"] = image_path
    if bbox:
        meta["bbox"] = json.dumps(bbox)
    return Document(page_content=caption, metadata=meta)


def _make_formula_chunk(
    text: str, page: int, source_name: str,
    image_path: str | None = None, bbox: list[float] | None = None
) -> Document:
    """Create a formula/equation chunk with standard metadata."""
    meta = {
        "chunk_type": "formula",
        "page": page,
        "source_file": source_name,
        "parse_mode": "docling",
    }
    if image_path:
        meta["image_path"] = image_path
    if bbox:
        meta["bbox"] = json.dumps(bbox)
    return Document(page_content=text, metadata=meta)


def _crop_formula_image(
    pdf_path: Path, page_num: int, bbox: list[float], images_dir: Path,
    doc_id: str, formula_idx: int
) -> str | None:
    """Crop a formula region from the PDF page and save as PNG."""
    try:
        import fitz
        pdf = fitz.open(str(pdf_path))
        page = pdf[page_num]
        x0, y0, x1, y1 = bbox
        rect = fitz.Rect(x0, y0, x1, y1) + fitz.Rect(-5, -5, 5, 5)  # padding
        mat = fitz.Matrix(3, 3)  # 3x zoom for readable equations
        clip = page.get_pixmap(matrix=mat, clip=rect)
        filename = f"page{page_num}_eq{formula_idx}.png"
        clip.save(str(images_dir / filename))
        pdf.close()
        return f"{doc_id}/{filename}"
    except Exception as e:
        logger.debug(f"Failed to crop formula image: {e}")
        return None


def _ocr_formula(image_path: Path) -> str | None:
    """Run pix2tex LaTeX OCR on a formula image. Returns LaTeX string or None."""
    try:
        from pix2tex.cli import LatexOCR
        from PIL import Image
        model = _get_latex_ocr()
        img = Image.open(image_path)
        result = model(img)
        if result and len(result) < 2000:  # sanity check against hallucination
            return result
        return None
    except Exception as e:
        logger.debug(f"pix2tex OCR failed: {e}")
        return None


_latex_ocr = None


def _get_latex_ocr():
    """Cached pix2tex model singleton."""
    global _latex_ocr
    if _latex_ocr is None:
        from pix2tex.cli import LatexOCR
        logger.info("Loading pix2tex LaTeX OCR model...")
        _latex_ocr = LatexOCR()
    return _latex_ocr


# ── Cached converter singleton ───────────────────────────────────────────

_converter = None


def _get_converter(settings: Settings):
    """Get or create the cached DocumentConverter."""
    global _converter
    if _converter is not None:
        return _converter

    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        PdfPipelineOptions,
        TableStructureOptions,
        AcceleratorOptions,
    )

    logger.info("Docling: initializing converter (first-time model download may take minutes)...")

    pipeline_options = PdfPipelineOptions()
    pipeline_options.generate_picture_images = False  # images handled by poppler; docling crashes on some PDFs
    pipeline_options.do_ocr = settings.docling_ocr
    pipeline_options.do_code_enrichment = False
    pipeline_options.table_structure_options = TableStructureOptions(mode="fast")
    pipeline_options.accelerator_options = AcceleratorOptions(device=settings.docling_device)

    if settings.docling_picture_description:
        pipeline_options.do_picture_description = True

    _converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
        }
    )
    logger.info("Docling: converter ready.")
    return _converter


def _get_element_page(element) -> int:
    """Extract 0-indexed page number from a docling element."""
    if element.prov and len(element.prov) > 0:
        return element.prov[0].page_no - 1  # docling is 1-indexed
    return 0


def _get_element_bbox(element, page_height: float) -> list[float] | None:
    """Extract bbox from a docling element, converting to top-left origin."""
    if not element.prov or len(element.prov) == 0:
        return None
    bbox = element.prov[0].bbox
    return _convert_bbox(bbox.l, bbox.t, bbox.r, bbox.b, page_height)


_MIN_CHUNK_LENGTH = 50  # Skip junk chunks (code fences, bare headings, etc.)


def _chunk_text_elements(doc, settings: Settings, source_name: str) -> list[Document]:
    """Use HybridChunker on the full document, extract only text chunks."""
    try:
        from docling.chunking import HybridChunker
        chunker = HybridChunker(max_tokens=settings.chunk_size // 4)
    except Exception as e:
        logger.warning(f"HybridChunker init failed, falling back to simple split: {e}")
        return _fallback_text_chunks(doc, settings, source_name)

    chunks = []
    try:
        for chunk in chunker.chunk(doc):
            # Skip table/image chunks — we handle those directly
            is_visual = False
            if chunk.meta and chunk.meta.doc_items:
                for item in chunk.meta.doc_items:
                    label = str(item.label) if hasattr(item, "label") else ""
                    if label in ("table", "picture"):
                        is_visual = True
                        break
            if is_visual:
                continue

            # Skip junk chunks (code fences, bare headings, formatting artifacts)
            if len(chunk.text.strip()) < _MIN_CHUNK_LENGTH:
                continue

            # Get page from first doc_item provenance
            page = 0
            if chunk.meta and chunk.meta.doc_items:
                item = chunk.meta.doc_items[0]
                if item.prov and len(item.prov) > 0:
                    page = item.prov[0].page_no - 1

            text_chunk = _make_text_chunk(chunk.text, page, source_name)

            # Add heading context if available (store as string for FAISS compatibility)
            if chunk.meta and chunk.meta.headings:
                text_chunk.metadata["headings"] = " > ".join(chunk.meta.headings)

            chunks.append(text_chunk)
    except Exception as e:
        logger.warning(f"HybridChunker failed: {e}")
        return _fallback_text_chunks(doc, settings, source_name)

    return chunks


def _fallback_text_chunks(doc, settings: Settings, source_name: str) -> list[Document]:
    """Simple fallback: split document markdown with RecursiveCharacterTextSplitter."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    md = doc.export_to_markdown()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    splits = splitter.split_text(md)
    return [_make_text_chunk(text, 0, source_name) for text in splits]


def process(
    file_path: Path, doc_id: str, settings: Settings, source_name: str
) -> list[Document]:
    """Process a document with docling and return LangChain Document chunks.

    Args:
        file_path: Path to the document file.
        doc_id: Unique document ID for image storage paths.
        settings: App settings (chunk_size, docling_* options).
        source_name: Clean filename for citations (doc_id prefix stripped).

    Returns:
        List of LangChain Documents with consistent metadata.
    """
    from docling_core.types.doc import PictureItem, TableItem, DocItemLabel

    converter = _get_converter(settings)
    result = converter.convert(str(file_path))
    doc = result.document

    # Get page heights for bbox conversion
    page_heights: dict[int, float] = {}
    if hasattr(doc, "pages") and doc.pages:
        for page_no, page_obj in doc.pages.items():
            if hasattr(page_obj, "size") and page_obj.size:
                page_heights[page_no] = page_obj.size.height

    # Prepare image storage
    images_dir = settings.upload_dir / doc_id / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    all_chunks: list[Document] = []
    img_idx = 0

    for element, _level in doc.iterate_items():
        page = _get_element_page(element)
        page_h = page_heights.get(page + 1, 792.0)  # +1 for 1-indexed lookup
        bbox = _get_element_bbox(element, page_h)

        if isinstance(element, TableItem):
            try:
                md = element.export_to_markdown(doc=doc)
            except Exception:
                md = element.text if hasattr(element, "text") else ""
            if md and md.strip() and not _is_garbage_table(md):
                chunk = _make_table_chunk(md, page, source_name, bbox)
                all_chunks.append(chunk)

        elif isinstance(element, PictureItem):
            caption = ""
            try:
                caption = element.caption_text(doc)
            except Exception:
                pass
            if not caption:
                caption = f"Figure on page {page + 1}"

            image_path = None
            try:
                img = element.get_image(doc)
                if img:
                    filename = f"page{page}_img{img_idx}.png"
                    img.save(images_dir / filename)
                    image_path = f"{doc_id}/{filename}"
                    img_idx += 1
            except Exception as e:
                logger.debug(f"Failed to save docling image: {e}")

            chunk = _make_image_chunk(caption, page, source_name, image_path, bbox)
            all_chunks.append(chunk)

        elif hasattr(element, "label") and element.label == DocItemLabel.FORMULA:
            # Crop formula region from PDF as image
            formula_image_path = None
            if bbox:
                formula_image_path = _crop_formula_image(
                    file_path, page, bbox, images_dir, doc_id, img_idx
                )
                if formula_image_path:
                    img_idx += 1

            # Optional: OCR to LaTeX
            content = f"Equation on page {page + 1}"
            if settings.docling_equation_ocr and formula_image_path:
                full_img_path = images_dir / formula_image_path.split("/")[-1]
                latex = _ocr_formula(full_img_path)
                if latex:
                    content = f"${latex}$"

            chunk = _make_formula_chunk(content, page, source_name, formula_image_path, bbox)
            all_chunks.append(chunk)

    # Chunk text elements with HybridChunker
    text_chunks = _chunk_text_elements(doc, settings, source_name)
    all_chunks.extend(text_chunks)

    # Post-processing: deduplicate and tag reference chunks
    all_chunks = _deduplicate_chunks(all_chunks)
    _tag_reference_chunks(all_chunks)
    _enrich_section_metadata(all_chunks)

    # Assign chunk_index
    for i, chunk in enumerate(all_chunks):
        chunk.metadata["chunk_index"] = i

    text_count = sum(1 for c in all_chunks if c.metadata.get("chunk_type") == "text")
    table_count = sum(1 for c in all_chunks if c.metadata.get("chunk_type") == "table")
    image_count = sum(1 for c in all_chunks if c.metadata.get("chunk_type") == "image")
    formula_count = sum(1 for c in all_chunks if c.metadata.get("chunk_type") == "formula")
    logger.info(
        f"Docling: {len(all_chunks)} chunks "
        f"({text_count} text, {table_count} table, {image_count} image, {formula_count} formula) "
        f"from {file_path.name}"
    )
    return all_chunks
