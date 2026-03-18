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
    retrieval_top_k: int = 4

    # Re-ranking
    rerank_enabled: bool = False
    rerank_top_n: int = 4
    rerank_provider: RerankProvider = RerankProvider.FLASHRANK
    rerank_model: str = ""  # empty = auto-select default per provider

    # Hybrid search
    hybrid_search_enabled: bool = False
    hybrid_bm25_weight: float = 0.5

    # Chat memory
    memory_max_messages: int = 20
    memory_session_ttl: int = 3600

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
