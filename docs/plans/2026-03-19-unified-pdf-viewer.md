# Plan: Unified PDF Viewer

**Date**: 2026-03-19
**Status**: Planned
**Goal**: Merge the "Content" / "PDF Page" / text-only views into one unified experience

---

## Problem

Currently clicking a source opens `ContentLightbox` with a confusing split:

- **Text chunks** → shows raw text (no PDF context)
- **PDF button** → opens modal with "Content" vs "PDF Page" toggle
- **Image chunks** → shows extracted image
- **Table chunks** → shows markdown-rendered table

The "Content / PDF Page" toggle is awkward — users don't think in terms of "content" vs "pdf page". They want to see where the information came from in the original document.

## Design

### Unified Behavior

**Any source with a PDF** → opens PDF.js viewer at the cited page with highlight.

The current 3 experiences collapse into:

| Source Type | Has PDF? | What Opens |
|-------------|----------|------------|
| Text chunk | Yes | PDF viewer at page, bbox highlight (if available), text layer for selection |
| Table chunk | Yes | PDF viewer at page, bbox highlight around table |
| Image chunk | Yes | PDF viewer at page, bbox highlight around figure |
| Text chunk | No (web source, .txt, .docx) | Raw text view (current behavior) |
| Table chunk | No | Markdown table view (current behavior) |
| Image chunk | No image_path | Fallback text view |

### Key Changes

1. **Remove "Content / PDF Page" toggle** — PDF is always the default when a PDF source exists
2. **Add text layer to PdfViewer** — enables text selection (Ctrl+C), search in the future
3. **Add collapsible chunk panel** — raw chunk text shown in a small expandable panel below the PDF (not a separate tab)
4. **Unify source click behavior** — clicking any source (text/table/image) with a `doc_id + page` opens PdfViewer
5. **Keep fallbacks** — non-PDF sources (web, .docx, .txt) still use text/markdown views

### Component Architecture

```
ContentLightbox (orchestrator: zoom, pan, keyboard, navigation)
├── PdfViewer (when source has doc_id + page, i.e. from a PDF)
│   ├── <canvas> — PDF page rendering
│   ├── <div class="textLayer"> — invisible text selection layer (NEW)
│   ├── <canvas> — bbox highlight overlay
│   └── Page nav bar (prev/next, page input, "Go to source")
├── ImageView (when image source has no PDF page — rare fallback)
├── TableView (when table source has no PDF page — non-PDF files)
├── TextView (when text source has no PDF — web/docx/txt)
└── ChunkPanel (collapsible footer showing raw chunk text) (NEW)
```

---

## Implementation Steps

### Step 1: Add text layer to PdfViewer

**File**: `frontend/src/components/PdfViewer.jsx`

PDF.js has a built-in `TextLayer` API. After rendering the canvas, render an aligned text layer div on top:

```javascript
import { TextLayer } from 'pdfjs-dist'
```

After `pageObj.render()` completes:
1. Create/clear a `<div class="textLayer">` positioned over the canvas
2. Call `TextLayer.create({ textContentSource: pageObj.getTextContent(), container: div, viewport })`
3. The text layer is transparent but selectable — users can highlight + copy text from the PDF

**CSS**: import `pdfjs-dist/web/pdf_viewer.css` for the text layer styles, or replicate the minimal needed rules:
```css
.textLayer {
  position: absolute;
  top: 0; left: 0;
  width: 100%; height: 100%;
  overflow: hidden;
  line-height: 1;
  opacity: 0.25;  /* slightly visible for selection feedback */
}
.textLayer span {
  position: absolute;
  white-space: pre;
  color: transparent;
  pointer-events: all;
}
.textLayer ::selection {
  background: rgba(59, 130, 246, 0.3);  /* blue selection highlight */
}
```

**Interaction with zoom/pan**: The text layer div must have the same transform as the canvas container so text positions align at all zoom levels.

**Interaction with drag-to-pan**: When zoom > 1, we currently capture mouseDown for panning. This conflicts with text selection. Solution: only pan on middle-click or when holding Shift. Normal click + drag = text selection. Or simpler: keep current behavior (pan on drag), add a "Select text" mode toggle button.

**Recommended approach**: Don't fight the interaction. At zoom=1 (default), cursor is default and text selection works. At zoom>1, cursor is grab and drag pans. User can still select text by using Ctrl+A or the chunk panel below. This matches how most PDF viewers work (Adobe, Chrome's built-in viewer).

### Step 2: Remove "Content / PDF Page" toggle from ContentLightbox

**File**: `frontend/src/components/ContentLightbox.jsx`

Remove:
- `viewMode` state (`'content' | 'pdf'`)
- The toggle button group (lines 170-186)
- The `viewMode` reset effect (lines 127-131)
- The hint about toggling to PDF Page (line 296)

Replace the rendering logic:

```
Current:
  viewMode === 'pdf' → PdfViewer
  isImage → <img>
  isTable → <MarkdownRenderer>
  isText → <div>{text}</div>

New:
  hasPdfView → PdfViewer (any chunk type with doc_id + page)
  isImage && !hasPdfView → <img> fallback
  isTable && !hasPdfView → <MarkdownRenderer> fallback
  isText && !hasPdfView → <div>{text}</div> fallback
```

This means:
- Text chunks from PDFs → PdfViewer
- Table chunks from PDFs → PdfViewer (with bbox around the table)
- Image chunks from PDFs → PdfViewer (with bbox around the figure)
- Web sources → text view (no change)
- Non-PDF doc sources → text/table view (no change)

### Step 3: Add collapsible ChunkPanel below the PDF

**File**: `frontend/src/components/ContentLightbox.jsx` (inline, not a separate component)

Below the PDF viewer and zoom controls, add a collapsible panel:

```jsx
{source.content && hasPdfView && (
  <div className="lightbox-chunk-panel">
    <button
      className="lightbox-chunk-toggle"
      onClick={() => setChunkPanelOpen(!chunkPanelOpen)}
    >
      {chunkPanelOpen ? <ChevronDown size={14}/> : <ChevronRight size={14}/>}
      Chunk Text
    </button>
    {chunkPanelOpen && (
      <div className="lightbox-chunk-content">
        {isTable
          ? <MarkdownRenderer content={source.content} />
          : <pre>{source.content}</pre>
        }
      </div>
    )}
  </div>
)}
```

**CSS**: Dark background panel, max-height 150px with scrollbar, monospace for text, rendered markdown for tables.

### Step 4: Unify click handling in MessageBubble

**File**: `frontend/src/components/MessageBubble.jsx`

Currently:
- Image gallery → `{ type: 'image', index: i }`
- Table gallery → `{ type: 'table', index: i }`
- Source citation PDF button → `{ type: 'text', index: i }`

The `type` field currently determines which source array to use AND how to render. After the change:
- `type` still determines which source array (for prev/next navigation within same type)
- But rendering always prefers PdfViewer when `doc_id + page` are available

**No changes needed to MessageBubble** — the source arrays are already correct. The rendering logic change is entirely in ContentLightbox (Step 2).

### Step 5: Update SourceCitation — rename "PDF" button

**File**: `frontend/src/components/SourceCitation.jsx`

The separate "PDF" button is no longer needed for text sources because clicking the source header should open the PDF viewer directly. But we keep the button for quick access:

- Rename from "PDF" to "View" (since it now opens any source in the viewer)
- Also show for table and image chunks (currently only shown for text chunks)
- Consider: make clicking the source header itself open the viewer (expand still available via the chevron)

**Minimal change**: Just rename the button label. The `onViewPdf` callback name stays the same internally.

### Step 6: CSS cleanup

**File**: `frontend/src/App.css`

- Remove `.lightbox-view-toggle` styles (the Content/PDF toggle is gone)
- Add `.lightbox-chunk-panel`, `.lightbox-chunk-toggle`, `.lightbox-chunk-content` styles
- Add `.textLayer` styles for PDF.js text selection
- Update `.lightbox-hint` text

---

## File Changes Summary

| File | Change | Effort |
|------|--------|--------|
| `frontend/src/components/PdfViewer.jsx` | Add text layer rendering after canvas render | Medium |
| `frontend/src/components/ContentLightbox.jsx` | Remove toggle, unify rendering, add chunk panel | Medium |
| `frontend/src/components/SourceCitation.jsx` | Rename "PDF" → "View" | Small |
| `frontend/src/App.css` | Remove toggle CSS, add chunk panel + text layer CSS | Small |
| `frontend/src/components/MessageBubble.jsx` | No changes needed | None |

---

## Edge Cases

| Case | Behavior |
|------|----------|
| Web source (no doc_id) | Shows raw text, no PDF viewer |
| .docx/.txt source (doc_id but no PDF) | `/pdf` endpoint returns 404 → PdfViewer shows error → falls back to text |
| Image with no image_path and no page | Shows caption text only |
| Table from non-PDF file | Shows markdown table (no PDF available) |
| Scanned PDF (no text layer) | PDF renders as image, text layer is empty (no selectable text), bbox highlight still works |
| PDF with rotation | `viewport.convertToViewportPoint()` handles this (already implemented) |

### Fallback for non-PDF documents

PdfViewer's `/pdf` endpoint only serves `.pdf` files. For non-PDF documents (docx, txt, etc.), the endpoint returns 404. PdfViewer catches this and shows an error state. ContentLightbox should detect this and fall back to text/table/image view.

**Approach**: Add `onError` callback prop to PdfViewer. When PDF load fails, ContentLightbox falls back to the old rendering (text/table/image views). This ensures non-PDF documents still work.

```jsx
// In ContentLightbox:
const [pdfFailed, setPdfFailed] = useState(false)

// Reset when navigating
useEffect(() => { setPdfFailed(false) }, [currentIndex])

// Rendering:
hasPdfView && !pdfFailed
  ? <PdfViewer ... onError={() => setPdfFailed(true)} />
  : /* existing fallback views */
```

---

## Interaction Model

| Zoom Level | Cursor | Left-click+drag | Text Selection |
|-----------|--------|----------------|----------------|
| 1x (default) | default | selects text | Yes (via text layer) |
| >1x (zoomed) | grab | pans the view | No (use chunk panel to copy) |

| Keyboard | Action |
|----------|--------|
| Esc | Close lightbox |
| Left/Right arrows | Previous/next source |
| PageUp/PageDown | Previous/next PDF page |
| +/- | Zoom in/out |
| 0 | Reset zoom |

---

## Not in Scope (future)

- Multi-bbox highlighting (multiple sources on same page)
- PDF search (Ctrl+F within the viewer)
- Annotation/bookmark system
- Continuous scroll mode (all pages visible)
