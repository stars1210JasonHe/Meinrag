# MEINRAG HTTP API

Reference for external integrators — agents, MCP servers, scripts, browser clients. Pairs with [`README.md`](README.md) (project overview) and [`.env.example`](.env.example) (server-side configuration).

> **Stability**: the endpoints below are the ones live on `main`. Anything not listed here is implementation detail and may change without notice.

---

## Base URL + auth

| | |
|---|---|
| **Default base URL** | `http://localhost:8000` (dev). In production, set behind your reverse proxy. |
| **Auth model** | Single header — `X-User-Id: <user_id>`. There is **no token-based auth yet**. The header is trusted. Do not expose this server to untrusted callers without putting real auth in front of it (see "Security notes" at the bottom). |
| **User auto-create** | First request with a new `X-User-Id` creates the user record. The header value is the stable user identifier; pick one and stick with it for an integration. |
| **Content type** | All POST / PATCH bodies are `application/json`. Upload uses `multipart/form-data`. |
| **Errors** | Standard FastAPI error model — `{"detail": "<message>"}` with HTTP 4xx/5xx. Validation errors return 422 with the field-level error list. |

---

## Endpoint reference

### Health

```
GET  /health
GET  /health/deep
```

`/health` is a quick liveness check. `/health/deep` exercises DB, vector store, and LLM connectivity. Use the deep check for canary monitoring; the shallow one for load-balancer health probes.

```bash
curl -s http://localhost:8000/health
# {"status":"ok","llm_provider":"openai","vector_store":"faiss","document_count":16}
```

### Users

```
GET  /users
POST /users                    Body: {"user_id": str, "display_name": str?}
GET  /users/current            Header: X-User-Id
```

`GET /users/current` is the canonical "who am I" check — useful for an agent to confirm its `X-User-Id` is valid before doing anything else.

### Documents — listing + smart search

```
GET  /documents
       ?search=<str>         smart dispatch (see below)
       ?collection=<name>    restrict to one user-curated collection
       ?limit=<int>          1..200, default 50
       ?offset=<int>         default 0
```

**Search dispatch:**

| Query length | Path | What it matches |
|---|---|---|
| empty | full list | paginated by uploaded_at DESC |
| ≤ 3 words / ≤ 20 chars | SQL ILIKE | filename + primary_category + subtags + summary |
| 4+ words / 21+ chars | semantic | embeds the query, FAISS-searches the chunk-summary index, aggregates hits by `doc_id`, ranks by mean chunk score with hit-count tiebreaker |

If semantic returns zero hits, the endpoint silently falls through to ILIKE — you always get an answer.

```bash
# Short query: ILIKE on metadata fields
curl -s "http://localhost:8000/documents?search=section230" \
     -H "X-User-Id: alice"

# Long query: semantic over chunk summaries
curl -s "http://localhost:8000/documents?search=$(python -c \
  'import urllib.parse; print(urllib.parse.quote("magic numbers in oxygen isotopes"))')" \
     -H "X-User-Id: alice"
```

Response shape:
```json
{
  "documents": [
    {
      "doc_id": "abc123def456",
      "filename": "paper.pdf",
      "file_type": ".pdf",
      "chunk_count": 47,
      "primary_category": "research-scientific",
      "subtags": ["nuclear-physics"],
      "collections": [],
      "user_id": "alice",
      "uploaded_at": "2026-05-04T12:00:00+00:00"
    }
  ],
  "total": 17
}
```

### Documents — taxonomy + corpus stats

```
GET  /documents/taxonomy
GET  /documents/stats
```

`/documents/taxonomy` returns the 3-layer structure:
```json
{
  "primary_categories": ["legal-compliance", "research-scientific", "technical-engineering", "education-research"],
  "domain_options": {
    "research-scientific": ["nuclear-physics", "machine-learning", ...]
  },
  "user_collections": ["my-saved-set-1", ...]
}
```

`/documents/stats` — agent-friendly corpus snapshot (doc count, chunk count, edges):
```json
{ "documents": 16, "chunks": 1847, "edges": 2103, "collections": 0 }
```

### Documents — single-doc operations

```
POST   /documents/upload                     multipart: file + ?collections=&auto_suggest=
GET    /documents/{doc_id}/download          original file bytes
GET    /documents/{doc_id}/chunks?page=N     parsed chunks + bbox + summary metadata
GET    /documents/{doc_id}/graph             chunk-level force graph for one doc
GET    /documents/{doc_id}/mindmap           recursive concept tree (cached)
GET    /documents/{doc_id}/info              doc metadata
GET    /documents/{doc_id}/status            ingest state (uploading/parsing/ready/error)
PATCH  /documents/{doc_id}                   update primary_category / subtags / collections
POST   /documents/{doc_id}/reclassify        re-run AI classification
DELETE /documents/{doc_id}
POST   /documents/collections/save           save a multi-doc selection as a named collection
```

#### Upload example

```bash
curl -s -X POST "http://localhost:8000/documents/upload?auto_suggest=true" \
     -H "X-User-Id: alice" \
     -F "file=@./my_paper.pdf"
```

Response:
```json
{
  "doc_id": "9f8e7d6c5b4a",
  "filename": "my_paper.pdf",
  "chunk_count": 23,
  "primary_category": "research-scientific",
  "subtags": ["nuclear-physics"],
  "collections": [],
  "suggested_collections": null,
  "user_id": "alice",
  "message": "Document uploaded and indexed successfully. Classified as research-scientific"
}
```

Ingest is **synchronous up through chunking + embedding** (the response above arrives only when the doc is queryable). Figure extraction and per-chunk LLM summaries run in the background — the doc is searchable immediately, summaries become available within ~30-60 s for a 20-page paper.

#### Patch a doc's classification

```bash
curl -s -X PATCH "http://localhost:8000/documents/9f8e7d6c5b4a" \
     -H "X-User-Id: alice" \
     -H "Content-Type: application/json" \
     -d '{
           "primary_category": "education-research",
           "subtags": ["pedagogy"],
           "collections": ["my-curated-readings"]
         }'
```

Any field omitted is left unchanged on the server. `null` explicitly clears.

### Query — the main RAG endpoint

```
POST /query                non-streaming, full response with citations + telemetry
POST /query/stream         SSE: sources → tokens → done
POST /query/chunk-context  ask about a specific source chunk
POST /query/ask-ai         pure LLM, no retrieval
POST /query/ask-ai/stream  SSE for ask-ai
```

#### Request body (shared by `/query` and `/query/stream`)

```json
{
  "question": "What does Section 230 immunize?",
  "doc_ids": ["abc123", "def456"],
  "collection": "legal-compliance",
  "primary_category": "research-scientific",
  "session_id": "sess-uuid-1234",
  "top_k": 10,
  "force_web_search": false
}
```

| Field | Required | Meaning |
|---|---|---|
| `question` | yes | 1..2000 chars |
| `doc_ids` | no | restrict retrieval to this set |
| `collection` | no | restrict to a user-curated collection |
| `primary_category` | no | restrict to docs in one taxonomy primary |
| `session_id` | no | enables chat history; create a UUID per conversation thread, reuse it for follow-ups |
| `top_k` | no | 1..20, default 10 |
| `force_web_search` | no | bypasses corpus retrieval, hits DuckDuckGo |

#### Non-streaming response (`/query`)

```json
{
  "question": "...",
  "answer": "Section 230 of the Communications Decency Act immunizes... [1][2]",
  "sources": [
    {
      "doc_id": "...",
      "source_file": "crs_R46751_section230.pdf",
      "chunk_index": 12,
      "content": "...",
      "score": 0.87,
      "page": 4,
      "bbox": [0.12, 0.34, 0.56, 0.78]
    }
  ],
  "session_id": "sess-uuid-1234",
  "confidence_tier": "high",
  "chunks_included": 8,
  "chunks_available": 47,
  "context_used_tokens": 6234,
  "context_budget_tokens": 12000,
  "context_mode": "chunks",
  "web_search_used": false,
  "query_types": ["fact"],
  "fast_path": false
}
```

#### Streaming response (`/query/stream`)

Standard SSE — `Content-Type: text/event-stream`. Events arrive in order:

```
event: sources
data: {"sources": [...], "session_id": "...", "query_types": [...], "confidence_tier": "high", "chunks_included": 8, ...}

event: token
data: {"text": "Section "}

event: token
data: {"text": "230 "}

...

event: done
data: {}
```

**Agent integration tips:**
- Render `sources` event first — that lets you show the citation chips before the answer text fills in.
- The token `text` field is **already escaped for safe rendering** (no special encoding needed).
- An `error` event shape: `event: error\ndata: {"message": "..."}` — handle it as a terminal event.

```python
# Python streaming example using httpx
import httpx, json

with httpx.stream(
    "POST",
    "http://localhost:8000/query/stream",
    headers={"X-User-Id": "alice", "Content-Type": "application/json"},
    json={"question": "What does Section 230 immunize?", "top_k": 10},
    timeout=60.0,
) as resp:
    event = None
    for line in resp.iter_lines():
        if not line:
            continue
        if line.startswith("event:"):
            event = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            payload = json.loads(line.split(":", 1)[1])
            if event == "sources":
                print("sources:", [s["source_file"] for s in payload["sources"]])
            elif event == "token":
                print(payload["text"], end="", flush=True)
            elif event == "done":
                print("\n[done]")
                break
            elif event == "error":
                print("\n[error]:", payload["message"])
                break
```

### Sessions

```
GET    /sessions                        list user sessions
GET    /sessions/{session_id}/messages  full conversation history
DELETE /sessions/{session_id}
```

Sessions are persistent (Postgres-backed). To continue a conversation, reuse the `session_id` from a prior `/query` response.

### Graph

```
GET /graph/documents                                doc-level graph (corpus overview)
GET /graph/nodes?doc_id=&edge_types=                chunk-level graph for one doc
GET /graph/neighbors?doc_id=&chunk_index=&hops=     neighbourhood subgraph
```

`/graph/documents` returns aggregated cross-doc edges:
```json
{
  "nodes": [{"doc_id": "...", "label": "paper.pdf", "node_type": "document", ...}],
  "edges": [
    {
      "source_doc_id": "abc",
      "target_doc_id": "def",
      "relation": "similar_to",
      "score": 0.82,            // alias of mean_score
      "supporting_pairs": 3,    // chunk pairs supporting this doc-pair edge
      "mean_score": 0.82
    }
  ]
}
```

Use `supporting_pairs + mean_score` for visual weight (thickness × opacity) when rendering the graph. The thresholds gating which doc-pairs become edges are controlled server-side by `GRAPH_SIMILAR_MIN_SCORE` (default 0.7) and `GRAPH_SIMILAR_MIN_PAIRS` (default 2) — see [`.env.example`](.env.example).

---

## Pagination

Endpoints that can return large lists accept `limit` and `offset`:

```
GET /documents?limit=50&offset=0
GET /documents?search=foo&limit=20&offset=40
```

`limit` is clamped to `[1, 200]` server-side. If you need every doc, paginate — don't try to ask for `limit=10000`.

---

## Error model

```json
HTTP 422
{
  "detail": [
    {
      "type": "string_too_long",
      "loc": ["body", "question"],
      "msg": "String should have at most 2000 characters",
      "input": "..."
    }
  ]
}
```

Common cases:

| Status | Meaning |
|---|---|
| 400 | Bad request (e.g. invalid collection name) |
| 404 | Doc / session not found, or hidden by user-isolation |
| 422 | Validation error — see `detail` array |
| 500 | Server error — check server logs |

---

## Best practices for agents and MCP servers

1. **Pick a stable `X-User-Id`** for your agent and reuse it. The corpus, sessions, and chat history are scoped per user.

2. **Use `?search=` for retrieval, `/query` for answers.** A common mistake is over-querying `/query` to find docs by name — that burns LLM tokens. Use `GET /documents?search=` to *find* docs (zero LLM cost on the short-query path) and `/query` only when you actually need an answer.

3. **Use semantic search for the long-tail.** When the user asks "find the doc about magic numbers in oxygen-24," put the whole phrase in `?search=`. The server detects long-query and routes to the semantic FAISS path automatically.

4. **Reuse `session_id` across follow-ups.** If your agent is having a conversation, generate a UUID once per conversation and pass it on every `/query` call. The server pulls in chat history automatically. Don't pass it for one-shot lookups.

5. **Stream when latency matters.** `/query/stream` returns the first source-list event in <1 s typically. The user sees citations before the answer text starts streaming.

6. **Honor `confidence_tier`.** When it's `low` or `moderate`, surface that to the user — the system isn't fully sure. When it's the literal text *"The provided documents do not contain information about this topic."* the corpus genuinely doesn't cover the question; consider fall-through to `/query/ask-ai` (pure LLM) or `force_web_search: true`.

7. **Don't poll `/documents/{id}/status`.** Ingest is synchronous up to "queryable." If the upload returned 200, the doc is searchable. Status is only useful for tracking background figure-extraction + summary completion — and even those rarely fail.

8. **Idempotent retries**: `POST /documents/upload` deduplicates by file hash — re-uploading the same bytes returns the existing doc_id. `PATCH /documents/{id}` is naturally idempotent. `POST /query` is **not** idempotent (it spawns a session if none provided), so don't auto-retry on 5xx without backoff.

9. **Mind the `total` field on listings.** Search returns `total` = absolute count of matching docs. Use it to drive client-side pagination, but don't rely on it for "is there more" — instead check `len(documents) == limit` to decide whether to fetch the next page.

10. **Bbox provenance is intact.** Every `source` chunk in a `/query` response carries `page` and `bbox`. If you're rendering a PDF in your agent's UI, you can highlight the exact rectangle the answer drew from. This is a real product differentiator — use it.

---

## Example: minimal end-to-end agent integration

```python
"""Smallest possible agent loop against MEINRAG."""
import httpx
import uuid

BASE = "http://localhost:8000"
USER = "my-agent"
SESSION = str(uuid.uuid4())

def search_docs(query: str, limit: int = 10) -> list[dict]:
    r = httpx.get(f"{BASE}/documents",
                  params={"search": query, "limit": limit},
                  headers={"X-User-Id": USER})
    r.raise_for_status()
    return r.json()["documents"]

def ask(question: str, doc_ids: list[str] | None = None) -> dict:
    r = httpx.post(f"{BASE}/query",
                   headers={"X-User-Id": USER, "Content-Type": "application/json"},
                   json={
                       "question": question,
                       "doc_ids": doc_ids,
                       "session_id": SESSION,
                       "top_k": 10,
                   },
                   timeout=120.0)
    r.raise_for_status()
    return r.json()

# 1. Find candidate docs
docs = search_docs("nuclear shell model")
print(f"Found {len(docs)} candidate docs")

# 2. Ask scoped to those docs
answer = ask(
    "What computational approaches are used for shell-model calculations?",
    doc_ids=[d["doc_id"] for d in docs[:5]],
)

# 3. Use the answer + show citations
print(f"\nAnswer: {answer['answer']}\n")
print(f"Confidence: {answer['confidence_tier']}")
print("Sources:")
for s in answer["sources"]:
    print(f"  - {s['source_file']} chunk {s['chunk_index']} @ score {s['score']:.2f}")
```

---

## MCP integration notes

If you're wrapping MEINRAG as an MCP server (so an LLM agent can use it as a tool):

- **Tool: `meinrag.search`** — `(query: str, limit: int = 10) → list[doc]`. Wraps `GET /documents?search=`. Cheap, no LLM cost.
- **Tool: `meinrag.ask`** — `(question: str, doc_ids: list[str] | None) → answer + sources`. Wraps `POST /query`. Always returns sources; the agent should *render those* alongside the answer text rather than just showing the answer.
- **Tool: `meinrag.fetch_chunks`** — `(doc_id: str, page: int | None) → list[chunk]`. Wraps `GET /documents/{doc_id}/chunks`. Useful for re-grounding when the agent wants to verify a specific claim.
- **Tool: `meinrag.list_taxonomy`** — `() → taxonomy`. Wraps `GET /documents/taxonomy`. Lets the agent suggest scope filters.

Don't expose `/documents/upload`, `PATCH /documents/{id}`, or `DELETE /documents/{id}` to general agents — those should be operator-gated.

Tool descriptions should mention that **citation chunks carry `bbox` + `page`** so the calling agent can show exact PDF excerpts rather than re-quoting from the answer text.

---

## Security notes (read this if you're putting MEINRAG on the public internet)

- **No auth today.** `X-User-Id` is trusted. Put a real auth proxy (oauth2-proxy, Cloudflare Access, etc.) in front before exposing.
- **No rate limits in-app.** Apply at the proxy layer.
- **CORS** is permissive in dev. Configure `ALLOWED_ORIGINS` in `.env` for production deployments.
- **Uploads are accepted from any authenticated user.** A malicious doc with prompt-injection content can't directly compromise the server, but it CAN poison your retrieval index. Operate uploads on trust until something better lands.
- **API keys live in `.env`.** Never commit. The `.gitignore` already protects `.env`, but double-check before pushing.

If you find a security issue, please report it privately via GitHub Issues with a "[security]" prefix rather than opening a public PR.
