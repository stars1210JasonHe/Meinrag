"""Test docling speed with optimizations disabled."""
import time
from pathlib import Path

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableStructureOptions
from docling_core.types.doc import PictureItem, TableItem, TextItem

PDF = Path("test cases/attention_is_all_you_need.pdf")

configs = {
    "default (all models)": {},
    "no OCR": {"do_ocr": False},
    "no OCR + no code enrichment": {"do_ocr": False, "do_code_enrichment": False},
    "no OCR + no code + fast tables": {"do_ocr": False, "do_code_enrichment": False, "fast_tables": True},
}

for name, opts in configs.items():
    print(f"\n{'='*50}")
    print(f"Config: {name}")
    print(f"{'='*50}")

    pipeline_options = PdfPipelineOptions()
    pipeline_options.generate_picture_images = True

    if opts.get("do_ocr") is False:
        pipeline_options.do_ocr = False
    if opts.get("do_code_enrichment") is False:
        pipeline_options.do_code_enrichment = False
    if opts.get("fast_tables"):
        pipeline_options.table_structure_options = TableStructureOptions(mode="fast")

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )

    start = time.time()
    result = converter.convert(str(PDF))
    elapsed = time.time() - start
    doc = result.document

    texts = tables = pictures = 0
    for element, _level in doc.iterate_items():
        if isinstance(element, PictureItem):
            pictures += 1
        elif isinstance(element, TableItem):
            tables += 1
        elif isinstance(element, TextItem):
            texts += 1

    print(f"  Time: {elapsed:.1f}s")
    print(f"  Elements: {texts} text, {tables} table, {pictures} picture")
