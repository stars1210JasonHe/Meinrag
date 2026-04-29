# Domain Taxonomy Restructure — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Split the conflated "Domains" concept on the dashboard into three clean layers — **Primary Category** (固定 ~10, 来自 `taxonomy.json`), **Sub-tags**（细粒度，per-doc 元数据）, **Collections**（用户手动建的文件夹）—— so the sidebar stays bounded as the corpus grows and the user's mental model matches the data.

**Diagnosis (root cause):**
- Today the dashboard sidebar shows `existing_collections` (per-doc free-form strings the AI classifier writes) but labels them "Domains".
- The classifier writes *sub-domain*–level strings (`regulatory-guidance`, `patent`, `court-decision`, ...) — fine-grained tags being treated as primary navigation.
- 50-doc corpus → 100+ "domains". Symptom: domains 比 docs 多。
- A clean primary-category taxonomy already exists in `data/taxonomy.json` (10 categories like `legal-compliance`, `finance-accounting`, …) but is not used as navigation.

**Architecture (three layers, separated):**

| Layer | Source | Cardinality | UI role |
|---|---|---|---|
| **Primary Category** | `taxonomy.json` (fixed ~10) | Single per doc | Sidebar primary navigation |
| **Sub-tags** | AI classifier (free, drawn from taxonomy domains/sub-domains) | Multiple per doc | Chips on the doc card; searchable; not in sidebar |
| **Collections** | User-named (optional) | 0..N per doc | Sidebar second section; long-term may be empty |

**Data model:**
- New column `documents.primary_category` (nullable string; validated at write time against `PRIMARY_CATEGORIES`).
- New column `documents.subtags` (JSON array of strings; nullable / default `[]`).
- Existing `document_collections` junction stays — but only stores **user-curated** collections going forward (no AI writes here anymore).

**Tech stack:** SQLAlchemy 2 / Alembic / FastAPI / Pydantic v2 / React 19 / TanStack Query.

---

## File Structure

**Modified — backend:**
- `app/db/models.py` — add `primary_category`, `subtags` columns to `DocumentModel`; update `to_dict()`
- `app/models/schemas.py` — split `CollectionsResponse`; add `primary_category` + `subtags` to `Document` schema
- `app/services/collection_suggester.py` — output `{primary_category, subtags, collection_suggestions[]}` instead of one collection string
- `app/routers/documents.py` — `/documents`, `/documents/upload`, `/documents/{id}`, `/documents/{id}/reclassify` propagate the new fields
- `app/db/repositories.py` — `DocumentRepository` create/update accept new fields

**Modified — frontend:**
- `frontend/src/pages/DashboardPage.jsx` — split sidebar into "Categories" (固定) + "Collections"（用户）; doc cards show sub-tag chips
- `frontend/src/lib/api.js` — typed shape for `Document` updated
- `frontend/src/i18n/en.json` / `zh.json` — labels: `categories`, `subtags`, `collections`

**Created:**
- `alembic/versions/XXXX_add_primary_category_and_subtags.py` — migration
- `scripts/backfill_primary_category.py` — one-shot backfill for existing docs

**Not touched:** classifier prompt template (the *taxonomy* itself doesn't change; only how the classifier output is *structured*).

---

## Task 1: Schema migration — add `primary_category` + `subtags`

**Files:**
- Modify: `app/db/models.py`
- Create: `alembic/versions/XXXX_add_primary_category_and_subtags.py`

- [ ] **Step 1: Add columns to `DocumentModel`**

```python
# in app/db/models.py, DocumentModel

primary_category: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
subtags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
```

Add `JSON` to the imports at the top.

- [ ] **Step 2: Update `to_dict()`**

```python
result = {
    ...
    "primary_category": self.primary_category,
    "subtags": self.subtags or [],
    "collections": [dc.collection for dc in self.collections],  # user-curated only
    ...
}
```

- [ ] **Step 3: Generate the migration**

```bash
uv run alembic revision --autogenerate -m "add primary_category and subtags to documents"
```

Inspect the generated file. It should add the column + JSON column. Hand-edit if autogenerate produces noise. Make sure the JSON column has `server_default='[]'` for Postgres so existing rows are non-null.

- [ ] **Step 4: Apply locally**

```bash
uv run alembic upgrade head
```

**Verification:**
- Migration applies without error on the dev Postgres.
- `\d documents` in psql shows the two new columns.
- Existing rows have `primary_category = NULL` and `subtags = []`.
- Migration reverses cleanly: `alembic downgrade -1` then `alembic upgrade head` again.

---

## Task 2: Update Pydantic schemas + API responses

**Files:**
- Modify: `app/models/schemas.py`

- [ ] **Step 1: Split `CollectionsResponse`** (currently returns `taxonomy_categories` + `existing_collections`)

```python
class TaxonomyResponse(BaseModel):
    primary_categories: list[str]      # from PRIMARY_CATEGORIES (fixed)
    domain_options: dict[str, list[str]]  # primary -> domains (for AI suggestion UI)
    user_collections: list[str]        # from document_collections junction (user-curated only)
```

Keep the old `CollectionsResponse` as a deprecated alias for one release if other code references it; otherwise delete.

- [ ] **Step 2: Add fields to `Document` schema**

```python
class Document(BaseModel):
    doc_id: str
    filename: str
    ...
    primary_category: str | None = None
    subtags: list[str] = Field(default_factory=list)
    collections: list[str] = Field(default_factory=list)  # user-curated
```

**Verification:**
- `uv run pytest tests/ --ignore=tests/test_frontend_e2e.py --ignore=tests/test_api_workflow.py -v` passes.
- A quick `curl http://localhost:8000/documents` shows the new fields populated as `null` / `[]` for existing rows.

---

## Task 3: Refactor classifier output

**Files:**
- Modify: `app/services/collection_suggester.py`
- Modify: `app/routers/documents.py` (consumer)

- [ ] **Step 1: Change the LLM prompt to return structured JSON**

Output shape:
```json
{
  "primary_category": "legal-compliance",
  "subtags": ["regulation-policy", "regulatory-guidance"],
  "collection_suggestions": []   // empty unless an existing user collection clearly fits
}
```

- `primary_category` MUST be one of `PRIMARY_CATEGORIES`; if uncertain, emit `"other"` (add `"other"` to PRIMARY_CATEGORIES if not already).
- `subtags` are drawn from the taxonomy's domain + sub-domain levels for the chosen primary.
- `collection_suggestions` are *existing* user collection names that fit; never invent new ones — that's the user's job.

- [ ] **Step 2: Validate the LLM output**

After parsing, validate:
- `primary_category in PRIMARY_CATEGORIES` else fall back to `"other"`.
- Each subtag in `ALL_DOMAINS` or `ALL_SUBDOMAINS` (build that list from `TAXONOMY`); else drop silently.
- `collection_suggestions` ∩ existing user collections; drop unknowns.

- [ ] **Step 3: Update upload + reclassify routes**

- `POST /documents/upload` — write `primary_category`, `subtags` from classifier; do **not** auto-write to `document_collections` anymore.
- `POST /documents/{id}/reclassify` — same, plus emit `collection_suggestions` so the frontend can surface them.

**Verification:**
- Upload one of the demo PDFs (`data/demo/germany_residence_act.pdf`); response has `primary_category="legal-compliance"`, `subtags` non-empty, `collections=[]`.
- Re-classify → same result.

---

## Task 4: New `/documents/taxonomy` endpoint (additive)

**Files:**
- Modify: `app/routers/documents.py`

- [ ] **Step 1: Add the new endpoint**

```python
@router.get("/documents/taxonomy", response_model=TaxonomyResponse)
async def get_taxonomy(...):
    return TaxonomyResponse(
        primary_categories=PRIMARY_CATEGORIES,
        domain_options={k: list(v.keys()) for k, v in TAXONOMY.items()},
        user_collections=existing_user_collections_from_db,
    )
```

The old `GET /documents/collections` stays functional during the sprint so the
frontend (T6) and the @online test consumers (5 files) don't break mid-flight.
The locked decision (hard-remove, no alias) is honoured by T8's final cleanup
commit removing it after every consumer is migrated — same outcome, safer
sequencing.

**Verification:**
- `curl http://localhost:8000/documents/taxonomy | jq` shows the three fields populated.
- `curl http://localhost:8000/documents/collections` still returns the legacy shape (will be removed in T8).

---

## Task 5: Backfill existing documents

**Files:**
- Create: `scripts/backfill_primary_category.py`

- [ ] **Step 1: Logic**

For each existing document:
1. Look at its current `collections` (junction rows).
2. If any matches a `PRIMARY_CATEGORY` exactly → set `primary_category` to that, remove from junction.
3. For each remaining string: if it's a domain or sub-domain in `TAXONOMY` → append to `subtags`, remove from junction.
4. Anything left → keep as user-curated collection.
5. If `primary_category` still unset, run the classifier on the doc summary (or first chunk) once.

- [ ] **Step 2: Run it**

```bash
uv run python scripts/backfill_primary_category.py
```

Idempotent — re-running is safe (skips docs that already have `primary_category` set).

**Verification:**
- Before: `SELECT count(*) FROM documents WHERE primary_category IS NULL;` returns the full corpus size.
- After: returns 0.
- Spot-check 5 docs: `primary_category` makes sense, `subtags` non-empty, junction now contains only user-named collections.

---

## Task 6: Frontend — split sidebar into Categories + Collections

**Files:**
- Modify: `frontend/src/pages/DashboardPage.jsx`
- Modify: `frontend/src/lib/api.js` (if API helper exists)
- Modify: `frontend/src/i18n/en.json`, `zh.json`

- [ ] **Step 1: Fetch new shape**

Replace the current `fetchCollections` with `fetchTaxonomy` returning `{ primary_categories, domain_options, user_collections }`.

- [ ] **Step 2: Sidebar layout — two sections**

```
[ All ]                               (count)

Categories                            ← header (固定 10)
  · legal-compliance                 (count)
  · finance-accounting               (count)
  · …

My Collections                        ← header (用户建的, 可空)
  · 上海建设法规                      (count)
  · …                                + Create

[ Chat with this category/collection ]
```

Filter logic: clicking a category filters by `doc.primary_category === cat`; clicking a collection filters by `doc.collections.includes(col)`.

- [ ] **Step 3: Doc card / row — show sub-tags as chips**

Below the filename + collections, render `subtags` as small monochrome chips (~10px font, soft border). Click → adds the tag to the active filter chip set in the main area.

- [ ] **Step 4: Remove the old "Domains" label** from the sidebar header — replace with `t('dashboard.categories')`.

- [ ] **Step 5: i18n**

```json
// en
"dashboard.categories": "Categories",
"dashboard.collections": "My Collections",
"dashboard.subtags": "Tags",
"dashboard.createCollection": "+ New collection",

// zh
"dashboard.categories": "类别",
"dashboard.collections": "我的文件夹",
"dashboard.subtags": "标签",
"dashboard.createCollection": "+ 新建文件夹",
```

**Verification:**
- Local: `npm run dev`. Sidebar shows two sections; clicking a category filters; clicking a collection filters; sub-tag chips render on cards; click chip → adds to filter; "All" resets.
- Empty state for "My Collections" when zero — shows the create CTA, not just blank.
- Theme: dark and light both look intentional.

---

## Task 7: Update the Auto-Categorize modal

**Files:**
- Modify: `frontend/src/components/AutoCategorize*` (find with grep) — present primary category + subtags + collection suggestions separately
- Modify: `frontend/src/pages/DashboardPage.jsx` (the bulk reclassify entry point, if any)

- [ ] **Step 1: New modal layout**

```
Primary category:  [legal-compliance ▼]   ← single-select dropdown of PRIMARY_CATEGORIES
Sub-tags:          [regulation-policy] [regulatory-guidance]  ← chips, removable
Collection (optional): [+ pick existing ▼] [+ create new]      ← multi
```

Confirm button issues the `PATCH /documents/{id}` with all three fields.

**Verification:**
- Re-classify one of the demo PDFs through the UI; modal shows AI suggestions for all three layers; user can override; saves correctly.

---

## Task 8: Verify + cleanup + push

- [ ] **Cleanup commit: remove legacy `/documents/collections` endpoint and `CollectionsResponse` model.** All consumers migrated by now (frontend T6, test files updated). Final hard-remove honours Q3.
- [ ] Backend tests: `uv run pytest tests/ --ignore=tests/test_frontend_e2e.py --ignore=tests/test_api_workflow.py -v`
- [ ] Spin up dev stack, upload all 4 demo PDFs from `data/demo/`, verify:
  - Each gets a sensible `primary_category`
  - `subtags` are populated and on-taxonomy
  - `collections` is empty (user hasn't manually filed yet)
  - Sidebar shows ~3-5 categories with non-zero counts (not 12+ random labels)
- [ ] Manual: create a user collection ("德国法律"), file the Germany PDF into it, verify it appears in the "My Collections" section with count=1
- [ ] `git push origin main`

---

## Locked decisions (2026-04-29)

1. **Uncategorized = NULL** — `primary_category` is nullable. UI surfaces "(uncategorized)" as a virtual sidebar entry, drives the user to act on docs the classifier wasn't sure about. No `"other"` category bucket.

2. **Sub-tags constrained to taxonomy** — drawn from `data/taxonomy.json` (domain + sub-domain levels, ~150 strings). LLM picks from this vocabulary; unknown tags are dropped. User extends the vocabulary by editing `taxonomy.json` and restarting the server.

3. **Hard-remove the legacy `existing_collections` field** — no deprecation alias. Single-user self-hosted; no external consumers.

4. **Test both flows in T8** — backfill (T5) handles existing dev-DB docs; the 4 demo PDFs in `data/demo/` go through the new upload flow as the fresh-flow validator. Both must produce sensible categories for ship-readiness.

---

**Ship-readiness gate:**
- Sidebar 类别数 = `len(PRIMARY_CATEGORIES)`，恒定。
- 文档增加不会让侧栏变长（只有"My Collections"会，由用户控制）。
- Sub-tags 在卡片上展示但不是导航。
- Auto-Categorize 给出三层建议，用户可单独覆盖任何一层。
