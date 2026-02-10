# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

MEINRAG is a RAG (Retrieval-Augmented Generation) backend API built with FastAPI and LangChain. Users upload documents (PDF, DOCX, TXT, MD, HTML, XLSX, PPTX), which are chunked, embedded, and stored in a vector store. Queries retrieve relevant chunks and pass them as context to an LLM.

## Commands

```bash
# Install dependencies (uses uv, not pip)
uv sync

# Run the server
uv run uvicorn app.main:app --reload

# Run the base test suite (phases 1-3)
uv run python test.py

# Run the chatbot upgrade test suite (phases A-E: filtering, rerank, memory, hybrid)
uv run python test_chatbot.py
```

Dev dependencies (pytest, httpx, fpdf2) are in the `[dependency-groups] dev` section of `pyproject.toml`.

## Architecture

### Request Flow

```
Upload: File -> DocumentProcessor (load+chunk) -> VectorStoreManager.add_documents -> DocumentRegistry
Query:  Question -> build_rag_chain (retriever pipeline) -> LLM -> answer
```

### Key Abstractions

- **`VectorStoreManager`** (`app/vectorstore/base.py`) — Abstract base class. Implementations: `ChromaStoreManager` (default, auto-persists) and `FAISSStoreManager` (manual persist, rebuild-on-delete). Switching is via `VECTOR_STORE` env var + factory in `vectorstore/factory.py`.

- **`build_rag_chain()`** (`app/rag/chain.py`) — Constructs the LCEL chain. Supports optional `doc_ids` filtering, hybrid search (BM25+vector via EnsembleRetriever), LLM re-ranking (LLMListwiseRerank), and chat-aware prompting. All features are off by default; the function is backwards-compatible with the original `(vector_store, llm, top_k)` signature.

- **`SessionMemoryManager`** (`app/rag/memory.py`) — Thread-safe in-memory chat session store with TTL expiry and message trimming. Stored in `app.state.memory_manager`.

### Dependency Injection

All shared resources are initialized in `app/main.py::lifespan()` and stored on `app.state`. DI functions in `app/dependencies.py` pull from `request.app.state` for use with FastAPI's `Depends()`.

### Configuration

Pydantic Settings in `app/config.py` reads from `.env`. Key groups: LLM provider (OpenAI/OpenRouter), vector store type (Chroma/FAISS), chunking params, retrieval params, re-ranking, hybrid search, chat memory, server config.

### Prompts

`app/rag/prompts.py` has two templates: `RAG_PROMPT` (stateless) and `RAG_CHAT_PROMPT` (includes `MessagesPlaceholder("chat_history")`). The chain selects based on whether `chat_history` is provided.

## Patterns to Follow

- All vector store implementations must implement `VectorStoreManager` ABC (including `similarity_search_with_filter` and `get_all_documents`).
- Document chunks always get `doc_id` in metadata (set in `add_documents`), which enables filtering and deletion.
- FAISS lacks native metadata filtering — use over-fetch + post-filter pattern (see `faiss_store.py`).
- New features in `chain.py` should be additive: check `settings` for feature flags, default to off.
- The LLM and embeddings are separate — embeddings always use OpenAI `text-embedding-3-small` regardless of chat model provider.

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | System status |
| POST | `/documents/upload` | Upload and index a document |
| GET | `/documents` | List all documents |
| DELETE | `/documents/{doc_id}` | Remove a document |
| POST | `/query` | Ask a question (supports `doc_ids`, `session_id`) |
