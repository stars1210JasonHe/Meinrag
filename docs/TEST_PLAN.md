# MEINRAG Test Plan (v2 — Redesign)

## Overview

This test plan covers all backend API endpoints, core services, and integration flows after the v0.2.0 redesign. It accounts for the **2 existing documents** already in the system and covers the new features: multi-collection documents, user system with isolation, collection editing, AI taxonomy classification, source UX, and file download.

### Existing System State

| doc_id | filename | chunks | collections | user_id |
|--------|----------|--------|-------------|---------|
| `9485fe63ffcb` | 2512.20798v2.pdf | 94 | `["other"]` | admin |
| `f854b4f6ae47` | 80201000.pdf | 316 | `["legal-framework"]` | admin |

- 1 user: `admin`
- `USER_ISOLATION` defaults to `all`
- `DEFAULT_USER` defaults to `admin`

---

## Test Categories

### Category A: No API Key Required (Offline)

Validate schemas, config, registry (multi-collection + user), user registry, and HTTP error handling.

### Category B: API Key Required (Online)

Validate document processing, vector store, RAG chain, AI taxonomy suggestions, and full API workflows including user isolation, collection editing, download, and reclassification.

---

## Category A: Offline Tests

### A1. Configuration

| # | Test | Expected |
|---|------|----------|
| A1.1 | Load settings from `.env` | All fields populated; `default_user="admin"`, `user_isolation="all"` |
| A1.2 | Validate enum values | Only valid `vector_store` and `llm_provider` accepted |
| A1.3 | Validate numeric ranges | Out-of-range rejected |
| A1.4 | `users_file` defaults to `data/users.json` | Path resolves correctly |

### A2. Schema Validation

| # | Test | Expected |
|---|------|----------|
| A2.1 | `QueryRequest` with valid data | Created, `collection` is `str \| None` |
| A2.2 | `QueryRequest` with empty question | Validation error |
| A2.3 | `QueryRequest` with question > 2000 chars | Validation error |
| A2.4 | `QueryRequest` with `top_k=0` or `top_k=21` | Validation error |
| A2.5 | `UploadResponse` with `collections` list | `collections: list[str]`, `suggested_collections: list[str] \| None` |
| A2.6 | `DocumentInfo` with `collections` + `user_id` | Both required fields present |
| A2.7 | `DocumentUpdateRequest` with valid collections | Created with `collections: list[str]` |
| A2.8 | `DocumentUpdateResponse` with all fields | `doc_id`, `collections`, `message` |
| A2.9 | `UserCreateRequest` with `user_id` + `display_name` | Created correctly |
| A2.10 | `UserInfo` with all fields | `user_id`, `display_name`, `created_at` |
| A2.11 | `CollectionsResponse` | `taxonomy_categories: list[str]` (11), `existing_collections: list[str]` |
| A2.12 | `SourceChunk` includes `doc_id` field | `doc_id: str \| None` present |

### A3. Document Registry (Multi-Collection + User)

| # | Test | Expected |
|---|------|----------|
| A3.1 | `add()` with `collections=["legal-compliance", "contracts"]` | Stored with both collections |
| A3.2 | `add()` with no collections | Defaults to `["other"]` |
| A3.3 | `add()` with `user_id="jason"` | Stored with `user_id` field |
| A3.4 | `list_all()` without user filter | Returns all documents |
| A3.5 | `list_all(user_id="admin")` | Returns only admin's documents |
| A3.6 | `list_by_collection("legal-compliance")` | Returns docs containing that collection (membership check) |
| A3.7 | `list_by_collection("legal-compliance", user_id="admin")` | Filtered by both collection AND user |
| A3.8 | `list_by_collection("nonexistent")` | Empty list |
| A3.9 | `update_collections(doc_id, ["new-a", "new-b"])` | Collections replaced, returns updated doc |
| A3.10 | `get_all_collections()` | Returns union of all collection names across all docs |
| A3.11 | `get_all_collections(user_id="admin")` | Returns collections only from admin's docs |
| A3.12 | Migration: old `"collection": "law"` format | Auto-migrates to `"collections": ["law"]`, adds `"user_id": "admin"` |
| A3.13 | Persistence: data survives re-instantiation | JSON file reloaded correctly |
| A3.14 | `get(doc_id)` / `remove(doc_id)` / `count()` | Same behavior as before |

### A4. User Registry

| # | Test | Expected |
|---|------|----------|
| A4.1 | Init creates default user | `admin` user exists after init |
| A4.2 | `add("jason", "Jason")` | User created with timestamp |
| A4.3 | `add("jason", "Dup")` — duplicate | Raises `ValueError` |
| A4.4 | `get("jason")` | Returns user dict |
| A4.5 | `get("nonexistent")` | Returns `None` |
| A4.6 | `exists("jason")` / `exists("nobody")` | `True` / `False` |
| A4.7 | `list_all()` | Returns list of all users |
| A4.8 | Persistence: data survives re-instantiation | JSON file reloaded correctly |

### A5. Chat Memory

| # | Test | Expected |
|---|------|----------|
| A5.1–A5.7 | (Unchanged from v1) | Same behavior |

### A6. HTTP Error Handling

| # | Test | Expected |
|---|------|----------|
| A6.1 | `POST /documents/upload` with `.exe` | 400 |
| A6.2 | `DELETE /documents/nonexistent_id` | 404 |
| A6.3 | `POST /query` with empty body | 422 |
| A6.4 | `GET /health` | 200, status "ok" |
| A6.5 | `PATCH /documents/nonexistent` | 404 |
| A6.6 | `POST /documents/nonexistent/reclassify` | 404 |
| A6.7 | `GET /documents/nonexistent/download` | 404 |
| A6.8 | `POST /users` with duplicate `user_id` | 409 |

---

## Category B: Online Tests (API Key Required)

### B1. Document Processing
(Unchanged from v1)

### B2. Vector Store Operations

| # | Test | Expected |
|---|------|----------|
| B2.1–B2.8 | (Unchanged from v1) | Same behavior |
| B2.9 | `update_document_metadata(doc_id, {"collections_csv": "a\|b"})` | Metadata updated on all chunks for that doc_id |

### B3. RAG Chain
(Unchanged from v1)

### B4. AI Collection Suggestion (Taxonomy-Based)

| # | Test | Expected |
|---|------|----------|
| B4.1 | AI safety paper → suggestions | Returns `list[str]` with >= 1 item from taxonomy |
| B4.2 | Patterns paper → suggestions | Returns `list[str]` with >= 1 item |
| B4.3 | German Basic Law → suggestions | Returns `list[str]` with legal-related tag |
| B4.4 | Suggestion format | All lowercase, no spaces, <= 50 chars each |
| B4.5 | With `existing_collections` param | Suggestions aware of existing; may reuse or suggest new |

### B5. Full API Workflow (End-to-End with Existing Data)

#### B5-U: User System

| # | Test | Existing Data | Expected |
|---|------|---------------|----------|
| B5-U.1 | `GET /users` | 1 admin user | 200, list contains `admin` |
| B5-U.2 | `POST /users {"user_id":"jason","display_name":"Jason"}` | — | 201, user created |
| B5-U.3 | `POST /users {"user_id":"jason",...}` duplicate | jason exists | 409 |
| B5-U.4 | `GET /users/current` with `X-User-Id: jason` | — | 200, `user_id: "jason"` |
| B5-U.5 | `GET /users/current` without header | — | 200, `user_id: "admin"` (default) |

#### B5-D: Document Upload (Multi-Collection)

| # | Test | Existing Data | Expected |
|---|------|---------------|----------|
| B5-D.1 | Upload PDF with `?collections=legal-compliance,regulation-policy` | 2 docs exist | 200, `collections: ["legal-compliance","regulation-policy"]`, `user_id: "admin"` |
| B5-D.2 | Upload PDF with no `collections` param | — | 200, `collections: ["other"]` |
| B5-D.3 | Upload PDF with `?auto_suggest=true` | — | 200, `suggested_collections` is non-empty list |
| B5-D.4 | Upload as `X-User-Id: jason` | — | 200, `user_id: "jason"` |

#### B5-L: Document Listing

| # | Test | Existing Data | Expected |
|---|------|---------------|----------|
| B5-L.1 | `GET /documents` as admin | 2 existing + uploaded | 200, `total >= 2`, all have `collections` list + `user_id` |
| B5-L.2 | `GET /documents?collection=legal-compliance` as admin | doc from B5-D.1 | 200, each doc has `"legal-compliance"` in `collections` |
| B5-L.3 | `GET /documents?collection=other` as admin | existing doc `9485fe63ffcb` | 200, `total >= 1` |
| B5-L.4 | `GET /documents?collection=legal-framework` as admin | existing doc `f854b4f6ae47` | 200, `total >= 1` |
| B5-L.5 | `GET /documents/collections` as admin | — | 200, `taxonomy_categories` has 11 items, `existing_collections` includes `"other"`, `"legal-framework"` |

#### B5-I: User Isolation

| # | Test | Existing Data | Expected |
|---|------|---------------|----------|
| B5-I.1 | Upload as `X-User-Id: jason` | — | 200, `user_id: "jason"` |
| B5-I.2 | `GET /documents` as admin | jason's doc exists | Admin does NOT see jason's doc |
| B5-I.3 | `GET /documents` as jason | — | Jason sees only own docs |
| B5-I.4 | `POST /query` as admin | jason's doc exists | Answer does NOT reference jason's doc content |
| B5-I.5 | `POST /query` as jason with `collection` matching jason's doc | — | Answer references jason's doc content |

#### B5-E: Collection Editing

| # | Test | Existing Data | Expected |
|---|------|---------------|----------|
| B5-E.1 | `PATCH /documents/{doc_id}` with `{"collections":["research-scientific","computer-science-ai"]}` | doc from B5-D.2 | 200, collections updated |
| B5-E.2 | Verify listing reflects updated collections | — | `GET /documents` shows new collections on that doc |
| B5-E.3 | `POST /documents/{doc_id}/reclassify` | doc from B5-D.1 | 200, `collections` is list with >= 1 taxonomy tag |

#### B5-W: Download

| # | Test | Existing Data | Expected |
|---|------|---------------|----------|
| B5-W.1 | `GET /documents/{doc_id}/download` for uploaded doc | doc from B5-D.1 | 200, binary content, `Content-Type` header present |
| B5-W.2 | `GET /documents/nonexistent/download` | — | 404 |

#### B5-Q: Query

| # | Test | Existing Data | Expected |
|---|------|---------------|----------|
| B5-Q.1 | `POST /query {"question":"What is discussed?"}` as admin, no filter | 2+ admin docs | 200, `answer` > 20 chars, `sources` non-empty, each source has `doc_id` |
| B5-Q.2 | `POST /query` with `collection: "legal-compliance"` as admin | doc from B5-D.1 | 200, answer about legal content |
| B5-Q.3 | `POST /query` with `session_id: "test-s1"` as admin | — | 200, `session_id: "test-s1"` in response |
| B5-Q.4 | Follow-up query with same `session_id` | prior context | 200, answer references prior conversation |
| B5-Q.5 | Query with `collection: "legal-framework"` as admin | existing doc `f854b4f6ae47` | 200, answer about German Basic Law |

#### B5-X: Delete

| # | Test | Existing Data | Expected |
|---|------|---------------|----------|
| B5-X.1 | `DELETE /documents/{doc_id}` | doc from B5-D.1 | 200, `doc_id` in response |
| B5-X.2 | Verify deleted doc removed from listing | — | `GET /documents?collection=legal-compliance` no longer includes it |

---

## Backwards Compatibility (with Existing Data)

| # | Test | Expected |
|---|------|----------|
| BC.1 | Existing doc `9485fe63ffcb` (was `collection: "other"`) | After migration: `collections: ["other"]`, `user_id: "admin"` |
| BC.2 | Existing doc `f854b4f6ae47` (was `collection: "legal-framework"`) | After migration: `collections: ["legal-framework"]`, `user_id: "admin"` |
| BC.3 | `GET /documents` returns both existing docs | Both appear with `collections` list + `user_id` |
| BC.4 | `POST /query` without `X-User-Id` header | Falls back to `admin`, sees both existing docs |
| BC.5 | Old vector store chunks (no `collections_csv` metadata) | Query still works — filtering uses registry→doc_ids, not chunk metadata |

---

## Test Execution

### Run Offline Tests (Category A)
```bash
uv run pytest tests/ -k "not online" -v
```

### Run All Tests (Category A + B)
```bash
# Requires OPENAI_API_KEY in .env
uv run pytest tests/ -v
```

### Run Specific Test Groups
```bash
uv run pytest tests/test_schemas.py -v           # A2: Schemas
uv run pytest tests/test_registry.py -v           # A3+A4: Registry + Users
uv run pytest tests/test_suggest.py -v            # B4: AI Suggestions
uv run pytest tests/test_api_workflow.py -v        # B5: Full API Workflow
```

### Run Legacy Script Tests
```bash
uv run python test.py           # Original phases 1-3
uv run python test_chatbot.py   # Phases A-E
```

> **Note**: `test_collections.py` is outdated (uses old single-collection API) and should not be run.

---

## Test File Structure

```
tests/
  conftest.py               # Shared fixtures, test PDF paths, online marker
  test_schemas.py            # A2: Schema validation (multi-collection, user models)
  test_registry.py           # A3+A4: Document registry + User registry
  test_memory.py             # A5: Chat memory
  test_api_errors.py         # A6: HTTP error handling
  test_vectorstore.py        # B2: Vector store operations (online)
  test_chain.py              # B3: RAG chain (online)
  test_suggest.py            # B4: AI taxonomy suggestion (online)
  test_api_workflow.py       # B5: Full API workflow (online)
```

---

## Fixtures (conftest.py)

| Fixture | Scope | Description |
|---------|-------|-------------|
| `settings` | function | Load test Settings (reads `.env`) |
| `test_dir` | session | Temp directory `data/test_pytest/`, cleaned up after |
| `registry` | function | Fresh DocumentRegistry per test |
| `memory_manager` | function | Fresh SessionMemoryManager per test |

Test PDFs (real files in `test cases/`):
- `PDF_AI_SAFETY` — 2512.20798v2.pdf (17p, AI safety research)
- `PDF_PATTERNS` — 2602.10009v1.pdf (20p, pattern discovery research)
- `PDF_LAW` — 80201000.pdf (142p, German Basic Law)

---

## Markers

| Marker | Description |
|--------|-------------|
| `@online` | Requires OpenAI API key (skipped otherwise) |

---

## Pass Criteria

- **All Category A tests must pass** before merging any code change
- **All Category B tests must pass** before releasing a new version
- No test should take longer than 60 seconds individually
- Zero tolerance for crashes or unhandled exceptions in API endpoints
- User isolation must be verified: user A cannot see user B's documents or query results
- Collection migration must be transparent: existing data works without manual intervention

---

## Automated Test Count (v0.2.0)

| File | Offline | Online | Total |
|------|---------|--------|-------|
| test_schemas.py | 24 | — | 24 |
| test_registry.py | 22 | — | 22 |
| test_memory.py | 7 | — | 7 |
| test_api_errors.py | 6 | — | 6 |
| test_vectorstore.py | — | 8 | 8 |
| test_chain.py | — | 8 | 8 |
| test_suggest.py | — | 5 | 5 |
| test_api_workflow.py | — | 20 | 20 |
| **Total** | **59** | **41** | **100+** |

> Actual count from last run: **130 tests, all passing.**
