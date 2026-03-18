# Feature Research: GraphRAG, Dedicated Reranker, In-Browser PDF Viewer

**Date**: 2026-03-18
**Status**: Research complete, pending decision
**Related**: `docs/rag-landscape-research-guide.md`, `data/rag-landscape-report_2026-03-18.pdf`

---

## Table of Contents

1. [GraphRAG — Deep Dive](#1-graphrag--deep-dive)
2. [Dedicated Reranker — Implementation Plan](#2-dedicated-reranker--implementation-plan)
3. [In-Browser PDF Viewer — Implementation Plan](#3-in-browser-pdf-viewer--implementation-plan)
4. [Priority & Recommendation](#4-priority--recommendation)

---

## 1. GraphRAG — Deep Dive

### 1.1 What Is GraphRAG?

Standard RAG: `chunk text → embed → find similar chunks → answer`

GraphRAG adds a knowledge graph layer between documents and retrieval:

```
Documents
    ↓  LLM extracts entities + relationships (expensive)
Knowledge Graph:  [Entity A] --relationship--> [Entity B]
    ↓  Leiden algorithm groups entities into communities
Community Summaries (LLM-generated)
    ↓
Query → traverse graph + retrieve connected context → answer
```

**Key difference**: Vector RAG retrieves chunks similar to the query. GraphRAG retrieves *connected context* — it knows Entity A relates to Entity B through Relationship X, enabling multi-hop reasoning across documents.

### 1.2 Three Main Implementations

#### Microsoft GraphRAG (the original)

- **Paper**: "From Local to Global: A Graph RAG Approach to Query-Focused Summarization" (arXiv 2404.16130)
- **Repo**: `microsoft/graphrag`
- **Indexing pipeline** (6 phases):
  1. Split documents into ~1200-token chunks
  2. Link documents to chunks for provenance
  3. **Entity & relationship extraction** — 1 LLM call per chunk (the expensive part)
  4. **Community detection** — Hierarchical Leiden algorithm (no LLM, pure graph math)
  5. **Community summarization** — 1 LLM call per community
  6. **Embedding** — vector embeddings for chunks, entities, and summaries
- **Query modes**:
  - **Local search**: find entities in query → fan out to neighbors → gather text → answer (~$0.01/query)
  - **Global search**: map-reduce over all community summaries → synthesize (N+1 LLM calls, expensive)
  - **DRIFT search**: starts global, drills into local
- **Limitation**: requires full rebuild when new documents are added

#### NanoGraphRAG (lightweight reimplementation)

- **Repo**: `gusye1234/nano-graphrag`
- ~1,100 lines of Python, simplified Microsoft GraphRAG
- **Storage**: NetworkX (default, in-memory), Neo4j; FAISS, Milvus for vectors
- Uses top-K important communities instead of map-reduce over ALL communities (much cheaper)
- Supports incremental inserts but must recompute community reports
- Query modes: local, global, and "naive" (standard vector search fallback)

#### LightRAG (the practical choice)

- **Repo**: `HKUDS/LightRAG` (~29.6K stars)
- **Paper**: EMNLP 2025
- **Key differences from Microsoft GraphRAG**:
  - No community detection / Leiden algorithm — skips the expensive hierarchy
  - Dual-level retrieval: combines vector search + graph traversal
  - Indexes entities AND relationships as first-class searchable objects
  - Incremental updates (~50% faster than rebuild)
  - Claims ~6,000x fewer tokens per query vs Microsoft GraphRAG
- **Storage backends** (very flexible):
  - KV: JSON (default), PostgreSQL, Redis, MongoDB
  - Vector: NanoVectorDB (default), pgvector, FAISS, Chroma, Qdrant
  - Graph: NetworkX (default), Neo4j, PostgreSQL
- **Best fit for MEINRAG**: supports FAISS + SQLite, incremental updates, cheapest option

### 1.3 When GraphRAG Actually Helps

| Query Type | Standard RAG | GraphRAG | Winner |
|-----------|-------------|----------|--------|
| Single-doc factual ("What is X?") | 94% | 95% | RAG (not worth the cost) |
| Cross-doc relationships ("How does A relate to B?") | 34% | **91%** | **GraphRAG** |
| Global themes ("What are the main topics?") | Poor | Good | **GraphRAG** |
| Multi-hop reasoning | 68% F1 | **65% F1** (HotpotQA) | Mixed |
| Summarization | **86% BERTScore** | Lower | RAG |

**Key benchmark** (arXiv 2502.11371, Feb 2025): The best approach is routing — send factual queries to RAG, reasoning queries to GraphRAG (1.1-6.4% improvement).

### 1.4 Cost Analysis

GraphRAG indexing requires LLM calls per chunk, not just embedding:

| Corpus Size | Standard RAG (embedding only) | GraphRAG (GPT-4o-mini) | Cost Multiplier |
|------------|-------------------------------|------------------------|-----------------|
| 55K words (1 paper) | $0.006 | $0.06 | 10x |
| 45K words tech docs | $0.006 | $0.06 – $0.50 | 10-80x |
| 1M tokens (large corpus) | $0.01 | $8 – $30 | 800-3000x |

**With GPT-4-Turbo**: multiply by another 25x. The Wizard of Oz (~55K words) costs $3.29.

### 1.5 Real-World Limitations

1. **~35% of needed entities are missed** during extraction — fundamental accuracy ceiling
2. **LLM hallucinations become permanent graph nodes** — served as "facts" during retrieval
3. **Entity disambiguation is hard** — "MSFT" vs "Microsoft" vs "the Redmond company" get separate nodes
4. **Knowledge conflicts are unresolved** — contradictory relationships from different sources coexist
5. **Domain-specific terminology often missed** by generic extraction prompts
6. **Path explosion** in dense, interconnected domains can exceed 300ms for multi-hop queries
7. **Microsoft GraphRAG requires full rebuild** when new documents added (LightRAG handles incrementally)

### 1.6 Infrastructure Requirements

**Minimum (development):**
- No graph database needed — NetworkX (in-memory, serialized to disk) works fine
- Any vector store (FAISS works)
- File-based KV storage
- An LLM API key

**Production (large corpus):**
- Graph database recommended: Neo4j, PostgreSQL + Apache AGE
- Proper vector database: pgvector, Qdrant, FAISS
- NetworkX hits memory limits at tens of millions of nodes

### 1.7 Assessment for MEINRAG

| Factor | Assessment |
|--------|-----------|
| Technical feasibility | LightRAG is the best fit (FAISS + SQLite support, incremental updates) |
| Cost | Every upload becomes expensive — need user confirmation before indexing |
| Value for current use case | **Low** for single-doc Q&A (our primary use). **High** for cross-doc queries |
| Effort | Hard — new subsystem, entity extraction pipeline, graph storage |
| Recommendation | **Park as P2.** Hybrid search + reranking + reference demotion covers 90% of queries |

**If we pursue it later**: `pip install lightrag-hku`, start with NetworkX + FAISS (both already in our stack), add `GRAPHRAG_ENABLED=false` config flag.

---

## 2. Dedicated Reranker — Implementation Plan

### 2.1 Current State

**File**: `app/rag/chain.py` (lines 118-136)

- Uses `LLMListwiseRerank` — sends all candidate chunks to gpt-4o-mini, asks it to sort by relevance
- **Bug**: The imports (`from langchain.retrievers...`) are broken in langchain 1.2.9. Code only works because `rerank_enabled = False` (lazy imports never execute)
- Config: `rerank_enabled: bool = False`, `rerank_top_n: int = 4`
- No way to choose which reranker to use — hardcoded to LLM-based

### 2.2 Available Options

| Option | Latency | Cost | Quality | VRAM | Install |
|--------|---------|------|---------|------|---------|
| **FlashRank** (local, CPU) | 5-20ms | $0 | Good | 0 | `pip install flashrank` (34MB model) |
| **Cross-encoder BGE** (local, CUDA) | 30-80ms | $0 | **Best** | 1.1GB | `pip install sentence-transformers` |
| **Jina Reranker** (API) | 100-300ms | Free 10M tokens | Great | 0 | Already in langchain_community |
| **Cohere Rerank** (API) | 100-300ms | ~$0.002/query | Great | 0 | `pip install langchain-cohere` |
| **LLM-based** (current) | 500-2000ms | ~$0.0006/query | OK | 0 | Already installed (broken imports) |

#### FlashRank Details (recommended first step)

- Zero API cost, zero GPU usage, CPU-only
- Models available:

| Model | Size | Notes |
|-------|------|-------|
| `ms-marco-TinyBERT-L-2-v2` | ~4 MB | Fastest, lowest quality |
| `ms-marco-MiniLM-L-12-v2` | ~34 MB | Best quality in FlashRank |
| `ms-marco-MultiBERT-L-12` | ~150 MB | Multilingual (100+ languages) |

- Works on Windows, pure Python with ONNX runtime
- LangChain class: `FlashrankRerank` in `langchain_community`

#### Cross-Encoder Details (recommended upgrade)

- Uses `sentence-transformers` (already compatible with our torch 2.6.0+cu124)
- Models and VRAM on RTX 3060 12GB:

| Model | Params | VRAM (FP16) | Quality |
|-------|--------|-------------|---------|
| `cross-encoder/ms-marco-MiniLM-L-6-v2` | 22.7M | ~50 MB | Good |
| `cross-encoder/ms-marco-MiniLM-L-12-v2` | 33.4M | ~70 MB | Better |
| `BAAI/bge-reranker-base` | 278M | ~560 MB | Strong multilingual |
| `BAAI/bge-reranker-v2-m3` | 568M | ~1.1 GB | **Best multilingual** |

- All fit easily on 12GB VRAM (alongside docling if needed)
- Max sequence length: 512 tokens — fine for ~1000-char chunks

#### Jina Reranker Details (API alternative)

- Already in `langchain_community` — no extra pip install
- 10M free tokens per API key
- Models: `jina-reranker-v2-base-multilingual` (100+ languages)
- Rate limit: 100 RPM free, 500 RPM paid

### 2.3 Implementation

#### Config Changes (`app/config.py`)

```python
# Add to Settings:
rerank_provider: str = "flashrank"  # "flashrank", "cross-encoder", "jina", "cohere", "llm"
rerank_model: str = ""              # empty = auto-select default per provider
```

#### Factory Function (`app/rag/chain.py`)

All rerankers implement `BaseDocumentCompressor` and work with `ContextualCompressionRetriever`:

```python
def _get_reranker(settings, llm=None) -> BaseDocumentCompressor:
    provider = settings.rerank_provider
    top_n = settings.rerank_top_n

    if provider == "flashrank":
        from langchain_community.document_compressors.flashrank_rerank import FlashrankRerank
        model = settings.rerank_model or "ms-marco-MiniLM-L-12-v2"
        return FlashrankRerank(model=model, top_n=top_n)

    elif provider == "cross-encoder":
        from langchain_community.cross_encoders import HuggingFaceCrossEncoder
        from langchain.retrievers.document_compressors import CrossEncoderReranker
        model_name = settings.rerank_model or "BAAI/bge-reranker-v2-m3"
        model = HuggingFaceCrossEncoder(model_name=model_name)
        return CrossEncoderReranker(model=model, top_n=top_n)

    elif provider == "jina":
        from langchain_community.document_compressors.jina_rerank import JinaRerank
        model = settings.rerank_model or "jina-reranker-v2-base-multilingual"
        return JinaRerank(model=model, top_n=top_n)

    elif provider == "cohere":
        from langchain_cohere import CohereRerank
        model = settings.rerank_model or "rerank-english-v3.0"
        return CohereRerank(model=model, top_n=top_n)

    elif provider == "llm":
        from langchain.retrievers.document_compressors import LLMListwiseRerank
        return LLMListwiseRerank.from_llm(llm, top_n=top_n)

    else:
        raise ValueError(f"Unknown rerank_provider: {provider}")
```

#### Integration Point

In `build_rag_chain()`, replace the current `LLMListwiseRerank` block with:

```python
if settings.rerank_enabled:
    compressor = _get_reranker(settings, llm)
    retriever = ContextualCompressionRetriever(
        base_compressor=compressor,
        base_retriever=retriever,
    )
```

#### Dependencies

```toml
# pyproject.toml — add to [project.optional-dependencies]
rerank = ["flashrank>=0.2", "sentence-transformers>=3.0"]
```

Or just add `flashrank` to main dependencies (it's tiny, no heavy deps).

### 2.4 Recommended Rollout

1. **Fix broken imports first** — change `langchain.retrievers` to `langchain_classic.retrievers`
2. **Add FlashRank** — zero cost, instant speed win, tiny dependency
3. **Add config options** — `rerank_provider`, `rerank_model`
4. **Test**: compare FlashRank vs LLM-based vs no reranking on same queries
5. **Later**: add cross-encoder option for users with GPU who want best quality

---

## 3. In-Browser PDF Viewer — Implementation Plan

### 3.1 Current State (already 80% built)

| Component | Status | Location |
|-----------|--------|----------|
| Backend `page-highlight` endpoint | **Done** | `documents.py:204-284` — renders page as PNG with bbox (red rect) + text (yellow highlight) |
| Chunk metadata (page, bbox, doc_id) | **Done** | `SourceChunk` schema in `schemas.py:62-73` |
| Frontend `ContentLightbox` | **Done** | Zoom 1-8x, pan, keyboard nav, "Content" vs "PDF Page" toggle |
| "PDF" button on source citations | **Done** | `SourceCitation` component with `<FileText> PDF` button |
| Image caching | **Done** | `Cache-Control: public, max-age=86400` |

#### Existing Data Flow

```
User asks question
    → /query/stream returns SourceChunk[] with { doc_id, page, bbox, content, chunk_type }
    → MessageBubble renders SourceCitation for each chunk
    → User clicks "PDF" button
    → ContentLightbox opens, builds URL:
        /documents/{doc_id}/page-highlight?page=3&bbox=100,200,300,400
    → Backend renders PDF page 3 with red rectangle at bbox
    → Frontend displays as zoomable/pannable image
```

### 3.2 What's Missing

#### A. Multi-Page Navigation (Easy, High Impact)

Currently only shows the single cited page. User can't browse to adjacent pages.

**Backend changes:**
- Add `GET /documents/{doc_id}/info` → returns `{ total_pages, filename, file_size }`
- Use `fitz.open()` to get `doc.page_count`

**Frontend changes:**
- Add prev/next page buttons to `ContentLightbox` (arrow buttons already exist for source navigation — add page-level nav)
- Display "Page 3 / 15" indicator
- Allow `page-highlight?page={n}` without bbox/text params (just renders the page, no highlight)
- Keyboard: PageUp/PageDown for page navigation (currently arrows switch between sources)

#### B. Page Thumbnail Sidebar (Medium)

Vertical strip of page thumbnails on the left side of the lightbox.

**Backend changes:**
- Add `GET /documents/{doc_id}/page-thumbnail?page={n}` — render at DPI 36 (~10KB per thumbnail)
- Or batch: `GET /documents/{doc_id}/thumbnails?pages=0-14` returning a sprite sheet

**Frontend changes:**
- Scrollable sidebar component inside `ContentLightbox`
- Lazy-load thumbnails (visible pages + 2 ahead)
- Highlight current page + all pages that have cited chunks (different border color)
- Click thumbnail to jump to that page

#### C. Multi-Bbox Highlighting Per Page (Medium)

If a query returns 3 chunks from the same page, currently requires 3 separate views.

**Backend changes:**
- Extend `page-highlight` to accept multiple bboxes:
  ```
  ?page=3&bboxes=100,200,300,400;50,100,200,150
  ```
- Or: `?page=3&chunk_indices=0,3,7` — backend looks up stored chunks and highlights all

**Frontend changes:**
- Group sources by `(doc_id, page)` before sending to lightbox
- Pass all bboxes for same page in one request
- Different colors per chunk (red, blue, green) with legend

#### D. Document Outline / Section Navigation (Optional)

Show section headings from the document for quick navigation.

- We already store `headings` metadata in docling chunks (e.g., "Introduction > Background")
- Build a sidebar tree from heading metadata
- Click heading → jump to that page

### 3.3 Implementation: Two Approaches

#### Approach A: Enhanced Server-Rendered PNGs (recommended)

Keep the current architecture. Backend renders pages as PNG images; frontend displays them.

**Pros:**
- Builds on existing working code
- Server-side highlighting is pixel-perfect
- No large JS bundle increase
- Works with any PDF (no client-side rendering issues)

**Cons:**
- No text selection in PDF
- No in-PDF search
- Network round-trip per page view

**Changes needed:**

| Change | File | Effort |
|--------|------|--------|
| Add `/documents/{doc_id}/info` endpoint | `documents.py` | Small |
| Add `/documents/{doc_id}/page-thumbnail` endpoint | `documents.py` | Small |
| Support multiple bboxes in `page-highlight` | `documents.py` | Small |
| Add page prev/next buttons | `ContentLightbox.jsx` | Small |
| Add page counter display | `ContentLightbox.jsx` | Small |
| Add thumbnail sidebar component | New `PageThumbnails.jsx` | Medium |
| Group sources by page | `MessageBubble.jsx` | Small |

#### Approach B: Client-Side PDF.js Viewer

Replace server-rendered PNGs with PDF.js rendering in the browser.

```
npm install pdfjs-dist react-pdf
```

**Pros:**
- Text selection in PDF
- In-PDF search (Ctrl+F)
- Instant page navigation (no server round-trip)
- Native annotation/highlight API
- Continuous scroll mode

**Cons:**
- ~500KB added to JS bundle
- Needs CORS headers for PDF serving from backend
- Highlight overlay logic moves to frontend (canvas layer)
- More complex implementation
- Some PDFs render differently than server-side fitz

**Changes needed:**

| Change | File | Effort |
|--------|------|--------|
| Add CORS for PDF serving | `documents.py` | Small |
| Create PDF viewer component with PDF.js | New `PdfViewer.jsx` | Large |
| Implement highlight overlay on canvas | `PdfViewer.jsx` | Large |
| Wire bbox data to canvas highlights | `PdfViewer.jsx` | Medium |
| Replace `ContentLightbox` PDF mode | `ContentLightbox.jsx` | Medium |

### 3.4 Recommended Rollout (Approach A)

**Step 1 — Page Navigation** (1-2 hours, highest impact):
- Add `/documents/{doc_id}/info` endpoint
- Add prev/next page buttons + page counter to `ContentLightbox`
- Transforms single-page view into a document browser

**Step 2 — Thumbnail Sidebar** (half day):
- Add `/documents/{doc_id}/page-thumbnail` endpoint
- Create `PageThumbnails` component
- Highlight pages with cited chunks

**Step 3 — Multi-Bbox Highlights** (half day):
- Extend `page-highlight` to accept multiple bboxes
- Group frontend sources by (doc_id, page)
- Color-code different chunks

**Step 4 — PDF.js Migration** (optional, 1-2 days):
- Only if text selection / in-PDF search becomes a user need
- Can coexist with server-rendered approach (toggle in settings)

---

## 4. Priority & Recommendation

### Effort vs Impact Matrix

```
Impact
  ▲
  │   ★ FlashRank reranker        ★ PDF page navigation
  │         (easy, high)                (easy, high)
  │
  │              ★ Thumbnail sidebar    ★ Cross-encoder reranker
  │                   (medium, high)        (medium, high)
  │
  │                        ★ Multi-bbox highlights
  │                             (medium, medium)
  │
  │                                          ★ GraphRAG (LightRAG)
  │                                              (hard, situational)
  │
  └──────────────────────────────────────────────────────► Effort
```

### Recommended Order

| # | Feature | Effort | Impact | Dependencies |
|---|---------|--------|--------|--------------|
| 1 | **FlashRank reranker** | Easy (1-2h) | High | `pip install flashrank` |
| 2 | **Fix broken reranker imports** | Trivial | Unblocks reranking | None |
| 3 | **PDF page navigation** | Easy (1-2h) | High | 1 new backend endpoint |
| 4 | **PDF thumbnail sidebar** | Medium (half day) | High | 1 new endpoint + component |
| 5 | **Multi-bbox page highlights** | Medium (half day) | Medium | Backend param change |
| 6 | **Cross-encoder reranker option** | Medium (2-3h) | High | `pip install sentence-transformers` |
| 7 | **GraphRAG (LightRAG)** | Hard (days) | Situational | `pip install lightrag-hku` |

### Decision Needed

- **Reranker**: FlashRank (free, local, instant) or Jina (API, free 10M tokens)?
- **PDF viewer**: Approach A (server-rendered, incremental) or Approach B (PDF.js, bigger rewrite)?
- **GraphRAG**: Start experimenting now, or park for later?
