# Multi-select Restore + T8 Final Cleanup — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Close two open threads from the 2026-04-29 sprint:
1. The Dashboard force-graph removal orphaned the multi-select → save-as-collection flow. Restore it via per-row checkboxes (already implemented in working tree, needs committing) plus a "peek selection" popover so users can review/remove selections that aren't on screen.
2. Hard-remove the legacy `GET /documents/collections` endpoint per the locked Domain Q3 decision, migrate the 4 remaining consumers (1 frontend page + 3 test files), fix the one misclassified demo doc, close the Domain T8 task.

**Three commits, one push at the end.**

---

## Pre-flight check (before starting)

- [ ] **Confirm git working-tree state** matches the plan's assumptions:
  - `app/routers/documents.py` MAY have an uncommitted PATCH-handler fix (T7 work, but commit was already made — should be clean)
  - `frontend/src/pages/DashboardPage.jsx` HAS the multi-select checkbox + state-prop wiring (uncommitted)
  - `scripts/test_multiselect_dashboard.py`, `scripts/test_search_then_select.py` are new files
- [ ] `git status --short` and verify expected uncommitted set

---

## File Structure

**Modified:**
- `frontend/src/pages/DashboardPage.jsx` — already done in M1 (DocRow gets `selected` + `onSelectToggle` props + checkbox button)
- `frontend/src/components/SelectionActionBar.jsx` — add clickable count, peek state, popover host (M2)
- `frontend/src/pages/GraphPage.jsx` — `fetchCollections` → `fetchTaxonomy` migration (M4)
- `frontend/src/lib/api.js` — drop `fetchCollections` helper (M4); KEEP `saveCollection` (different endpoint, still used)
- `frontend/src/i18n/locales/{en,zh}.json` — peek-selection strings (M2)
- `app/routers/documents.py` — drop `list_collections` handler + `CollectionsResponse` import (M5)
- `app/models/schemas.py` — drop `CollectionsResponse` class (M5)
- `tests/test_api_workflow.py` — `GET /collections` → `GET /taxonomy` (M5)
- `tests/test_collection_integration.py` — finish migration begun in 2026-04-29 (M5)
- `tests/test_multi_select_backend.py` — `GET /collections` → `GET /taxonomy` (M5)
- `tests/test_frontend_multi_select_e2e.py` — `GET /collections` → `GET /taxonomy` (M5)
- `tests/test_schemas.py` — delete `TestCollectionsResponse` test class (M5)

**Created:**
- `frontend/src/components/SelectedDocsPopover.jsx` — peek list with per-row × removal (M2)
- (already exists, will commit) `scripts/test_multiselect_dashboard.py`, `scripts/test_search_then_select.py` — diagnostic / regression scripts (M1)

**Not touched:**
- `POST /documents/collections/save` — different endpoint, still in use, do not remove
- `frontend/src/components/SaveCollectionDialog.jsx` — works as-is

---

## Task M1: Commit Path B (multi-select checkboxes)

Already implemented + validated by Playwright (3-doc selection across 3 different searches). Just commit.

**Files (verify staged):**
- `frontend/src/pages/DashboardPage.jsx`
- `scripts/test_multiselect_dashboard.py` (new)
- `scripts/test_search_then_select.py` (new)

- [ ] `git add` the files
- [ ] Commit message:
  ```
  feat(dashboard): per-row multi-select checkboxes — restore save-as-collection flow

  The 2026-04-29 force-graph removal orphaned the shift-click multi-select
  entry point. Selection / SelectionActionBar / SaveCollectionDialog all
  remained but had no UI affordance to trigger them.

  DocRow now hosts a hover-reveal checkbox on the left edge that toggles
  selection.toggleDoc(docId). Selection state is global (per useSelection
  hook, persisted in localStorage), so it survives search filtering — the
  shopping-cart pattern from the original force-graph flow is preserved:

    search "germany" → ✓ → search "section230" → ✓ → 2 selected → Save

  Verified via scripts/test_search_then_select.py: select doc A under one
  search, search away (A no longer visible), select doc B, both remain in
  selection.docs.
  ```
- [ ] `git push origin main`

**Verification:** smoke check via Playwright already done. Build already passed.

---

## Task M2: Peek-selection popover (REPLACES existing hover tooltip)

**Review-3 finding:** SelectionActionBar already has a hover-only tooltip (`hoverItems` state + `previewItems` array) showing the first 5 selected items as truncated `doc_id_prefix…`. **It's nearly useless** — doc IDs aren't human-readable and it's not interactive. Plan: **replace** the hover tooltip with a click-toggle popover that lists filenames with × per row.

When 2+ docs are selected and not all visible (typical after multi-search), users currently can see the count but can't see WHICH docs. The popover solves that and replaces dead UX.

**Files:**
- Create: `frontend/src/components/SelectedDocsPopover.jsx`
- Modify: `frontend/src/components/SelectionActionBar.jsx` — drop `hoverItems` state + `previewItems` + the hover tooltip; add `peekOpen` state; make count text a `<button>`
- Modify: `frontend/src/pages/DashboardPage.jsx` — pass `documents` array down to action bar
- Modify: `frontend/src/i18n/locales/en.json`, `zh.json`

- [ ] **Step 1: SelectedDocsPopover component**

```jsx
function SelectedDocsPopover({ selectedDocs, onRemove, onClose }) {
  // outside-click + ESC handlers; max-h-60 scroll; per-row × button
}
```

  - Receives `selectedDocs: [{doc_id, filename}]`, `onRemove(doc_id)`, `onClose`
  - Positioned `fixed bottom-24 left-1/2 -translate-x-1/2 z-50` (action bar is at `bottom-6`, so 96px clears it cleanly)
  - Up to ~36px per row × cap at 6 visible → `max-h-60 overflow-y-auto`
  - Click outside (mousedown listener on document, ignore if click is inside popover or inside action bar count button) → `onClose()`
  - ESC → `onClose()`
  - Theme-aware: `bg-[color:var(--bg-2)]/95`, `border var(--border)`, etc. — match existing dialog primitives

- [ ] **Step 2: Refactor SelectionActionBar**
  - **Remove**: `hoverItems` useState, `setHoverItems`, `previewItems` array (lines 21-22, 64-69, 123-148 region)
  - **Remove**: the hover-tooltip span block at lines 129-148
  - **Add**: `peekOpen` useState (default false)
  - **Receives new prop**: `documents` (full list — required so popover can look up filenames for selected doc_ids that aren't currently visible)
  - The "N selected" text becomes a `<button onClick={() => setPeekOpen(p => !p)}>` (style adjusted: keep flex-row alignment, add cursor-pointer)
  - Compute `selectedDocs = useMemo(() => documents.filter(d => selection.hasDoc(d.doc_id)), [documents, selection.docs])`
  - When `peekOpen && selectedDocs.length > 0`, render `<SelectedDocsPopover>` outside the toolbar (sibling, not child — z-index hierarchy clear)
  - **Edge case (handled by existing logic):** when last item removed, `selection.count === 0` → SelectionActionBar returns null at line 41 → popover unmounts naturally; no explicit cleanup needed

- [ ] **Step 3: DashboardPage prop pass-through**
  - At line ~812: `<SelectionActionBar documents={documents} onAsk=... onVisualize=... onSave=... />`
  - `documents` is the FULL document list, not `filtered`/`displayedDocs` — so popover can name docs that aren't in the current search filter

- [ ] **Step 4: i18n** (verified non-existent — these are net-new keys)
  ```json
  // en
  "selection.peekTitle": "Selected documents",
  "selection.peekRemove": "Remove from selection",

  // zh
  "selection.peekTitle": "已选文档",
  "selection.peekRemove": "从选择中移除"
  ```

**Verification:**
- Click "N selected" → popover opens with all selected filenames (including ones not in current search results)
- Click × on a row → that doc deselected, count decrements, popover row removed
- Click outside / ESC → popover closes; selection state preserved
- Removing last item → action bar + popover both vanish
- Theme dark+light both intentional

**Commit message:**
```
feat(dashboard): peek-selection popover for cross-search multi-select

Click "N selected" in the action bar → expand into a popover listing
selected docs by filename with × per row. Solves the gap that arises
when selected docs aren't all visible at the same time (typical after
multi-search). Popover dismisses on outside-click or ESC; removing the
last item collapses both popover and action bar.
```

---

## Task M3: Fix R46795 misclassification (data-only)

R46795 (`crs_R46795_ai_background.pdf`) was auto-classified as `hr-personal` (subtags: employment, payroll). Should be `legal-compliance` since it's a CRS report on AI policy. The "labor market impact" section confused the embedding classifier.

This is a **runtime data fix**, not a code change. Will be applied via curl during M5's verification step; mentioned in the M5 commit body but produces no file diff.

```bash
DOCID=$(curl -s -H "X-User-Id: admin" http://localhost:8000/documents | \
  python -c "import sys,json; print([d['doc_id'] for d in json.load(sys.stdin)['documents'] if 'R46795' in d['filename']][0])")

curl -X PATCH http://localhost:8000/documents/$DOCID \
  -H "Content-Type: application/json" -H "X-User-Id: admin" \
  -d '{"primary_category": "legal-compliance", "subtags": ["regulation-policy", "regulatory-guidance"]}'
```

**Verification:** Dashboard sidebar `Hr Personal · 1` row disappears; `Legal Compliance · 5` count goes up by 1.

---

## Task M4: Migrate GraphPage to fetchTaxonomy

`frontend/src/pages/GraphPage.jsx` is the last consumer of `fetchCollections`. Once migrated, the helper can be removed from `api.js`.

**Files:**
- Modify: `frontend/src/pages/GraphPage.jsx`
- Modify: `frontend/src/lib/api.js` (drop `fetchCollections`; keep `saveCollection`)

- [ ] **Step 1: GraphPage swaps**
  - Line 7: import `fetchTaxonomy` instead of `fetchCollections`
  - Line 124-126: query key `['collections', USER_ID]` → `['taxonomy', USER_ID]`; query fn `fetchCollections` → `fetchTaxonomy`
  - Line 175: `collectionsData?.existing_collections || []` → `taxonomyData?.user_collections || []`

- [ ] **Step 2: Drop `fetchCollections` from `api.js`**
  - Remove the export at lines 38-39
  - Confirm no callers remain via `grep -r "fetchCollections" frontend/src` — should return zero hits

- [ ] **Step 3: Build sanity**
  - `cd frontend && npm run build` — clean

- [ ] **Step 4: Render sanity** (optional but quick)
  - Playwright: visit `/graph`, confirm page renders without console errors

Goes into the M5 commit (one logical change — frontend cleanup of legacy endpoint consumers).

---

## Task M5: Hard-remove legacy `/documents/collections` endpoint + tests sweep

**Backend:**
- Modify: `app/routers/documents.py` — drop `list_collections()` handler + the `CollectionsResponse` import
- Modify: `app/models/schemas.py` — drop the `CollectionsResponse` class

**Tests (5 files — Review-2 caught a missed line):**
- `tests/test_api_workflow.py` — line 213 region (`@online`, run only with API key)
- `tests/test_collection_integration.py` — lines **329, 406, 507** region (3 occurrences; 507 is the second-user isolation test)
- `tests/test_multi_select_backend.py` — line 126 region (`@online`)
- `tests/test_frontend_multi_select_e2e.py` — lines 101, 301 region (E2E with live backend; line 315 is `POST /collections/save` which STAYS)
- `tests/test_schemas.py` — delete `TestCollectionsResponse` class (line 277 area) AND remove `CollectionsResponse` from the import block at the top of the file

- [ ] **Step 1: Backend deletion**
  - Remove the entire `@router.get("/collections", response_model=CollectionsResponse, deprecated=True)` block in `documents.py`
  - Remove `CollectionsResponse` from the imports
  - In `schemas.py` remove the `class CollectionsResponse(BaseModel):` block
  - Verify import: `uv run python -c "from app.routers.documents import router; from app.models.schemas import TaxonomyResponse; print('ok')"` → ok

- [ ] **Step 2: Test file sweep**
  - In each of the 4 test files, search for `/documents/collections` and `existing_collections` / `taxonomy_categories`
  - Replace URL `/documents/collections` → `/documents/taxonomy`
  - Replace key `taxonomy_categories` → `primary_categories`
  - Replace key `existing_collections` → `user_collections`
  - In `test_schemas.py`, delete the `TestCollectionsResponse` class entirely

- [ ] **Step 3: Curl verification**
  - `curl -s -o /dev/null -w "%{http_code}" -H "X-User-Id: admin" http://localhost:8000/documents/collections` → **404**
  - `curl -s -H "X-User-Id: admin" http://localhost:8000/documents/taxonomy | python -c "import sys,json; d=json.load(sys.stdin); print(sorted(d.keys()))"` → `['domain_options', 'primary_categories', 'user_collections']`

- [ ] **Step 4: Smoke test**
  - `uv run pytest tests/test_collection_smoke.py -q` (~50s) — should pass
  - `uv run pytest tests/test_schemas.py -q` (offline) — should pass after `TestCollectionsResponse` deletion

- [ ] **Step 5: Apply M3 R46795 PATCH** (data fix; described in M3)

- [ ] **Step 6: Commit**
  ```
  chore(api): hard-remove legacy /documents/collections endpoint (T8 cleanup)

  Closes the locked Q3 decision from the 2026-04-29 Domain restructure
  sprint: hard-remove the deprecated GET /documents/collections endpoint
  and the CollectionsResponse schema. The new GET /documents/taxonomy
  (shipped 2026-04-29) is the sole replacement.

  Migrated remaining consumers:
    * frontend/src/pages/GraphPage.jsx — fetchCollections → fetchTaxonomy,
      existing_collections → user_collections
    * frontend/src/lib/api.js — fetchCollections helper removed
      (saveCollection POST helper kept — different endpoint, still in use)
    * tests: api_workflow / collection_integration / multi_select_backend /
      frontend_multi_select_e2e — URL + key swap
    * tests/test_schemas.py — TestCollectionsResponse class removed

  Also fixes one auto-classification miss: R46795 ("AI Background, Issues,
  Policy" CRS report) was assigned hr-personal at upload time because the
  embedding classifier matched the labor-market impact section. Re-classified
  to legal-compliance via PATCH /documents/{id} (runtime data fix; no file
  diff in this commit).

  Closes Domain T8.
  ```
- [ ] `git push origin main`

---

## Verification gate (must all pass before declaring done)

| Check | Expected | How |
|---|---|---|
| Multi-select | hover-reveal checkbox per row; checked state persists across search filters | manual or `scripts/test_search_then_select.py` |
| Action bar | "N selected" appears for ≥1 selected; Save / Ask / Visualize buttons live | screenshot |
| Peek popover | click N selected → popover opens listing all selected filenames; × deselects | manual |
| GraphPage | renders without errors; user collections show under nav rail | open `/graph` |
| Endpoint removal | `GET /documents/collections` → 404 | curl |
| Replacement | `GET /documents/taxonomy` → 200 with 3 keys | curl |
| Backend imports | `app.routers.documents` + `app.models.schemas` import clean | python -c |
| Smoke test | `tests/test_collection_smoke.py` passes | pytest |
| Schema test | `tests/test_schemas.py` passes after `TestCollectionsResponse` removed | pytest |
| Build | `npm run build` clean | npm |
| R46795 | shows under Legal Compliance in dashboard sidebar, not Hr Personal | screenshot |
| All tasks | marked completed in TaskList | TaskUpdate |

---

## Open questions (resolved before starting)

1. **Should peek popover allow Save directly?** No — popover is review/remove only; Save stays in the action bar.
2. **R46795 fix as a separate commit?** No — bundled in M5 commit body. It's a one-shot data fix tied to T8 closure.
3. **Should `fetchCollections` removal preserve a deprecation alias?** No — it's a single-user self-host project, no external consumers. Q3 lock applies.
4. **Should I commit the diagnostic scripts?** Mixed:
   - `scripts/test_multiselect_dashboard.py`, `scripts/test_search_then_select.py` — **yes**, regression-pattern starters that document the verification trail.
   - `scripts/diag_dashboard.py` — **no**, purely one-off diagnostic during the lucide-icon-rename hunt; not worth the long-term carry.
5. **Replace existing hover tooltip vs add popover beside it?** Replace. The hover tooltip shows truncated `doc_id_prefix…` strings — useless for human review. Popover with filenames + × is strictly better.

---

## Risks (acknowledged, accept)

- **HMR cache during dev session:** dev frontend at :5173 auto-reloads; user may see a brief 404 if they hit `/documents/collections` directly mid-deploy. Self-host, no real concern.
- **`@online` tests:** 3 of the 4 test files won't run in offline mode anyway (need API key), so the test sweep is for accuracy when someone DOES run online — not for CI gate.
- **Peek popover positioning:** action bar is `position: fixed; bottom: ~24px`. Popover above with `bottom: 90px` should clear. May need to adjust on small screens; cap with viewport-aware logic only if user reports it.
- **Build size:** peek popover ~3-5 KB net. Within the 700 KB warning threshold? Bundle is already ~1 MB main; adding more doesn't trip a new warning.
