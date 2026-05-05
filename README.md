# MEINRAG

**RAG application for grounded, cited answers over your document library.**

Upload a corpus, browse it visually, ask questions in natural language, and get answers with clickable source citations that jump straight into the PDF at the right page and bounding box. Every claim is traceable.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.13+-blue.svg)
![React](https://img.shields.io/badge/react-19+-blue.svg)

---

## What's in the box

### Four pages, one app
- **Dashboard** — sunburst over a 3-layer taxonomy (primary category → sub-tags → user collections). Hover a wedge to see the docs in it; click to scope queries.
- **Chat** — streaming answers with `[N]` citations that open the right doc, scroll to the chunk, and bbox-highlight. Multi-doc selection, saved collections, persistent sessions.
- **Graph** — cross-doc similarity graph with weighted edges (thickness = supporting chunk pairs, opacity = mean similarity). Drill into a chunk → "Open chunk" lands you in chat with the PDF highlighted and a primed question.
- **Mind map** — LLM-derived concept tree per document. 3 layers by default; auto-deepens to 4 where content earns it.

### Retrieval
- Hybrid search (BM25 + dense vectors via Reciprocal Rank Fusion)
- Optional LLM-based router that pre-filters docs before vector search (default-on for ≥15 docs)
- LLM listwise re-ranker (FlashRank by default; switchable to cross-encoder, Jina, Cohere, or LLM)
- Per-chunk summaries embedded in a separate FAISS index — dual-index retrieval merges raw + summary scores
- Chunk-edge graph (5 relation types: follows, co_located, describes, references, similar_to) feeds composite scoring + graph expansion
- Cross-doc `similar_to` edges aggregated by doc-pair, gated by configurable score floor + minimum supporting pairs
- Smart web search fallback (DuckDuckGo, full-page fetch, LLM query rewriting) when corpus retrieval is empty
- Calibrated refusal: when docs don't cover the question, the system says so instead of hallucinating

### Authoring + organization
- Upload PDF, DOCX, TXT, MD, HTML, XLSX, PPTX
- Docling-based PDF parser with figure/table extraction (background process, cached models)
- AI auto-classification into the 3-layer taxonomy on upload
- Multi-select shopping-cart pattern for ad-hoc collection building
- Per-doc inline reclassification

### UX
- React 19 + Vite + Tailwind 4 + shadcn/ui
- Light + dark theme via CSS custom properties
- EN + 中文 UI (i18n via i18next)
- Streaming token-by-token response via Server-Sent Events
- Markdown rendering with syntax highlighting
- Multi-language Q&A (ask in English or Chinese)

### Operations
- Pydantic Settings with full `.env.example` coverage
- Alembic migrations for the Postgres schema
- Docker production stack (`docker-compose.prod.yml`) with backend, frontend, Postgres, and a docling model cache volume
- Deep health-check endpoint that pings DB + vector store + LLM
- Credibility benchmark harness with LLM-judge scoring (`scripts/test_dev_credibility.py`)

---

## Quick start

### Production stack via Docker

The fastest way to a running app. Builds Postgres + backend + frontend in one shot.

**Prereqs**: Docker Desktop (or Docker Engine + Compose v2) and an OpenAI API key.

```bash
git clone https://github.com/stars1210JasonHe/Meinrag.git
cd Meinrag
cp .env.example .env
# At minimum, set OPENAI_API_KEY=sk-...
docker compose -f docker-compose.prod.yml up --build
```

Open <http://localhost:5173>.

**First-boot timings** (one-time):
- Postgres ready: ~5 s
- Backend image build (`uv sync`): ~2 min
- Frontend image build (`npm ci` + `vite build`): ~1 min
- Docling model download (cached to `docling_cache` volume): ~5 min

Subsequent `up` is fast — images, deps, and docling models are cached.

```bash
docker compose -f docker-compose.prod.yml down       # stop, keep data
docker compose -f docker-compose.prod.yml down -v    # stop + wipe DB / uploads / vectors
```

Persistent state lives in named volumes: `pgdata`, `app_data`, `docling_cache`.

### Dev mode (hot reload)

For day-to-day work. Backend reloads on save (`uvicorn --reload`); frontend HMR via Vite. Docker only runs Postgres.

```bash
# Backend
pip install uv
uv sync
cp .env.example .env  # set OPENAI_API_KEY
docker compose up -d  # starts Postgres on :5432
uv run alembic upgrade head
uv run uvicorn app.main:app --reload  # :8000

# Frontend (in another terminal)
cd frontend
npm install
npm run dev  # :5173
```

> On Windows, `uvicorn --reload` occasionally stops detecting file changes after several days uptime. Bounce the process if you commit code and the API still serves the old behaviour.

---

## Architecture

### Request flow

```
Upload  → DocumentProcessor (load + chunk + embed)
        → VectorStoreManager.add_documents
        → DocumentRepository (Postgres)
        → background figure extraction + summary embedding

Query   → optional Router (LLM doc pre-filter for large scopes)
        → Hybrid retrieval (BM25 + dense, RRF-merged)
        → optional LLM re-rank
        → context-budgeted prompt
        → LLM (streaming SSE)
        → response with citations + telemetry
```

### Key abstractions

- **`VectorStoreManager`** (`app/vectorstore/base.py`) — ABC with `ChromaStoreManager` (auto-persist) and `FAISSStoreManager` (manual persist, rebuild-on-delete) implementations. Switch via `VECTOR_STORE` env var.
- **`build_rag_chain()`** (`app/rag/chain.py`) — LCEL chain factory. All advanced features (router, hybrid, rerank, chat history) are additive flags.
- **Repository classes** (`app/db/repositories.py`) — async, SQLAlchemy 2.0. `DocumentRepository`, `UserRepository`, `ChatSessionRepository`, `EdgeRepository`.
- **Edge builder** (`app/services/edge_builder.py`) — populates `chunk_edges` rows during ingest. Cross-doc `similar_to` edges are gated by `graph_similar_min_score` and aggregated for the doc-level graph view.

### Tracked configuration

Three JSON files in `data/` are tracked by git because the app reads them at startup:

- `data/taxonomy.json` — primary categories + sub-tag definitions for classification + the dashboard sunburst
- `data/query_types.json` — per-query-type scoring weights (fact / overview / reference / exploratory)
- `data/scoring_profiles/*.json` — domain-specific score profiles (academic / general / law)

Everything else under `data/` is gitignored (uploads, vectorstore, mindmap cache, eval artifacts).

---

## Project structure

```
MEINRAG/
├── app/                      # FastAPI backend
│   ├── config.py             # Pydantic Settings — every knob is here
│   ├── main.py               # FastAPI app + lifespan
│   ├── dependencies.py       # DI helpers
│   ├── db/                   # SQLAlchemy models + async session + repositories
│   ├── llm/                  # Provider integration (OpenAI / OpenRouter)
│   ├── models/               # Pydantic request/response schemas
│   ├── rag/                  # RAG chain, prompts, retrieval pipeline
│   ├── routers/              # health, documents, query, sessions, graph, stats
│   ├── services/             # document processor, classifier, edge builder, mindmap, etc.
│   └── vectorstore/          # FAISS + Chroma implementations
├── alembic/                  # DB migrations
├── frontend/                 # React 19 + Vite + Tailwind 4
│   └── src/
│       ├── pages/            # DashboardPage, ChatPage, GraphPage, PdfViewerPage
│       ├── components/       # 30+ components (SourceTabs, MindmapTree, Sunburst, ...)
│       ├── hooks/            # useDocTabs, useDocMindmap, ...
│       ├── i18n/             # EN + ZH locale files
│       └── lib/              # API client, utils
├── tests/                    # Pytest suite (in-memory SQLite, no Postgres required)
├── scripts/                  # Active utilities (10) — see scripts/README in-source
│   └── test_dev_credibility.py  # LLM-judge credibility benchmark
├── data/                     # Mostly gitignored; tracked: taxonomy.json + query_types.json + scoring_profiles/
├── Dockerfile                # Backend image
├── frontend/Dockerfile       # Frontend image (vite build → nginx)
├── docker-compose.yml        # Dev (just Postgres)
├── docker-compose.prod.yml   # Full prod stack
├── pyproject.toml            # uv-managed Python deps
├── .env.example              # Every env var, grouped, with comments
├── CLAUDE.md                 # Architecture + patterns for code agents
└── README.md
```

---

## Configuration

All settings live in [`app/config.py`](app/config.py) (the `Settings` Pydantic class) with defaults baked in. Override via env vars — see [`.env.example`](.env.example) for **every** supported variable, grouped by purpose with inline comments.

### Defaults you should know about

| Variable | Default | Notes |
|---|---|---|
| `RETRIEVAL_TOP_K` | `10` | |
| `ROUTER_ENABLED` | `true` | LLM doc pre-filter when scope ≥ `ROUTER_MIN_SCOPE` (15) |
| `HYBRID_SEARCH_ENABLED` | `true` | BM25 + dense via RRF |
| `SUMMARY_ENABLED` | `true` | Per-chunk summaries → second FAISS index |
| `QUERY_EXPANSION_ENABLED` | `true` | |
| `WEB_SEARCH_ENABLED` | `true` | Auto-fallback when retrieval empty |
| `RERANK_ENABLED` | `false` | Turn on for ambiguous queries |
| `GRAPH_SIMILAR_MIN_SCORE` | `0.7` | Cosine floor per chunk pair for cross-doc edges |
| `GRAPH_SIMILAR_MIN_PAIRS` | `2` | Minimum supporting chunk pairs for a doc-pair edge |
| `OPENAI_MODEL` | `gpt-4o-mini` | |
| `VECTOR_STORE` | `faiss` | Switch to `chroma` for native metadata filtering |
| `MEMORY_SESSION_TTL` | `2592000` (30 d) | Chat history is persistent — short TTLs lose data |

### Switching providers

**OpenRouter** (chat only — embeddings always use OpenAI):
```env
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-...
OPENROUTER_MODEL=openai/gpt-4o-mini
```

**Re-ranker provider** (when `RERANK_ENABLED=true`):
```env
RERANK_PROVIDER=cross-encoder    # flashrank | cross-encoder | jina | cohere | llm
RERANK_TOP_N=4
```

---

## API endpoints

### Documents
- `POST /documents/upload` — upload + index
- `GET /documents` — list (filter by `?collection=`, `?primary_category=`, `?subtags=`)
- `GET /documents/taxonomy` — taxonomy categories + user collection counts (replaces the legacy `/documents/collections`)
- `GET /documents/{id}/download` — original file
- `GET /documents/{id}/chunks` — chunks with bbox + page + summary metadata
- `GET /documents/{id}/graph` — chunk-level graph for one doc
- `GET /documents/{id}/mindmap` — LLM-derived concept tree (recursive, up to 4 levels)
- `PATCH /documents/{id}` — update primary_category, subtags, or collections
- `POST /documents/{id}/reclassify` — re-run AI classification
- `POST /documents/collections/save` — save a multi-select collection by name
- `DELETE /documents/{id}`

### Query
- `POST /query` — non-streaming, returns full response with sources + telemetry (`chunks_included`, `chunks_available`, `context_used_tokens`, `confidence_tier`, etc.)
- `POST /query/stream` — same but SSE: `sources` → `tokens` → `done`
- `POST /query/chunk-context` — ask about a specific source chunk
- `POST /query/ask-ai` / `POST /query/ask-ai/stream` — pure LLM, no retrieval

Common request body fields:
```json
{
  "question": "What is this about?",
  "doc_ids": ["abc123", "def456"],
  "collection": "legal-compliance",
  "primary_category": "research-scientific",
  "session_id": "session-123",
  "top_k": 10,
  "force_web_search": false
}
```

### Graph
- `GET /graph/documents` — corpus-level graph: doc nodes + aggregated cross-doc similarity edges (with `supporting_pairs` + `mean_score`)
- `GET /graph/nodes?doc_id=...` — chunk-level graph for one doc
- `GET /graph/neighbors?doc_id=...&chunk_index=...&hops=...` — neighbourhood subgraph

### Sessions
- `GET /sessions` — list user sessions
- `GET /sessions/{id}/messages` — message history
- `DELETE /sessions/{id}`

### Stats + health
- `GET /stats/corpus` — doc count, chunk count, taxonomy distribution
- `GET /health` — quick check
- `GET /health/deep` — DB + vector store + LLM connectivity

### Users
- `GET /users` / `POST /users` / `GET /users/current`

---

## Development

### Tests

```bash
# Offline tests (no API key, no Postgres — uses in-memory SQLite)
uv run pytest tests/ --ignore=tests/test_frontend_e2e.py --ignore=tests/test_api_workflow.py -v

# Online API tests (requires OPENAI_API_KEY)
uv run pytest tests/test_api_workflow.py -v

# Frontend E2E (requires both servers + Playwright)
uv run pytest tests/test_frontend_e2e.py -v -s
```

Current count: 94 backend tests pass offline.

### Credibility benchmark

`scripts/test_dev_credibility.py` runs a curated query set against the live dev backend and uses an LLM judge (gpt-4o-mini at temperature 0) to score:
- **Correctness** (does the answer address the question with the expected concepts?)
- **Groundedness** (are claims supported by the cited chunks?)
- **Calibration** (does the system refuse honestly on out-of-corpus questions?)

```bash
# Backend on :8000, OPENAI_API_KEY in env
uv run python scripts/test_dev_credibility.py
# Writes data/test_queries/dev_corpus_report_<date>.md
```

Useful before changing prompts, swapping models, or shipping retrieval changes — vendor "no regression" claims don't always survive your specific corpus.

### Code patterns

- All vector store implementations must implement `VectorStoreManager` ABC (including `similarity_search_with_filter` and `get_all_documents`).
- Document chunks always get `doc_id` in metadata — used for filtering and deletion.
- FAISS lacks native metadata filtering — use over-fetch + post-filter pattern.
- Repository methods are all `async`. Tests use in-memory SQLite (aiosqlite); TestClient tests override `get_db` with a SQLite session factory.
- Schema changes require an Alembic migration: `alembic revision --autogenerate -m "description"`.
- LLM and embeddings are separate — embeddings always use OpenAI `text-embedding-3-small` regardless of chat-model provider.

---

## Contributing

PRs welcome. The flow:

1. Fork and branch (`git checkout -b feature/your-thing`).
2. Make changes, add tests where the logic is non-trivial.
3. Run `uv run pytest tests/` — 94 should still pass.
4. Run `cd frontend && npm run build` — should be clean.
5. Open a PR.

If you're touching retrieval or prompting, also run `scripts/test_dev_credibility.py` against the same corpus before and after, and include the diff in the PR description.

---

## License

MIT — see [LICENSE](LICENSE).

---

## Acknowledgments

- [LangChain](https://www.langchain.com/) — chain primitives
- [ChromaDB](https://www.trychroma.com/), [FAISS](https://github.com/facebookresearch/faiss) — vector stores
- [Docling](https://github.com/DS4SD/docling) — PDF parsing with figure extraction
- [react-force-graph-2d](https://github.com/vasturiano/react-force-graph) — graph viz
- [react-d3-tree](https://github.com/bkrem/react-d3-tree) — mind map renderer
- [shadcn/ui](https://ui.shadcn.com/) — UI primitives
- [OpenAI](https://openai.com/), [OpenRouter](https://openrouter.ai/) — LLM providers

---

**Repository**: <https://github.com/stars1210JasonHe/Meinrag>
