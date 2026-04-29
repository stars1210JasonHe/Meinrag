# Dashboard Redesign — Distinct Identity from Graph

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Make Dashboard visually + functionally distinct from Graph. Today both
pages lead with a force graph — same "wow", duplicate purpose. After this sprint:

| Page | Identity | Hero element |
|---|---|---|
| **Dashboard** | "我的文档库管理" — find docs, see corpus shape | **Taxonomy Sunburst** + stats + recent uploads |
| **Graph** | "文档之间的关系" — relationships, exploration | Force graph + mindmap toggle |

**Pause:** Domain T7 + T8 are paused until this sprint completes; they pick up
afterwards as part of the same uncommitted change.

**Sprint context:** Builds directly on Domain T1–T6. The 3-layer taxonomy (`primary_category` → domain → sub-tag) is exactly the data the sunburst visualizes — this is the visible payoff of that restructure.

**Bundle budget:** d3-hierarchy / d3-shape / d3-scale / d3-scale-chromatic are
**already** present in `node_modules` (transitive dep of react-force-graph + react-d3-tree). Declaring them as direct deps in `package.json` adds **zero** download cost.

---

## File Structure

**Modified:**
- `frontend/src/pages/DashboardPage.jsx` — remove force-graph from main area; add hero band + category-grouped doc list
- `frontend/package.json` — declare d3-hierarchy, d3-shape, d3-scale, d3-scale-chromatic as direct deps
- `frontend/src/i18n/locales/en.json`, `zh.json` — labels for hero / sunburst / category section

**Created:**
- `frontend/src/components/Sunburst.jsx` — pure SVG hierarchical sunburst, theme-aware, hover + click events
- `frontend/src/components/RecentStrip.jsx` — top N recently uploaded docs as cards
- `frontend/src/components/CategorySection.jsx` — collapsible doc list under a category header
- `frontend/src/hooks/useTaxonomyHierarchy.js` — turn `documents[]` + `taxonomyData.domain_options` into the d3-hierarchy data structure

**Removed (from Dashboard only — still used elsewhere):**
- The `<ForceGraph2D>` instance + its hover/highlight state in `DashboardPage.jsx`. The component itself stays imported on Graph page.

---

## Layout (new Dashboard main area)

```
┌────────────────────────────────────────────────────────────┐
│ Header: search + filter chips + upload                     │
├──────────┬─────────────────────────────────────────────────┤
│ Sidebar  │ ┌────────────────┬───────────────────────────┐  │
│  Scope   │ │                │ Stats: 6 docs · 4 cats     │  │
│  ─All    │ │   Sunburst     │        sparkline ↗          │  │
│  Categ.  │ │  (~280×280)    │  Recent: [card][card][card]│  │
│   Legal  │ │   3 rings      │                             │  │
│   Tech   │ │                │                             │  │
│   ...    │ └────────────────┴───────────────────────────┘  │
│  Coll.   │ ─── 文档 grouped by category ──────────────────  │
│   ...    │ ▾ Legal Compliance · 2                           │
│          │   · germany_residence_act.pdf  [chip][chip]      │
│          │   · canada_irpa.pdf           [chip][chip]       │
│          │ ▾ Research Scientific · 1                        │
│          │   · attention_is_all_you_need.pdf                │
│          │ ▸ Education Research · 1 (collapsed)             │
└──────────┴─────────────────────────────────────────────────┘
```

**Heights:** Hero band ~30% of viewport, doc list ~70%. The hero is "ambient"
— delight on arrival, doesn't dominate working time.

---

## Task D1: Declare d3 deps as direct

**Files:**
- Modify: `frontend/package.json`

- [ ] Run from `frontend/`:
```bash
npm install --save d3-hierarchy d3-shape d3-scale d3-scale-chromatic
```

These are already pulled in transitively, so `npm install` resolves to
existing versions, no actual download.

**Verification:**
- `package.json` has the 4 packages under `dependencies`.
- `npm run build` still completes.

---

## Task D2: `Sunburst.jsx` component

**Files:**
- Create: `frontend/src/components/Sunburst.jsx`

- [ ] **Step 1: Component shape**

```jsx
function Sunburst({
  data,                     // { name, children: [...] } — d3 hierarchy input
  size = 280,
  onSegmentClick,           // (segment) => void — segment is { layer, name, count, path[] }
  onSegmentHover,           // (segment | null) => void
  highlightPath,            // string[] — array of names to highlight, [] = none
}) { ... }
```

- [ ] **Step 2: Implementation**
  - Use `d3.partition()` for layout.
  - Use `d3.arc()` for the per-segment SVG path.
  - 3 rings: inner = primary_category, middle = domain, outer = sub-domain.
  - Color: stable per-primary using `d3.scaleOrdinal(d3.schemeTableau10)`; outer rings inherit + lighten with `d3.color().brighter()`.
  - Hover: full opacity on segment's whole branch (siblings dim to 40%).
  - Click: emit segment + path so parent can wire to `selectedScope`.
  - Empty state: when `data.children.length === 0`, render a soft outline placeholder ring + caption "Upload to populate".

- [ ] **Step 3: Theme awareness**
  - Background, text, separator stroke read from CSS vars (`--bg`, `--fg`, `--border`).
  - Light + dark both must look intentional.

**Verification:**
- Sunburst renders with the 6 dev-DB docs across 4 categories.
- Hovering a slice fades others; tooltip shows name + count.
- Clicking a primary slice triggers `onSegmentClick({layer:'category', name:'legal-compliance', count: 2, path: ['legal-compliance']})`.

---

## Task D3: `useTaxonomyHierarchy` hook

**Files:**
- Create: `frontend/src/hooks/useTaxonomyHierarchy.js`

- [ ] **Step 1: Logic**

```js
// Input: documents[], taxonomyData.domain_options
// Output: { name: 'corpus', children: [
//   { name: 'legal-compliance', count: 2, children: [
//     { name: 'regulation-policy', count: 2, children: [
//       { name: 'regulatory-guidance', count: 2 }
//     ]}
//   ]}
// ]}
```

  - For each doc, walk: `primary_category` → for each `subtag`, find which domain it belongs to via `domain_options`, then nest the sub-tag under the domain.
  - Collapse zero-count branches.
  - Empty / NULL primary_category → skipped (the sidebar's "Uncategorized" entry handles those).

**Verification:**
- Snapshot the hook's output for the 6 dev-DB docs and inspect — confirm the tree shape matches expectation.

---

## Task D4: `RecentStrip.jsx` component

**Files:**
- Create: `frontend/src/components/RecentStrip.jsx`

- [ ] **Step 1: Component**

```jsx
function RecentStrip({ documents, onDocClick, max = 5 }) { ... }
```

  - Sort by `uploaded_at` desc, take top N.
  - Each card: small file icon + filename (truncate) + relative time + primary_category badge.
  - Compact cards (~120px wide) in a horizontal flex row, no scroll on overflow (just truncate).
  - Click → `onDocClick(doc)` (parent typically opens chat scoped to doc).

**Verification:**
- Renders 5 most recent docs from the corpus, click jumps to chat.

---

## Task D5: `CategorySection.jsx` component

**Files:**
- Create: `frontend/src/components/CategorySection.jsx`

- [ ] **Step 1: Component**

```jsx
function CategorySection({
  primaryCategory,          // string — null means "Uncategorized"
  docs,                     // documents in this category
  collapsed,                // boolean — controlled by parent
  onToggle,                 // (newCollapsed: boolean) => void
  onDocClick,
  onDocViewPdf,
  onDocDownload,
  onDocDelete,
}) { ... }
```

  - Header row: `▾`/`▸` + category name + count badge + clickable to toggle.
  - Children: existing `DocRow` reused (already shows subtags as chips after T6).
  - Default: top 3 categories expanded, rest collapsed. State persisted in localStorage by category name.

**Verification:**
- Sections render, expand/collapse works, doc rows look identical to current.

---

## Task D6: Rewrite `DashboardPage.jsx` main area

**Files:**
- Modify: `frontend/src/pages/DashboardPage.jsx`

- [ ] **Step 1: Remove force-graph machinery**
  - Delete: `<ForceGraph2D>` element, `graphRef`, `containerRef`, `dimensions`, `hoverNode`, `highlightNodes`, `highlightLinks`, `handleNodeClick` for force-graph nodes, `handleNodeHover`, `graphData` memo. Keep node-click logic that still applies (e.g., open chat from a doc — but that lives elsewhere now).
  - Drop the `import ForceGraph2D from 'react-force-graph-2d'` line.
  - The unused state setters and the resize observer go too.

- [ ] **Step 2: New main layout**
  - Top hero band (`min-height: 280px`, flex-row):
    - Left: `<Sunburst>` (~35% width, square)
    - Right: stats strip (`Stat` cards) on top, `<RecentStrip>` below
  - Below hero: scrollable list of `<CategorySection>` for each `primary_category` present in the corpus.
  - "Uncategorized" section appears at the bottom if any docs have NULL primary.

- [ ] **Step 3: Wire interactions**
  - Sunburst `onSegmentClick({layer, name})` → `setSelectedScope({type: layer === 'category' ? 'category' : ..., value: name})`. Inner ring is category-level; middle/outer ring (subtag) → activate as a tag chip filter, not a scope change.
  - When `selectedScope` is set, the doc list filters to the matching docs (existing logic preserved).
  - The chip-filter row stays — moves to right above the doc-list, below the hero.

**Verification:**
- Dashboard loads, no force graph visible, sunburst rendered.
- Sidebar nav still works.
- Click a sunburst slice → docs below filter accordingly.
- Click "All" sidebar → reset.
- Theme toggle (dark/light) — sunburst recolours, both look intentional.
- Search bar in header still works.
- Upload still works.
- Multi-select still works.

---

## Task D7: i18n strings

**Files:**
- Modify: `frontend/src/i18n/locales/en.json`, `zh.json`

- [ ] Keys to add:

```json
// en
"dashboard.heroTitle": "Your knowledge",
"dashboard.recentLabel": "Recent uploads",
"dashboard.sunburstEmpty": "Upload a document to see your taxonomy",
"dashboard.expandAll": "Expand all",
"dashboard.collapseAll": "Collapse all",

// zh
"dashboard.heroTitle": "你的知识库",
"dashboard.recentLabel": "最近上传",
"dashboard.sunburstEmpty": "上传文档后将显示分类结构",
"dashboard.expandAll": "全部展开",
"dashboard.collapseAll": "全部折叠",
```

---

## Task D8: Verify + screenshot

- [ ] `npm run build` passes (no new bundle warnings beyond existing 988 KB)
- [ ] Playwright check: visit `/`, screenshot, confirm sunburst renders + categories listed below
- [ ] Manual: hover sunburst → tooltip; click sunburst arc → docs filter; sidebar click → docs filter; click "All" → resets; switch theme → looks good in both
- [ ] Screenshot saved to `/tmp/d8_dashboard.png` for review
- [ ] After approval — resume Domain T7 + T8

---

## Open questions (none — proceed)

All four locked decisions from Domain T1 sprint still apply (NULL = uncategorized; sub-tags taxonomy-bounded; hard-remove old endpoint in T8; verify via demo PDFs in T8). No new decisions needed; this sprint reuses the same data shape.

---

## Ship-readiness gate

- Dashboard's hero IS NOT a force graph (the visual differentiator from Graph).
- Sunburst tells the corpus story at a glance: structure depth + balance.
- All current dashboard features still work (search, multi-select, upload, delete, chat scope).
- Light + dark theme both intentional.
- No bundle-size regression beyond existing baseline.
