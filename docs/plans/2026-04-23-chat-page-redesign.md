# Chat Page Redesign — Tabbed Doc Viewer as Main Area Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flip the Chat page from "chat-big + sources-panel-right" to "tabbed doc viewer as main area + chat as right sidebar", matching NotebookLM/Perplexity UX. Users see full docs (PDF or rendered text) as the focus, with chat messages + source cards on the side.

**Architecture:** Main area = tab bar + viewer (`PdfViewer` for PDF, new `TextDocViewer` for non-PDF files rendered as chunk-anchored markdown). Chat sidebar (~340px right) = messages + input + simplified source cards. Citation click routes: resolve source → ensure tab is open → switch to tab → scroll to chunk location → apply highlight. Tabs persist across chat turns within a session. Ask AI / Web search stay in chat messages (no tab). Color system unified via `HIGHLIGHT_COLORS` by source index.

**Tech Stack:** React 19 + Tailwind 4 + react-pdf (existing) + react-i18next + react-markdown. No new dependencies.

**Predecessor context:** HEAD = `0ad049f` (mindmap frontend rolled back, backend mindmap endpoints still live but unused on frontend). Today's work is PURELY the Chat page redesign — no mindmap work.

---

## Scope (confirmed with user)

- Layout flip: PDF/text main, chat right
- Tabs: max ~6 visible + horizontal scroll for overflow
- Tabs persist during chat session, user can close with X, auto-reopen on new citation
- PDF: reuse existing `PdfViewer.jsx` (page-by-page, not continuous scroll, with fully-functional PageUp/PageDown + search)
- Non-PDF (DOCX/TXT/MD/HTML/XLSX/PPTX): new `TextDocViewer.jsx` — renders all chunks as markdown with `#chunk-{N}` anchors + click-to-scroll + background highlight
- Ask AI / Web search: stay in chat messages, no tab created
- Streaming: don't auto-jump to citations during streaming
- Bbox highlight lifecycle: persists until user clicks another source or a new answer arrives (does NOT clear on scroll)
- Source list ordering: by score (current behavior, unchanged)
- History restore: open first cited doc of last answer as tab; button to restore all
- Session history panel: keep existing toggleable left panel; just narrower layout
- Unified highlight colors: use `PdfViewer.jsx`'s `HIGHLIGHT_COLORS` rotation, indexed by source position

---

## File Structure

**Created:**
- `frontend/src/components/TextDocViewer.jsx` — non-PDF full-doc viewer with chunk anchors (~160 lines)
- `frontend/src/components/SourceTabs.jsx` — tab bar with overflow handling (~100 lines)
- `frontend/src/components/SourceCard.jsx` — compact source card for chat sidebar (~70 lines)
- `frontend/src/hooks/useDocTabs.js` — tab state management (~80 lines)

**Modified:**
- `frontend/src/pages/ChatPage.jsx` — rewrite layout to use tabs + chat sidebar (~200 lines of diff)
- `frontend/src/i18n/locales/en.json` — add `chatRedesign.*` keys
- `frontend/src/i18n/locales/zh.json` — same, Chinese

**Deleted:**
- `frontend/src/components/SourceViewer.jsx` — replaced by `PdfViewer` + `TextDocViewer`
- `frontend/src/components/SourceItem.jsx` — replaced by `SourceCard` (NOTE: verify nothing else uses it before deleting; if referenced elsewhere, keep it)

**NOT modified:** all backend files, `PdfViewer.jsx`, `MarkdownRenderer.jsx` (if exists), `lib/citations.js`, DashboardPage.jsx, GraphPage.jsx, other pages.

---

## Task 1: `useDocTabs` hook — tab state management

**Files:**
- Create: `frontend/src/hooks/useDocTabs.js`

This hook owns the "which docs are open as tabs" state. Pure state — no rendering. The hook is the foundation that the rest of the redesign uses.

- [ ] **Step 1: Create the hook file**

Create `E:\MEINRAG\frontend\src\hooks\useDocTabs.js`:

```javascript
import { useState, useCallback, useMemo } from 'react'

/**
 * Manages which documents are open as tabs in the Chat page's main area.
 *
 * Tabs persist across chat turns within a session. Sources from each answer
 * trigger auto-open + activation. User can close via X.
 *
 * Tab shape: { doc_id: string, filename: string, file_type: string }
 *   - file_type: the raw type string from backend (e.g. "pdf", "docx")
 *   - Renderer decides which component to use based on file_type
 */
export function useDocTabs() {
  const [tabs, setTabs] = useState([])           // ordered list of tabs
  const [activeDocId, setActiveDocId] = useState(null)

  /**
   * Open (or activate existing) tab for this doc.
   * If a tab for doc_id already exists, just activate it.
   * Otherwise, push a new tab to the end and activate it.
   */
  const openTab = useCallback((doc) => {
    if (!doc || !doc.doc_id) return
    setTabs(prev => {
      const exists = prev.some(t => t.doc_id === doc.doc_id)
      if (exists) return prev
      return [...prev, {
        doc_id: doc.doc_id,
        filename: doc.filename || doc.source_file || doc.doc_id,
        file_type: doc.file_type || _inferTypeFromFilename(doc.filename || doc.source_file),
      }]
    })
    setActiveDocId(doc.doc_id)
  }, [])

  /**
   * Close a tab. If it was active, fall back to the tab to its left
   * (or null if none left).
   */
  const closeTab = useCallback((doc_id) => {
    setTabs(prev => {
      const idx = prev.findIndex(t => t.doc_id === doc_id)
      if (idx === -1) return prev
      const next = prev.filter(t => t.doc_id !== doc_id)
      return next
    })
    setActiveDocId(current => {
      if (current !== doc_id) return current
      // Pick the tab that would remain to the left of the closed one
      const remaining = tabs.filter(t => t.doc_id !== doc_id)
      if (remaining.length === 0) return null
      const idx = tabs.findIndex(t => t.doc_id === doc_id)
      const nextActive = remaining[Math.max(0, idx - 1)]
      return nextActive?.doc_id ?? null
    })
  }, [tabs])

  /**
   * Switch to tab by doc_id. No-op if not open.
   */
  const activateTab = useCallback((doc_id) => {
    if (!doc_id) return
    setActiveDocId(current => {
      if (current === doc_id) return current
      // Only switch if tab is actually open
      const exists = tabs.some(t => t.doc_id === doc_id)
      return exists ? doc_id : current
    })
  }, [tabs])

  /**
   * Reset everything (e.g. on session switch).
   */
  const resetTabs = useCallback(() => {
    setTabs([])
    setActiveDocId(null)
  }, [])

  /**
   * Given an array of source objects (from a chat answer), open tabs for
   * every unique doc_id. Returns the first doc_id encountered — caller
   * can choose to activate it or not.
   */
  const openTabsForSources = useCallback((sources) => {
    if (!sources || sources.length === 0) return null
    const seen = new Set()
    const newTabs = []
    for (const s of sources) {
      if (!s.doc_id || seen.has(s.doc_id)) continue
      seen.add(s.doc_id)
      newTabs.push({
        doc_id: s.doc_id,
        filename: s.source_file || s.doc_id,
        file_type: _inferTypeFromFilename(s.source_file),
      })
    }
    if (newTabs.length === 0) return null
    setTabs(prev => {
      const existingIds = new Set(prev.map(t => t.doc_id))
      const toAdd = newTabs.filter(t => !existingIds.has(t.doc_id))
      return [...prev, ...toAdd]
    })
    return newTabs[0].doc_id
  }, [])

  const activeTab = useMemo(
    () => tabs.find(t => t.doc_id === activeDocId) || null,
    [tabs, activeDocId],
  )

  return {
    tabs,
    activeDocId,
    activeTab,
    openTab,
    closeTab,
    activateTab,
    resetTabs,
    openTabsForSources,
  }
}

function _inferTypeFromFilename(filename) {
  if (!filename) return 'unknown'
  const lower = filename.toLowerCase()
  for (const ext of ['pdf', 'docx', 'doc', 'txt', 'md', 'html', 'xlsx', 'xls', 'pptx', 'ppt']) {
    if (lower.endsWith('.' + ext)) return ext
  }
  return 'unknown'
}
```

- [ ] **Step 2: Verify no syntax errors via build**

Run from `E:\MEINRAG`:
```bash
cd frontend && npm run build 2>&1 | tail -5
```
Expected: build succeeds. If it fails, hook has a syntax error.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/useDocTabs.js
git commit -m "$(cat <<'EOF'
feat(chat): useDocTabs hook for tab state management

Owns which docs are open as tabs in the Chat page main area. Provides
openTab / closeTab / activateTab / openTabsForSources / resetTabs.
Infers file_type from filename extension. Pure state — no rendering.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `TextDocViewer` component — non-PDF full-doc viewer

**Files:**
- Create: `frontend/src/components/TextDocViewer.jsx`

Renders all chunks of a non-PDF doc as a single scrollable markdown document, with anchor-based navigation to a selected chunk and background highlight.

- [ ] **Step 1: Create the component**

Create `E:\MEINRAG\frontend\src\components\TextDocViewer.jsx`:

```jsx
import { useEffect, useRef, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Loader2 } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useTranslation } from 'react-i18next'
import { fetchDocumentChunks } from '@/lib/api'
import { cn } from '@/lib/utils'

const USER_ID = 'admin'

// Same color palette as PdfViewer.jsx HIGHLIGHT_COLORS (keep in sync)
const HIGHLIGHT_COLORS = [
  { bg: 'rgba(59,130,246,0.18)', border: '#3b82f6' },   // blue
  { bg: 'rgba(245,158,11,0.18)', border: '#f59e0b' },   // amber
  { bg: 'rgba(16,185,129,0.18)', border: '#10b981' },   // emerald
  { bg: 'rgba(236,72,153,0.18)', border: '#ec4899' },   // pink
  { bg: 'rgba(168,85,247,0.18)', border: '#a855f7' },   // violet
]

export { HIGHLIGHT_COLORS }

/**
 * Renders all chunks of a non-PDF doc with anchor navigation.
 *
 * Props:
 *   docId: string — the document id
 *   activeChunkIndex: number | null — chunk to scroll to and highlight
 *   activeSourceColorIndex: number — index into HIGHLIGHT_COLORS for active chunk
 */
export default function TextDocViewer({ docId, activeChunkIndex, activeSourceColorIndex = 0 }) {
  const { t } = useTranslation()
  const containerRef = useRef(null)

  const { data, isLoading, error } = useQuery({
    queryKey: ['doc-chunks-all', docId],
    queryFn: () => fetchDocumentChunks(docId, null, USER_ID),
    staleTime: 5 * 60 * 1000,
    enabled: !!docId,
  })

  // Sort chunks by chunk_index so the doc reads in order
  const orderedChunks = useMemo(() => {
    if (!data?.chunks) return []
    return [...data.chunks].sort((a, b) => (a.chunk_index ?? 0) - (b.chunk_index ?? 0))
  }, [data])

  // On active chunk change, scroll into view
  useEffect(() => {
    if (activeChunkIndex == null || !containerRef.current) return
    const el = containerRef.current.querySelector(`#chunk-${activeChunkIndex}`)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }
  }, [activeChunkIndex])

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full opacity-40">
        <Loader2 className="animate-spin" size={20} />
      </div>
    )
  }

  if (error) {
    return (
      <div className="p-8 text-sm opacity-60" style={{ color: 'var(--fg)' }}>
        {t('textDocViewer.error', { defaultValue: 'Failed to load document' })}
      </div>
    )
  }

  if (!orderedChunks.length) {
    return (
      <div className="p-8 text-sm opacity-60 text-center" style={{ color: 'var(--fg)' }}>
        {t('textDocViewer.empty', { defaultValue: 'This document has no chunks.' })}
      </div>
    )
  }

  const color = HIGHLIGHT_COLORS[activeSourceColorIndex % HIGHLIGHT_COLORS.length]

  return (
    <div
      ref={containerRef}
      className="h-full overflow-y-auto px-6 py-4 text-sm leading-relaxed max-w-3xl mx-auto"
      style={{ color: 'var(--fg)' }}
    >
      {orderedChunks.map(chunk => {
        const isActive = chunk.chunk_index === activeChunkIndex
        return (
          <div
            key={chunk.chunk_index}
            id={`chunk-${chunk.chunk_index}`}
            className={cn(
              'my-2 px-3 py-2 rounded transition-colors',
              isActive ? 'border-l-4' : 'border-l-4 border-transparent',
            )}
            style={isActive ? {
              backgroundColor: color.bg,
              borderLeftColor: color.border,
            } : {}}
          >
            <ReactMarkdown remarkPlugins={[remarkGfm]}>
              {chunk.content || ''}
            </ReactMarkdown>
          </div>
        )
      })}
    </div>
  )
}
```

- [ ] **Step 2: Verify build**

Run:
```bash
cd frontend && npm run build 2>&1 | tail -5
```
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/TextDocViewer.jsx
git commit -m "$(cat <<'EOF'
feat(chat): TextDocViewer — non-PDF full-doc viewer with chunk anchors

Renders all chunks of a doc as a single markdown-rendered stream,
sorted by chunk_index. Each chunk has #chunk-{idx} anchor. Active
chunk scrolls into view + gets a colored background + left border
using the same HIGHLIGHT_COLORS palette as PdfViewer. For DOCX/TXT/
MD/HTML/XLSX/PPTX — anything that isn't PDF.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `SourceTabs` component — tab bar with overflow handling

**Files:**
- Create: `frontend/src/components/SourceTabs.jsx`

The tab bar at the top of the main area. Shows one tab per open doc. Handles overflow via horizontal scroll when tabs exceed viewport.

- [ ] **Step 1: Create the component**

Create `E:\MEINRAG\frontend\src\components\SourceTabs.jsx`:

```jsx
import { useRef, useEffect } from 'react'
import { X, FileText, FileType2 } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * Tab bar for the Chat page main area.
 *
 * Props:
 *   tabs: [{ doc_id, filename, file_type }]
 *   activeDocId: string | null
 *   onActivate: (doc_id) => void
 *   onClose: (doc_id) => void
 */
export default function SourceTabs({ tabs, activeDocId, onActivate, onClose }) {
  const scrollRef = useRef(null)
  const activeRef = useRef(null)

  // Ensure active tab is visible on change
  useEffect(() => {
    if (activeRef.current) {
      activeRef.current.scrollIntoView({ behavior: 'smooth', block: 'nearest', inline: 'nearest' })
    }
  }, [activeDocId])

  if (tabs.length === 0) return null

  return (
    <div
      ref={scrollRef}
      className="flex items-end gap-0.5 overflow-x-auto overflow-y-hidden shrink-0 border-b"
      style={{
        borderColor: 'var(--border-strong, rgba(255,255,255,0.14))',
        scrollbarWidth: 'thin',
      }}
    >
      {tabs.map(tab => {
        const active = tab.doc_id === activeDocId
        const Icon = tab.file_type === 'pdf' ? FileText : FileType2
        return (
          <div
            key={tab.doc_id}
            ref={active ? activeRef : null}
            className={cn(
              'flex items-center gap-1.5 px-3 py-2 text-xs cursor-pointer shrink-0 border-r transition-colors',
              active
                ? 'bg-[var(--bg-1)] border-b-2 border-b-[var(--signature,#5b7ec9)]'
                : 'opacity-60 hover:opacity-100',
            )}
            style={{
              borderRightColor: 'var(--border-strong, rgba(255,255,255,0.14))',
              color: 'var(--fg)',
              maxWidth: 200,
            }}
            onClick={() => onActivate(tab.doc_id)}
            title={tab.filename}
          >
            <Icon size={12} className="shrink-0 opacity-70" />
            <span className="truncate">{tab.filename}</span>
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                onClose(tab.doc_id)
              }}
              className="shrink-0 p-0.5 rounded hover:bg-white/10 opacity-50 hover:opacity-100"
              aria-label="Close tab"
            >
              <X size={11} />
            </button>
          </div>
        )
      })}
    </div>
  )
}
```

- [ ] **Step 2: Verify build**

Run:
```bash
cd frontend && npm run build 2>&1 | tail -5
```
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/SourceTabs.jsx
git commit -m "$(cat <<'EOF'
feat(chat): SourceTabs — tab bar with overflow scroll for open docs

Horizontal scroll when tabs exceed viewport width. Active tab gets
a signature-blue bottom border. Each tab has an X to close. Icon
per file type (FileText for PDF, FileType2 for others). Truncates
filename at 200px with full-name tooltip.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `SourceCard` component — compact source card for chat sidebar

**Files:**
- Create: `frontend/src/components/SourceCard.jsx`

Replaces the larger `SourceItem` pattern. Each source = one compact row showing citation number + filename + page + text preview. Click activates the tab + jumps to chunk.

- [ ] **Step 1: Create the component**

Create `E:\MEINRAG\frontend\src\components\SourceCard.jsx`:

```jsx
import { FileText, Table2, Image, Calculator } from 'lucide-react'
import { cn } from '@/lib/utils'
import { HIGHLIGHT_COLORS } from './TextDocViewer'

const TYPE_ICONS = {
  text: FileText,
  table: Table2,
  image: Image,
  formula: Calculator,
}

/**
 * Compact source card for the chat sidebar's "Sources" list.
 *
 * Props:
 *   source: the source object ({doc_id, source_file, chunk_index, chunk_type,
 *           page, content, summary})
 *   index: 0-based position in the sources array (matches [N] minus 1)
 *   isActive: bool — is this the currently selected source (for visual state)
 *   onClick: () => void
 */
export default function SourceCard({ source, index, isActive, onClick }) {
  const Icon = TYPE_ICONS[source.chunk_type] || FileText
  const color = HIGHLIGHT_COLORS[index % HIGHLIGHT_COLORS.length]
  const preview = (source.summary || source.content || '').trim().replace(/\s+/g, ' ').slice(0, 80)
  const pageLabel = source.page != null ? `p.${source.page + 1}` : null
  const filename = (source.source_file || source.doc_id || '?').replace(/\.[^.]+$/, '')

  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'w-full text-left px-3 py-2 border-l-2 transition-colors',
        isActive ? 'bg-white/5' : 'hover:bg-white/5',
      )}
      style={{
        borderLeftColor: isActive ? color.border : 'transparent',
        color: 'var(--fg)',
      }}
    >
      <div className="flex items-center gap-1.5 mb-1">
        <span
          className="text-[10px] font-semibold px-1.5 py-0.5 rounded"
          style={{
            backgroundColor: color.bg,
            color: color.border,
          }}
        >
          [{index + 1}]
        </span>
        <Icon size={11} className="opacity-50 shrink-0" />
        <span className="text-xs truncate flex-1 opacity-80">{filename}</span>
        {pageLabel && (
          <span className="text-[10px] opacity-40 shrink-0">{pageLabel}</span>
        )}
      </div>
      {preview && (
        <p className="text-[11px] opacity-50 line-clamp-2 leading-snug">
          {preview}
        </p>
      )}
    </button>
  )
}
```

- [ ] **Step 2: Verify build**

Run:
```bash
cd frontend && npm run build 2>&1 | tail -5
```
Expected: build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/SourceCard.jsx
git commit -m "$(cat <<'EOF'
feat(chat): SourceCard — compact source card for the chat sidebar

Replaces larger SourceItem for the new redesign. One row per source:
citation number [N] (colored by HIGHLIGHT_COLORS), file icon, filename
(without extension), page label, 80-char text preview. Active source
gets a colored left border.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Rewrite `ChatPage.jsx` with new layout

**Files:**
- Modify: `frontend/src/pages/ChatPage.jsx`

This is the big integration task. Everything from Tasks 1-4 plugs in here. Preserve all existing behavior: session history, streaming, supplement actions, scope/collection selection, keyboard navigation. Only the **layout** of chat + sources + viewer changes.

**Strategy:** replace the two render blocks (chat area + source panel) with:
- Main area (flex-1): `<SourceTabs>` + either `<PdfViewer>` or `<TextDocViewer>` based on active tab's file_type
- Chat sidebar (w-[340px] or w-80): existing chat messages + input + a new `<SourceCard>` list where old source chips/panel were

- [ ] **Step 1: Read the current ChatPage.jsx to locate render blocks**

Before editing, locate these specific sections of `frontend/src/pages/ChatPage.jsx`:
- Top of return statement (around line 538-540) — outer `<div className="flex h-full overflow-hidden">`
- Session history panel (around lines 541-579) — keep AS-IS, just will live to the left of the new layout
- Chat messages + input (around lines 582-770) — this becomes the RIGHT sidebar in new layout
- Source panel (around lines 772-808) — DELETE entirely, replaced by tabs + viewer

Read with `git show HEAD:frontend/src/pages/ChatPage.jsx` if needed to get a clean version.

- [ ] **Step 2: Add hook + component imports at top of ChatPage.jsx**

Find the imports section (top of file). Add:

```javascript
import { useDocTabs } from '@/hooks/useDocTabs'
import SourceTabs from '@/components/SourceTabs'
import TextDocViewer from '@/components/TextDocViewer'
import SourceCard from '@/components/SourceCard'
import PdfViewer from '@/components/PdfViewer'
```

REMOVE (no longer used):
```javascript
import SourceItem from '@/components/SourceItem'
import SourceViewer from '@/components/SourceViewer'
```

- [ ] **Step 3: Add tab state inside the component**

Inside the `ChatPage` function, near the other `useState` calls (around lines 100-110), add:

```javascript
const {
  tabs,
  activeDocId,
  activeTab,
  openTab,
  closeTab,
  activateTab,
  resetTabs,
  openTabsForSources,
} = useDocTabs()
```

- [ ] **Step 4: Replace the `onCitationClick` logic**

Find the existing `makeMarkdownComponents` callback (around line 110-116):

```javascript
const markdownComponents = useMemo(
  () => makeMarkdownComponents((sourceIndex) => {
    if (sourceIndex >= 0 && sourceIndex < sources.length) {
      setSelectedSource(sourceIndex)
      setShowSources(true)
    }
  }),
  [sources.length]
)
```

Replace with:

```javascript
const onCitationClick = useCallback((sourceNum) => {
  // sourceNum is 1-based from the citation [N]; sources array is 0-based
  const idx = sourceNum - 1
  if (idx < 0 || idx >= displaySources.length) return
  const { source } = displaySources[idx]
  // 1. Ensure the doc tab is open
  openTab({
    doc_id: source.doc_id,
    filename: source.source_file,
    file_type: null, // useDocTabs infers from filename
  })
  // 2. Activate the tab
  activateTab(source.doc_id)
  // 3. Set the selected source (drives PDF page / TextDocViewer chunk scroll)
  setSelectedSource(source.originalIndex)
}, [displaySources, openTab, activateTab])

const markdownComponents = useMemo(
  () => makeMarkdownComponents(onCitationClick),
  [onCitationClick],
)
```

Note: `displaySources` already exists (already sorted by score). `source.originalIndex` already exists (added by the sort). This wiring works without changing existing data flow.

- [ ] **Step 5: Open tabs when a new answer arrives**

Find the section that handles new sources arriving (around line 200-204):

```javascript
if (lastSources) {
  setSources(lastSources)
  setShowSources(true)
} else {
  setSources([])
}
```

Replace with:

```javascript
if (lastSources) {
  setSources(lastSources)
  // Open tabs for any new docs cited; activate the first one if no tab is active
  const firstDocId = openTabsForSources(lastSources)
  if (firstDocId && !activeDocId) {
    activateTab(firstDocId)
  }
} else {
  setSources([])
}
```

- [ ] **Step 6: Reset tabs on session switch**

Find `startNewChat` (around line 145-155) and `loadSession` (search for `loadSession` function). Add `resetTabs()` at the top of each. For example, in `startNewChat`:

```javascript
const startNewChat = () => {
  resetTabs()       // <-- add this line first
  // ...existing code
}
```

Same for the start of `loadSession`.

- [ ] **Step 7: Replace the entire render return with the new layout**

Find the `return (` at the start of the JSX render (around line 538). Replace EVERYTHING from that line to the end of the function (including the outer `</div>` matched at line 809) with:

```jsx
return (
  <div className="flex h-full overflow-hidden">
    {/* Session history — UNCHANGED from current behavior */}
    {showHistory && (
      <div
        className="w-56 border-r flex flex-col shrink-0"
        style={{ borderColor: 'var(--border-strong, rgba(255,255,255,0.14))', backgroundColor: 'var(--bg-1, #0c0c0f)' }}
      >
        <div className="p-2 border-b" style={{ borderColor: 'var(--border-strong, rgba(255,255,255,0.14))' }}>
          <button
            onClick={startNewChat}
            className="flex items-center gap-2 w-full px-3 py-2 rounded-lg text-xs"
            style={{ backgroundColor: 'var(--signature, #5b7ec9)', color: '#fff' }}
          >
            <Plus size={14} /> {t('chat.newChat')}
          </button>
        </div>
        <div className="flex-1 overflow-auto py-1">
          {sessions.length === 0 ? (
            <p className="px-3 py-4 text-xs opacity-30 text-center">{t('chat.noSessionsYet')}</p>
          ) : (
            sessions.map(s => (
              <button
                key={s.session_id}
                onClick={() => loadSession(s.session_id)}
                className={cn(
                  'w-full px-3 py-2 text-left text-xs truncate transition-colors',
                  sessionId === s.session_id ? 'bg-white/10' : 'hover:bg-white/5',
                )}
                style={{ color: 'var(--fg, #f4f2ee)' }}
              >
                <div className="truncate">{s.preview || t('common.empty')}</div>
                <div className="opacity-30 mt-0.5">
                  {new Date(s.last_access).toLocaleDateString()}
                </div>
              </button>
            ))
          )}
        </div>
      </div>
    )}

    {/* MAIN AREA — tabs + PDF/TextDoc viewer */}
    <div className="flex-1 flex flex-col min-w-0">
      {tabs.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-sm opacity-40" style={{ color: 'var(--fg)' }}>
          {t('chat.emptyMain', { defaultValue: 'Your source documents will appear here when you ask a question.' })}
        </div>
      ) : (
        <>
          <SourceTabs
            tabs={tabs}
            activeDocId={activeDocId}
            onActivate={activateTab}
            onClose={closeTab}
          />
          <div className="flex-1 overflow-hidden">
            {activeTab && (
              activeTab.file_type === 'pdf' ? (
                <PdfViewer
                  key={activeTab.doc_id}
                  docId={activeTab.doc_id}
                  page={selectedSource != null && sources[selectedSource]?.doc_id === activeTab.doc_id
                    ? sources[selectedSource].page
                    : null}
                  highlights={selectedSource != null && sources[selectedSource]?.doc_id === activeTab.doc_id
                    ? [{
                        bbox: sources[selectedSource].bbox,
                        isActive: true,
                        colorIndex: selectedSource,
                      }]
                    : []}
                />
              ) : (
                <TextDocViewer
                  key={activeTab.doc_id}
                  docId={activeTab.doc_id}
                  activeChunkIndex={selectedSource != null && sources[selectedSource]?.doc_id === activeTab.doc_id
                    ? sources[selectedSource].chunk_index
                    : null}
                  activeSourceColorIndex={selectedSource ?? 0}
                />
              )
            )}
          </div>
        </>
      )}
    </div>

    {/* CHAT SIDEBAR — w-[360px] or similar */}
    <div
      className="w-[360px] border-l flex flex-col shrink-0"
      style={{
        borderColor: 'var(--border-strong, rgba(255,255,255,0.14))',
        backgroundColor: 'var(--bg-1, #0c0c0f)',
      }}
    >
      {/* Chat messages — this replicates the middle area's message list from the old layout.
          Scope/collection chip header kept if present in old code; if not, leave empty here. */}
      <div className="flex-1 overflow-y-auto px-3 py-3">
        {messages.map((m, i) => (
          <div
            key={i}
            className={cn(
              'mb-3 rounded-lg px-3 py-2 text-sm',
              m.role === 'user'
                ? 'ml-6 bg-[var(--signature,#5b7ec9)] text-white'
                : 'mr-6',
            )}
            style={m.role === 'user' ? {} : { backgroundColor: 'var(--bg, #08080a)', color: 'var(--fg)' }}
          >
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {m.content}
            </ReactMarkdown>
            {m.role === 'assistant' && m.refused && (
              <SupplementActions
                question={m.question}
                sessionId={sessionId}
                onResponse={onSupplementResponse}
              />
            )}
          </div>
        ))}
        {streaming && (
          <div className="mr-6 rounded-lg px-3 py-2 text-sm" style={{ backgroundColor: 'var(--bg, #08080a)', color: 'var(--fg)' }}>
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
              {streamingText || '...'}
            </ReactMarkdown>
          </div>
        )}
      </div>

      {/* Sources list (compact cards) */}
      {sources.length > 0 && (
        <div className="border-t shrink-0 max-h-[40%] overflow-y-auto" style={{ borderColor: 'var(--border-strong, rgba(255,255,255,0.14))' }}>
          <div className="px-3 py-2 text-[10px] uppercase tracking-wider opacity-40 sticky top-0" style={{ backgroundColor: 'var(--bg-1, #0c0c0f)' }}>
            {t('chat.sourcesWithCount', { count: sources.length })}
          </div>
          {displaySources.map(({ source: s, originalIndex }) => (
            <SourceCard
              key={originalIndex}
              source={s}
              index={originalIndex}
              isActive={originalIndex === selectedSource}
              onClick={() => {
                setSelectedSource(originalIndex)
                openTab({
                  doc_id: s.doc_id,
                  filename: s.source_file,
                  file_type: null,
                })
                activateTab(s.doc_id)
              }}
            />
          ))}
        </div>
      )}

      {/* Input area — preserves existing input logic */}
      <div className="border-t p-3 shrink-0" style={{ borderColor: 'var(--border-strong, rgba(255,255,255,0.14))' }}>
        {/* KEEP the existing InputBar or textarea + send button from the old layout — the plan
            can't show the exact JSX because it depends on the specific InputBar props in use.
            Paste the same input block that was in the middle area before. */}
      </div>
    </div>
  </div>
)
```

**Note on the input area at the bottom of the sidebar:** the exact JSX for the input box (InputBar, send button, scope selector, etc.) depends on what the original middle area had. Copy it verbatim from the old render block. The surrounding padding / flex just changes.

**Also:** some existing state that was used only for the OLD source panel (`showSources`, `selectedSource` keyboard nav loop) may still be referenced — keep those state variables, even if unused by the new UI, so the rest of the component still compiles. We can remove dead code in Task 6.

- [ ] **Step 8: Verify the build compiles**

Run:
```bash
cd frontend && npm run build 2>&1 | tail -10
```
Expected: build succeeds. If it fails, common causes:
- Unused imports warning (non-fatal in vite)
- Typo in JSX (vite shows the line)
- Missing `SupplementActions` or `InputBar` import — re-add from the old top of file
- `showHistory` state missing — it existed before, verify it's still declared

If the build fails due to reference errors to functions from the old source panel (like `setShowSources`), just declare them as no-op stubs at the top of the component (cleanup in Task 6):
```javascript
const [showSources, setShowSources] = useState(false) // legacy, removed in Task 6
```

- [ ] **Step 9: Manual smoke test**

Start dev server + backend, open `http://localhost:5173`, navigate to Chat page. Verify:

1. Main area shows "Your source documents will appear here..." empty state initially
2. Chat sidebar on the right with input at bottom
3. Ask any question (e.g., "what is attention?")
4. Answer streams in chat sidebar
5. Sources list appears at bottom of chat sidebar
6. Source cards show `[1]`, `[2]`, filename, page, text preview
7. Tab appears in main area
8. PDF loads in main area (if source is a PDF doc)
9. Click a source card → PDF jumps to that page + bbox highlight appears
10. Click another source card → jumps to next page or doc
11. If multi-doc question: multiple tabs appear, clicking tab switches viewer
12. Close a tab with X → tab removed, active switches to adjacent
13. New question → new sources → new tabs auto-open

If anything is broken, debug before committing. `showHistory` toggle and scope selection should also still work — verify.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/pages/ChatPage.jsx
git commit -m "$(cat <<'EOF'
feat(chat): redesign layout — tabbed doc viewer + chat sidebar

Main area: SourceTabs + PdfViewer (PDF) or TextDocViewer (non-PDF).
Right sidebar (360px): chat messages + compact SourceCard list + input.
Session history panel unchanged on far left (toggleable).

Tabs open automatically on citation click, persist per session, close
via X. Citation [N] click resolves to source -> ensures tab open ->
activates tab -> PDF jumps to page+bbox OR TextDocViewer scrolls to
chunk anchor. Ask AI / Web search stay in chat messages (no tab).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Cleanup — delete `SourceViewer`, `SourceItem`; add i18n keys

**Files:**
- Delete: `frontend/src/components/SourceViewer.jsx`
- Delete: `frontend/src/components/SourceItem.jsx` (only if nothing else imports it — verify first)
- Modify: `frontend/src/i18n/locales/en.json` — add `chat.emptyMain`, `textDocViewer.*`
- Modify: `frontend/src/i18n/locales/zh.json` — same in Chinese
- Modify: `frontend/src/pages/ChatPage.jsx` — remove dead state (`showSources`, keyboard ArrowUp/Down loop that depended on the old source panel)

- [ ] **Step 1: Check if `SourceItem` is used elsewhere**

Run:
```bash
grep -rn "SourceItem" frontend/src/ | grep -v node_modules
```

- If ONLY `ChatPage.jsx` referenced it (and we removed that import in Task 5): safe to delete
- If another file imports it (TableGallery, etc.): LEAVE the file alone, just confirm ChatPage no longer imports it

Record the finding before proceeding.

- [ ] **Step 2: Delete SourceViewer.jsx (always safe — we replaced its usage)**

```bash
rm frontend/src/components/SourceViewer.jsx
```

- [ ] **Step 3: Delete SourceItem.jsx if unused**

ONLY if the grep in Step 1 showed no other importers:
```bash
rm frontend/src/components/SourceItem.jsx
```

Otherwise skip — it's fine to leave unused source files.

- [ ] **Step 4: Add i18n keys**

Open `E:\MEINRAG\frontend\src\i18n\locales\en.json`. Find the existing `chat` section. Add:

```json
    "emptyMain": "Your source documents will appear here when you ask a question.",
```

Find or create a top-level `textDocViewer` section:

```json
  "textDocViewer": {
    "empty": "This document has no chunks.",
    "error": "Failed to load document"
  },
```

Ensure valid JSON (commas correct, no trailing commas). Validate:
```bash
uv run python -c "import json; json.load(open('frontend/src/i18n/locales/en.json', encoding='utf-8'))"
```

Open `E:\MEINRAG\frontend\src\i18n\locales\zh.json`. Add the same keys in Chinese:

In the `chat` section:
```json
    "emptyMain": "提问后,相关的文档会出现在这里。",
```

Top-level `textDocViewer`:
```json
  "textDocViewer": {
    "empty": "该文档暂无片段。",
    "error": "文档加载失败"
  },
```

Validate:
```bash
uv run python -c "import json; json.load(open('frontend/src/i18n/locales/zh.json', encoding='utf-8'))"
```

- [ ] **Step 5: Remove dead state from `ChatPage.jsx`**

Open `E:\MEINRAG\frontend\src\pages\ChatPage.jsx`. Remove these if still present (leftover from the old layout):

```javascript
const [showSources, setShowSources] = useState(false) // LEGACY — remove
```

Any code inside `startNewChat`, `loadSession`, or `sendMessage` that sets `setShowSources(...)` — delete those lines.

Any keyboard handler inside the `useEffect` that was for ArrowUp/Down sourcing navigation (looking for `selectedSource != null` + `displaySources.findIndex` pattern around line 517-528) — the logic may still be useful (up/down to navigate sources with keyboard), KEEP it if `selectedSource` is still used (it is, to drive PDF highlight). Do NOT delete if it compiles.

If removing any code breaks the build, revert just that change and leave it alone. The goal here is to stop at build-green.

- [ ] **Step 6: Final build verification**

Run:
```bash
cd frontend && npm run build 2>&1 | tail -8
```
Expected: build succeeds. No orphan imports.

Also check for stray references to the deleted components:
```bash
grep -rn "SourceViewer\|SourceItem" frontend/src/ 2>&1 | head -10
```

If any SourceViewer references remain → they must be imports to delete.
If SourceItem references remain (and the file still exists because we decided to keep it in Step 3): fine.

- [ ] **Step 7: Run focused backend tests to confirm no regressions**

Run:
```bash
uv run pytest tests/test_mindmap.py tests/test_router.py tests/test_retrieval.py tests/test_config_router.py -v 2>&1 | tail -6
```
Expected: all pre-existing tests pass (~100+ tests).

- [ ] **Step 8: Commit + push**

```bash
git add frontend/src/components/SourceViewer.jsx frontend/src/components/SourceItem.jsx frontend/src/i18n/locales/en.json frontend/src/i18n/locales/zh.json frontend/src/pages/ChatPage.jsx
git commit -m "$(cat <<'EOF'
chore(chat): remove deprecated SourceViewer + dead state; i18n keys

SourceViewer replaced by PdfViewer/TextDocViewer in main area.
SourceItem replaced by SourceCard in sidebar (or kept if other
components still use it — check grep). Dead showSources state
removed. New i18n keys: chat.emptyMain, textDocViewer.{empty,error}.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"

git push origin main 2>&1 | tail -3
```

---

## Self-Review

**Spec coverage:**
- Flip layout to PDF-main + chat-sidebar: Task 5 ✓
- Tabs with overflow: Task 3 ✓
- TextDocViewer for non-PDF: Task 2 ✓
- PdfViewer reuse for PDF: Task 5 ✓
- Compact SourceCard in sidebar: Task 4 ✓
- Citation click → open tab → activate → jump to location: Task 5 Steps 4-5 ✓
- Tabs persist across turns, auto-reopen on new citation: Task 1 + Task 5 ✓
- Ask AI / Web search stay in chat messages (no tabs): inherited — no citation → no tab created
- Unified HIGHLIGHT_COLORS: Tasks 2 + 4 both import from TextDocViewer
- Session history panel unchanged: Task 5 Step 7 preserves it
- Bbox highlight doesn't disappear on scroll: inherited from PdfViewer behavior
- No streaming auto-jump: deliberately not wired — citations appear but don't auto-trigger
- Session restore opens first source's tab: Task 5 Step 5 (`openTabsForSources` + `activateTab` on `!activeDocId`)

**Placeholder scan:**
- Task 5 Step 7 has `/* KEEP the existing InputBar ... Paste the same input block */` — this is a deliberate instruction to the operator because the exact input block JSX isn't shown in the plan. They must read the old file and copy it verbatim. Not a placeholder — it's a targeted instruction.
- Task 6 Step 5: "Any keyboard handler ... KEEP it if selectedSource is still used" — also deliberate, guiding operator through a judgment call.
- No "TBD" / "implement later" patterns.
- No test-without-code patterns.

**Type / name consistency:**
- `useDocTabs` returns `{tabs, activeDocId, activeTab, openTab, closeTab, activateTab, resetTabs, openTabsForSources}` — Task 5 uses all of these consistently.
- Tab shape: `{doc_id, filename, file_type}` — consistent Task 1 → Task 3 → Task 5.
- `HIGHLIGHT_COLORS` exported from `TextDocViewer.jsx`, imported by `SourceCard.jsx` — Tasks 2 + 4 match.
- `source.originalIndex` — used in Task 5 Step 4; matches existing `displaySources` shape in the unchanged part of ChatPage (it's added when `sources` is mapped + sorted).
- `sources[selectedSource]?.chunk_index` + `.doc_id` + `.page` + `.bbox` — these are existing fields on source objects from the backend.

**Known risks:**
- Task 5 Step 7 requires the operator to copy the input block from the OLD layout. If they skip this, the user has no way to send messages. Flag clearly during execution.
- `PdfViewer` prop `highlights` — I assumed `[{bbox, isActive, colorIndex}]` format based on Task 2's HIGHLIGHT_COLORS and PdfViewer's `highlights[0].bbox` / `.isActive` / `.colorIndex` access pattern seen at `app/frontend/src/components/PdfViewer.jsx:111-117`. Verify this matches actual usage before shipping.
- `fetchDocumentChunks(docId, null, userId)` — plan assumes null returns all chunks. Verified via `app/routers/documents.py:522-558` where `page is None` bypasses the filter.
- The `showHistory` state — I assume it's still declared in the component. If it was removed in a prior refactor, the plan's Step 7 render block references `showHistory` unconditionally; operator must verify.
- Mobile: not handled. Width < 768px will be cramped. Deliberate v1 scope.

**What this plan does NOT do (intentional scope boundaries):**
- No backend changes — zero risk to backend tests
- No new dependencies — react-d3-tree still uninstalled
- No mobile-specific layout — fix later
- No test additions — frontend UX-heavy changes are manually verified
- No handling for standalone image file uploads (rare case)
- No tab-persistence across browser refresh (in-memory state only)
