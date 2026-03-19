# Plan: Refactor PdfViewer from raw pdfjs-dist to react-pdf

**Date**: 2026-03-19
**Status**: Planned

---

## Problem

Current `PdfViewer.jsx` uses raw `pdfjs-dist` (300+ lines) with manual:
- Canvas sizing and render task management
- Text layer creation and positioning (CSS mismatch bugs)
- Scale calculation to avoid CSS shrinking
- Render lifecycle and cleanup

This caused multiple debugging rounds for text selection alignment, overlay positioning, and canvas scaling.

## Solution

Replace with `react-pdf` (v10) which handles all of the above automatically. Keep our custom overlay, page navigation, and highlight logic.

---

## What react-pdf gives us for free

| Problem we had | react-pdf solution |
|----------------|-------------------|
| Canvas scale calculation | `<Page width={containerWidth} />` — auto-sizes |
| Text layer alignment | `renderTextLayer={true}` (default) + CSS import |
| Canvas cleanup on unmount | Handled internally |
| Render task cancellation | Handled internally |
| Text selection | Works out of the box with included CSS |
| Device pixel ratio handling | Auto retina support |

## What we keep custom

- Page navigation UI (prev/next, page input)
- Bbox highlight overlay (red rectangle for table/image/formula chunks)
- Text highlight overlay (yellow rectangles for text chunks without bbox)
- Zoom/pan controls (managed by parent ContentLightbox)
- Copy/Quote/Ask toolbar

---

## New PdfViewer.jsx Design

```jsx
import { Document, Page, pdfjs } from 'react-pdf'
import 'react-pdf/dist/Page/TextLayer.css'
import 'react-pdf/dist/Page/AnnotationLayer.css'

// Worker setup
pdfjs.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString()

function PdfViewer({ docId, page, bbox, chunkText, zoom, pan, dragging, onClick, onError }) {
  const [numPages, setNumPages] = useState(null)
  const [currentPage, setCurrentPage] = useState((page || 0) + 1) // react-pdf is 1-indexed
  const [pageSize, setPageSize] = useState(null) // { width, height, originalWidth, originalHeight }

  const pdfUrl = useMemo(() => `${API_BASE}/documents/${docId}/pdf`, [docId])
  const initialPage = (page || 0) + 1

  return (
    <div className="pdf-viewer-wrapper" onClick={onClick}>
      <div className="pdf-viewer-canvas-container" style={{ transform, cursor }}>
        <Document
          file={pdfUrl}
          onLoadSuccess={({ numPages }) => setNumPages(numPages)}
          onLoadError={() => onError?.()}
          loading={<div className="pdf-viewer-loading">Loading PDF...</div>}
          error={<div className="pdf-viewer-error">Failed to load PDF</div>}
        >
          <Page
            pageNumber={currentPage}
            height={Math.round(window.innerHeight * 0.82)}
            renderTextLayer={true}
            renderAnnotationLayer={false}
            onLoadSuccess={(pageInfo) => setPageSize(pageInfo)}
          >
            {/* Custom highlight overlay as child of Page */}
            <HighlightOverlay
              bbox={bbox}
              chunkText={chunkText}
              pageSize={pageSize}
              isSourcePage={currentPage === initialPage}
            />
          </Page>
        </Document>
      </div>

      {/* Page nav bar — same as current */}
      {/* ... */}
    </div>
  )
}
```

### HighlightOverlay Component

Renders as a child of `<Page>`, positioned absolutely over the canvas:

```jsx
function HighlightOverlay({ bbox, chunkText, pageSize, isSourcePage }) {
  if (!isSourcePage || !pageSize) return null

  // Bbox highlight (red rectangle) — for table/image/formula chunks
  if (bbox && bbox.length === 4) {
    const [x0, y0, x1, y1] = bbox
    // Convert PDF points to percentages of page dimensions
    return (
      <div className="pdf-highlight-overlay">
        <div className="pdf-highlight-bbox" style={{
          left: `${(x0 / pageSize.originalWidth) * 100}%`,
          top: `${(y0 / pageSize.originalHeight) * 100}%`,
          width: `${((x1 - x0) / pageSize.originalWidth) * 100}%`,
          height: `${((y1 - y0) / pageSize.originalHeight) * 100}%`,
        }} />
      </div>
    )
  }

  // Text highlight (yellow) — for text chunks without bbox
  // Use customTextRenderer on <Page> instead of canvas overlay
  return null
}
```

### Text Highlighting via customTextRenderer

Instead of drawing on a canvas overlay, use `<Page>`'s `customTextRenderer` prop to wrap matching text in `<mark>` tags:

```jsx
const makeTextRenderer = (chunkText) => {
  if (!chunkText) return undefined
  const normalize = (s) => s.replace(/\s+/g, ' ').trim().toLowerCase()
  const fragments = buildFragments(normalize(chunkText))

  return ({ str }) => {
    const norm = normalize(str)
    const matched = fragments.some(f => f.includes(norm) || norm.includes(f))
    return matched ? `<mark>${str}</mark>` : str
  }
}

<Page
  customTextRenderer={isSourcePage ? makeTextRenderer(chunkText) : undefined}
/>
```

CSS for `<mark>` inside text layer:
```css
.textLayer mark {
  background: rgba(250, 204, 21, 0.4);
  color: transparent;
  border-radius: 2px;
}
```

This is **much simpler** than the canvas overlay approach — no coordinate conversion, no canvas sizing, automatically scales with zoom.

---

## File Changes

| File | Change |
|------|--------|
| `frontend/src/components/PdfViewer.jsx` | Rewrite: replace raw pdfjs-dist with react-pdf `<Document>` + `<Page>` |
| `frontend/src/App.css` | Remove manual `.textLayer` CSS (react-pdf provides it), update highlight styles |
| `frontend/vite.config.js` | Update manualChunks if needed |
| `frontend/package.json` | Add `react-pdf`, keep `pdfjs-dist` (peer dep) |

### What gets deleted from PdfViewer.jsx

- `pdfjsLib.getDocument()` — replaced by `<Document file={url}>`
- `pageObj.render()` — replaced by `<Page pageNumber={n}>`
- `new TextLayer()` / `tl.render()` — replaced by `renderTextLayer={true}`
- `canvasRef`, `overlayRef`, `textLayerRef` — no longer needed
- `renderTaskRef`, `textLayerInstanceRef` — handled internally
- `pdfDocRef` + destroy logic — handled internally
- `renderedViewport` state — replaced by `onLoadSuccess` page dimensions
- `highlightChunkText()` canvas drawing — replaced by `customTextRenderer`
- `TARGET_HEIGHT` calculation — replaced by `height={...}` prop on `<Page>`

### What stays

- Page navigation state + UI (prev/next, page input, Go to source)
- `onError` callback to ContentLightbox
- Keyboard handlers (PageUp/PageDown)
- `chunkText` and `bbox` props
- Zoom/pan/dragging props from parent

---

## Highlight Strategy Summary

| Chunk type | Has bbox? | Highlight method |
|-----------|----------|-----------------|
| Table/Image/Formula | Yes | `<div>` overlay positioned with CSS percentages inside `<Page>` children |
| Text (docling) | No | `customTextRenderer` wraps matching text in `<mark>` tags |
| Text (non-docling, has bbox) | Yes | Same `<div>` overlay as tables |

---

## Migration Steps

1. `npm install react-pdf` (keeps existing `pdfjs-dist` as peer dep)
2. Rewrite `PdfViewer.jsx` using `<Document>` + `<Page>` + `customTextRenderer`
3. Update CSS — remove manual `.textLayer` rules, add `<mark>` highlight style
4. Remove manual pdfjs-dist imports (worker setup stays, just uses `pdfjs` from react-pdf)
5. Test: text selection, highlight, page nav, zoom
6. Build, verify bundle size
