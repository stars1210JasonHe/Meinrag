# MEINRAG

**RAG application for grounded, cited answers over your document library.**

Upload a corpus, browse it visually, ask questions in natural language, and get answers with clickable source citations that jump straight into the PDF at the right page and bounding box. Every claim is traceable.

![Tests](https://github.com/stars1210JasonHe/Meinrag/actions/workflows/test.yml/badge.svg)
![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.13+-blue.svg)
![React](https://img.shields.io/badge/react-19+-blue.svg)

---

## What's in the box

### Four pages, one app
- **Dashboard** — sunburst over a 3-layer taxonomy (primary category → sub-tags → user collections). Hover a wedge to see the docs in it; click to scope queries. Smart server-side search (filename / category / subtags / summary for short queries; semantic FAISS for long).
- **Chat** — streaming answers with `[N]` citations that open the right doc, scroll to the chunk, and bbox-highlight. Multi-doc selection, saved collections, persistent sessions, **pinnable doc tabs** (refuses to close until unpinned).
- **Graph** — cross-doc similarity graph with weighted edges, tiered by strength (strong = solid signature-blue, weak = dashed faint gray). Typeahead doc picker with Recent / Collections / Documents sections. Drill into a chunk → "Open chunk" lands you in chat with the PDF highlighted and a primed question. **Multi-doc chunk view** (toggle from the toolbar when 2+ docs are selected): renders every chunk from N docs in one canvas, colour-coded by doc, shape-coded by chunk type (text=circle, table=square, figure=triangle, formula=diamond), with a keyword filter to answer "do all 3 papers mention X?" at a glance.
- **Mind map** — LLM-derived concept tree per document. 3 layers by default; auto-deepens to 4 where content earns it. The LLM also suggests a per-doc colour palette that the multi-doc chunk graph uses as the doc-identity colour.

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
- In-browser viewer at `/pdf/<doc_id>` handles both PDF and DOCX (DOCX rendered via `docx-preview` with chunk-level highlighting; citation clicks deep-link via `?chunk=N`)

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

**First steps in the UI** (the corpus starts empty):
1. Click the **Upload** button (top-right) and add a PDF or two. Auto-classification runs in the background — for PDFs the docling pipeline downloads ~2 GB of layout models on the first upload, so allow a few minutes.
2. When the doc card appears with a category badge, head to **Chat**, pick the doc, and ask anything about it.
3. To curate a subset, multi-select doc cards on the dashboard → "Save as collection" in the bottom action bar.

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
# Backend (install uv first — see https://docs.astral.sh/uv/getting-started/installation/)
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
| `TAXONOMY_PATH` | `data/taxonomy.json` | Per-deployment classification taxonomy file |
| `CLASSIFICATION_ENABLED` | `true` | Set `false` to disable auto-classify / reclassify (assign categories deterministically instead) |

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

### Running multiple independent deployments

One codebase can serve several independent libraries (e.g. a generic library and
a legal library) — no fork, no branch. Each deployment is differentiated purely by
environment; the cleanest isolation is **one Docker Compose project per deployment**:

```bash
docker compose -p meinrag-generic --env-file .env.generic up -d
docker compose -p legal-library   --env-file .env.legal   up -d
```

Per-deployment env vars: `TAXONOMY_PATH`, `CLASSIFICATION_ENABLED`, `DATABASE_URL`,
`VECTORSTORE_DIR`, `UPLOAD_DIR`, `PORT`, `REDIS_URL`, `ANONYMIZATION_ENABLED` (+ key).

**Caveats:**
- **Do not share one Redis** across deployments — the ARQ summary-task queue would
  mix jobs, so one library's documents could be processed against another's vector
  store. Give each deployment its own Redis (separate container, or distinct DB index).
- Prefer Docker over bare processes for multi-instance — containers isolate the
  filesystem, so any path-derived cache cannot collide between deployments.
- A deployment that assigns categories deterministically (e.g. legal `doc_type` from
  curated source folders) should set `CLASSIFICATION_ENABLED=false` so the
  probabilistic classifier never runs.

A legal deployment plans its ingest with `scripts/ingest_legal_corpus.py` (dry-run by
default; `data/legal_corpus_map.json` holds the curated folder→`doc_type` rules,
file-type whitelist, `*_files/` web-asset exclusion, and filename-level PII triage).
`--execute` POSTs each included file to a running server's `/upload` with the
deterministic `primary_category`/`subtags` override (stays human-gated until the PII
unfreeze). doc_type is folder-derived, never classifier-guessed.

---

## Enabling Anonymization (Optional)

MEINRAG ships with an optional PII de-identification plugin (Microsoft
Presidio + spaCy) that pseudonymizes documents before they reach the
embedding API or vector store. The vector store sees `[PERSON_1]`
instead of "Alice Smith"; authorized users see the original names in
chat answers thanks to a reversible mapping table (Fernet-encrypted).

**Default: OFF.** OSS users don't pay for the ~580 MB of spaCy NER
models unless they enable the feature.

### What's protected, what's not

| Component | Sees raw PII? |
|---|---|
| OpenAI embedding API | No |
| Vector store (FAISS) | No |
| BM25 index | No (disabled when anonymization is on) |
| LLM completion API | **Yes** — transient, for authorized users only |
| API response (citations) | Yes — for authorized users only |
| Encrypted mappings table | Stored Fernet-encrypted; only decrypted at query time |

The LLM-completion exposure is intentional: anonymized chunks degrade
answer quality too much. The bigger risk (PII persisting in vector
store + embedding API logs) is covered.

### Enabling

1. Install the extra dependency group:
   ```bash
   uv sync --extra anonymization
   ```
2. Download spaCy models (one-time, ~580 MB):
   ```bash
   uv run python -m spacy download en_core_web_lg
   uv run python -m spacy download zh_core_web_trf
   ```
3. Generate a Fernet encryption key:
   ```bash
   uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
4. Set environment variables in `.env`:
   ```
   ANONYMIZATION_ENABLED=true
   ANONYMIZATION_ENCRYPTION_KEY=<paste the key from step 3>
   ```
5. Run the migration (already applied if you've been running migrations,
   but safe to re-run):
   ```bash
   uv run alembic upgrade head
   ```
6. Verify the key works at startup:
   ```bash
   uv run python scripts/verify_anonymization_key.py
   ```
7. Restart the server. Upload a new document. Inspect via:
   ```bash
   uv run python scripts/scan_vector_store_for_pii.py --doc <doc_id>
   ```
   Expected: zero PII hits.

### Important caveats

- **No retroactive protection.** Enabling the flag protects only
  **new** uploads. To anonymize an existing doc, use
  `scripts/reanonymize_doc.py <doc_id>` (re-runs the pipeline through
  the anonymization step).
- **Disabling is one-way.** Flipping the flag back to false leaves
  pseudonymized chunks in the vector store — chat answers will show
  `[PERSON_1]` placeholders. To revert, re-ingest affected docs with
  the flag off.
- **Lose the key, lose the mappings.** The encryption key is the only
  way to recover original PII from the mapping table. If lost, those
  docs are effectively destroyed for de-anonymization purposes.
  Back up the key to a secrets manager / offline copy.
- **BM25 is disabled when anonymization is on.** Keyword queries
  containing raw PII (e.g. "show me everything about Alice Smith") will
  not match anonymized chunks via BM25. Vector + reranker still work
  semantically.
- **Default-off forever.** This is a deployment-time choice; the OSS
  main branch will never auto-enable anonymization.

---

## API endpoints

> Building an external agent or MCP integration? See **[`API.md`](API.md)** for the
> full reference — auth, request/response shapes, curl + Python examples, SSE streaming
> format, error model, pagination, and best-practice notes for agent integrations.

**Multi-user note**: requests with no `X-User-Id` header default to the configured `DEFAULT_USER` (`admin`). To scope documents and chat sessions per user, send `X-User-Id: <any-string>` — the backend auto-creates the user on first request. There is no built-in authentication; treat the user header as advisory, not a security boundary.

### Documents
- `POST /documents/upload` — upload + index
- `GET /documents` — list. Optional `?search=` (smart: ILIKE on filename/category/subtags/summary for short queries, semantic FAISS for long), `?collection=`, `?limit=` (max 200), `?offset=`
- `GET /documents/taxonomy` — taxonomy categories + user collection counts (replaces the legacy `/documents/collections`)
- `GET /documents/{id}/download` — original file
- `GET /documents/{id}/chunks` — chunks with bbox + page + summary metadata
- `GET /documents/{id}/graph` — chunk-level graph for one doc
- `GET /documents/{id}/mindmap` — LLM-derived concept tree (recursive, up to 4 levels)
- `PATCH /documents/{id}` — update primary_category, subtags, or collections
- `POST /documents/{id}/reclassify` — re-run AI classification
- `POST /documents/backfill-metadata` — bulk classification backfill (`{items: [{doc_id, primary_category?, subtags?}], dry_run?}`); writes registry + chunk metadata with a single vector-store persist
- `POST /documents/collections/save` — save a multi-select collection by name
- `DELETE /documents/{id}`

> **How `collection` filtering resolves:** a document belongs to a collection via the
> `document_collections` junction table — populated by the `?collections=` upload
> parameter, `PATCH /documents/{id}`, or `POST /documents/collections/save`. The
> `collection` parameter on `/query` and `/search` resolves **only** against that
> table; `primary_category`/classification is a separate axis and is never consulted
> for collection scoping.

### Query
- `POST /query` — non-streaming, returns full response with sources + telemetry (`chunks_included`, `chunks_available`, `context_used_tokens`, `confidence_tier`, etc.)
- `POST /query/stream` — same but SSE: `sources` → `tokens` → `done`
- `POST /query/chunk-context` — ask about a specific source chunk
- `POST /query/ask-ai` / `POST /query/ask-ai/stream` — pure LLM, no retrieval
- `POST /search` — retrieve-only: ranked corpus chunks (full text), **no LLM answer**, no web fallback. For MCP / agent consumers that reason over raw results themselves. Body: `query`, optional `top_k` / `doc_ids` / `collection` / `subtags`. Returns `results` (deanonymized `SourceChunk[]`) + `confidence_tier` + `total_available` + `query_types`.

Common request body fields:
```json
{
  "question": "What is this about?",
  "doc_ids": ["abc123", "def456"],
  "collection": "legal-compliance",
  "subtags": ["matter:acme-v-globex", "stage:discovery"],
  "primary_category": "research-scientific",
  "session_id": "session-123",
  "top_k": 10,
  "force_web_search": false
}
```

#### Scoping a query

`collection`, `subtags` and `doc_ids` all narrow which documents a query may draw on, and
they intersect: `collection` AND every value in `subtags` AND `doc_ids`. `subtags` matches
as a **case-insensitive substring** of a document's stored tags, so `matter:acme` selects
`matter:acme-v-globex` — and, since there is no boundary check, a short value like `acme`
will also match anything else containing it. Prefix your tags (`matter:`, `stage:`) and
pass them in full to keep a filter precise.

**A scope that resolves to zero documents returns zero results.** A collection that does
not exist, a subtag nothing carries, an AND whose intersection is empty, or a list of
doc_ids that were since deleted all produce an empty answer — not a corpus-wide one.
That distinction matters most on corpora where documents belong to different clients or
matters: "nothing matched" and "here is someone else's document" are different answers,
and before #4 the API returned the second one silently.

`doc_ids: []` means "no documents", not "no filter". Omit the field to leave the query
unscoped.

### Graph
- `GET /graph/documents` — corpus-level graph: doc nodes + aggregated cross-doc similarity edges (with `supporting_pairs` + `mean_score`)
- `GET /graph/nodes?doc_id=...` — chunk-level graph for one doc
- `GET /graph/nodes-multi?doc_ids=A,B,C&edge_types=&include_intra_doc=` — chunk-level graph across N docs (max 10) in one round-trip; powers the multi-doc Chunk view
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

## Limitations & costs

Honesty up front before you deploy this anywhere.

### Costs (you will burn LLM credits)

- **OpenAI key is required** — embeddings always go through OpenAI even if `LLM_PROVIDER=openrouter`.
- **Per-chunk summaries are on by default** (`SUMMARY_ENABLED=true`). Uploading a 20-page PDF produces ~40-80 `gpt-4o-mini` summary calls plus embedding calls. Building a 20-doc corpus typically costs **$0.10-$0.50**.
- **Each query** costs roughly **$0.01-$0.05** depending on context length and whether the router fires.
- The credibility benchmark (`scripts/test_dev_credibility.py`) makes ~14 query calls + ~42 LLM-judge calls per run — budget ~$0.10 per benchmark run.

If you want to keep costs minimal during exploration: set `SUMMARY_ENABLED=false`, lower `RETRIEVAL_TOP_K`, and disable the router with `ROUTER_ENABLED=false`.

### Hardware

- **Docling models are ~2 GB** and download on first PDF upload. The `docling_cache` volume in the prod compose persists them; subsequent boots are fast.
- **FAISS is in-process** — the index lives in the backend's memory and persists to a local file. Implication: you cannot horizontally scale the backend, and large corpora (>10k chunks) will slow startup. Switch to `VECTOR_STORE=chroma` for production.
- **No GPU required.** All LLM + embedding work happens via OpenAI's API. The cross-encoder re-ranker (`RERANK_PROVIDER=cross-encoder`) runs on CPU; expect ~200ms latency per query.

### Security

- **No authentication.** The default deployment is single-user. The `X-User-Id` header is advisory — it scopes data per user but does not prevent anyone from impersonating another user. **Do not expose ports 5173 / 8000 publicly without putting an auth proxy in front.**
- **No rate limiting.** A misbehaving client can drain your OpenAI key. Add a reverse-proxy-level rate limit if the backend is reachable from untrusted networks.
- The default Postgres password in `docker-compose.yml` is `postgres` (dev only). The prod compose uses `${POSTGRES_PASSWORD}` from `.env` — set a strong one.

### Scope

- **Single-process, single-machine** by design today. There's no Celery / arq queue running by default (`TASK_BACKEND=background` uses FastAPI's in-process queue).
- **English + 中文 UI** only. Adding a third locale is straightforward (`frontend/src/i18n/locales/`) but not done.
- **No mobile-first UI.** Layouts target desktop / wide tablet.

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

PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide. TL;DR: fork → branch → run the offline test suite → open a PR. For anything bigger than a typo, please open an issue first so we can align on direction.

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
