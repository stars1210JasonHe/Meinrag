# Plan: Click Source → Opens PDF Directly + Toolbar in Viewer

**Date**: 2026-03-19
**Status**: Planned
**Prerequisite**: Unified PDF viewer (committed `84ea82c`)

---

## Problem

Current flow requires 2 steps to see the PDF:

```
1. Click source header → expands raw text (useless for PDFs)
2. Click "View" button → opens PDF viewer lightbox
```

User wants:

```
1. Click source header → PDF viewer opens directly
```

Additionally, Copy/Quote/Ask buttons are on the source citation row, but once the user is in the PDF viewer they can't access them without closing the viewer first.

---

## Target UX

### Source list (in chat message)

```
Sources (4)
├── [▸] quantitative_modeling.pdf  p.3  [Table] 92%  #12  [⬇]
├── [▸] quantitative_modeling.pdf  p.7        85%  #31  [⬇]
├── [▸] quantitative_modeling.pdf  p.1  [Image] 78%  #5   [⬇]
└── [▸] some-website.com                       72%       [⬇]
```

- Click any PDF source → **PDF viewer opens** at that page with highlight
- Click web source → **expands raw text** (no PDF available)
- Download button stays on each row (always accessible)
- Score badge, page, chunk type badge stay visible
- Chevron icon: `▸` for PDF sources (indicates "opens viewer"), expand/collapse for non-PDF

### Inside the PDF viewer (lightbox)

```
┌─────────────────────────────────────────────────┐
│  [X]                                            │
│                                                 │
│  [◀]     ┌──────────────────────┐        [▶]   │
│          │                      │               │
│          │   PDF page canvas    │               │
│          │   + text layer       │               │
│          │   + bbox highlight   │               │
│          │                      │               │
│          └──────────────────────┘               │
│                                                 │
│       [◀ 3 / 15 ▶] [Go to source]              │  ← page nav
│                                                 │
│  [- 100% +] [Reset]    [Copy] [Quote] [Ask]     │  ← toolbar
│                                                 │
│  [▸ Chunk Text]                                 │  ← collapsible
│                                                 │
│  Source 1 of 4 · filename.pdf p.3               │  ← info
│  Select text · Scroll zoom · Dbl-click toggle   │
└─────────────────────────────────────────────────┘
```

- **Copy**: copies `source.content` to clipboard, shows "Copied!" feedback
- **Quote**: inserts quoted excerpt into the chat input
- **Ask**: opens inline input to ask about this chunk
- These 3 buttons sit in the toolbar row next to zoom controls

---

## File Changes

### 1. `SourceCitation.jsx` — Click header opens PDF viewer

**Current header click**: `onClick={() => setExpanded(!expanded)}`

**New logic**:

```jsx
const hasPdf = source.doc_id && source.page != null && !isWeb && onViewPdf

const handleHeaderClick = () => {
  if (hasPdf) {
    onViewPdf(sourceIdx)       // open PDF viewer
  } else {
    setExpanded(!expanded)     // expand raw text (web/non-PDF)
  }
}
```

**Remove**: "View" button (lines 137-146) — header click replaces it

**Remove from header** (for PDF sources only): Copy, Quote, Ask buttons — moved into lightbox

**Keep on header**: Score badge, page number, chunk type badge, Download button, chevron icon

**Chevron icon change**: For PDF sources, always show `▸` (not toggle). For non-PDF, keep expand/collapse chevron.

### 2. `ContentLightbox.jsx` — Add Copy/Quote/Ask toolbar

**New props**: `onCopy`, `onQuote`, `onAskAbout`

**Add toolbar** between zoom controls and chunk panel:

```jsx
{/* Action toolbar */}
<div className="lightbox-toolbar">
  <div className="lightbox-zoom-controls">
    {/* existing zoom buttons */}
  </div>
  <div className="lightbox-actions">
    <button onClick={handleCopy} title="Copy chunk text">
      <Copy size={15} /> {copied ? 'Copied!' : 'Copy'}
    </button>
    <button onClick={() => onQuote?.(quotedText)} title="Quote in input">
      <Quote size={15} /> Quote
    </button>
    <button onClick={() => setShowAsk(!showAsk)} title="Ask about this">
      <MessageCircleQuestion size={15} /> Ask
    </button>
  </div>
</div>
```

**Copy handler** (inside ContentLightbox):
```jsx
const [copied, setCopied] = useState(false)
const handleCopy = () => {
  navigator.clipboard.writeText(source.content).then(() => {
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  })
}
```

**Quote handler**: truncate to 200 chars, wrap in quotes, call `onQuote`

**Ask handler**: show inline input below toolbar (same pattern as SourceCitation's ask input)

**State additions**: `copied` (bool), `showAsk` (bool), `askInput` (string)

### 3. `MessageBubble.jsx` — Pass callbacks to ContentLightbox

**Current**: ContentLightbox gets `sources, currentIndex, onClose, onNavigate, type`

**Add**: `onQuote, onAskAbout`

```jsx
<ContentLightbox
  sources={lightboxSources}
  currentIndex={lightboxState.index}
  onClose={() => setLightboxState({ type: null, index: null })}
  onNavigate={(i) => setLightboxState(prev => ({ ...prev, index: i }))}
  type={lightboxState.type}
  onQuote={onQuote}
  onAskAbout={onAskAboutChunk}
/>
```

### 4. `App.css` — Toolbar styles

**Add** `.lightbox-toolbar` (flex row, space-between for zoom + actions):

```css
.lightbox-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  max-width: 800px;
  gap: 12px;
}

.lightbox-actions {
  display: flex;
  gap: 4px;
}

.lightbox-actions button {
  /* similar to zoom control buttons but with text labels */
  display: flex;
  align-items: center;
  gap: 4px;
  background: rgba(255, 255, 255, 0.1);
  border: none;
  color: #ccc;
  padding: 4px 10px;
  border-radius: 6px;
  cursor: pointer;
  font-size: 0.8rem;
}

.lightbox-actions button:hover {
  background: rgba(255, 255, 255, 0.2);
  color: #fff;
}

.lightbox-ask-input {
  /* inline ask input below toolbar */
}
```

**Remove**: `.source-view-pdf-btn` styles (button is gone)

---

## Edge Cases

| Scenario | Behavior |
|----------|----------|
| PDF source, click header | Opens PDF viewer |
| Web source, click header | Expands raw text |
| .docx source with page but no PDF | PdfViewer fails → `onError` → fallback to text |
| Copy in viewer | Copies `source.content` (chunk text), not selected PDF text |
| Quote in viewer | Inserts quoted excerpt, closes lightbox |
| Ask in viewer | Shows inline input, submits question, closes lightbox |
| Ask button clicked but empty input | Submit disabled |

---

## What Does NOT Change

- `PdfViewer.jsx` — no changes
- Image/Table gallery click → still opens lightbox (same as before)
- Download button — stays on source citation row
- Score, page number, chunk type badges — stay on source citation row
- Non-PDF source expand/collapse — stays the same

---

## Summary

| File | Changes | Effort |
|------|---------|--------|
| `SourceCitation.jsx` | Header click opens viewer for PDFs, remove "View" button, remove Copy/Quote/Ask for PDFs | Small |
| `ContentLightbox.jsx` | Add toolbar with Copy/Quote/Ask, state for copied/ask | Medium |
| `MessageBubble.jsx` | Pass `onQuote`, `onAskAbout` to ContentLightbox | Small |
| `App.css` | Add toolbar styles, remove `.source-view-pdf-btn` | Small |
