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

## Architecture

### Processing Pipeline

```
Upload request
  → DocumentProcessor.load_and_split(file_path, doc_id)
    → if PARSE_MODE == "docling":
        → DoclingDocumentProcessor.process(file_path, doc_id)
          → docling.DocumentConverter.convert(file_path)
            → Heron layout model (text, tables, figures, headings)
            → TableFormer (cell-level table structure)
            → RapidOCR (scanned pages)
            → Optional: SmolVLM picture descriptions
          → DoclingDocument (unified representation)
          → HybridChunker → docling chunks
          → map_to_langchain_documents()
            → List[LangChain Document] with standard metadata
    → else: existing modes (default / enhanced / vision)
```

### File Changes

#### New Files

**`app/services/docling_processor.py`** (~200 lines)

Core wrapper around docling. Responsibilities:
- Configure `DocumentConverter` with pipeline options
- Run conversion: `converter.convert(file_path)` → `DoclingDocument`
- Iterate over document elements (`PictureItem`, `TableItem`, `TextItem`)
- Extract and save figure images to `data/uploads/{doc_id}/images/`
- Use `HybridChunker` for structure-aware chunking
- Map each chunk to a LangChain `Document` with our metadata schema

Key function:
```python
def process(file_path: Path, doc_id: str, settings: Settings, source_name: str) -> list[Document]:
    """Process a document with docling and return LangChain Document chunks.

    source_name: clean filename for citations (doc_id prefix stripped).
    Sets chunk_index and parse_mode on every chunk before returning.
    """
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
  - `docling_ocr: bool = True` — enable OCR for scanned pages

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

### Chunking Strategy

Use docling's `HybridChunker` instead of our `RecursiveCharacterTextSplitter`:

```python
from docling.chunking import HybridChunker

chunker = HybridChunker(
    tokenizer="Xenova/gpt-4o",  # GPT tokenizer — matches OpenAI embedding model's tokenization
    max_tokens=settings.chunk_size // 4,  # ~250 tokens for chunk_size=1000
)
chunks = list(chunker.chunk(doc))
```

Note: The tokenizer must approximate OpenAI's `text-embedding-3-small` tokenization. A GPT-family tokenizer is the closest match. The exact tokenizer ID will be verified during implementation — docling may accept `"cl100k_base"` or a tiktoken-compatible name. The `max_tokens` ratio (chars / 4) is a rough approximation; we'll calibrate against actual chunk sizes during testing.

Benefits:
- Tables stay as single chunks (not split mid-row)
- Figures keep their captions
- Headings are preserved as context in each chunk
- Reading order is respected

Each docling chunk contains references back to the original `DocItem` elements, allowing us to extract the `chunk_type`, `page`, `bbox`, and `image_path` for our metadata.

### Picture Description (Optional)

When `DOCLING_PICTURE_DESCRIPTION=true`:

```python
pipeline_options.do_picture_description = True
pipeline_options.picture_description_options = PictureDescriptionVlmOptions(
    repo_id="HuggingFaceTB/SmolVLM-256M-Instruct",
)
```

SmolVLM-256M runs locally on CPU (~500MB model download on first run). Descriptions are stored in the figure's metadata and used as the chunk's `page_content`.

When disabled (default): the chunk's `page_content` uses `element.caption_text(doc)` — the caption extracted from document structure.

### OCR

Enabled by default (`DOCLING_OCR=true`). Uses RapidOCR (bundled with docling, no extra install). Automatically activates on pages with bitmap regions.

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

First run with docling downloads neural models from HuggingFace (~500MB-1GB). This is too slow for an HTTP upload request. The docling processor must handle this:

1. **Startup check:** During `has_docling()` or app lifespan, log a warning if models are not cached:
   `"Docling models not yet downloaded. First document processing will take several minutes."`
2. **Pre-download command** (recommended): Add a CLI helper or document a one-liner:
   ```bash
   uv run python -c "from docling.document_converter import DocumentConverter; DocumentConverter()"
   ```
   This triggers the model download without processing a document.
3. **Timeout handling:** The `process()` function should not have an artificial timeout — let docling download and process. The FastAPI upload endpoint already has no timeout by default. If a reverse proxy is in front, the user must configure its timeout.

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
- Verify table content is preserved (not split mid-table)
- Compare quality: same PDF through enhanced vs docling mode
- Test with/without picture descriptions
- Test OCR on a scanned PDF
- Test non-PDF formats: DOCX, PPTX, XLSX

### Open Questions (to resolve during implementation)

1. Exact bbox coordinate system in docling 2.80+ — verify origin and axis direction
2. `HybridChunker` tokenizer: verify that `"Xenova/gpt-4o"` or `"cl100k_base"` is accepted. Calibrate `max_tokens` against actual chunk sizes.

### Resolved Questions

3. ~~Whether `langchain-docling` package is needed~~ → **No.** Use direct docling API. The project doesn't use LangChain loaders for enhanced or vision mode — keeping it consistent. Avoids an extra dependency.
4. ~~First-run model download UX~~ → **Solved:** startup warning log + documented pre-download command (see Installation section).
