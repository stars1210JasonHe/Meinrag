from enum import Enum
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProvider(str, Enum):
    OPENAI = "openai"
    OPENROUTER = "openrouter"


class VectorStoreType(str, Enum):
    CHROMA = "chroma"
    FAISS = "faiss"


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
    vector_store: VectorStoreType = VectorStoreType.CHROMA

    # Paths
    upload_dir: Path = Path("data/uploads")
    vectorstore_dir: Path = Path("data/vectorstore")
    metadata_file: Path = Path("data/metadata.json")

    # Chunking
    chunk_size: int = 1000
    chunk_overlap: int = 200

    # Retrieval
    retrieval_top_k: int = 4

    # Re-ranking
    rerank_enabled: bool = False
    rerank_top_n: int = 4

    # Hybrid search
    hybrid_search_enabled: bool = False
    hybrid_bm25_weight: float = 0.5

    # Chat memory
    memory_max_messages: int = 20
    memory_session_ttl: int = 3600

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"


def get_settings() -> Settings:
    return Settings()
