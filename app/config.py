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
    openrouter_api_key: str = ""
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_site_url: str = "http://localhost:8000"
    openrouter_site_name: str = "MEINRAG"

    # Vector store
    vector_store: VectorStoreType = VectorStoreType.FAISS

    # Paths
    upload_dir: Path = Path("data/uploads")
    vectorstore_dir: Path = Path("data/vectorstore")
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

    # Re-ranking
    rerank_enabled: bool = False
    rerank_top_n: int = 4
    rerank_provider: RerankProvider = RerankProvider.FLASHRANK
    rerank_model: str = ""  # empty = auto-select default per provider

    # Query expansion for vague queries (re-query with LLM-expanded terms)
    query_expansion_enabled: bool = True
    query_expansion_score_threshold: float = 0.3  # trigger when all scores below this

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
    # On by default as of 2026-04-22 (eval cleared ship gates with
    # retrieval_top_k=10). See docs/plans/2026-04-22-router-default-on.md.
    router_enabled: bool = True
    router_min_scope: int = 15      # below this many docs, router is bypassed
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


def get_settings() -> Settings:
    return Settings()


# ---------------------------------------------------------------------------
# Per-model context window lookup. Normalized (lowercased, provider-stripped).
# Fallback = 8192 for unknown models (conservative).
# ---------------------------------------------------------------------------
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
    "claude-opus-4-7": 200_000,
    # Google
    "gemini-1.5-flash": 1_000_000,
    "gemini-1.5-pro": 2_000_000,
    "gemini-2.0-flash": 1_000_000,
    # Meta / open
    "llama-3.1-70b": 128_000,
    "llama-3.1-8b": 128_000,
    "llama-3.3-70b": 128_000,
}

DEFAULT_MODEL_WINDOW = 8_192


def lookup_model_window(model_name: str) -> int:
    """Resolve context window size for a model name. Handles provider prefixes
    ('openai/gpt-4o-mini' → 'gpt-4o-mini'), case, and partial matches.
    """
    if not model_name:
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
    return DEFAULT_MODEL_WINDOW


# Per-query-type budget multiplier. Multiplies effective_chunk_budget by this ratio.
# Fact queries need small focused context; synthesis needs breadth.
# Values tuned conservatively; verify with credibility test.
QUERY_BUDGET_RATIOS: dict[str, float] = {
    "fact": 0.25,
    "overview": 0.60,
    "reference": 0.40,
    "exploratory": 1.00,
    "synthesis": 0.80,  # deliberately < 1.0; test showed top_k=10 regresses synthesis
}

DEFAULT_QUERY_BUDGET_RATIO = 0.60
