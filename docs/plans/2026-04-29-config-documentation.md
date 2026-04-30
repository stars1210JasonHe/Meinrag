# Config Documentation Sprint — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Make `.env.example` a complete reference for every `Settings` field, and bring the README Configuration section up to date. Anyone cloning the repo today should be able to read one file (`.env.example`) and know what every knob does, what its default is, and when they'd change it.

**Audit performed 2026-04-29:**
- `Settings` class declares ~50 fields
- `.env.example` covers ~20
- README Configuration section has 4 stale defaults (lies):
  - `VECTOR_STORE=chroma` (real default `faiss`)
  - `MEMORY_SESSION_TTL=3600` (real default `2592000` — 30 days, fixed 2026-04-20)
  - `HYBRID_SEARCH_ENABLED=false` (real default `True`, on by default since 2026-04-21)
  - `WEB_SEARCH_SCORE_THRESHOLD=0.5` (real default `0.0`)
- README "Advanced Features" subsection still teaches users to enable hybrid search (already on)

---

## File Structure

**Modified:**
- `.env.example` — restructured + expanded to cover every `Settings` field, grouped by purpose
- `README.md` — Configuration section trimmed: brief pointer to `.env.example` + a small "What's actually default-on" call-out + advanced-tuning subsection that's accurate

**Not touching:**
- `app/config.py` — all defaults already correct, no code changes needed
- `Settings` class — same. Doc-only sprint.

---

## Layout for the new `.env.example`

Sections, in order, each with a comment header explaining when you'd change the section's variables:

```
# .env.example — Copy to .env and edit.
# Every setting from app/config.py Settings is documented here. Defaults
# shown match the code; commented-out lines = use the default.
#
# Quick start: cp .env.example .env  →  set OPENAI_API_KEY  →  done.

# ── Required ─────────────────────────────────────────────────
OPENAI_API_KEY=sk-...

# ── LLM provider ─────────────────────────────────────────────
LLM_PROVIDER=openai                    # openai | openrouter
OPENAI_MODEL=gpt-4o-mini
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
# OPENROUTER_API_KEY=...
# OPENROUTER_MODEL=openai/gpt-4o-mini
# OPENROUTER_SITE_URL=http://localhost:8000
# OPENROUTER_SITE_NAME=MEINRAG

# ── Database ─────────────────────────────────────────────────
# DATABASE_URL=sqlite+aiosqlite:///data/meinrag.db
# DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/meinrag
POSTGRES_USER=meinrag
POSTGRES_PASSWORD=CHANGE_ME
POSTGRES_DB=meinrag

# ── Vector store ─────────────────────────────────────────────
VECTOR_STORE=faiss                     # faiss | chroma

# ── Document parsing ─────────────────────────────────────────
PARSE_MODE=docling                     # default | enhanced | vision | docling
# IMAGE_DESCRIPTION_MODEL=gpt-4o-mini
# IMAGE_DESCRIPTION_MAX_TOKENS=512
# POPPLER_FIGURE_EXTRACTION=true
# Vision mode (only when PARSE_MODE=vision)
# VISION_MODEL=gpt-4o-mini
# VISION_MAX_TOKENS=4096
# VISION_PAGE_DPI=150
# Docling mode (only when PARSE_MODE=docling) — needs `uv sync --extra docling`
# DOCLING_OCR=false
# DOCLING_PICTURE_DESCRIPTION=false
# DOCLING_EQUATION_OCR=false           # pix2tex LaTeX OCR — heavy
# DOCLING_DEVICE=auto                  # auto | cpu | cuda | mps

# ── Chunking ─────────────────────────────────────────────────
CHUNK_SIZE=1000
CHUNK_OVERLAP=200

# ── Retrieval ────────────────────────────────────────────────
RETRIEVAL_TOP_K=10                     # bumped from 4 in 2026-04-22 default-on flip
QUERY_EXPANSION_ENABLED=true
QUERY_EXPANSION_SCORE_THRESHOLD=0.3
# OPEN_QUESTION_DETECTION=false
# DEDUP_THRESHOLD=0.7
# QUERY_TYPES_FILE=data/query_types.json
# SCORING_PROFILE=general

# ── Hybrid search (default-on as of 2026-04-21) ──────────────
HYBRID_SEARCH_ENABLED=true
# HYBRID_BM25_WEIGHT=0.5               # legacy ensemble; retrieval.py uses RRF
# RRF_K=60

# ── Re-rank (off by default) ─────────────────────────────────
RERANK_ENABLED=false
# RERANK_TOP_N=4
# RERANK_PROVIDER=flashrank            # flashrank | cross-encoder | jina | cohere | llm
# RERANK_MODEL=                        # empty = auto-pick per provider

# ── Router prefix (default-on as of 2026-04-22) ──────────────
# Pre-filter docs via small LLM before vector search when scope is large.
ROUTER_ENABLED=true
# ROUTER_MIN_SCOPE=15                  # below this many docs, router is skipped
# ROUTER_TOP_K=8                       # how many docs router picks
# ROUTER_MODEL=gpt-4o-mini

# ── Chunk summary (default-on as of 2026-04-19) ──────────────
SUMMARY_ENABLED=true
# SUMMARY_PROVIDER=openai
# SUMMARY_MODEL=gpt-4o-mini
# SUMMARY_MIN_CHARS=200
# SUMMARY_MAX_CHUNKS_FOR_OVERVIEW=30

# ── Graph edges ──────────────────────────────────────────────
# Min cosine similarity to keep a cross-doc similar_to edge. Affects both
# visualization AND retrieval scoring.
# GRAPH_SIMILAR_MIN_SCORE=0.6

# ── Visual proximity linking ─────────────────────────────────
# VISUAL_PROXIMITY_ENABLED=true
# VISUAL_PROXIMITY_PAGES=1

# ── Context window management ────────────────────────────────
# Effective input budget = min(MAX_CONTEXT_TOKENS or ∞, model_window × ratio)
#                          − reserved_output − reserved_overhead
# MAX_CONTEXT_TOKENS=                  # hard cap; empty = derive from model
# CONTEXT_BUDGET_RATIO=0.6
# RESERVED_OUTPUT_TOKENS=2048
# RESERVED_PROMPT_OVERHEAD_TOKENS=512
# HISTORY_MAX_BUDGET_RATIO=0.4         # chat history ≤ this fraction of input
# HISTORY_MIN_RESERVE_RATIO=0.2        # but always reserve at least this much

# ── Chat memory ──────────────────────────────────────────────
# MEMORY_MAX_MESSAGES=20
MEMORY_SESSION_TTL=2592000             # 30 days — chat history is persistent.
                                       # Pre-2026-04-20 default of 1h caused data loss.

# ── Web search fallback ──────────────────────────────────────
# Triggered on empty retrieval results or explicit force_web_search=true.
WEB_SEARCH_ENABLED=true
# WEB_SEARCH_MAX_RESULTS=9
# WEB_SEARCH_PROVIDER=duckduckgo
# WEB_SEARCH_SCORE_THRESHOLD=0.0       # 0 = disable score-based auto-fallback

# ── User system ──────────────────────────────────────────────
# DEFAULT_USER=admin
# USER_ISOLATION=all                   # all | documents | none

# ── Background tasks ─────────────────────────────────────────
TASK_BACKEND=background                # background (FastAPI) | arq (needs Redis)
# REDIS_URL=redis://localhost:6379

# ── Server ───────────────────────────────────────────────────
HOST=0.0.0.0
PORT=8000
LOG_LEVEL=info
HOST_PORT=5173                         # public port for Docker prod stack frontend
# CORS_ORIGINS=http://localhost:5173
# MAX_UPLOAD_SIZE_MB=50

# ── Paths (rarely change) ────────────────────────────────────
# UPLOAD_DIR=data/uploads
# VECTORSTORE_DIR=data/vectorstore
```

**Conventions:**
- Active line (no `#`) when the value is required OR when documenting a non-obvious default that users frequently want to verify (e.g., `RETRIEVAL_TOP_K`, `HYBRID_SEARCH_ENABLED`, `MEMORY_SESSION_TTL`).
- Commented line (`# KEY=value`) when the default is fine and rarely overridden.
- Inline comments explain WHEN to change, not what the var is (the var name should be self-explanatory).

---

## Layout for the new README Configuration section

Replace the current ~50 lines with a tighter ~25-line version:

```markdown
## Configuration

Every setting lives in `app/config.py` (`Settings` class) with defaults baked
in. Override via environment variables — see [`.env.example`](.env.example)
for every supported variable, grouped by purpose.

**What's default-on (you don't need to opt in):**

- `RETRIEVAL_TOP_K=10`
- `ROUTER_ENABLED=true` — small-LLM doc pre-filter before vector search
- `HYBRID_SEARCH_ENABLED=true` — BM25 + dense via Reciprocal Rank Fusion
- `SUMMARY_ENABLED=true` — per-chunk summaries for the compiled retrieval layer
- `QUERY_EXPANSION_ENABLED=true`
- `WEB_SEARCH_ENABLED=true` — DuckDuckGo fallback when retrieval returns empty

**Common tuning knobs:**

| Variable | Default | When to change |
|---|---|---|
| `OPENAI_MODEL` | `gpt-4o-mini` | Quality vs cost; verify with `tests/test_query_credibility.py` before committing |
| `RETRIEVAL_TOP_K` | `10` | Lower for speed; higher (≤20) for recall on long docs |
| `RERANK_ENABLED` | `false` | Turn on for ambiguous queries; uses FlashRank by default |
| `MEMORY_SESSION_TTL` | `2592000` (30 d) | Set 0 to never expire; smaller values risk data loss |
| `MAX_CONTEXT_TOKENS` | derive from model | Hard-cap context if you hit budget overruns |

For Docker prod stack setup see [Run from scratch with Docker](#run-from-scratch-with-docker-production-stack) above.
```

Keep the existing "Advanced Features" anchors but rewrite to **describe** rather than **enable** the now-default-on features, with commented-out blocks showing how to disable them.

---

## Task CD1: Rewrite `.env.example`

**Files:**
- Modify: `.env.example`

- [ ] Replace entire file with the layout above
- [ ] Verify each `key` matches the actual `Settings` field (snake_case → SCREAMING_SNAKE)
- [ ] All defaults match `app/config.py`
- [ ] No "lies" — never show `KEY=false` if real default is `true`

**Verification:**
```bash
# Every uppercase var in .env.example exists in Settings (modulo aliases)
uv run python -c "
from app.config import Settings
import re
fields = {f.upper() for f in Settings.model_fields}
with open('.env.example') as f:
    used = re.findall(r'^#? ?([A-Z_]+)=', f.read(), re.MULTILINE)
unknown = [u for u in used if u not in fields and u not in {'POSTGRES_USER', 'POSTGRES_PASSWORD', 'POSTGRES_DB', 'HOST_PORT'}]
print('unknown env vars in .env.example:', unknown)
assert not unknown, unknown
"
```

---

## Task CD2: Sync README Configuration section

**Files:**
- Modify: `README.md` (sections at line ~241 — Configuration, ~274 — Advanced Features)

- [ ] Replace Configuration section with the trimmed version above
- [ ] Update Advanced Features subsection — describe, don't teach-to-enable
- [ ] Fix the 4 stale defaults
- [ ] Add a hyperlink to `.env.example`

**Verification:**
- `grep -E "(VECTOR_STORE=chroma|MEMORY_SESSION_TTL=3600|HYBRID_SEARCH_ENABLED=false|WEB_SEARCH_SCORE_THRESHOLD=0\.5)" README.md` → no matches
- README lists all 6 default-on features

---

## Task CD3: Verify + commit

- [ ] Run the env-var audit verification command above
- [ ] `grep -c "^#" .env.example` — comments outnumber active lines (good ratio)
- [ ] Single commit: `docs(config): comprehensive .env.example + README sync with Settings defaults`
- [ ] Push

---

## Ship-readiness gate

- Every `Settings` field appears in `.env.example` (active or commented)
- No `.env.example` line shows a non-default value as if it were the default
- README Configuration section accurate; advanced features described not "how to enable"
- `data/test_queries/query_test.db` schema unaffected (this is a doc-only sprint)
- Existing `.env` files keep working (we only added vars; didn't rename)
