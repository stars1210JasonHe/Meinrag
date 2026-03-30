# MeinRAG Frontend Redesign — Design Spec

**Date:** 2026-03-30
**Status:** Approved
**Principle:** Minimal by default, powerful when needed. Clean surface, depth on demand.

**Reference mockups:** `docs/Frontend/` (dashboard.png, AI Chat.png, Graph View.png, PDF Viewer.png)

---

## Tech Stack

| Layer | Choice |
|-------|--------|
| UI | React 19 + Vite 7 |
| Styling | Tailwind CSS + shadcn/ui |
| API | @tanstack/react-query + fetch |
| Graph | vis-network |
| PDF | react-pdf |
| Markdown | react-markdown |
| Icons | lucide-react |

---

## Navigation

Left sidebar, collapsed by default (icons only), expandable on hover:

```
[≡]  MeinRAG
[📊] Dashboard
[💬] Chat
[🔗] Graph
[📄] PDF Viewer
─────────
[↑]  Upload
[⚙]  Settings
[👤] User
```

---

## Page 1: Dashboard

**Purpose:** Document and domain search/filter hub. Not a stats page — a search portal.

```
┌──────────────────────────────────────────────┐
│  🔍 Search documents, domains, topics...     │
├──────────────────────────────────────────────┤
│  Filters: [Technical] [Research] [Physics] ✕ │
├──────────────────────────────────────────────┤
│  📄 attention_is_all_you_need.pdf            │
│     Deep Learning · Technical · 12 Oct       │
│  📄 data-anonymization-rag.pdf               │
│     Security · Technical · 20 Mar            │
│  📄 spintronic_sources.pdf                   │
│     Physics · Research · 15 Mar              │
│  ...                                         │
│                                              │
│         [ + Upload Document ]                │
└──────────────────────────────────────────────┘
```

**Components:**
- `SearchBar` — full-text search across document names, collections, domains
- `FilterTags` — clickable tag pills for category/domain filtering. Click to add filter, ✕ to remove. Each document only appears once — filters narrow the list, not group it.
- `DocumentList` — flat list of documents. Each row: filename, domain/category tags, date. `...` menu for actions (delete, reclassify, download, edit)
- `UploadButton` — bottom or floating, drag-drop support

**Placeholder for future:** Space for additional info (trending topics, recent activity, etc.) — left empty for now.

---

## Page 2: AI Chat

**Purpose:** Query documents, view answer + sources. PDF preview embedded for continuous experience.

**Default state (no sources yet):**
```
┌─────────────────────────────────────────────┐
│                                             │
│  Welcome to MeinRAG                         │
│  Ask anything about your documents...       │
│                                             │
│ ┌─────────────────────────────────────────┐ │
│ │ Ask anything...              [→]│ │
│ └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

**After query (sources panel slides in):**
```
┌─────────────────────────┬───────────────────┐
│                         │ SOURCES            │
│ User: Explain Shor's   │                    │
│ algorithm         [fact,│ [1] 📄 Quantum... │
│              reference] │     98% · p.112    │
│                         │ [2] 📊 Table 1    │
│ AI: Shor's algorithm    │     Complexity     │
│ is a quantum algorithm  │ [3] 📐 Eq. (3)   │
│ for integer...          │     f(x)=a^x mod N│
│                         │ [4] 🖼️ Figure 2  │
│                         │     Circuit diagram│
│                         │                    │
│                         ├────────────────────┤
│                         │ PDF PREVIEW        │
│                         │ ┌────────────────┐ │
│                         │ │ p.112 [bbox]   │ │
│                         │ │ ████████       │ │
│                         │ └────────────────┘ │
│                         │ [Open full PDF ▸]  │
│ ┌─────────────────────┐│                    │
│ │Ask anything... [→]  ││                    │
│ └─────────────────────┘│                    │
└─────────────────────────┴───────────────────┘
```

**Components:**
- `ChatMessages` — streaming markdown answer. Formulas rendered inline (code block). Images and tables are NOT inline — they are source references only.
- `QueryTypeBadges` — auto-displayed from `_analyze_query` result: `fact` `overview` `reference` `exploratory`. Display only, not selectable.
- `SourcePanel` — right panel, slides in when sources arrive:
  - Each source: type icon + label + score + page
  - 📄 text: excerpt
  - 📊 table: label "Table 1" (not markdown)
  - 🖼️ image: label "Figure 2" + small thumbnail
  - 📐 formula: label "Equation 3" or rendered equation
  - Click source → shows PDF preview below with bbox highlight
- `PdfPreview` — replaces source list when a source is clicked (full panel):
  - "← Back to sources" link at top to return to source list
  - PDF view of the selected source's page with bbox highlight
  - "Open full PDF" button → navigates to PDF Viewer page, preserving state
  - Page navigation within preview (◀ ▶)
- `InputBar` — text input + Analyze button. Web search as small toggle icon.

**Experience continuity:** Chat → click source → PDF preview in panel → click "Open full PDF" → PDF Viewer page opens at same page with same highlight. Back button returns to Chat with sources panel intact.

**Power user:** `1-9` to quick-select source. `Esc` to close source panel. `Enter` to send message.

---

## Page 3: Graph View

**Purpose:** Explore chunk relationships visually. Interactive knowledge graph.

```
┌──────────────────────────────────────────────┐
│ [●Text] [●Table] [●Formula] [●Image]        │
│ [follows] [describes] [references] [similar] │
│ Scope: [All ▼]                  🔍 Search    │
├──────────────────────────────────────────────┤
│                                              │
│         ◉ CH-A182                            │
│        / \                                   │
│       /   \  similar_to                      │
│      ◉     ◉──── TBL-X293                   │
│             |  references                    │
│         ◉ IMG-99                             │
│           describes                          │
│                                              │
│                                              │
└──────────────────────────────────────────────┘
```

**Node clicked → bottom panel slides up:**
```
├──────────────────────────────────────────────┤
│ ☷ TBL-X293 · Table 2                    ✕  │
│ ┌────────────────────────────────────┐      │
│ │ Model      │ BLEU │ Parameters    │      │
│ │ Transformer│ 28.4 │ 65M          │      │
│ └────────────────────────────────────┘      │
│ Source: attention_is_all_you_need.pdf  p.7   │
│ [Ask about this ▸]  [Open in PDF ▸]         │
│                                              │
│ ▸ Ask: [                              ] [→] │
└──────────────────────────────────────────────┘
```

**Components:**
- `GraphToolbar` — compact one-row bar:
  - Node type toggles (colored dots, click to show/hide)
  - Edge type toggles (click to show/hide)
  - Scope dropdown (filter by document)
  - Search input (find node by content)
- `GraphCanvas` — vis-network, dark background, force-directed
  - Nodes: colored by type (text=blue, table=amber, formula=purple, image=green)
  - Edges: labeled on hover only (not always visible — less clutter)
  - Click node → highlight 1-hop neighbors + slide up NodePreview
  - Double-click → expand 2-hop
  - Zoom/pan with mouse
- `NodePreview` — bottom panel (hidden by default, slides up on node click):
  - Content: table as table, image as thumbnail, text as excerpt, formula as equation
  - Source info + "Open in PDF" link
  - "Ask about this" — inline input + answer display, stays in graph page
  - ✕ to close

**Power user:** `F` fit all. `R` reset layout. Scroll zoom. Right-click context menu. `Esc` close preview.

---

## Page 4: PDF Viewer

**Purpose:** Deep reading with extracted content. Reached from Chat ("Open full PDF") or Dashboard (click document).

```
┌──────────────────────────────────────────────┐
│  ◀ ▶  p.12/48   [−][+] 100%  🔍 Find  ⎙ ↓ │
├─────────────────────────────┬────────────────┤
│                             │ PAGE CHUNKS    │
│  Technical Specification:   │                │
│  Neural Architecture        │ 📊 Table 1    │
│                             │ 📐 Eq. (3)    │
│  The proposed architecture  │ 📄 "The       │
│  leverages a multi-head     │   proposed..." │
│  attention mechanism...     │ 🖼️ Figure 1   │
│                             │                │
│  ┌─────────────────────┐   │ Click chunk →  │
│  │  [BBOX HIGHLIGHT]   │   │ highlights on  │
│  │  ████████████████   │   │ PDF page       │
│  └─────────────────────┘   │                │
│                             │                │
└─────────────────────────────┴────────────────┘
```

**Components:**
- `PdfToolbar` — page nav, zoom (actual %), search (Ctrl+F), print, download
- `PdfCanvas` — react-pdf with bbox highlight overlay
- `PageChunksPanel` — right sidebar:
  - Lists all chunks on the current page, grouped by type
  - Each chunk: type icon + label or excerpt
  - Click → highlights bbox on PDF
  - Auto-updates on page change
  - Toggle visible with button (default: visible when navigated from Chat/Graph, hidden when browsing directly)

**State preservation:** When navigated from Chat (via "Open full PDF"), the page, highlight, and active chunk are preserved. Back button returns to Chat.

**Power user:** `←` `→` page nav. `Ctrl+F` search. `Ctrl+G` go to page. `Esc` dismiss highlight.

---

## Cross-Page Interactions

**Chat → Graph:** Source panel has "View in Graph" button → Graph page opens with these source nodes highlighted.

**Chat → PDF:** Click source → PDF preview in panel. "Open full PDF" → PDF Viewer page. State preserved.

**Dashboard → PDF:** Click document → PDF Viewer opens.

**Dashboard → Chat:** PDF Viewer has "Ask about this document" input → opens Chat with document scope pre-set.

**Graph → PDF:** Node preview has "Open in PDF" → PDF Viewer at that page.

**Graph → Chat:** Node preview "Ask about this" → inline answer in graph page (stays in graph).

## Additional Design Details

**Session history (7):** Backend stores source chunks per query in `chat_messages` (new field). Opening a session restores full conversation + sources. Session list accessible from Chat page (collapsible left panel or dropdown).

**Source timing (8):** Sources display as soon as ready. Answer streams in parallel. If LLM is fast, they appear together. If slow, user sees sources first.

**Graph initial state (9):** Default shows document-level nodes (one node per document, connected by cross-doc similar_to edges). Click a document node → expands into its chunks. Scope filters: by category, domain, or specific document. From Chat "View in Graph" → opens already expanded to chunk level.

**PDF Viewer entry (10):** From sidebar → shows last opened document. No document → "Select a document from Dashboard" prompt.

**Scope indicator (17):** Chat input bar shows current scope: "All documents" or "Searching in: filename.pdf [✕]". Scope selector as dropdown next to input.

**Notifications (16):** Toast notifications (top-right, auto-dismiss): upload complete, processing status, errors. No notification center.

**Loading states (15):** Skeleton loaders for document list, source panel. Spinner for graph loading. PDF loading indicator.

**Error handling (14):** Connection banner (existing). Per-component error states with retry button.

**i18n (12):** UI supports English and Chinese. Language toggle in Settings.

**PageChunksPanel filter (5):** Only show visual chunks (table/image/formula) + current active text chunk. Not all text chunks on the page.

---

## New Backend APIs

| Endpoint | Method | Returns |
|----------|--------|---------|
| `/graph/nodes` | GET | Chunk nodes with metadata for vis-network |
| `/graph/edges` | GET | Edges with type filtering |
| `/graph/neighbors` | GET | 1-2 hop subgraph for a node |
| `/graph/documents` | GET | Document-level nodes + cross-doc edges (for initial graph view) |
| `/documents/{id}/chunks` | GET | Chunks by doc, filterable by `?page=N` |

**Modified existing:**
- `/query` response: add `query_types` field from analysis
- `/query/stream`: add `query_analysis` SSE event with types + label
- `chat_messages` table: add `sources_json` column to persist source chunks per message

**Score normalization (1):** All scores normalized to 0-100% before sending to frontend. Composite scores rescaled: `display_score = score / max_score_in_result_set * 100`.

---

## Design Principles

1. **Show less, reveal more** — default view is clean. Details on hover/click/keyboard
2. **No duplicate information** — answer in chat, sources in panel. Not both.
3. **Type-aware sources** — tables as "Table 1", images as thumbnails, formulas as equations. Never raw markdown.
4. **Continuous experience** — Chat PDF preview → Full PDF Viewer. State preserved. Back button works.
5. **Keyboard-first for power users** — `1-9` sources, `F` fit graph, `Ctrl+F` search, `Esc` dismiss
6. **Dark theme only**
7. **Labels everywhere** — "Table 1", "Figure 2" not chunk_index numbers
8. **Documents appear once** — filter by tags, don't duplicate in multiple categories
9. **Scores as percentages** — normalized 0-100%, not raw floats
