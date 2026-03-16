# Docling Parse Mode — Design Spec

## Goal

Add `PARSE_MODE=docling` as a 4th parse mode that uses IBM's docling SDK for document processing. Docling provides neural layout analysis, table structure recognition, figure extraction with captions, OCR, and reading order detection — significantly improving accuracy on complex PDFs compared to the current PyMuPDF + Poppler pipeline. Existing modes (default, enhanced, vision) remain untouched.

## Motivation

Current enhanced mode limitations:
- PyMuPDF text extraction loses reading order on multi-column PDFs
- Poppler figure extraction uses spatial proximity heuristics (80px) for caption matching — fragile on complex layouts
- Table extraction via `find_tables()` misses nested/complex tables
- No OCR support for scanned documents
- Figure descriptions require paid OpenAI vision API calls

Docling solves all of these with local neural models (no API costs for core processing).

## Evaluation Results (tested 2026-03-16)

Tested on `attention_is_all_you_need.pdf` and `physics_terahertz_spintronic.pdf`:

| Metric | Docling (optimized) | Enhanced (PyMuPDF+Poppler) |
|---|---|---|
| Figure detection | Exact count (4/6) | Over-extracts (22 duplicates) or under-extracts (3/6) |
| Caption quality | Clean, correct association | Duplicated/wrong captions |
| Table structure | DataFrame export with shape (4x4, 10x5, 20x13) | Markdown only, Unicode crash on some |
| Bounding boxes | Every element | Partial coverage |
| Processing time (CPU) | 31-50s per paper | 3-6s per paper |
| Processing time (GPU) | ~5-10s estimated | N/A |

**Verdict:** Docling extraction quality is significantly better. Speed is acceptable with GPU and optimizations.

## Architecture

### Processing Pipeline

```
Upload request
  → DocumentProcessor.load_and_split(file_path, doc_id)
    → if PARSE_MODE == "docling":
        → docling_processor.process(file_path, doc_id, settings, source_name)
          → DocumentConverter.convert(file_path)  [cached converter, GPU if available]
            → Heron layout model (text, tables, figures, headings)
            → TableFormer fast mode (cell-level table structure)
            → RapidOCR (optional, off by default)
            → Optional: SmolVLM picture descriptions
          → DoclingDocument (unified representation)
          → Split strategy:
              Text elements  → HybridChunker (structure-aware splitting)
              Table elements → Direct markdown export via table.export_to_markdown()
              Image elements → Direct extraction via element.get_image() + caption_text()
          → map_to_langchain_documents()
            → List[LangChain Document] with standard metadata
    → else: existing modes (default / enhanced / vision)
```

### File Changes

#### New Files

**`app/services/docling_processor.py`** (~250 lines)

Core wrapper around docling. Responsibilities:
- Configure `DocumentConverter` with optimized pipeline options
- Cache converter instance (singleton — don't reload models per document)
- Auto-detect GPU via `AcceleratorOptions(device="auto")`
- Run conversion: `converter.convert(file_path)` → `DoclingDocument`
- Iterate over document elements:
  - `TextItem` → HybridChunker for structure-aware text splitting
  - `TableItem` → `table.export_to_markdown(doc=doc)` as single chunk (no triplet format)
  - `PictureItem` → `element.get_image(doc)` saved as PNG + `caption_text(doc)` as content
- Map each chunk to a LangChain `Document` with our metadata schema

Key function:
```python
def process(file_path: Path, doc_id: str, settings: Settings, source_name: str) -> list[Document]:
    """Process a document with docling and return LangChain Document chunks.

    source_name: clean filename for citations (doc_id prefix stripped).
    Sets chunk_index and parse_mode on every chunk before returning.
    """
```

Converter caching (module-level singleton):
```python
_converter: DocumentConverter | None = None

def _get_converter(settings: Settings) -> DocumentConverter:
    global _converter
    if _converter is None:
        pipeline_options = PdfPipelineOptions()
        pipeline_options.generate_picture_images = True
        pipeline_options.do_ocr = settings.docling_ocr
        pipeline_options.do_code_enrichment = False  # not needed for RAG
        pipeline_options.table_structure_options = TableStructureOptions(mode="fast")
        pipeline_options.accelerator_options = AcceleratorOptions(device="auto")  # GPU if available
        if settings.docling_picture_description:
            pipeline_options.do_picture_description = True
        _converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
        )
    return _converter
```

Availability check:
```python
def has_docling() -> bool:
    """Return True if docling is installed."""
    try:
        import docling  # noqa: F401
        return True
    except ImportError:
        return False
```

**`tests/test_docling_processor.py`** (~150 lines)

- Unit tests with mocked docling objects (no real model download needed)
- Tests for metadata mapping, bbox conversion, image saving, availability check
- Integration test marked with `@pytest.mark.skipif(not has_docling(), ...)` for when docling is actually installed

#### Modified Files

**`app/config.py`**
- Add `DOCLING = "docling"` to `ParseMode` enum
- Add settings:
  - `docling_picture_description: bool = False` — enable SmolVLM image descriptions
  - `docling_ocr: bool = False` — enable OCR for scanned pages (off by default — most PDFs are native text)
  - `docling_device: str = "auto"` — accelerator device: "auto", "cpu", "cuda", "mps"

**`app/services/document_processor.py`**
- Add docling branch in `load_and_split()` between vision and enhanced (no suffix restriction — docling handles all file types):
  ```python
  # === DOCLING MODE (all file types) ===
  if parse_mode == ParseMode.DOCLING:
      try:
          from app.services.docling_processor import process, has_docling
          if not has_docling():
              raise ImportError("docling not installed. Install with: uv sync --extra docling")
          return process(file_path, doc_id, self._settings, self._clean_name)
      except Exception as e:
          logger.warning(f"Docling mode failed, falling back: {e}")
          # For PDFs, try enhanced mode. For other formats, fall through to default loaders.
          if suffix == ".pdf":
              parse_mode = ParseMode.ENHANCED
          else:
              pass  # fall through to default loaders below
  ```
- Note: `process()` receives `self._clean_name` and sets `source_file`, `chunk_index`, and `parse_mode` on all chunks internally — no post-processing loop needed in the caller.

**`pyproject.toml`**
- Add optional dependency group:
  ```toml
  [project.optional-dependencies]
  docling = ["docling>=2.80.0"]
  ```
- Install with: `uv sync --extra docling`

### Metadata Schema

All modes produce LangChain `Document` objects with consistent metadata. Docling mode maps to the same schema:

| Field | Source in Docling | Example |
|---|---|---|
| `chunk_type` | Element type: `TextItem` → `"text"`, `TableItem` → `"table"`, `PictureItem` → `"image"` | `"table"` |
| `page` | `element.prov[0].page_no - 1` (docling is 1-indexed, we use 0-indexed) | `2` |
| `bbox` | `element.prov[0].bbox` → convert to `[x0, y0, x1, y1]` PDF points → JSON string | `"[72, 100, 540, 300]"` |
| `image_path` | Save `element.get_image(doc)` as PNG → `"{doc_id}/page{N}_img{M}.png"` | `"abc123/page2_img0.png"` |
| `source_file` | Passed in as `source_name` parameter (caller strips doc_id prefix) | `"paper.pdf"` |
| `chunk_index` | Sequential index assigned inside `process()` before returning | `5` |
| `parse_mode` | Set to `"docling"` on every chunk inside `process()` | `"docling"` |

### Bounding Box Conversion

Docling provides bounding boxes via provenance data. The coordinate system uses PDF points (72 DPI) with origin at bottom-left. Our system expects `[x0, y0, x1, y1]` with origin at top-left (same as PyMuPDF).

Conversion:
```python
def _convert_docling_bbox(prov, page_height: float) -> list[float]:
    """Convert docling bbox (bottom-left origin) to top-left origin."""
    bbox = prov.bbox
    return [bbox.l, page_height - bbox.t, bbox.r, page_height - bbox.b]
```

This needs verification during implementation — docling may already use top-left origin in newer versions.

### Chunking Strategy (Hybrid Approach)

**Text elements:** Use docling's `HybridChunker` for structure-aware splitting. Benefits:
- Headings preserved as context in each chunk
- Reading order respected
- Undersized paragraphs merged with peers

**Table elements:** Skip HybridChunker. Export directly via `table.export_to_markdown(doc=doc)` as a single chunk. This preserves markdown table format (which works well for our retrieval) instead of HybridChunker's triplet format (`row, col = value`) which is harder to read and may hurt retrieval quality. Large tables split using our existing `_split_large_table()` helper (preserves header rows).

**Image elements:** Skip HybridChunker. Extract directly:
- `page_content` = `element.caption_text(doc)` (or `"Figure on page N"` fallback)
- Save `element.get_image(doc)` as PNG to `data/uploads/{doc_id}/images/`
- Include bbox from provenance data

HybridChunker tokenizer configuration:
```python
from docling_core.transforms.chunker.tokenizer.openai import OpenAITokenizer
import tiktoken

tokenizer = OpenAITokenizer(
    tokenizer=tiktoken.encoding_for_model("gpt-4o"),
    max_tokens=settings.chunk_size // 4,  # ~250 tokens for chunk_size=1000
)
chunker = HybridChunker(tokenizer=tokenizer)
```

Note: Requires `docling-core[chunking-openai]` extra. There is a known import bug (#459) where HybridChunker unconditionally imports `transformers`. If this is not fixed in our version, fallback to `HuggingFaceTokenizer` with explicit `max_tokens`.

### Speed Optimizations

Tested configurations on `attention_is_all_you_need.pdf` (15 pages):

| Config | CPU Time | Notes |
|---|---|---|
| Default (all models) | 50.6s | Baseline |
| No OCR | 40.3s | Same quality on native-text PDFs |
| No OCR + no code enrichment | 41.3s | Same quality (no code in paper) |
| No OCR + no code + fast tables | 31.4s | Same element count, 1.6x faster |

Applied optimizations:
1. **`do_ocr = False`** by default (config flag to enable for scanned PDFs)
2. **`do_code_enrichment = False`** always (not needed for RAG)
3. **`TableStructureOptions(mode="fast")`** — minor accuracy tradeoff, meaningful speed gain
4. **`AcceleratorOptions(device="auto")`** — auto-detect GPU (CUDA/MPS), fall back to CPU
5. **Cached converter instance** — models loaded once at first use, reused for all subsequent documents

Expected with GPU: ~5-10s per paper (5-6x speedup over CPU).

### Picture Description (Optional)

When `DOCLING_PICTURE_DESCRIPTION=true`:

```python
pipeline_options.do_picture_description = True
```

SmolVLM-256M runs locally on CPU/GPU (~500MB model download on first run). Descriptions are stored in the figure's metadata and used as the chunk's `page_content`.

When disabled (default): the chunk's `page_content` uses `element.caption_text(doc)` — the caption extracted from document structure.

### OCR

Disabled by default (`DOCLING_OCR=false`). Most PDFs have native text — OCR adds ~10s overhead with no benefit. Enable for scanned documents via config flag. Uses RapidOCR (bundled with docling, no extra install).

### Fallback Chain

```
docling (PDF) → enhanced → default
docling (non-PDF) → default loaders (DOCX/PPTX/XLSX/HTML)
```

If docling fails on a **PDF**, falls back to enhanced mode (PyMuPDF + Poppler), then default. If docling fails on a **non-PDF** (DOCX, PPTX, etc.), falls back directly to the default loaders for that format — enhanced mode is PDF-only and would be a no-op for other formats.

### Installation

```bash
# Standard install (no docling)
uv sync

# With docling support
uv sync --extra docling
```

### Model Pre-Download

First run with docling downloads neural models from HuggingFace (~1.2GB). This is too slow for an HTTP upload request. Solutions:

1. **Pre-download command** (recommended):
   ```bash
   uv run python -c "from docling.document_converter import DocumentConverter; DocumentConverter()"
   ```
   Or: `docling-tools models download`

2. **Startup log:** On first `process()` call, log: `"Docling: downloading models (~1.2GB), this may take several minutes..."`

3. **Cached converter:** After first load, the singleton converter is reused — subsequent uploads are fast.

### Compatibility

- All existing modes unchanged
- Same API endpoints, same response format
- Same frontend — no changes needed
- Same vector store, same retrieval pipeline
- Page highlight endpoint works with docling bbox data (same `[x0,y0,x1,y1]` format)
- Works with both SQLite and PostgreSQL
- `_supplement_visual_chunks()` in `query.py` works automatically — it keys on `chunk_type == "image"` and `chunk_type == "table"`, which docling chunks provide

### What We Don't Build

- No new API endpoints
- No new frontend components
- No custom layout analysis (docling handles it)
- No caption matching heuristics (docling has `caption_text()`)
- No LibreOffice conversion for non-PDF (docling handles DOCX/PPTX/XLSX/HTML natively)
- No `langchain-docling` dependency — use direct docling API (langchain-docling loses image data and bbox info)

### Testing Plan

**Unit tests (offline, mocked):**
- `has_docling()` returns True/False correctly
- Metadata mapping: TextItem → text chunk, TableItem → table chunk, PictureItem → image chunk
- Bbox conversion (docling coords → our format)
- Image saving (PIL Image → PNG file → correct path)
- Fallback when docling not installed
- Config settings parsed correctly
- `ParseMode.DOCLING == "docling"` enum value exists
- Update existing `test_parse_mode_enum_values` to include DOCLING

**Integration tests (requires docling installed):**
- Process a real PDF and verify chunk count, types, metadata
- Verify figure images are saved to correct paths
- Verify table content is preserved as markdown (not triplet format)
- Compare quality: same PDF through enhanced vs docling mode
- Test with/without picture descriptions
- Test OCR on a scanned PDF
- Test non-PDF formats: DOCX, PPTX, XLSX

### Resolved Questions

1. ~~Whether `langchain-docling` package is needed~~ → **No.** Use direct docling API. langchain-docling loses image data, bbox info, and structured table data. Our project doesn't use LangChain loaders for enhanced or vision mode.
2. ~~First-run model download UX~~ → **Solved:** pre-download command + startup log + cached converter singleton.
3. ~~HybridChunker for tables~~ → **No.** HybridChunker uses triplet format for tables which loses structure. Tables exported directly via `table.export_to_markdown()`.
4. ~~Disk usage~~ → ~2.2-2.7GB total (packages + models) on Windows with CPU PyTorch. GPU users need CUDA PyTorch (~2.5GB extra).

### Open Questions (to resolve during implementation)

1. Exact bbox coordinate system in docling 2.80+ — verify origin and axis direction
2. `OpenAITokenizer` import bug (#459) — may need fallback to HuggingFaceTokenizer with explicit max_tokens
