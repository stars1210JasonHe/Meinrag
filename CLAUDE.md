# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MEINRAG is a RAG (Retrieval-Augmented Generation) application built with FastAPI, LangChain, and PostgreSQL. Users upload documents (PDF, DOCX, TXT, MD, HTML, XLSX, PPTX), which are chunked, embedded, and stored in a vector store. Queries retrieve relevant chunks and pass them as context to an LLM. A React frontend provides the user interface.

## Commands

```bash
# Install dependencies (uses uv, not pip)
uv sync

# Start PostgreSQL (Docker)
docker compose up -d

# Run database migrations
uv run alembic upgrade head

# Run the server
uv run uvicorn app.main:app --reload

# Run offline tests (no API key needed)
uv run pytest tests/ --ignore=tests/test_frontend_e2e.py --ignore=tests/test_api_workflow.py -v

# Run online API tests (requires OPENAI_API_KEY)
uv run pytest tests/test_api_workflow.py -v

# Run frontend E2E tests (requires both servers + playwright)
uv run pytest tests/test_frontend_e2e.py -v -s
```

Dev dependencies (pytest, pytest-asyncio, httpx, fpdf2, aiosqlite) are in the `[dependency-groups] dev` section of `pyproject.toml`.

## Architecture

### Request Flow

```
Upload: File -> DocumentProcessor (load+chunk) -> VectorStoreManager.add_documents -> DocumentRepository (DB)
Query:  Question -> build_rag_chain (retriever pipeline) -> LLM -> answer + ChatSessionRepository (DB)
```

### Database (PostgreSQL)

5 tables via SQLAlchemy 2.0 async ORM (`app/db/models.py`):
- `users` — user accounts
- `documents` — document metadata (FK to users)
- `document_collections` — junction table for multi-collection support
- `chat_sessions` — chat session tracking with TTL
- `chat_messages` — individual messages within sessions

Migrations managed by Alembic (`alembic/`). For tests, in-memory SQLite via `aiosqlite` replaces PostgreSQL.

### Key Abstractions

- **`VectorStoreManager`** (`app/vectorstore/base.py`) — Abstract base class. Implementations: `ChromaStoreManager` (default, auto-persists) and `FAISSStoreManager` (manual persist, rebuild-on-delete). Switching is via `VECTOR_STORE` env var + factory in `vectorstore/factory.py`.

- **`build_rag_chain()`** (`app/rag/chain.py`) — Constructs the LCEL chain. Supports optional `doc_ids` filtering, hybrid search (BM25+vector via EnsembleRetriever), LLM re-ranking (LLMListwiseRerank), and chat-aware prompting. All features are off by default; the function is backwards-compatible with the original `(vector_store, llm, top_k)` signature.

- **Repository classes** (`app/db/repositories.py`) — `DocumentRepository`, `UserRepository`, `ChatSessionRepository`. All async, backed by PostgreSQL via SQLAlchemy sessions. Chat sessions are persistent (survive server restarts).

### Dependency Injection

The lifespan in `app/main.py` initializes the DB engine, session factory, vector store, LLM, and embeddings on `app.state`. DI functions in `app/dependencies.py`:
- `get_db()` — yields a request-scoped `AsyncSession` with auto commit/rollback
- `get_registry(db)` — returns `DocumentRepository(db)`
- `get_user_registry(db)` — returns `UserRepository(db)`
- `get_memory_manager(settings, db)` — returns `ChatSessionRepository(db, ...)`
- `get_current_user(settings, user_registry)` — resolves user from `X-User-Id` header, auto-creates if new

### Configuration

Pydantic Settings in `app/config.py` reads from `.env`. Key groups: LLM provider (OpenAI/OpenRouter), vector store type (Chroma/FAISS), database URL, chunking params, retrieval params, re-ranking, hybrid search, chat memory, user system, server config.

### Prompts

`app/rag/prompts.py` has two templates: `RAG_PROMPT` (stateless) and `RAG_CHAT_PROMPT` (includes `MessagesPlaceholder("chat_history")`). The chain selects based on whether `chat_history` is provided.

## Patterns to Follow

- All vector store implementations must implement `VectorStoreManager` ABC (including `similarity_search_with_filter` and `get_all_documents`).
- Document chunks always get `doc_id` in metadata (set in `add_documents`), which enables filtering and deletion.
- FAISS lacks native metadata filtering — use over-fetch + post-filter pattern (see `faiss_store.py`).
- New features in `chain.py` should be additive: check `settings` for feature flags, default to off.
- The LLM and embeddings are separate — embeddings always use OpenAI `text-embedding-3-small` regardless of chat model provider.
- Repository methods are all `async` — always `await` them in routers and dependencies.
- DB schema changes require an Alembic migration (`alembic revision --autogenerate -m "description"`).
- Tests use in-memory SQLite (aiosqlite) — no PostgreSQL needed to run tests. TestClient tests override `get_db` with a SQLite session factory.

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | System status |
| GET | `/users` | List all users |
| POST | `/users` | Create a user |
| GET | `/users/current` | Get current user (from X-User-Id header) |
| POST | `/documents/upload` | Upload and index a document |
| GET | `/documents` | List documents (optional `?collection=`) |
| GET | `/documents/collections` | List collections + taxonomy |
| GET | `/documents/{doc_id}/download` | Download original file |
| PATCH | `/documents/{doc_id}` | Update document collections |
| POST | `/documents/{doc_id}/reclassify` | AI reclassify document |
| DELETE | `/documents/{doc_id}` | Remove a document |
| POST | `/query` | Ask a question (supports `doc_ids`, `session_id`, `collection`) |
