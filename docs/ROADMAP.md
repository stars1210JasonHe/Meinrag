# MEINRAG Roadmap

Current status as of 2026-02-19. **Version: v0.6**

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
- [x] PostgreSQL-backed `ChatSessionRepository` (replaced in-memory store)
- [x] Persistent chat sessions survive server restarts
- [x] Auto-trim to `MEMORY_MAX_MESSAGES`, auto-expire after `MEMORY_SESSION_TTL`
- [x] `RAG_CHAT_PROMPT` with `MessagesPlaceholder("chat_history")`
- [x] `session_id` on request/response schemas
- [x] Sessions API: `GET /sessions`, `GET /sessions/{id}/messages`, `DELETE /sessions/{id}`

### Phase 7 — Chatbot Upgrade: Hybrid Search
- [x] `rank-bm25` dependency
- [x] `get_all_documents()` on both stores (for BM25 index building)
- [x] `_build_hybrid_retriever()` — `EnsembleRetriever` with BM25 + vector, merged via RRF
- [x] `HYBRID_SEARCH_ENABLED` / `HYBRID_BM25_WEIGHT` config flags (off by default)
- [x] Hybrid retriever respects `doc_ids` filtering

### Phase 8 — Collections Feature (Manual + AI)
- [x] Multi-collection documents with junction table (`document_collections`)
- [x] Vector store filtering extended for collections (Chroma + FAISS)
- [x] Upload endpoint accepts `collection` parameter + `auto_suggest=true`
- [x] AI auto-categorization via `collection_suggester.py`
- [x] Inline collection editing + AI reclassify
- [x] Hierarchical taxonomy sidebar with document counts

### Phase 9 — Multi-User System
- [x] PostgreSQL `users` table with `X-User-Id` header-based identification
- [x] Per-user document isolation (configurable: `all` | `documents` | `none`)
- [x] User creation, switching, and auto-creation on first request
- [x] User menu in header with profile management

### Phase 10 — Frontend Chat UI (React)
- [x] Full React 18 + Vite frontend with 15+ component files
- [x] Sidebar: chat history, document tree, collection browser, upload buttons
- [x] Chat area: message bubbles, source citations, welcome screen
- [x] Input bar: text input, send button, web search button, quote injection
- [x] Session management: new chat, select session, delete session

### Phase 11 — Smart Web Search
- [x] DuckDuckGo web search fallback when no relevant docs found
- [x] Score threshold auto-fallback (`web_search_score_threshold: 0.5`)
- [x] Manual "Search Web" button for on-demand web search
- [x] LLM query rewriting for optimized search queries
- [x] Multi-query search with URL deduplication
- [x] Parallel full-page fetching for top 3 web results
- [x] Web source citations with ask/copy/quote buttons

### Phase 12 — Chunk Interaction
- [x] `POST /query/chunk-context` endpoint for asking about specific chunks
- [x] Document chunks: fetch ±2 neighbor chunks for surrounding context
- [x] Web chunks: fetch full page content via httpx
- [x] Copy button (clipboard) and Quote button (inject into input bar)
- [x] `get_chunks_by_doc()` on both vector store implementations

### Phase 13 — Dual-Answer Mode
- [x] Enhanced RAG prompt: supplements with general knowledge when docs insufficient
- [x] Clear labeling: "From your documents" vs "From general knowledge"
- [x] `POST /query/ask-ai` endpoint for pure LLM general knowledge answers
- [x] "Ask AI" button on assistant messages with purple Sparkles icon
- [x] Collapsible "AI Knowledge" section with purple theme
- [x] `AskAIRequest`/`AskAIResponse` schemas with validation

---

## Up Next

### Phase 14 — Streaming Responses
- [ ] `POST /query/stream` endpoint returning Server-Sent Events (SSE)
- [ ] Stream LLM tokens as they arrive instead of waiting for full answer
- [ ] Frontend renders partial answers in real time
- [ ] Streaming for both RAG and Ask AI responses

### Phase 15 — Markdown Rendering
- [ ] Install `react-markdown` + `remark-gfm` for GitHub-flavored markdown
- [ ] Render AI responses with proper formatting (bold, lists, code blocks, tables)
- [ ] Syntax highlighting for code blocks (`rehype-highlight`)
- [ ] Apply to both RAG answers and AI Knowledge section

### Phase 16 — Observability & Production Hardening
- [ ] Structured JSON logging
- [ ] Request tracing (correlation IDs)
- [ ] LangSmith or custom callback handler for chain tracing
- [ ] Health endpoint checks LLM/vector store connectivity
- [ ] Dockerfile + docker-compose for full-stack deployment
- [ ] CI pipeline (lint, test, build image)

### Phase 17 — Advanced Retrieval
- [ ] Parent-document retriever (store small chunks, retrieve full sections)
- [ ] Metadata-rich filtering (date range, file type, tags)
- [ ] Configurable embedding models (swap out `text-embedding-3-small`)

### Future Ideas
- [ ] User authentication (login/password with JWT)
- [ ] Document versioning
- [ ] Conversation export (PDF/Markdown)
- [ ] Analytics dashboard
- [ ] Dark mode / theme support
- [ ] Mobile responsive improvements
- [ ] Multi-language UI (i18n)
- [ ] Drag-and-drop file upload

---

## Current Architecture Snapshot

```
app/
  config.py              Settings (env-driven)
  main.py                FastAPI lifespan, app factory
  dependencies.py        DI functions (settings, store, llm, memory)
  db/
    models.py            SQLAlchemy ORM (5 tables: users, documents, collections, sessions, messages)
    session.py           Async engine + session factory
    repositories.py      DocumentRepository, UserRepository, ChatSessionRepository
  models/
    schemas.py           Request/response Pydantic models
  llm/
    provider.py          LLM + embeddings factory
  vectorstore/
    base.py              VectorStoreManager ABC
    chroma_store.py      ChromaDB implementation
    faiss_store.py       FAISS implementation
    factory.py           Store type switching
  rag/
    prompts.py           RAG, Chat, Web Search, Chunk Context, Ask AI prompts
    chain.py             Retrieval pipeline (filter, hybrid, rerank, chat)
  services/
    document_processor.py  File loading + chunking
    collection_suggester.py  AI collection suggestion
    web_search.py        DuckDuckGo web search service
  routers/
    health.py            GET /health
    documents.py         Upload, list, delete, collections, reclassify
    query.py             POST /query, /query/chunk-context, /query/ask-ai
    sessions.py          GET/DELETE /sessions
frontend/
  src/
    App.jsx              Main React component + state management
    App.css              Application styles
    api/                 API client modules (client, documents, query, sessions, users)
    components/          15+ React components (Header, Sidebar, ChatArea, MessageBubble, etc.)
```

## Query Pipeline (current)

```
request (question, top_k, doc_ids?, session_id?, collection?, force_web_search?)
  |
  |-- force_web_search? -> skip to web search pipeline
  |
  |-- load chat_history from ChatSessionRepository (if session_id)
  |
  |-- build retriever:
  |     hybrid enabled?  -> EnsembleRetriever (BM25 + vector, RRF merge)
  |     doc_ids present? -> filtered retriever (similarity_search_with_filter)
  |     default          -> vector store as_retriever
  |
  |-- rerank enabled? -> ContextualCompressionRetriever (LLMListwiseRerank)
  |
  |-- check results:
  |     no results?           -> web search fallback
  |     best score < 0.5?     -> web search fallback
  |     has results            -> continue to RAG chain
  |
  |-- web search fallback:
  |     LLM rewrites query -> 2-3 search queries
  |     DuckDuckGo search (max 9 results, deduplicated)
  |     Fetch full page for top 3 results (parallel, with timeout)
  |     Build context -> WEB_SEARCH_PROMPT -> LLM -> answer
  |
  |-- RAG chain:
  |     select prompt (with/without chat_history)
  |     LCEL: retriever | format_docs -> prompt -> LLM -> StrOutputParser
  |
  |-- store exchange in ChatSessionRepository (if session_id)
  |
  -> QueryResponse (answer, sources, question, session_id, web_search_used)
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
| `WEB_SEARCH_ENABLED` | `true` | Web search fallback when docs insufficient |
| `WEB_SEARCH_MAX_RESULTS` | `9` | Max web search results per query set |
| `WEB_SEARCH_SCORE_THRESHOLD` | `0.5` | Min similarity score before triggering web fallback |
