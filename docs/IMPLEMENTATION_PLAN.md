# MEINRAG Enhancement Plan: Collections + Completed Chatbot Features

## Context
The basic RAG backend (Phases 1-5) and chatbot upgrade (document filtering, re-ranking, chat memory, hybrid search) are **COMPLETE**.

**NEW REQUIREMENT**: Add collection/category organization so users can group documents by topic (e.g., "law", "medical", "technical") and query specific collections. This enables:
- Upload documents with a `collection` tag (e.g., "law", "medical")
- List documents by collection
- Query specific collections: `POST /query?collection=law`
- Collections stored in separate vector store namespaces or via metadata filtering

---

## STATUS: What's Complete vs What's New

### ✅ COMPLETE — Chatbot Upgrade (Phases A-E)
All 4 chatbot features have been fully implemented and tested:
1. **Document filtering** — Query specific docs via `doc_ids` parameter
2. **LLM re-ranking** — Improve result quality with `RERANK_ENABLED=true`
3. **Chat memory** — Conversation history via `session_id` parameter
4. **Hybrid search** — BM25+vector fusion with `HYBRID_SEARCH_ENABLED=true`

Files modified (13):
- `pyproject.toml` (added `rank-bm25`)
- `app/config.py` (6 new settings)
- `app/models/schemas.py` (`doc_ids`, `session_id` fields)
- `app/vectorstore/{base,chroma_store,faiss_store}.py` (filtering methods)
- `app/rag/{prompts,chain,memory}.py` (full retrieval pipeline)
- `app/{main,dependencies}.py` (memory manager DI)
- `app/routers/query.py` (wired all features)
- `.env.example`, `.env`

Test suite created: `test_chatbot.py`

### ❌ NEW REQUIREMENT — Collections Feature (Phase G + H)
User wants to organize documents by **collection/category** (like folders):
- Upload: `POST /documents/upload?collection=law` (manual)
- Upload: `POST /documents/upload?auto_suggest=true` (AI suggests collection)
- List: `GET /documents?collection=law` : ar
- Query: `POST /query` with `{"collection": "law"}`
- Query without collection: searches ALL documents

**Phase G**: Basic collections (manual assignment)
**Phase H**: AI auto-suggest collection on upload (LLM analyzes content → suggests name → user accepts/overrides)

Design decisions:
- ✅ Dynamic collection names (no predefined list)
- ✅ Single-user demo (no auth/multi-tenancy)
- ✅ Query without collection = search all documents
- ✅ AI suggests collection name by analyzing first ~3 chunks of content

---

## Current Retrieval Pipeline
```
query + (optional doc_ids) + (optional collection) + (optional chat_history)
  -> filter by collection/doc_ids                        [Phase G - NEW]
  -> hybrid retriever (vector + BM25, merged via RRF)    [if enabled, Phase E ✅]
  -> re-ranker (LLM listwise rerank)                     [if enabled, Phase C ✅]
  -> format context
  -> chat-aware prompt (system + history + question)      [if session_id, Phase D ✅]
  -> LLM -> answer -> store in session memory
```

---

## PHASE G: Collections Feature (NEW)

### Design Decision
Use **metadata-based collections** (not separate vector stores) because:
- Simpler architecture — one vector store, filter by `collection` metadata
- Both Chroma and FAISS support metadata filtering (already implemented)
- Easy to query across collections or combine multiple collections
- No need to manage multiple store instances

### Changes Required

#### 1. `app/models/schemas.py` — Extend schemas
```python
class UploadResponse:
    collection: str | None  # NEW: which collection this doc belongs to

class DocumentInfo:
    collection: str | None  # NEW: collection tag

class QueryRequest:
    collection: str | None  # NEW: filter by collection name
    # existing: doc_ids, session_id
```

#### 2. `app/models/document.py` — Add collection field
```python
def add(self, doc_id, filename, file_type, chunk_count, collection=None):
    self._data["documents"][doc_id] = {
        ...
        "collection": collection,  # NEW
    }

def list_by_collection(self, collection: str) -> list[dict]:
    # NEW: filter documents by collection
```

#### 3. `app/routers/documents.py` — Accept collection on upload
```python
@router.post("/upload")
async def upload_document(
    file: UploadFile,
    collection: str | None = None,  # NEW query parameter
    ...
):
    # Add collection to chunk metadata
    for chunk in chunks:
        chunk.metadata["collection"] = collection

    # Store in registry
    registry.add(..., collection=collection)

@router.get("")
async def list_documents(
    collection: str | None = None,  # NEW: optional filter
    ...
):
    if collection:
        return registry.list_by_collection(collection)
    else:
        return registry.list_all()
```

#### 4. `app/vectorstore/base.py` — Extend filter signature
```python
def similarity_search_with_filter(
    self, query: str, k: int,
    doc_ids: list[str] | None = None,
    collection: str | None = None  # NEW
) -> list[Document]:
```

#### 5. `app/vectorstore/chroma_store.py` — Implement collection filtering
```python
def similarity_search_with_filter(self, query, k, doc_ids=None, collection=None):
    where = {}
    if doc_ids:
        where["doc_id"] = {"$in": doc_ids}
    if collection:
        where["collection"] = collection

    # Combine filters with $and if both present
    if doc_ids and collection:
        where = {"$and": [{"doc_id": {"$in": doc_ids}}, {"collection": collection}]}

    return self._store.similarity_search(query, k=k, filter=where if where else None)
```

#### 6. `app/vectorstore/faiss_store.py` — Implement collection filtering
```python
def similarity_search_with_filter(self, query, k, doc_ids=None, collection=None):
    # Over-fetch + post-filter by collection AND/OR doc_ids
    candidates = self._store.similarity_search(query, k=k*5)
    filtered = candidates
    if collection:
        filtered = [d for d in filtered if d.metadata.get("collection") == collection]
    if doc_ids:
        filtered = [d for d in filtered if d.metadata.get("doc_id") in doc_ids]
    return filtered[:k]
```

#### 7. `app/rag/chain.py` — Pass collection through pipeline
```python
def build_rag_chain(
    vector_store, llm, top_k=4,
    doc_ids=None,
    collection=None,  # NEW
    chat_history=None,
    settings=None
):
    # When building filtered retriever, pass collection:
    retriever = _build_filtered_retriever(vector_store, doc_ids, collection, fetch_k)

def _build_filtered_retriever(vector_store, doc_ids, collection, top_k):
    def _search(query: str) -> list[Document]:
        return vector_store.similarity_search_with_filter(
            query, k=top_k, doc_ids=doc_ids, collection=collection
        )
    return RunnableLambda(_search)

def _build_hybrid_retriever(vector_store, top_k, bm25_weight, doc_ids=None, collection=None):
    all_docs = vector_store.get_all_documents()
    if collection:
        all_docs = [d for d in all_docs if d.metadata.get("collection") == collection]
    if doc_ids:
        all_docs = [d for d in all_docs if d.metadata.get("doc_id") in doc_ids]
    # ... rest unchanged
```

#### 8. `app/routers/query.py` — Wire collection into query endpoint
```python
@router.post("/query")
async def query_documents(
    request: QueryRequest,
    ...
):
    chain, retriever = build_rag_chain(
        vector_store=vector_store,
        llm=llm,
        top_k=request.top_k,
        doc_ids=request.doc_ids,
        collection=request.collection,  # NEW
        chat_history=chat_history,
        settings=settings,
    )

    # Also filter sources in response
    if request.collection:
        retrieved_docs = vector_store.similarity_search_with_filter(
            request.question, k=request.top_k,
            doc_ids=request.doc_ids, collection=request.collection
        )
```

#### 9. `.env` — Optional default collection
```
DEFAULT_COLLECTION=general  # If not specified on upload, use this
```

### API Examples

**Upload to "law" collection:**
```bash
POST /documents/upload?collection=law
Content-Type: multipart/form-data
file: contract.pdf

Response:
{
  "doc_id": "abc123",
  "filename": "contract.pdf",
  "chunk_count": 42,
  "collection": "law",
  "message": "Document uploaded and indexed successfully"
}
```

**Query only "law" collection:**
```bash
POST /query
{
  "question": "What are the termination clauses?",
  "collection": "law",
  "top_k": 4
}
```

**List all "law" documents:**
```bash
GET /documents?collection=law

Response:
{
  "documents": [
    {"doc_id": "abc123", "filename": "contract.pdf", "collection": "law", ...},
    {"doc_id": "def456", "filename": "agreement.docx", "collection": "law", ...}
  ],
  "total": 2
}
```

**Query specific doc within collection:**
```bash
POST /query
{
  "question": "What does section 5 say?",
  "collection": "law",
  "doc_ids": ["abc123"],  # Combine both filters
  "top_k": 3
}
```

### Implementation Order
1. Update schemas (`UploadResponse`, `DocumentInfo`, `QueryRequest`)
2. Extend `DocumentRegistry` with `collection` field + `list_by_collection()`
3. Update vector store interfaces (`base.py`, `chroma_store.py`, `faiss_store.py`)
4. Update `chain.py` helper functions to accept `collection`
5. Wire into upload endpoint (accept query param, tag chunks, store in registry)
6. Wire into list endpoint (filter by collection)
7. Wire into query endpoint (pass to chain + retrieval)
8. Update `.env` with `DEFAULT_COLLECTION` (optional)

### Backwards Compatibility
- `collection` is optional everywhere — existing API calls work unchanged
- If `collection=None`, behavior is identical to current system (search all docs)
- No breaking changes to existing schemas or endpoints

---

## PHASE H: AI Auto-Suggest Collection (NEW)

### Feature
When uploading a document, the LLM can analyze its content and suggest an appropriate collection name.

### Upload Flow
```
1. User uploads file WITHOUT specifying collection
   POST /documents/upload?auto_suggest=true

2. Backend:
   - Load and chunk document
   - Extract first 3 chunks (or ~1500 chars)
   - Call LLM with prompt: "Analyze this document and suggest a SHORT collection name (1-2 words)"
   - LLM responds: "legal" or "medical-reports" or "technical-docs"

3. Response includes suggested collection:
   {
     "doc_id": "abc123",
     "filename": "contract.pdf",
     "suggested_collection": "legal",
     "chunk_count": 42,
     "message": "Document processed. Suggested collection: legal"
   }

4. Frontend (Phase I) can display:
   "We suggest putting this in 'legal'. [Accept] [Change to: ___] [Skip]"
```

### Implementation

#### 1. `app/models/schemas.py` — Add suggestion field
```python
class UploadResponse:
    doc_id: str
    filename: str
    chunk_count: int
    collection: str | None
    suggested_collection: str | None = None  # NEW: AI suggestion
    message: str
```

#### 2. `app/services/collection_suggester.py` — NEW FILE
```python
from langchain_core.language_models import BaseChatModel

SUGGESTION_PROMPT = """\
Analyze the following document excerpt and suggest a SHORT collection name (1-2 words, lowercase, hyphen-separated if needed).

Choose a category that describes the document type or domain:
- Examples: "legal", "medical", "technical", "financial", "hr", "marketing", "research"
- Be specific but concise
- Return ONLY the collection name, nothing else

Document excerpt:
{content}

Collection name:"""

def suggest_collection(chunks: list[Document], llm: BaseChatModel) -> str:
    """Analyze document content and suggest a collection name."""
    # Take first 3 chunks or ~1500 chars
    content = "\n\n".join([c.page_content for c in chunks[:3]])
    content = content[:1500]

    response = llm.invoke(SUGGESTION_PROMPT.format(content=content))
    suggestion = response.content.strip().lower()

    # Clean: remove quotes, periods, ensure valid format
    suggestion = suggestion.replace('"', '').replace("'", '').replace('.', '')
    suggestion = suggestion.replace(' ', '-')

    return suggestion[:50]  # Max 50 chars
```

#### 3. `app/routers/documents.py` — Add auto_suggest logic
```python
@router.post("/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    collection: str | None = None,
    auto_suggest: bool = False,  # NEW query parameter
    settings: Settings = Depends(get_settings),
    vector_store: VectorStoreManager = Depends(get_vector_store),
    llm: BaseChatModel = Depends(get_llm),  # NEW dependency
    registry: DocumentRegistry = Depends(get_registry),
):
    # ... save file, process chunks ...

    suggested_collection = None
    if auto_suggest and not collection:
        # AI suggests collection
        from app.services.collection_suggester import suggest_collection
        suggested_collection = suggest_collection(chunks, llm)
        collection = suggested_collection  # Auto-assign for now

    # Add collection to chunks
    for chunk in chunks:
        chunk.metadata["collection"] = collection

    # ... store in vector store + registry ...

    return UploadResponse(
        doc_id=doc_id,
        filename=filename,
        chunk_count=len(chunks),
        collection=collection,
        suggested_collection=suggested_collection,
        message=f"Document uploaded. {f'Suggested collection: {suggested_collection}' if suggested_collection else ''}"
    )
```

#### 4. Alternative: Two-step flow (suggest first, then upload)
```python
@router.post("/suggest-collection")
async def suggest_collection_for_file(
    file: UploadFile,
    llm: BaseChatModel = Depends(get_llm),
):
    """Analyze uploaded file and return suggested collection WITHOUT saving."""
    # Read file, extract text, chunk, analyze
    # Return: {"suggested_collection": "legal"}
    # User can then call /upload with this collection
```

### Config
```env
COLLECTION_AUTO_SUGGEST=true  # Enable AI suggestions by default
```

### Implementation Order (Phase H)
1. Create `app/services/collection_suggester.py` with LLM prompt
2. Add `suggested_collection` to `UploadResponse`
3. Update upload endpoint with `auto_suggest` parameter
4. Wire LLM dependency into upload route
5. Test: upload contract.pdf with `auto_suggest=true` → should suggest "legal"

### Testing
```bash
# Upload with AI suggestion
curl -X POST "http://localhost:8000/documents/upload?auto_suggest=true" \
  -F "file=@contract.pdf"

Response:
{
  "doc_id": "abc123",
  "filename": "contract.pdf",
  "chunk_count": 42,
  "collection": "legal",
  "suggested_collection": "legal",
  "message": "Document uploaded. Suggested collection: legal"
}

# Upload with manual collection (AI skipped)
curl -X POST "http://localhost:8000/documents/upload?collection=my-custom-category" \
  -F "file=@report.pdf"

# Upload without collection (no AI, no collection)
curl -X POST "http://localhost:8000/documents/upload" \
  -F "file=@notes.txt"
```

---

## Verification (Full System)

### Chatbot Features (Already Complete ✅)
1. ✅ Upload 2 PDFs, query with `doc_ids=[one_id]` — results only from that doc
2. ✅ Enable `RERANK_ENABLED=true`, query — verify answer quality improves
3. ✅ Send query with `session_id="s1"`, then follow-up "what did you just say?" — memory works
4. ✅ Enable `HYBRID_SEARCH_ENABLED=true`, query exact keyword — BM25 boosts results
5. ✅ All features off (defaults) — identical behavior to original system

### Collections Feature (Phase G - To Be Implemented)
6. Upload contract.pdf with `collection=law` — doc tagged as "law"
7. Upload report.pdf with `collection=medical` — doc tagged as "medical"
8. `GET /documents?collection=law` — returns only law docs
9. Query with `{"collection": "law"}` — results only from law documents
10. Query with `{"collection": "law", "doc_ids": ["abc123"]}` — combined filtering works
11. Query with `{"collection": "law", "session_id": "s1"}` — collections work with chat memory
12. Upload without `collection` param — doc added with `collection=null`, searchable when no filter
13. Query without collection — searches ALL documents regardless of collection

### AI Auto-Suggest (Phase H - To Be Implemented)
14. Upload contract.pdf with `auto_suggest=true` — LLM suggests "legal"
15. Upload medical-report.docx with `auto_suggest=true` — LLM suggests "medical" or "healthcare"
16. Upload random-notes.txt with `auto_suggest=true` — LLM suggests "general" or similar
17. Verify suggestion is returned in response but can be overridden
18. Upload with both `collection=custom` and `auto_suggest=true` — manual collection takes priority, no AI call

---

## Summary: Implementation Plan

### What's Already Done ✅
- **Phases A-E**: Document filtering, re-ranking, chat memory, hybrid search (all complete)
- Files: 13 modified, 2 created (`memory.py`, `test_chatbot.py`)
- All features are optional, backwards-compatible, tested

### What to Implement Next

**Phase G: Collections (Manual Assignment)**
- Files to modify: 8 files
  - `app/models/schemas.py` — add `collection` field
  - `app/models/document.py` — add `collection` to registry + `list_by_collection()`
  - `app/vectorstore/{base,chroma_store,faiss_store}.py` — extend filtering for collections
  - `app/rag/chain.py` — pass `collection` through pipeline
  - `app/routers/{documents,query}.py` — wire collection into upload/list/query
- Estimated: ~1 hour, low complexity (similar to `doc_ids` filtering)

**Phase H: AI Auto-Suggest (Optional Enhancement)**
- Files to create: 1 new file (`app/services/collection_suggester.py`)
- Files to modify: 2 files (`schemas.py`, `documents.py`)
- Estimated: ~30 minutes, straightforward LLM integration

**Phase I: Frontend (Deferred)**
- Build web UI for chat + document management
- Will address the "second problem" mentioned by user

### Critical Design Decisions
1. **Metadata-based filtering** (not separate vector stores) — reuses existing `similarity_search_with_filter`
2. **Dynamic collection names** — no predefined list, users create as needed
3. **Default query = search all** — collection filtering is optional
4. **AI suggests, user decides** — LLM suggests collection, but user can override/skip

### Files Summary

**To Modify (Phase G):**
```
app/models/schemas.py          # Add collection field to request/response
app/models/document.py          # Add collection tracking + list_by_collection()
app/vectorstore/base.py         # Extend filter signature
app/vectorstore/chroma_store.py # Implement collection filtering
app/vectorstore/faiss_store.py  # Implement collection filtering
app/rag/chain.py                # Pass collection through retrievers
app/routers/documents.py        # Accept collection on upload, filter on list
app/routers/query.py            # Pass collection to RAG chain
```

**To Create (Phase H):**
```
app/services/collection_suggester.py  # LLM-based suggestion logic
```

**To Modify (Phase H):**
```
app/models/schemas.py          # Add suggested_collection field
app/routers/documents.py       # Add auto_suggest parameter + call suggester
```
