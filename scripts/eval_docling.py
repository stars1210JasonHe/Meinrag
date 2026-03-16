"""Evaluate docling vs enhanced mode on test PDFs.

Compares: chunk count, figure extraction, caption quality, table quality,
bounding boxes, processing time, and memory.

Usage:
    uv run python scripts/eval_docling.py
    uv run python scripts/eval_docling.py --pdf "path/to/specific.pdf"
    uv run python scripts/eval_docling.py --with-descriptions  # enable SmolVLM
"""
import argparse
import json
import sys
import time
from pathlib import Path

# ── Docling imports ──────────────────────────────────────────────────────────

def check_docling():
    try:
        import docling  # noqa: F401
        return True
    except ImportError:
        return False

if not check_docling():
    print("ERROR: docling not installed. Run: uv sync --extra docling")
    sys.exit(1)

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling_core.types.doc import PictureItem, TableItem, TextItem

# ── Enhanced mode imports ────────────────────────────────────────────────────

from app.config import Settings
from app.services.document_processor import DocumentProcessor

# ── Default test PDFs ────────────────────────────────────────────────────────

DEFAULT_PDFS = [
    Path("test cases1/ai_tool_verification_ttrl.pdf"),       # complex, figures+tables
    Path("test cases1/physics_terahertz_spintronic.pdf"),     # scientific, multi-column
    Path("test cases/attention_is_all_you_need.pdf"),         # famous paper, tables+figures
]

OUTPUT_DIR = Path("data/eval_docling")


def eval_docling(pdf_path: Path, with_descriptions: bool = False) -> dict:
    """Process a PDF with docling and collect stats."""
    print(f"\n{'='*60}")
    print(f"DOCLING: {pdf_path.name}")
    print(f"{'='*60}")

    pipeline_options = PdfPipelineOptions()
    pipeline_options.generate_picture_images = True
    pipeline_options.generate_page_images = False
    pipeline_options.do_table_structure = True
    pipeline_options.do_ocr = True

    if with_descriptions:
        pipeline_options.do_picture_description = True

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )

    start = time.time()
    result = converter.convert(str(pdf_path))
    elapsed = time.time() - start
    doc = result.document

    # Collect element stats
    texts, tables, pictures = [], [], []
    for element, _level in doc.iterate_items():
        if isinstance(element, PictureItem):
            pictures.append(element)
        elif isinstance(element, TableItem):
            tables.append(element)
        elif isinstance(element, TextItem):
            texts.append(element)

    # Print summary
    print(f"  Time: {elapsed:.1f}s")
    print(f"  Elements: {len(texts)} text, {len(tables)} table, {len(pictures)} picture")

    # Figure details
    print(f"\n  --- Figures ({len(pictures)}) ---")
    fig_details = []
    for i, pic in enumerate(pictures):
        caption = pic.caption_text(doc) if hasattr(pic, 'caption_text') else ""
        has_image = pic.get_image(doc) is not None if hasattr(pic, 'get_image') else False
        bbox = None
        page = None
        if pic.prov and len(pic.prov) > 0:
            page = pic.prov[0].page_no
            b = pic.prov[0].bbox
            bbox = [b.l, b.t, b.r, b.b]

        detail = {
            "index": i,
            "page": page,
            "caption": caption[:100] if caption else "(no caption)",
            "has_image": has_image,
            "bbox": bbox,
        }
        if with_descriptions and hasattr(pic, 'meta') and hasattr(pic.meta, 'description'):
            detail["description"] = str(pic.meta.description)[:100] if pic.meta.description else None

        fig_details.append(detail)
        print(f"  Fig {i}: page={page}, caption={detail['caption'][:60]}, image={has_image}, bbox={bbox is not None}")

    # Table details
    print(f"\n  --- Tables ({len(tables)}) ---")
    table_details = []
    for i, tbl in enumerate(tables):
        bbox = None
        page = None
        if tbl.prov and len(tbl.prov) > 0:
            page = tbl.prov[0].page_no
            b = tbl.prov[0].bbox
            bbox = [b.l, b.t, b.r, b.b]

        # Try to get table as markdown and as dataframe
        md_text = ""
        df_shape = None
        try:
            md_text = tbl.export_to_markdown(doc=doc)
        except Exception as e:
            md_text = f"(markdown export failed: {e})"
        try:
            df = tbl.export_to_dataframe(doc=doc)
            df_shape = df.shape
        except Exception:
            pass

        detail = {
            "index": i,
            "page": page,
            "bbox": bbox,
            "markdown_preview": md_text[:200] if md_text else "(empty)",
            "dataframe_shape": df_shape,
        }
        table_details.append(detail)
        print(f"  Table {i}: page={page}, shape={df_shape}, bbox={bbox is not None}")
        if md_text:
            preview = md_text[:150].replace('\n', ' | ')
            print(f"    Preview: {preview}")

    # Test HybridChunker
    print(f"\n  --- HybridChunker ---")
    try:
        from docling.chunking import HybridChunker
        chunker = HybridChunker(max_tokens=256)
        chunks = list(chunker.chunk(doc))
        chunk_types = {}
        for chunk in chunks:
            for item in chunk.meta.doc_items:
                label = str(item.label) if hasattr(item, 'label') else 'unknown'
                chunk_types[label] = chunk_types.get(label, 0) + 1

        print(f"  Chunks: {len(chunks)}")
        print(f"  By type: {chunk_types}")
        if chunks:
            print(f"  Sample chunk text (first): {chunks[0].text[:100]}...")
            # Check if page/bbox info is accessible
            first = chunks[0]
            if first.meta.doc_items:
                item = first.meta.doc_items[0]
                if item.prov:
                    print(f"  First chunk page: {item.prov[0].page_no}, bbox: present")
                else:
                    print(f"  First chunk: prov is empty (no page/bbox)")
    except Exception as e:
        print(f"  HybridChunker failed: {e}")
        chunks = []

    # Save images
    img_dir = OUTPUT_DIR / pdf_path.stem / "docling_images"
    img_dir.mkdir(parents=True, exist_ok=True)
    saved_images = 0
    for i, pic in enumerate(pictures):
        try:
            img = pic.get_image(doc)
            if img:
                img.save(img_dir / f"fig_{i}.png")
                saved_images += 1
        except Exception:
            pass
    print(f"\n  Saved {saved_images} figure images to {img_dir}")

    # Export full markdown
    md_path = OUTPUT_DIR / pdf_path.stem / "docling_full.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_text = doc.export_to_markdown()
    md_path.write_text(md_text, encoding="utf-8")
    print(f"  Full markdown: {md_path} ({len(md_text)} chars)")

    return {
        "mode": "docling",
        "pdf": pdf_path.name,
        "time_seconds": round(elapsed, 1),
        "text_count": len(texts),
        "table_count": len(tables),
        "picture_count": len(pictures),
        "chunk_count": len(chunks),
        "figures": fig_details,
        "tables": table_details,
        "saved_images": saved_images,
    }


def eval_enhanced(pdf_path: Path) -> dict:
    """Process a PDF with our enhanced mode and collect stats."""
    print(f"\n{'='*60}")
    print(f"ENHANCED: {pdf_path.name}")
    print(f"{'='*60}")

    settings = Settings()
    settings.parse_mode = "enhanced"
    processor = DocumentProcessor(settings)

    start = time.time()
    chunks = processor.load_and_split(pdf_path, doc_id="eval_test")
    elapsed = time.time() - start

    # Count by type
    type_counts = {}
    for chunk in chunks:
        ct = chunk.metadata.get("chunk_type", "unknown")
        type_counts[ct] = type_counts.get(ct, 0) + 1

    print(f"  Time: {elapsed:.1f}s")
    print(f"  Total chunks: {len(chunks)}")
    print(f"  By type: {type_counts}")

    # Figure details
    image_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "image"]
    print(f"\n  --- Figures ({len(image_chunks)}) ---")
    fig_details = []
    for i, chunk in enumerate(image_chunks):
        detail = {
            "index": i,
            "page": chunk.metadata.get("page"),
            "caption": chunk.page_content[:100],
            "has_image": bool(chunk.metadata.get("image_path")),
            "bbox": chunk.metadata.get("bbox") is not None,
        }
        fig_details.append(detail)
        print(f"  Fig {i}: page={detail['page']}, caption={detail['caption'][:60]}, image={detail['has_image']}, bbox={detail['bbox']}")

    # Table details
    table_chunks = [c for c in chunks if c.metadata.get("chunk_type") == "table"]
    print(f"\n  --- Tables ({len(table_chunks)}) ---")
    table_details = []
    for i, chunk in enumerate(table_chunks):
        detail = {
            "index": i,
            "page": chunk.metadata.get("page"),
            "bbox": chunk.metadata.get("bbox") is not None,
            "content_preview": chunk.page_content[:200].replace('\n', ' | '),
        }
        table_details.append(detail)
        print(f"  Table {i}: page={detail['page']}, bbox={detail['bbox']}")
        print(f"    Preview: {detail['content_preview'][:150]}")

    return {
        "mode": "enhanced",
        "pdf": pdf_path.name,
        "time_seconds": round(elapsed, 1),
        "total_chunks": len(chunks),
        "type_counts": type_counts,
        "figure_count": len(image_chunks),
        "table_count": len(table_chunks),
        "figures": fig_details,
        "tables": table_details,
    }


def compare(docling_result: dict, enhanced_result: dict):
    """Print side-by-side comparison."""
    pdf = docling_result["pdf"]
    print(f"\n{'='*60}")
    print(f"COMPARISON: {pdf}")
    print(f"{'='*60}")

    print(f"\n  {'Metric':<30} {'Docling':<20} {'Enhanced':<20}")
    print(f"  {'-'*70}")
    print(f"  {'Processing time':<30} {docling_result['time_seconds']:<20}s {enhanced_result['time_seconds']:<20}s")
    print(f"  {'Figures found':<30} {docling_result['picture_count']:<20} {enhanced_result['figure_count']:<20}")
    print(f"  {'Tables found':<30} {docling_result['table_count']:<20} {enhanced_result['table_count']:<20}")
    print(f"  {'Total chunks':<30} {docling_result['chunk_count']:<20} {enhanced_result['total_chunks']:<20}")
    print(f"  {'Images saved':<30} {docling_result['saved_images']:<20} {enhanced_result['figure_count']:<20}")

    # Caption quality comparison
    d_caps = [f["caption"] for f in docling_result["figures"] if f["caption"] != "(no caption)"]
    e_caps = [f["caption"] for f in enhanced_result["figures"] if f["caption"]]
    print(f"  {'Figures with captions':<30} {len(d_caps):<20} {len(e_caps):<20}")

    # Bbox coverage
    d_bbox = sum(1 for f in docling_result["figures"] if f["bbox"])
    e_bbox = sum(1 for f in enhanced_result["figures"] if f["bbox"])
    print(f"  {'Figures with bbox':<30} {d_bbox:<20} {e_bbox:<20}")

    d_tbbox = sum(1 for t in docling_result["tables"] if t["bbox"])
    e_tbbox = sum(1 for t in enhanced_result["tables"] if t["bbox"])
    print(f"  {'Tables with bbox':<30} {d_tbbox:<20} {e_tbbox:<20}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate docling vs enhanced mode")
    parser.add_argument("--pdf", type=str, help="Specific PDF to test (otherwise uses defaults)")
    parser.add_argument("--with-descriptions", action="store_true", help="Enable SmolVLM picture descriptions")
    parser.add_argument("--docling-only", action="store_true", help="Only run docling, skip enhanced")
    parser.add_argument("--enhanced-only", action="store_true", help="Only run enhanced, skip docling")
    args = parser.parse_args()

    if args.pdf:
        pdfs = [Path(args.pdf)]
    else:
        pdfs = [p for p in DEFAULT_PDFS if p.exists()]

    if not pdfs:
        print("No test PDFs found. Provide --pdf or place PDFs in 'test cases1/'")
        sys.exit(1)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    all_results = []

    for pdf in pdfs:
        print(f"\n\n{'#'*60}")
        print(f"# Processing: {pdf.name}")
        print(f"{'#'*60}")

        docling_result = None
        enhanced_result = None

        if not args.enhanced_only:
            try:
                docling_result = eval_docling(pdf, with_descriptions=args.with_descriptions)
            except Exception as e:
                print(f"\n  DOCLING ERROR: {e}")

        if not args.docling_only:
            try:
                enhanced_result = eval_enhanced(pdf)
            except Exception as e:
                print(f"\n  ENHANCED ERROR: {e}")

        if docling_result and enhanced_result:
            compare(docling_result, enhanced_result)

        all_results.append({
            "pdf": pdf.name,
            "docling": docling_result,
            "enhanced": enhanced_result,
        })

    # Save results
    results_path = OUTPUT_DIR / "eval_results.json"
    results_path.write_text(json.dumps(all_results, indent=2, default=str), encoding="utf-8")
    print(f"\n\nResults saved to {results_path}")
    print(f"Docling outputs in {OUTPUT_DIR}/*/")


if __name__ == "__main__":
    main()
