# MEINRAG Fix Plan

Based on CODE_REVIEW.md findings and user feedback.

---

## Phase 1: Critical Fixes

### 1.1 C2 — CORS: Restrict allowed origins
**Files:** `app/config.py`, `app/main.py`
- Add `cors_origins: str = "http://localhost:5173"` to Settings (comma-separated for multiple)
- In `main.py`, parse into list and use instead of `["*"]`
- Dev default: `http://localhost:5173`
- Production: set via `.env` → `CORS_ORIGINS=https://my-domain.com`
Q: For now just use env

### 1.2 C3 — Remove dead `collection` filter path
**Files:** `app/vectorstore/base.py`, `app/vectorstore/chroma_store.py`, `app/vectorstore/faiss_store.py`, `app/rag/chain.py`, `app/routers/query.py`
- Remove `collection` parameter from `similarity_search_with_filter()` (keep only `doc_ids`)
- Remove `collection` filtering logic from both Chroma and FAISS implementations
- Remove `collection` parameter from `build_rag_chain()` signature
- Clean up `query.py` — it already resolves everything to `doc_ids`, so remove `collection_for_chain` variable


---

## Phase 2: Major Fixes

### 2.1 M7 — Delete confirmation dialog
**Files:** `frontend/src/App.jsx`
- Add `if (!confirm('Delete this document? This cannot be undone.')) return` at top of `deleteDocument()`

### 2.2 M8 — Error-handle LLM in suggester
**Files:** `app/services/collection_suggester.py`
- Wrap `llm.invoke()` in try/except
- On failure: log error, return `["other"]` as fallback

### 2.3 M5 — Handle corrupted JSON in registries
**Files:** `app/models/document.py`, `app/models/user.py`
- In `_load()`: catch `json.JSONDecodeError`
- Log warning, return empty `{"documents": {}}` / `{"users": {}}`

### 2.4 M4 — File upload size limit
**Files:** `app/config.py`, `app/routers/documents.py`
- Add `max_upload_size_mb: int = 50` to Settings
- In upload endpoint: check `len(content) > settings.max_upload_size_mb * 1024 * 1024` after reading, raise 413

### 2.5 M3 — Registry read locking
**Files:** `app/models/document.py`, `app/models/user.py`
- Wrap `get()`, `list_all()`, `list_by_collection()`, `get_all_collections()`, `count()` in `with self._lock:`
- Same for `UserRegistry.get()`, `exists()`, `list_all()`

### 2.6 m7 + m8 — Download with user isolation
**Files:** `app/routers/documents.py`, `frontend/src/App.jsx`
- Add user ownership check to download endpoint (same pattern as other endpoints)
- Change frontend download from `<a>` tag to `fetch()` + blob URL (to include `X-User-Id` header)

---

## Phase 3: Minor Fixes

### 3.1 m4 — Validate `user_isolation` config
**Files:** `app/config.py`
- Change `user_isolation: str` to `user_isolation: Literal["all", "documents", "none"]`

### 3.2 m5 — Validate user exists
**Files:** `app/dependencies.py`
- In `get_current_user()`: check if user exists in registry
- If not, auto-create (same as `/users/current` does)
- Requires adding `get_user_registry` as dependency

### 3.3 m1 — Frontend error states
**Files:** `frontend/src/App.jsx`
- Add `connectionError` state
- If all 3 fetches fail → show error banner with retry button

### 3.4 m2 — Frontend memoization
**Files:** `frontend/src/App.jsx`
- Wrap `allCollections`, `filteredDocuments` in `useMemo`
- Wrap `getCollectionCount` in `useCallback`

---

## Phase 4: Deferred (future frontend redesign)

### 4.1 C1 — Settings page for API key config
- Future frontend settings page where user can configure API key, model, etc.
- For now: `.env` is sufficient and `.gitignore` protects it

### 4.2 M1 — Fix duplicate vector search
- Requires refactoring chain to return retrieved docs alongside answer
- Higher risk of breaking existing behavior, defer to next version

### 4.3 M2 — `get_all_documents()` memory issue
- Only relevant with hybrid search enabled (off by default)
- Defer until hybrid search is used in production

---

## Execution Order

```
Phase 1 (Critical):     1.1, 1.2           — do first
Phase 2 (Major):        2.1-2.6            — do second
Phase 3 (Minor):        3.1-3.4            — do third
Phase 4 (Deferred):     future sessions
```

## Files Changed Summary

| File | Changes |
|------|---------|
| `app/config.py` | Add `cors_origins`, `max_upload_size_mb`, change `user_isolation` type |
| `app/main.py` | Use config-based CORS origins |
| `app/vectorstore/base.py` | Remove `collection` param from `similarity_search_with_filter` |
| `app/vectorstore/chroma_store.py` | Remove `collection` filter logic |
| `app/vectorstore/faiss_store.py` | Remove `collection` filter logic |
| `app/rag/chain.py` | Remove `collection` param from `build_rag_chain` |
| `app/routers/query.py` | Remove `collection_for_chain`, simplify |
| `app/routers/documents.py` | Add size limit, add user check to download |
| `app/services/collection_suggester.py` | Wrap LLM call in try/except |
| `app/models/document.py` | Add read locks, handle corrupted JSON |
| `app/models/user.py` | Add read locks, handle corrupted JSON |
| `app/dependencies.py` | Validate user exists |
| `frontend/src/App.jsx` | Delete confirm, download via fetch, error states, memoization |
