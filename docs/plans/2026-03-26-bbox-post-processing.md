# Bbox Post-Processing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Compute merged bounding boxes for text chunks from docling's element-level bboxes, so every text chunk gets a precise highlight in the PDF viewer instead of fuzzy text-matching.

**Architecture:** After HybridChunker creates text chunks, each chunk's `chunk.meta.doc_items` contains the raw docling elements with exact page coordinates. We merge element bboxes into a single bbox per chunk and store it in metadata. For multi-page chunks (7 out of 70), we use the first page's elements only.

**Tech Stack:** Python, docling (HybridChunker, doc_items, prov bbox)

---

## Key Facts from Investigation

- `chunk.meta.doc_items` is a list of docling elements per chunk
- Each element has `prov[0].bbox` with `(l, t, r, b)` coordinates
- Bbox origin is **bottom-left** (t > b) — needs conversion to top-left for PDF viewer
- `_convert_bbox()` already exists in `docling_processor.py` for this conversion
- 7 out of 70 chunks span multiple pages — use first page's elements for bbox
- Table/image/formula chunks already have bboxes set — only text chunks need this
- Page heights available from `doc.pages[page_no].size.height`

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `app/services/docling_processor.py` | Modify | Compute merged bbox in `_chunk_text_elements()` |
| `tests/test_chunk_quality.py` | Modify | Tests for bbox merging logic |

**No frontend changes. No new files. Single function addition + wiring.**

---

## Task 1: Compute Merged Bbox for Text Chunks

**Files:**
- Modify: `app/services/docling_processor.py`
- Modify: `tests/test_chunk_quality.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_chunk_quality.py`:

```python
class TestBboxMerging:
    """Test merged bbox computation from docling element bboxes."""

    def test_single_element_bbox(self):
        """Single element bbox is returned directly."""
        from app.services.docling_processor import _merge_element_bboxes
        # bbox format: [x0, y0, x1, y1] (top-left origin, already converted)
        elements = [{"page": 1, "bbox": [100, 200, 400, 250]}]
        result = _merge_element_bboxes(elements, target_page=1)
        assert result == [100, 200, 400, 250]

    def test_multiple_elements_merged(self):
        """Multiple elements on same page produce a merged bbox."""
        from app.services.docling_processor import _merge_element_bboxes
        elements = [
            {"page": 1, "bbox": [100, 200, 400, 250]},
            {"page": 1, "bbox": [100, 260, 400, 310]},
            {"page": 1, "bbox": [80, 320, 420, 370]},
        ]
        result = _merge_element_bboxes(elements, target_page=1)
        # min x0=80, min y0=200, max x1=420, max y1=370
        assert result == [80, 200, 420, 370]

    def test_multi_page_uses_target_page(self):
        """Only elements on target_page are included in merged bbox."""
        from app.services.docling_processor import _merge_element_bboxes
        elements = [
            {"page": 2, "bbox": [100, 500, 400, 600]},
            {"page": 2, "bbox": [100, 610, 400, 700]},
            {"page": 3, "bbox": [100, 50, 400, 100]},  # different page
        ]
        result = _merge_element_bboxes(elements, target_page=2)
        assert result == [100, 500, 400, 700]

    def test_no_elements_on_target_page(self):
        """Returns None if no elements match target page."""
        from app.services.docling_processor import _merge_element_bboxes
        elements = [{"page": 3, "bbox": [100, 200, 400, 250]}]
        result = _merge_element_bboxes(elements, target_page=1)
        assert result is None

    def test_empty_elements(self):
        """Empty elements list returns None."""
        from app.services.docling_processor import _merge_element_bboxes
        assert _merge_element_bboxes([], target_page=1) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_chunk_quality.py::TestBboxMerging -v
```

Expected: FAIL — `_merge_element_bboxes` does not exist yet.

- [ ] **Step 3: Implement `_merge_element_bboxes`**

Add to `app/services/docling_processor.py` (after the chunk_utils imports, before `has_docling()`):

```python
def _merge_element_bboxes(
    elements: list[dict], target_page: int
) -> list[float] | None:
    """Merge element bboxes on a specific page into one enclosing bbox.

    Args:
        elements: List of {"page": int, "bbox": [x0, y0, x1, y1]} dicts
                  (already in top-left origin coordinates).
        target_page: Only include elements on this page.

    Returns:
        [x0, y0, x1, y1] merged bbox, or None if no elements on target_page.
    """
    page_bboxes = [e["bbox"] for e in elements if e["page"] == target_page]
    if not page_bboxes:
        return None

    x0 = min(b[0] for b in page_bboxes)
    y0 = min(b[1] for b in page_bboxes)
    x1 = max(b[2] for b in page_bboxes)
    y1 = max(b[3] for b in page_bboxes)
    return [x0, y0, x1, y1]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_chunk_quality.py::TestBboxMerging -v
```

- [ ] **Step 5: Wire into `_chunk_text_elements()`**

In `_chunk_text_elements()`, after creating each `text_chunk`, extract element bboxes and compute the merged bbox. Find the loop where chunks are created (around line 240):

```python
        for chunk in chunker.chunk(doc):
            # ... existing visual skip + min length check ...

            # Get page from first doc_item provenance
            page = 0
            if chunk.meta and chunk.meta.doc_items:
                item = chunk.meta.doc_items[0]
                if item.prov and len(item.prov) > 0:
                    page = item.prov[0].page_no - 1

            text_chunk = _make_text_chunk(chunk.text, page, source_name)

            # Add heading context
            if chunk.meta and chunk.meta.headings:
                text_chunk.metadata["headings"] = " > ".join(chunk.meta.headings)

            # === NEW: Compute merged bbox from doc_items ===
            if chunk.meta and chunk.meta.doc_items:
                elem_bboxes = []
                for item in chunk.meta.doc_items:
                    if item.prov and len(item.prov) > 0:
                        prov = item.prov[0]
                        item_page = prov.page_no - 1  # 0-indexed
                        bbox = prov.bbox
                        page_h = page_heights.get(prov.page_no, 792.0)
                        converted = _convert_bbox(bbox.l, bbox.t, bbox.r, bbox.b, page_h)
                        elem_bboxes.append({"page": item_page, "bbox": converted})

                merged = _merge_element_bboxes(elem_bboxes, target_page=page)
                if merged:
                    text_chunk.metadata["bbox"] = json.dumps(merged)

            chunks.append(text_chunk)
```

IMPORTANT: `page_heights` is defined in the `process()` function but `_chunk_text_elements()` doesn't have access to it. You need to pass `page_heights` as a parameter to `_chunk_text_elements()`.

Update function signature:
```python
def _chunk_text_elements(doc, settings, source_name, page_heights=None):
```

And the call in `process()`:
```python
    text_chunks = _chunk_text_elements(doc, settings, source_name, page_heights)
```

- [ ] **Step 6: Run full test suite**

```bash
uv run pytest tests/test_chunk_quality.py -v
uv run pytest tests/ --ignore=tests/test_frontend_e2e.py --ignore=tests/test_api_workflow.py -v -x
```

- [ ] **Step 7: Commit**

```bash
git add app/services/docling_processor.py tests/test_chunk_quality.py
git commit -m "feat: compute merged bboxes for text chunks from docling element coordinates"
```

---

## Task 2: Verify with Real Upload + Visual Test

- [ ] **Step 1: Restart server**

```bash
# Kill existing, start fresh
taskkill //F //IM python.exe
uv run uvicorn app.main:app --host 0.0.0.0 --port 9999
```

- [ ] **Step 2: Delete and re-upload attention paper**

```bash
curl -s -X DELETE "http://localhost:9999/documents/<doc_id>" -H "X-User-Id: admin"
curl -s -X POST "http://localhost:9999/documents/upload" -H "X-User-Id: admin" \
  -F "file=@test cases/attention_is_all_you_need.pdf"
```

- [ ] **Step 3: Verify chunks have bboxes**

```python
# Check how many text chunks now have bboxes
import pickle
with open('data/vectorstore/faiss/index.pkl', 'rb') as f:
    docstore, _ = pickle.load(f)
doc_id = '<new_doc_id>'
text_with_bbox = sum(1 for v in docstore._dict.values()
    if v.metadata.get('doc_id') == doc_id
    and v.metadata.get('chunk_type') == 'text'
    and v.metadata.get('bbox'))
text_total = sum(1 for v in docstore._dict.values()
    if v.metadata.get('doc_id') == doc_id
    and v.metadata.get('chunk_type') == 'text')
print(f'Text chunks with bbox: {text_with_bbox}/{text_total}')
```

Expected: Most text chunks now have bboxes (was 0 before).

- [ ] **Step 4: Run eval to verify no regression**

```bash
uv run python scripts/eval_retrieval.py --save bbox-post --doc-id <new_doc_id>
uv run python scripts/eval_retrieval.py --compare docling-fixed bbox-post
```

Expected: Scores unchanged (bbox doesn't affect retrieval, only display).

- [ ] **Step 5: Visual test in browser**

Open frontend, query the attention paper, click a text source. Should now show a bbox overlay (colored rectangle) instead of text-matching highlights. The bbox should cover the exact paragraph on the page.

- [ ] **Step 6: Commit and push**

```bash
git add -A
git commit -m "eval: bbox post-processing verification — text chunks now have precise bboxes"
git push origin feature/poppler-figure-extraction
```

---

## Summary

| Before | After |
|--------|-------|
| Text chunks: `bbox=null` | Text chunks: `bbox=[x0,y0,x1,y1]` (merged from elements) |
| PDF viewer: fuzzy text-matching highlights | PDF viewer: precise bbox overlays |
| Multi-page chunks: no bbox | Multi-page chunks: bbox from first page's elements |

**Changes:** ~30 lines in `docling_processor.py` + 5 tests. No frontend changes needed — the existing bbox overlay code in PdfViewer already handles bboxes when present.
