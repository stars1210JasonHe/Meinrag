"""A1: Configuration tests - No API key required."""
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings, LLMProvider, VectorStoreType, get_settings


class TestConfigLoading:
    """A1.1: Settings load with defaults or env values."""

    def test_settings_loads(self):
        settings = get_settings()
        assert settings is not None
        assert isinstance(settings.llm_provider, LLMProvider)
        assert isinstance(settings.vector_store, VectorStoreType)

    def test_default_values(self):
        """Verify key fields have valid values (may be overridden by .env)."""
        settings = Settings(openai_api_key="test-key")
        assert settings.chunk_size > 0
        assert settings.chunk_overlap >= 0
        assert settings.retrieval_top_k >= 1
        assert isinstance(settings.rerank_enabled, bool)
        assert isinstance(settings.hybrid_search_enabled, bool)
        assert settings.memory_max_messages > 0
        assert settings.memory_session_ttl > 0
        assert settings.port > 0

    def test_paths_are_path_objects(self):
        settings = Settings(openai_api_key="test-key")
        assert isinstance(settings.upload_dir, Path)
        assert isinstance(settings.vectorstore_dir, Path)


class TestConfigEnums:
    """A1.2: Enum validation for vector_store and llm_provider."""

    def test_valid_llm_providers(self):
        s1 = Settings(openai_api_key="k", llm_provider="openai")
        assert s1.llm_provider == LLMProvider.OPENAI

        s2 = Settings(openai_api_key="k", llm_provider="openrouter")
        assert s2.llm_provider == LLMProvider.OPENROUTER

    def test_invalid_llm_provider(self):
        with pytest.raises(ValidationError):
            Settings(openai_api_key="k", llm_provider="invalid")

    def test_valid_vector_store_types(self):
        s1 = Settings(openai_api_key="k", vector_store="chroma")
        assert s1.vector_store == VectorStoreType.CHROMA

        s2 = Settings(openai_api_key="k", vector_store="faiss")
        assert s2.vector_store == VectorStoreType.FAISS

    def test_invalid_vector_store(self):
        with pytest.raises(ValidationError):
            Settings(openai_api_key="k", vector_store="pinecone")


class TestConfigRanges:
    """A1.3: Numeric field types and ranges."""

    def test_bm25_weight_is_float(self):
        settings = Settings(openai_api_key="k", hybrid_bm25_weight=0.3)
        assert settings.hybrid_bm25_weight == 0.3

    def test_memory_ttl_is_positive(self):
        settings = Settings(openai_api_key="k", memory_session_ttl=100)
        assert settings.memory_session_ttl == 100

    def test_memory_max_messages_is_positive(self):
        settings = Settings(openai_api_key="k", memory_max_messages=10)
        assert settings.memory_max_messages == 10

    def test_chunk_size_is_int(self):
        settings = Settings(openai_api_key="k", chunk_size=500)
        assert settings.chunk_size == 500

    def test_rerank_top_n_is_int(self):
        settings = Settings(openai_api_key="k", rerank_top_n=3)
        assert settings.rerank_top_n == 3
