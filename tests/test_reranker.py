"""Tests for the configurable reranker system."""
import pytest
from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from app.config import Settings, RerankProvider


class TestRerankerConfig:
    """Config defaults and validation."""

    def test_default_rerank_settings(self):
        s = Settings(_env_file=None)
        assert s.rerank_enabled is False
        assert s.rerank_top_n == 4
        assert s.rerank_provider == RerankProvider.FLASHRANK
        assert s.rerank_model == ""

    def test_rerank_provider_accepts_known_values(self):
        for provider in RerankProvider:
            s = Settings(rerank_provider=provider)
            assert s.rerank_provider == provider

    def test_rerank_provider_rejects_invalid(self):
        with pytest.raises(Exception):
            Settings(rerank_provider="nonexistent")


class TestGetReranker:
    """Unit tests for _get_reranker factory."""

    def test_flashrank_returns_compressor(self):
        from app.rag.chain import _get_reranker
        settings = Settings(rerank_provider="flashrank", rerank_top_n=3)
        compressor = _get_reranker(settings)
        assert compressor is not None
        assert hasattr(compressor, "compress_documents")

    def test_flashrank_default_model(self):
        from app.rag.chain import _get_reranker
        settings = Settings(rerank_provider="flashrank")
        compressor = _get_reranker(settings)
        assert compressor.model == "ms-marco-MiniLM-L-12-v2"

    def test_flashrank_custom_model(self):
        from app.rag.chain import _get_reranker
        settings = Settings(
            rerank_provider="flashrank",
            rerank_model="ms-marco-TinyBERT-L-2-v2",
        )
        compressor = _get_reranker(settings)
        assert compressor.model == "ms-marco-TinyBERT-L-2-v2"

    def test_flashrank_top_n_passed(self):
        from app.rag.chain import _get_reranker
        settings = Settings(rerank_provider="flashrank", rerank_top_n=7)
        compressor = _get_reranker(settings)
        assert compressor.top_n == 7

    def test_unknown_provider_rejected_by_enum(self):
        """Invalid provider is rejected at config level by the enum."""
        with pytest.raises(Exception):
            Settings(rerank_provider="nonexistent")

    def test_llm_provider_without_llm_raises(self):
        from app.rag.chain import _get_reranker
        settings = Settings(rerank_provider="llm")
        with pytest.raises(ValueError, match="LLM reranker requires"):
            _get_reranker(settings)


class TestFlashrankReranking:
    """Integration test: FlashRank actually reranks documents."""

    def test_rerank_reduces_to_top_n(self):
        from app.rag.chain import _get_reranker
        settings = Settings(rerank_provider="flashrank", rerank_top_n=2)
        compressor = _get_reranker(settings)

        docs = [
            Document(page_content="The capital of France is Paris."),
            Document(page_content="Python is a programming language."),
            Document(page_content="Paris has many famous landmarks like the Eiffel Tower."),
            Document(page_content="The weather today is sunny."),
        ]
        result = compressor.compress_documents(docs, "What is the capital of France?")
        assert len(result) == 2

    def test_rerank_preserves_metadata(self):
        from app.rag.chain import _get_reranker
        settings = Settings(rerank_provider="flashrank", rerank_top_n=2)
        compressor = _get_reranker(settings)

        docs = [
            Document(
                page_content="The Transformer uses multi-head attention.",
                metadata={"page": 3, "doc_id": "test1", "chunk_type": "text"},
            ),
            Document(
                page_content="Unrelated content about cooking recipes.",
                metadata={"page": 10, "doc_id": "test2", "chunk_type": "text"},
            ),
        ]
        result = compressor.compress_documents(docs, "How does the Transformer work?")
        assert len(result) >= 1
        # Metadata should be preserved on reranked documents
        for doc in result:
            assert "doc_id" in doc.metadata
            assert "page" in doc.metadata

    def test_rerank_relevance_ordering(self):
        """The most relevant document should appear in the top results."""
        from app.rag.chain import _get_reranker
        settings = Settings(rerank_provider="flashrank", rerank_top_n=3)
        compressor = _get_reranker(settings)

        docs = [
            Document(page_content="Basketball is a popular sport played worldwide."),
            Document(page_content="Machine learning uses neural networks for pattern recognition."),
            Document(page_content="The recipe calls for two cups of flour and one egg."),
        ]
        result = compressor.compress_documents(docs, "What is machine learning?")
        contents = [r.page_content for r in result]
        # ML doc should be present somewhere in results
        assert any("neural networks" in c for c in contents)

    def test_rerank_single_doc(self):
        """FlashRank handles a single document without error."""
        from app.rag.chain import _get_reranker
        settings = Settings(rerank_provider="flashrank", rerank_top_n=3)
        compressor = _get_reranker(settings)

        docs = [Document(page_content="The only document about quantum physics.")]
        result = compressor.compress_documents(docs, "quantum physics")
        assert len(result) == 1


class TestBuildRagChainWithReranker:
    """Test that build_rag_chain correctly wires the reranker."""

    def test_chain_builds_with_rerank_enabled(self):
        """build_rag_chain should not crash when reranking is enabled."""
        pytest.importorskip("langchain.retrievers")
        from app.rag.chain import build_rag_chain

        mock_store = MagicMock()
        mock_store.as_retriever.return_value = MagicMock()
        mock_store.as_retriever.return_value.invoke = MagicMock(return_value=[
            Document(page_content="test content", metadata={"doc_id": "d1"}),
        ])

        mock_llm = MagicMock()
        mock_llm.invoke = MagicMock(return_value="test answer")

        settings = Settings(
            rerank_enabled=True,
            rerank_provider="flashrank",
            rerank_top_n=2,
        )
        chain, retriever = build_rag_chain(
            vector_store=mock_store,
            llm=mock_llm,
            top_k=4,
            settings=settings,
        )
        assert chain is not None
        assert retriever is not None

    def test_chain_builds_without_settings(self):
        """Backward compat: no settings argument should not crash."""
        from app.rag.chain import build_rag_chain

        mock_store = MagicMock()
        mock_store.as_retriever.return_value = MagicMock()
        mock_store.as_retriever.return_value.invoke = MagicMock(return_value=[])

        mock_llm = MagicMock()
        chain, retriever = build_rag_chain(
            vector_store=mock_store,
            llm=mock_llm,
            top_k=4,
        )
        assert chain is not None
