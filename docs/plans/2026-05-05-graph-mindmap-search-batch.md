# Graph + Mindmap + Search Polish Batch — 2026-05-05

**Goal:** Four targeted improvements to make the prod UX scale and feel intentional:

1. **G1** — Graph view stops being a hairball (weighted edges + tighter threshold).
2. **G2** — Graph node action ("Open chunk") integrates with chat instead of dumping users in standalone PDF.
3. **G3** — Mind map auto-deepens to 4 layers when content earns it; stays at 3 otherwise.
4. **G4** — Unified doc-search engine: dashboard + graph-page picker both backed by one server-side endpoint that scales to 1000+ docs and handles semantic queries.

**Sequencing:** G1 → G2 → G3 → G4. G1+G2 are same-day shippable. G3 invalidates mindmap caches. G4 is the largest (backend + two frontends).

Each task is a **separate commit**. One push at the end (or after each milestone if validation requires it).

---

## Pre-flight check

- [ ] `git status --short` is clean apart from the expected unrelated noise (untracked screenshots, etc.).
- [ ] Backend running on `:8000`, dev frontend on `:5173`.
- [ ] Latest credibility test passing (we shipped `19a37a5` with the download fix today's predecessor).
- [ ] Current corpus has ≥10 docs with cross-doc edges so the graph view is exercisable.

---

## G1 — Weighted graph edges + tighter default threshold

**Why:** With 16 mostly-related docs and `min_score=0.6` keeping any single chunk-pair above threshold as an edge, every doc connects to every doc. User can't see relationship strength.

**Backend changes:**

- `app/config.py`:
  - Bump `graph_similar_min_score: float = 0.6` → `0.7`.
  - Add `graph_similar_min_pairs: int = 2` (NEW). Document both in the comment block.
- `app/db/repositories.py` `get_cross_doc_edges()`:
  - Currently dedups to one edge per doc-pair. Change to **aggregate**: per pair, collect all chunk-pair scores, return:
    - `supporting_pairs: int` — count of distinct chunk pairs above `min_score`
    - `mean_score: float` — mean of those scores
    - `max_score: float` — max single-pair score (for tooltip)
  - Filter out pairs where `supporting_pairs < settings.graph_similar_min_pairs`.
- `app/models/schemas.py` `GraphEdge`:
  - Add optional fields: `supporting_pairs: int | None`, `mean_score: float | None`. Keep `score` for backward compat (set it to `mean_score`).
- `app/routers/graph.py` `/documents/graph` endpoint:
  - Pass settings to repo so the threshold gates inside the SQL/Python aggregation, not just at the edge-builder level.

**Frontend changes (`frontend/src/pages/GraphPage.jsx`):**

- Locate the edge-rendering pass (force-graph 2D `linkWidth` / `linkOpacity` callbacks).
- `linkWidth`: `1 + Math.min(supporting_pairs, 6) * 0.6` → 1.6px for 1 pair, ~4.6px at 6+ pairs.
- `linkOpacity`: `0.25 + (mean_score - 0.7) * 2.5` clamped to `[0.25, 1.0]` → faint at 0.7, full at 1.0.
- Tooltip on edge hover: `"{n} chunk pairs · mean score {x.xx}"`.

**Verify:**

- Reload graph view on the live corpus. Strong relationships (e.g. shell-model papers among themselves) should be visibly thicker and more opaque than weak cross-domain edges (e.g. attention paper ↔ CRS reports).
- Manually drop `graph_similar_min_score` to 0.5 in `.env` and confirm hairball returns. Restore to 0.7.
- Manually set `graph_similar_min_pairs=4` and confirm edges thin out further.

**Commit:** `feat(graph): weighted cross-doc edges + tighter similarity threshold`

---

## G2 — Collapse "Open in PDF" / "Ask about this" → single "Open chunk" with primed input

**Why:** The two buttons today both open the same screen but with different chat-input states. User confusion is real. Better: one button, with the chat input showing a *suggested* question as ghost-text the user can click-to-fill or type past.

**Frontend changes:**

- `frontend/src/pages/GraphPage.jsx:712-740`:
  - Replace the two-button row with a single button: `<ExternalLink size={12} /> {t('graph.openChunk')}`.
  - On click, navigate to:
    `/chat?doc=${doc_id}&chunk=${chunk_index}&suggest=${encodeURIComponent(suggestion)}`
  - Suggestion is computed as today (figure → "What does X show?" / table → "Explain the data in X" / formula → "Explain X" / default → "Tell me about: {label}").
  - Drop the `MessageSquare` icon import if it becomes unused.
- `frontend/src/pages/ChatPage.jsx`:
  - Read `?chunk=N` query param; pass it to the chat-PDF tab so it scrolls + bbox-highlights to that chunk on mount.
  - Read `?suggest=...` query param; render it as **ghost-text inside the chat input** (placeholder-like, but clickable to fill the input). When the user types anything, the ghost-text disappears.
- `frontend/src/components/InputBar.jsx` (or wherever the chat input lives):
  - Accept new prop `suggestion?: string`.
  - Render `<span class="ghost-suggestion">{suggestion}</span>` overlaid in the empty input field with `opacity: 0.4`. Click → `setInput(suggestion)`.
- `frontend/src/i18n/locales/{en,zh}.json`:
  - Add `graph.openChunk` (EN: `"Open chunk"`, ZH: `"打开片段"`).
  - Drop `graph.askAboutThis` if no other consumers (verify with grep).

**Verify:**

- Open Graph page → click any node (chunk-level view) → confirm one button "Open chunk".
- Click it → lands on Chat page, PDF tab is active and scrolled to the chunk with bbox highlight, chat input shows ghost-text suggestion.
- Type any character → ghost-text vanishes. Click ghost-text → input fills with the suggestion.
- For doc-level nodes (top of graph), button still says "Open chunk" but routes to `/chat?doc=${doc_id}` with no chunk param — chat opens the doc tab with no jump-to.

**Commit:** `feat(graph): single "Open chunk" action with primed chat input`

---

## G3 — Recursive mindmap with conditional 4th layer

**Why:** Current 3-layer ceiling under-decomposes long survey papers. User wants 4 levels where structure earns it, 3 where it doesn't.

**Backend changes:**

- `app/models/schemas.py`:
  - `MindmapLeaf` already has `chunk_indices`. Add optional `children: list["MindmapBranch"] | None = None` to `MindmapBranch` (recursive), and rename the type so a branch's child can itself be either a leaf (with chunk_indices) or a deeper branch.
  - Cleanest approach: collapse `MindmapBranch` and `MindmapLeaf` into one `MindmapNode` type with `name`, `chunk_indices: list[int] | None`, `children: list[MindmapNode] | None`. Update `MindmapTree.branches` accordingly.
- `app/rag/prompts.py` `MINDMAP_TREE_SYSTEM_PROMPT`:
  - Rewrite rule 3: `"3-6 top-level branches. Each branch has 2-5 sub-concept children. A child MAY have its own children (a 4th level) ONLY if there are ≥3 distinct sub-sub-concepts that meaningfully cluster within it; otherwise the child is a leaf with chunk_indices."`
  - Update the JSON schema example to show the recursive `children` (optional).
- `app/services/mindmap.py` `_parse_tree_response()`:
  - Replace the fixed two-level parse loop with a recursive parser. Validate that each leaf has `chunk_indices ⊆ valid_indices` and each non-leaf has `children`.
  - Hard-cap depth at 4 server-side (defense against runaway LLM output).
- `app/services/mindmap.py` `_load_cached_tree` / `_save_cached_tree`:
  - **Cache invalidation:** on first read, if the cached JSON has the old schema (top-level `branches` items lack `children` AND have a flat `leaves` array), discard and regenerate. Or: bump cache filename to `data/mindmaps/v2/{doc_id}.json` so old caches are silently abandoned. Pick the v2 path — simpler.

**Frontend changes:**

- `frontend/src/components/MindmapTree.jsx`:
  - Replace fixed-depth render with a recursive `<MindmapNode>` component that renders `children` if present, else a leaf badge with chunk count.
  - react-d3-tree natively supports arbitrary depth — adjust the data-shape adapter, not the tree component.
  - Test with a deep node (force regenerate one doc's mindmap) to confirm 4-level rendering is readable.

**Verify:**

- Delete `data/mindmaps/{doc_id}.json` for a long survey-style PDF (e.g. `crs_R46795_ai_background.pdf`).
- Reload mindmap → expect 4 layers in some branches (the dense ones), 3 elsewhere.
- Delete cache for a short focused paper (e.g. `stroberg_importance_truncated_2015.pdf`) → expect 3 layers throughout (LLM should not over-decompose).
- Confirm old caches still work (auto-regenerate via v2 path or schema-version check).

**Commit:** `feat(mindmap): recursive structure with conditional 4th layer`

---

## G4 — Unified server-side doc search

**Why:** Current dashboard search is client-side substring on `filename+collections+subtags`. Doesn't scale past ~500 docs (full /documents payload), and can't find docs by **what they're about** — only what they're called. Graph-page dropdown is a vanilla `<select>`, breaks visually at ~100+ docs.

**Backend changes:**

- `app/routers/documents.py` `GET /documents`:
  - Add query params: `search: str | None = None`, `limit: int = Query(default=50, le=200)`, `offset: int = 0`.
  - Inside the handler:
    - **Short query** (≤3 words OR ≤20 chars): SQL ILIKE across `filename`, `primary_category`, `subtags::text`, `summary`. Order by `uploaded_at DESC`.
    - **Long query** (4+ words OR 21+ chars): semantic search — embed the query, FAISS search over the **doc-summary** index (`summary_store`), pull doc_ids, fetch metadata, return ranked.
    - **Empty query**: existing behavior (paginated full list).
  - Always respect existing user-isolation filters.
- `app/models/schemas.py` `DocumentListResponse`:
  - Already has `total: int`. Add `has_more: bool` (computed: `offset + len(documents) < total`). Frontend uses it for pagination.
- `app/services/summary_store.py` (or wherever doc-summary embeddings live):
  - Confirm there's a doc-level summary index (vs the chunk-summary index). If not, add one — embed `summary || filename` per doc on upload, store in a separate FAISS namespace. Required for the long-query semantic path.
  - **If this gets non-trivial, descope semantic search to a follow-up commit and ship the ILIKE part of G4 first.**

**Frontend changes:**

- `frontend/src/lib/api.js`:
  - `fetchDocuments({ search, limit, offset })` — add params, return `{ documents, total, has_more }`.
- `frontend/src/pages/DashboardPage.jsx`:
  - Replace client-side `useMemo` filter with a debounced fetch. On `debouncedSearch` change, refetch `/documents?search=...&limit=50`.
  - When `search === ""`, use the existing paginated flow (no regression).
- `frontend/src/pages/GraphPage.jsx` doc picker:
  - Replace the `<select>` with a combobox (use `cmdk` or extend an existing shadcn/ui pattern).
  - Calls the same `/documents?search=...&limit=20` endpoint, debounced.
  - Recent-5 docs section at top (cached client-side from last viewed).

**Verify:**

- Dashboard: type a few characters → debounced fetch fires → results update. Filename matches surface immediately.
- Dashboard: type a content-y phrase ("magic numbers near oxygen") → semantic search returns the right shell-model paper even if "magic" isn't in the filename.
- Graph page: open doc picker → can scroll smoothly through 1000 mock docs (use a script to seed if needed). Type-to-search filters server-side.
- Backend timing: semantic-path queries return in <500ms on 1000-doc corpus.

**Commit:**
- If semantic search ships in this batch: `feat(search): unified server-side doc search (filename + semantic)`.
- If only ILIKE ships: `feat(search): server-side doc search with debounced filter` and follow-up `feat(search): semantic doc search via summary embeddings`.

---

## File Structure (summary)

**Modified:**
- `app/config.py` — G1 settings
- `app/db/repositories.py` — G1 aggregation, G4 search query
- `app/models/schemas.py` — G1 edge fields, G3 recursive node, G4 has_more
- `app/routers/documents.py` — G4 search params + handler logic
- `app/routers/graph.py` — G1 wire settings
- `app/services/mindmap.py` — G3 recursive parser + cache invalidation
- `app/services/summary_store.py` (or new) — G4 doc-summary index
- `app/rag/prompts.py` — G3 prompt rewrite
- `frontend/src/lib/api.js` — G4 API helper
- `frontend/src/pages/GraphPage.jsx` — G1 edge rendering, G2 button collapse, G4 combobox
- `frontend/src/pages/ChatPage.jsx` — G2 chunk param + suggest param
- `frontend/src/pages/DashboardPage.jsx` — G4 server-side search
- `frontend/src/components/InputBar.jsx` — G2 ghost-text suggestion
- `frontend/src/components/MindmapTree.jsx` — G3 recursive renderer
- `frontend/src/i18n/locales/{en,zh}.json` — G2 strings

**Created:**
- (none expected unless G4 needs a new combobox component file)

**Cache changes:**
- `data/mindmaps/v2/` — new path so old G3 caches are abandoned silently (~$0.001/doc to regenerate, ignorable).

---

## Risk + Rollback

- **G1**: low risk. If users complain edges are too sparse, drop `graph_similar_min_score` back to 0.65 via `.env`. No code rollback needed.
- **G2**: low risk. UI-only. Revert one commit if it breaks.
- **G3**: medium risk — schema change. The v2 cache path means old caches stay valid for older schema readers (we never read them again). If recursive parser misbehaves, the empty-tree fail-safe in `build_mindmap_tree` already covers it.
- **G4**: medium risk — requires summary-store work. If semantic search isn't ready, ship ILIKE-only first; semantic is a clean follow-up.

---

## Out of scope (deferred)

- Adding semantic-edge types (cites/extends/contrasts) between docs. Needs LLM-derived relations, separate batch.
- Mindmap depth as a user-configurable knob (current plan keeps it implicit; LLM decides).
- Multi-language search (combobox is filename-string-based; semantic path uses embeddings, which are already multilingual). Should "just work" but not explicitly tested.
- Production-readiness items (auth, rate limiting, load test) — separate plan.
