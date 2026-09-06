from enum import Enum
from typing import Literal
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    OPENAI = "openai"
    OPENROUTER = "openrouter"


class VectorStoreType(str, Enum):
    CHROMA = "chroma"
    FAISS = "faiss"


class ParseMode(str, Enum):
    DEFAULT = "default"
    ENHANCED = "enhanced"
    VISION = "vision"
    DOCLING = "docling"


class RerankProvider(str, Enum):
    FLASHRANK = "flashrank"
    CROSS_ENCODER = "cross-encoder"
    JINA = "jina"
    COHERE = "cohere"
    LLM = "llm"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM
    llm_provider: LLMProvider = LLMProvider.OPENAI
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    # LLM/embedding call hardening: bound every chat + embedding request so one
    # hung call can't deadlock ingest or starve /search. No timeout = OpenAI
    # client default (~600s); a 263-chunk doc = 263 sequential summary calls.
    llm_timeout: float = 60.0          # seconds per LLM/embedding HTTP request
    llm_max_retries: int = 2           # bounded retries on transient errors
    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_site_url: str = "http://localhost:8000"
    openrouter_site_name: str = "MEINRAG"

    # Vector store
    vector_store: VectorStoreType = VectorStoreType.FAISS

    # Paths
    upload_dir: Path = Path("data/uploads")
    vectorstore_dir: Path = Path("data/vectorstore")
    # Document-classification taxonomy file. Per-deployment configurable so one
    # codebase can run multiple independent libraries (e.g. a legal deployment
    # loads data/taxonomy.legal.json) without forking. Loaded once at import in
    # app/classification.py; restart to apply changes.
    taxonomy_path: Path = Path("data/taxonomy.json")
    # Auto-classification on upload + manual reclassify. When False, the
    # probabilistic classifier never runs (no doc_type/subtag guessing) — for
    # deployments that assign categories deterministically (e.g. a legal library
    # that derives doc_type from curated source folders at ingest).
    classification_enabled: bool = True
    # Strip 北大法宝 / export noise from chunk text at ingest (legal deployment).
    # Per-chunk, after parse, before embedding. Default off — patterns are inert
    # on non-法宝 corpora but cost cycles; the legal deployment sets this true.
    text_clean_enabled: bool = False
    # Drop intra-document duplicate paragraphs (by normalized text) at ingest.
    # Off by default — the same text at different positions can be legitimate
    # context in general corpora. Legal deployments set this true to remove PDF
    # extraction artifacts (a paragraph emitted twice).
    dedup_chunks_enabled: bool = False
    # Chunking
    chunk_size: int = 1000
    chunk_overlap: int = 200

    # Document parsing mode:
    #   "default"  — text-only extraction (fast, all file types)
    #   "enhanced" — tables + images via PyMuPDF (PDF only, falls back to default for others)
    #   "vision"   — render pages as images → vision LLM → structured markdown (all file types)
    #   "docling"  — neural layout analysis via docling (best accuracy, requires optional install)
    parse_mode: ParseMode = ParseMode.DEFAULT
    image_description_model: str = "gpt-4o-mini"
    image_description_max_tokens: int = 512

    # Poppler figure extraction (enhanced mode)
    poppler_figure_extraction: bool = True

    # Docling mode settings (requires: uv sync --extra docling)
    docling_ocr: bool = False
    docling_picture_description: bool = False
    docling_equation_ocr: bool = False  # pix2tex LaTeX OCR for formulas (optional)
    docling_device: str = "auto"  # "auto", "cpu", "cuda", "mps"

    # Vision mode settings
    vision_model: str = "gpt-4o-mini"
    vision_max_tokens: int = 4096
    vision_page_dpi: int = 150

    # Retrieval
    retrieval_top_k: int = 10
    # Cap on per-doc-coverage BACKFILL chunks for missing docs. A collection-
    # scoped query expands to all member doc_ids; without this, a 1456-doc
    # collection force-injects ~1453 mandatory chunks → reranker OOM + context
    # blow-up. Surfaced docs are always covered; only missing-doc backfill is
    # capped. Tuned to answer capacity, not collection size.
    per_doc_coverage_max_backfill: int = 30
    # Per-doc coverage on /search (retrieve-only). Coverage exists for ask-AI
    # answer comprehensiveness; agent/MCP consumers rank raw chunks themselves,
    # and on large collection scopes coverage enumerates every member doc per
    # query. /query is unaffected by this flag.
    search_coverage_enabled: bool = False

    # Re-ranking
    rerank_enabled: bool = False
    rerank_top_n: int = 4
    rerank_provider: RerankProvider = RerankProvider.FLASHRANK
    rerank_model: str = ""  # empty = auto-select default per provider
    # Hard cap on candidates fed to the cross-encoder reranker. The ONNX reranker
    # allocates per-candidate; thousands at once OOMs (~18GB on a 1456-doc
    # collection). Input is truncated to the top-N by score before scoring; the
    # remainder is unaffected by reranking. Output still comes from the reranker.
    rerank_max_candidates: int = 80
    # When True (default) the cross-encoder's order IS the final result order —
    # displayed values stay composite scores, so position and score can be
    # locally non-monotonic (two honest, different signals). False restores the
    # legacy behavior of re-sorting by composite after rerank, which discards
    # the cross-encoder's judgment.
    rerank_final_order: bool = True

    # Query expansion for vague queries (re-query with LLM-expanded terms)
    query_expansion_enabled: bool = True
    query_expansion_score_threshold: float = 0.3  # trigger when all scores below this

    # HyDE (Hypothetical Document Embeddings): LLM writes a hypothetical
    # answer document, which is embedded and searched ALONGSIDE the original
    # query (RRF fusion — a bad hypothesis can't evict direct hits). Closes
    # the register gap between colloquial/narrative queries and formal corpus
    # text (case-description -> legal filing). Adds one LLM call + one vector
    # search per query; off by default.
    hyde_enabled: bool = False

    # Open question detection (section-aware sampling for broad queries)
    open_question_detection: bool = False

    # Dedup threshold for hybrid Jaccard similarity
    dedup_threshold: float = 0.7

    # Query types config file (defines types, strategies, scoring weights)
    query_types_file: str = "data/query_types.json"

    # Background task backend
    task_backend: str = "background"  # "background" (FastAPI) or "arq" (Redis)
    redis_url: str = "redis://localhost:6379"

    # Summary generation (compiled layer)
    summary_enabled: bool = True
    summary_provider: str = "openai"  # "openai" or "openrouter"
    summary_model: str = "gpt-4o-mini"
    summary_min_chars: int = 200
    # Contextual chunk summaries: each chunk is summarised WITH the document's opening in
    # front of it, so the summary names the document and the article/section the chunk
    # belongs to. A bare one-line summary of a statute clause cannot say which statute it
    # is, and that is exactly what a short query fails to retrieve (measured 2026-09-06).
    summary_contextual: bool = True
    summary_context_head_chars: int = 1200  # how much of the document opening to show
    summary_max_chunks_for_overview: int = 30  # stride-sampled across doc for doc-level overview
    scoring_profile: str = "general"
    scoring_recency_decay: float = 0.001  # unused until recency signal is wired into _composite_score

    # Visual proximity linking (replace blanket visual supplements)
    visual_proximity_enabled: bool = True
    visual_proximity_pages: int = 1  # pages before/after to search

    # Hybrid search — dense vector + BM25 keyword matching merged via RRF.
    # On by default as of 2026-04-21: dense embeddings alone miss exact-keyword
    # queries (e.g., "7B", "175 billion", version numbers, dates). BM25 catches
    # these. Rank-fusion (Cormack et al. SIGIR 2009) damps noise from either
    # retriever. Research paper (2026-04-21 survey) notes all production RAG
    # systems (Perplexity, Glean) use hybrid retrieval.
    hybrid_search_enabled: bool = True
    hybrid_bm25_weight: float = 0.5  # used by legacy EnsembleRetriever in chain.py; retrieval.py uses RRF instead
    rrf_k: int = 60

    # Router prefix — LLM-based doc pre-filter for large scopes.
    # Runs one gpt-4o-mini call before vector search to pick the top-K docs
    # most likely to contain the answer. Cuts downstream rerank/budget cost.
    # Fail-safe: malformed output or LLM error falls back to the full scope.
    # On by default once the eval suite cleared ship gates with
    # retrieval_top_k=10.
    router_enabled: bool = True
    router_min_scope: int = 15      # below this many docs, router is bypassed
    # Above this many docs, router is also bypassed: it fetches every scoped
    # doc's registry row sequentially and puts a one-line-per-doc menu in the
    # LLM prompt — untenable on thousands-of-docs collection scopes.
    router_max_scope: int = 300
    router_top_k: int = 8           # how many docs router picks
    router_model: str = "gpt-4o-mini"

    # Graph edge building — controls when two docs get a similar_to edge in the document-level
    # graph view. Two knobs work together:
    #   - graph_similar_min_score: per chunk-pair cosine similarity floor.
    #   - graph_similar_min_pairs: how many such pairs are required before a doc-pair is rendered.
    # Defaults (0.7 / 2 pairs) keep the graph readable on dense corpora; lower the score to surface
    # weak relationships, lower min_pairs to surface single-shot matches. Affects BOTH the
    # visualization AND retrieval (composite graph_score + graph expansion).
    graph_similar_min_score: float = 0.7
    graph_similar_min_pairs: int = 2
    # How graph-expanded chunks are scored at retrieval time:
    #   "decay"  (default): parent_score x decay x edge_score — query-linked,
    #            mathematically always below the parent chunk.
    #   "legacy": raw static edge.score when present — query-INDEPENDENT, lets
    #            high-edge hub docs enter any query's results at a fixed high
    #            score (the constant-top-3 bug this replaces).
    graph_expansion_score_mode: str = "decay"

    # Per-stage score provenance logging ([SCORE-TRACE] lines, top-10 per
    # stage). Diagnostic for "where did this score come from" — off by default.
    retrieval_debug_trace: bool = False

    # Context window management — protects against overflow when passing chunks to LLM.
    # Effective budget = min(max_context_tokens or inf, model_window * context_budget_ratio).
    # Used output tokens are subtracted. See MODEL_WINDOWS below for per-model defaults.
    max_context_tokens: int | None = None            # hard cap (None = derive from model window)
    context_budget_ratio: float = 0.6                # fraction of model window available for input
    reserved_output_tokens: int = 2048               # reserve for LLM's generated answer
    reserved_prompt_overhead_tokens: int = 512       # system prompt + template + formatting overhead
    history_max_budget_ratio: float = 0.4            # chat history can take up to this share of input
    history_min_reserve_ratio: float = 0.2           # but always reserve at least this much

    # Chat memory
    memory_max_messages: int = 20
    memory_session_ttl: int = 2592000  # 30 days — safety floor; chat history is persistent

    # Web search fallback
    web_search_enabled: bool = True
    web_search_max_results: int = 9
    web_search_provider: str = "duckduckgo"
    web_search_score_threshold: float = 0.0  # score-based auto-fallback disabled; web search still triggers on empty results or force_web_search

    # Database: SQLite (default, zero-setup) or PostgreSQL (docker compose up postgres -d)
    # "postgresql+asyncpg://postgres:postgres@localhost:5432/meinrag"
    database_url: str = "sqlite+aiosqlite:///data/meinrag.db"

    # User system
    default_user: str = "admin"
    user_isolation: Literal["all", "documents", "none"] = "all"

    # CORS
    cors_origins: str = "http://localhost:5173"

    # Upload limits
    max_upload_size_mb: int = 50

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"

    # ─── PII anonymization plugin ───────────────────────────────────────────
    # Off by default. When enabled, pre-embedding pseudonymization replaces
    # PII in chunk text with typed placeholders (`[PERSON_1]` etc.) and
    # stores a Fernet-encrypted mapping in PostgreSQL so authorized users
    # can see original content at retrieval time. Requires installing the
    # `anonymization` extra (`uv sync --extra anonymization`) plus spaCy
    # models. See docs/plans/2026-05-21-anonymization-plugin.md.
    anonymization_enabled: bool = False
    # Fernet key (URL-safe base64-encoded 32 bytes). Generate via:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # MUST be set when anonymization_enabled=True (validator enforces).
    anonymization_encryption_key: str | None = None
    # Presidio analyzer confidence threshold for accepting a span as PII.
    # Default 0.7 matches research recommendation. Raise to reduce false
    # positives (over-anonymization); lower to catch more (more false negatives).
    anonymization_confidence_threshold: float = 0.7
    # Active per-chunk languages. Each adds a spaCy NER model:
    #   "en" -> en_core_web_lg (~750 MB)
    #   "zh" -> zh_core_web_trf (~500 MB)
    anonymization_languages: list[str] = ["en", "zh"]
    # Entity types to anonymize. Defaults follow article §11.2:
    # irreducibly-identifying PII only (names, IDs, contact info). Orgs,
    # locations, dates, non-DOB excluded by default since they carry high
    # semantic value for retrieval. Override via env CSV.
    anonymization_entity_types: list[str] = [
        "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN",
        "CREDIT_CARD", "IP_ADDRESS",
        "CHINESE_ID_NUMBER", "CHINESE_PHONE", "CHINESE_BANK_CARD",
        "CHINESE_PASSPORT",
    ]

    @model_validator(mode="before")
    @classmethod
    def _compat_parse_mode(cls, values):
        """Backward compat: accept PDF_PARSE_MODE as alias for PARSE_MODE."""
        if isinstance(values, dict):
            legacy_key = "pdf_parse_mode"
            new_key = "parse_mode"
            if legacy_key in values and new_key not in values:
                values[new_key] = values.pop(legacy_key)
            elif legacy_key in values:
                values.pop(legacy_key)
        return values

    @model_validator(mode="after")
    def _validate_anonymization_key(self):
        """If anonymization is enabled, an encryption key MUST be set —
        otherwise mappings can't be stored. Fail-fast at startup rather
        than at first upload.
        """
        if self.anonymization_enabled and not self.anonymization_encryption_key:
            raise ValueError(
                "ANONYMIZATION_ENABLED=true but ANONYMIZATION_ENCRYPTION_KEY is unset. "
                "Generate a Fernet key with: "
                'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            )
        return self


def get_settings() -> Settings:
    return Settings()


# ---------------------------------------------------------------------------
# Per-model context window lookup. Normalized (lowercased, provider-stripped).
# Unknown model -> DEFAULT_MODEL_WINDOW, and it is LOGGED: the old silent 8,192
# fallback shrank the fact-type chunk budget to one or two chunks the moment a model
# name outside this table was configured, with no error anywhere (measured 2026-09-02).
# ---------------------------------------------------------------------------
import logging as _logging

_log = _logging.getLogger(__name__)

MODEL_WINDOWS: dict[str, int] = {
    # OpenAI
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4.1": 1_047_576,
    "gpt-4.1-mini": 1_047_576,
    "gpt-4.1-nano": 1_047_576,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    "gpt-3.5-turbo-16k": 16_385,
    "o1": 128_000,
    "o1-mini": 128_000,
    "o1-preview": 128_000,
    "o3-mini": 128_000,
    # Anthropic
    "claude-3-haiku": 200_000,
    "claude-3-sonnet": 200_000,
    "claude-3-opus": 200_000,
    "claude-3-5-sonnet": 200_000,
    "claude-3-5-haiku": 200_000,
    "claude-haiku-4-5": 200_000,
    "claude-sonnet-4-5": 200_000,
    # 1M-context generation (Anthropic models reference): Opus 4.6+, Sonnet 4.6+, Sonnet 5.
    "claude-sonnet-4-6": 1_000_000,
    "claude-sonnet-5": 1_000_000,
    "claude-opus-4-6": 1_000_000,
    "claude-opus-4-7": 1_000_000,
    "claude-opus-4-8": 1_000_000,
    "claude-opus-5": 1_000_000,
    "claude-fable-5": 1_000_000,
    "claude-fable-5-1": 1_000_000,
    # Google
    "gemini-1.5-flash": 1_000_000,
    "gemini-1.5-pro": 2_000_000,
    "gemini-2.0-flash": 1_000_000,
    # Meta / open
    "llama-3.1-70b": 128_000,
    "llama-3.1-8b": 128_000,
    "llama-3.3-70b": 128_000,
}

# 128k, not 8k: every mainstream model since 2024 has at least this. A too-small guess fails
# SILENTLY (tiny context, no error); a too-large guess fails LOUDLY (the provider rejects the
# request), and loud is the failure mode we want for a misconfigured model name.
DEFAULT_MODEL_WINDOW = 128_000


def lookup_model_window(model_name: str) -> int:
    """Resolve context window size for a model name. Handles provider prefixes
    ('openai/gpt-4o-mini' → 'gpt-4o-mini'), case, and partial matches.
    """
    if not model_name:
        _log.warning("No LLM model name configured; assuming a %d-token window", DEFAULT_MODEL_WINDOW)
        return DEFAULT_MODEL_WINDOW
    norm = model_name.lower().strip()
    # Strip provider prefix
    if "/" in norm:
        norm = norm.split("/", 1)[-1]
    # Exact match first
    if norm in MODEL_WINDOWS:
        return MODEL_WINDOWS[norm]
    # Partial match — check if any known model is a prefix
    for known, window in MODEL_WINDOWS.items():
        if norm.startswith(known) or known.startswith(norm):
            return window
    _log.warning(
        "Model %r is not in MODEL_WINDOWS; assuming a %d-token window. Add it to the table "
        "in app/config.py so the context budget matches the real window.",
        model_name, DEFAULT_MODEL_WINDOW,
    )
    return DEFAULT_MODEL_WINDOW


# Per-query-type budget multiplier. Multiplies effective_chunk_budget by this ratio.
# Fact queries need small focused context; synthesis needs breadth.
# Values tuned conservatively; verify with credibility test.
QUERY_BUDGET_RATIOS: dict[str, float] = {
    "fact": 0.25,
    "overview": 0.60,
    "reference": 0.40,
    "exploratory": 1.00,
    # No "synthesis" entry: the classifier only emits the types listed in
    # data/query_types.json, and "synthesis" is not one of them, so a ratio for it was
    # dead configuration (tests/test_context_silent_failures.py keeps the two in step).
}

DEFAULT_QUERY_BUDGET_RATIO = 0.60
