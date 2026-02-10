# MEINRAG Roadmap

Current status as of 2026-02-10.

---

## Completed

### Phase 1 — Project Skeleton & Configuration
- [x] FastAPI app with lifespan startup/shutdown
- [x] Pydantic Settings loading from `.env`
- [x] LLM provider abstraction (OpenAI direct + OpenRouter proxy)
- [x] Embeddings always via OpenAI `text-embedding-3-small`
- [x] Logging setup, CORS middleware, global exception handler

### Phase 2 — Document Ingestion & Vector Storage
- [x] `DocumentProcessor` — load and chunk 7 file types (PDF, DOCX, TXT, MD, HTML, XLSX, PPTX)
- [x] `RecursiveCharacterTextSplitter` with configurable size/overlap
- [x] `VectorStoreManager` abstract interface
- [x] `ChromaStoreManager` — auto-persisting, native metadata filtering
- [x] `FAISSStoreManager` — manual persist, rebuild-on-delete
- [x] Factory pattern for switching stores via `VECTOR_STORE` env var
- [x] `DocumentRegistry` — thread-safe JSON-backed metadata store

### Phase 3 — RAG Chain & API Endpoints
- [x] LCEL chain: retriever -> format docs -> prompt -> LLM -> answer
- [x] `POST /documents/upload` — upload, process, chunk, embed, register
- [x] `GET /documents` — list all with metadata
- [x] `DELETE /documents/{doc_id}` — remove from store + registry + disk
- [x] `POST /query` — question answering with source chunks
- [x] `GET /health` — system status

### Phase 4 — Chatbot Upgrade: Document Filtering
- [x] `similarity_search_with_filter(query, k, doc_ids)` on both stores
- [x] Chroma: native `{"doc_id": {"$in": doc_ids}}` filter
- [x] FAISS: over-fetch (k*5) + post-filter pattern
- [x] `doc_ids` field on `QueryRequest`
- [x] `_build_filtered_retriever()` in chain.py
- [x] Query endpoint passes `doc_ids` through the full pipeline

### Phase 5 — Chatbot Upgrade: Re-ranking
- [x] `LLMListwiseRerank` compressor via `ContextualCompressionRetriever`
- [x] Over-fetch 3x when re-ranking enabled, then trim to `rerank_top_n`
- [x] `RERANK_ENABLED` / `RERANK_TOP_N` config flags (off by default)

### Phase 6 — Chatbot Upgrade: Chat Memory
- [x] `SessionMemoryManager` — thread-safe in-memory store with TTL expiry
- [x] Auto-trim to `MEMORY_MAX_MESSAGES`, auto-expire after `MEMORY_SESSION_TTL`
- [x] `RAG_CHAT_PROMPT` with `MessagesPlaceholder("chat_history")`
- [x] `session_id` on request/response schemas
- [x] Memory manager initialized at startup, available via DI
- [x] Query endpoint loads history, passes to chain, stores exchange after response

### Phase 7 — Chatbot Upgrade: Hybrid Search
- [x] `rank-bm25` dependency
- [x] `get_all_documents()` on both stores (for BM25 index building)
- [x] `_build_hybrid_retriever()` — `EnsembleRetriever` with BM25 + vector, merged via RRF
- [x] `HYBRID_SEARCH_ENABLED` / `HYBRID_BM25_WEIGHT` config flags (off by default)
- [x] Hybrid retriever respects `doc_ids` filtering

### Phase 8 — Collections Feature (Manual Assignment)
- [x] `collection` field added to schemas (`QueryRequest`, `UploadResponse`, `DocumentInfo`)
- [x] `DocumentRegistry.list_by_collection()` method
- [x] Vector store filtering extended for collections (Chroma + FAISS)
- [x] RAG chain passes `collection` through retrieval pipeline
- [x] Upload endpoint accepts `collection` query parameter
- [x] List endpoint filters by collection
- [x] Query endpoint supports collection filtering
- [x] Backwards compatible — collection is optional everywhere

### Phase 9 — AI Auto-Suggest Collection
- [x] `collection_suggester.py` service with LLM prompt
- [x] `suggested_collection` field in `UploadResponse`
- [x] Upload endpoint accepts `auto_suggest=true` parameter
- [x] LLM analyzes first ~1500 chars and suggests collection name
- [x] Suggestions are cleaned and validated (max 50 chars)
- [x] Manual collection takes priority over AI suggestion

---

## Up Next (Not Started)

### Phase 8 — Streaming Responses
- [ ] `POST /query/stream` endpoint returning Server-Sent Events (SSE)
- [ ] Stream LLM tokens as they arrive instead of waiting for full answer
- [ ] Frontend can render partial answers in real time

### Phase 9 — Persistent Chat Sessions
- [ ] Replace in-memory `SessionMemoryManager` with database-backed storage (SQLite or Redis)
- [ ] Sessions survive server restarts
- [ ] `GET /sessions` — list active sessions
- [ ] `GET /sessions/{session_id}` — retrieve full conversation history
- [ ] `DELETE /sessions/{session_id}` — clear a session

### Phase 10 — Authentication & Multi-Tenancy
- [ ] API key or JWT-based authentication middleware
- [ ] Per-user document isolation (users only see their own docs)
- [ ] Rate limiting per user/key

### Phase 11 — Frontend Chat UI
- [ ] Web-based chat interface (React or vanilla JS)
- [ ] File upload widget
- [ ] Document selector for `doc_ids` filtering
- [ ] Session management (new chat, history sidebar)
- [ ] Streaming message display

### Phase 12 — Observability & Production Hardening
- [ ] Structured JSON logging
- [ ] Request tracing (correlation IDs)
- [ ] LangSmith or custom callback handler for chain tracing
- [ ] Health endpoint checks LLM/vector store connectivity
- [ ] Dockerfile + docker-compose for deployment
- [ ] CI pipeline (lint, test, build image)

### Phase 13 — Advanced Retrieval
- [ ] Parent-document retriever (store small chunks, retrieve full sections)
- [ ] Multi-query retriever (LLM generates query variants for broader recall)
- [ ] Metadata-rich filtering (date range, file type, tags)
- [ ] Configurable embedding models (swap out `text-embedding-3-small`)

---

## Current Architecture Snapshot

```
app/
  config.py              Settings (env-driven)
  main.py                FastAPI lifespan, app factory
  dependencies.py        DI functions (settings, store, llm, memory)
  models/
    schemas.py           Request/response models
    document.py          DocumentRegistry (JSON metadata)
  llm/
    provider.py          LLM + embeddings factory
  vectorstore/
    base.py              VectorStoreManager ABC
    chroma_store.py      ChromaDB implementation
    faiss_store.py       FAISS implementation
    factory.py           Store type switching
  rag/
    prompts.py           RAG_PROMPT + RAG_CHAT_PROMPT
    chain.py             Retrieval pipeline (filter, hybrid, rerank, chat)
    memory.py            SessionMemoryManager (in-memory, TTL)
  services/
    document_processor.py  File loading + chunking
  routers/
    health.py            GET /health
    documents.py         Upload, list, delete
    query.py             POST /query (all features wired)
```

## Query Pipeline (current)

```
request (question, top_k, doc_ids?, session_id?)
  |
  |-- load chat_history from SessionMemoryManager (if session_id)
  |
  |-- build retriever:
  |     hybrid enabled?  -> EnsembleRetriever (BM25 + vector, RRF merge)
  |     doc_ids present? -> filtered retriever (similarity_search_with_filter)
  |     default          -> vector store as_retriever
  |
  |-- rerank enabled? -> ContextualCompressionRetriever (LLMListwiseRerank)
  |
  |-- select prompt:
  |     chat_history? -> RAG_CHAT_PROMPT (system + history + question)
  |     default       -> RAG_PROMPT (system + question)
  |
  |-- LCEL chain: retriever | format_docs -> prompt -> LLM -> StrOutputParser
  |
  |-- store exchange in memory (if session_id)
  |
  -> QueryResponse (answer, sources, question, session_id)
```

## Config Flags Summary

| Flag | Default | Effect |
|------|---------|--------|
| `RERANK_ENABLED` | `false` | LLM re-ranks retrieved docs (higher quality, slower) |
| `RERANK_TOP_N` | `4` | Final doc count after re-ranking |
| `HYBRID_SEARCH_ENABLED` | `false` | BM25 + vector fusion via RRF |
| `HYBRID_BM25_WEIGHT` | `0.5` | BM25 weight (vector = 1 - this) |
| `MEMORY_MAX_MESSAGES` | `20` | Max messages kept per chat session |
| `MEMORY_SESSION_TTL` | `3600` | Session expires after N seconds idle |
