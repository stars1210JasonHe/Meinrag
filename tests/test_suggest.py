"""B4: AI Collection Suggestion tests - Requires API key."""
from unittest.mock import MagicMock

import pytest

from app.classification import PRIMARY_CATEGORIES, ALL_DOMAINS
from app.llm.provider import create_chat_model
from app.services.collection_suggester import suggest_collections
from app.services.document_processor import DocumentProcessor
from app.services.embedding_classifier import clear_cache as clear_embedding_cache
from tests.conftest import online, PDF_AI_SAFETY, PDF_PATTERNS, PDF_LAW


@online
class TestAISuggestion:
    """B4.1 - B4.4: AI suggests appropriate collection names from taxonomy."""

    def test_ai_safety_paper(self, settings):
        """B4.1: AI safety research paper gets taxonomy-based suggestions."""
        llm = create_chat_model(settings)
        processor = DocumentProcessor(settings)
        chunks = processor.load_and_split(PDF_AI_SAFETY)

        suggestions = suggest_collections(chunks, llm)
        assert isinstance(suggestions, list)
        assert len(suggestions) >= 1
        for s in suggestions:
            assert len(s) <= 50
        print(f"  AI safety paper -> {suggestions}")

    def test_patterns_paper(self, settings):
        """B4.2: CS patterns paper gets taxonomy-based suggestions."""
        llm = create_chat_model(settings)
        processor = DocumentProcessor(settings)
        chunks = processor.load_and_split(PDF_PATTERNS)

        suggestions = suggest_collections(chunks, llm)
        assert isinstance(suggestions, list)
        assert len(suggestions) >= 1
        print(f"  Patterns paper -> {suggestions}")

    def test_law_document(self, settings):
        """B4.3: German Basic Law gets a legal suggestion."""
        llm = create_chat_model(settings)
        processor = DocumentProcessor(settings)
        chunks = processor.load_and_split(PDF_LAW)

        suggestions = suggest_collections(chunks, llm)
        assert isinstance(suggestions, list)
        assert len(suggestions) >= 1
        print(f"  German Basic Law -> {suggestions}")

    def test_suggestion_format(self, settings):
        """B4.4: Suggestions are lowercase, no spaces, <= 50 chars each."""
        llm = create_chat_model(settings)
        processor = DocumentProcessor(settings)
        chunks = processor.load_and_split(PDF_AI_SAFETY)

        suggestions = suggest_collections(chunks, llm)
        for suggestion in suggestions:
            assert suggestion == suggestion.lower(), f"Not lowercase: '{suggestion}'"
            assert " " not in suggestion, f"Contains spaces: '{suggestion}'"
            assert len(suggestion) <= 50

    def test_with_existing_collections(self, settings):
        """B4.5: Suggestions aware of existing collections."""
        llm = create_chat_model(settings)
        processor = DocumentProcessor(settings)
        chunks = processor.load_and_split(PDF_AI_SAFETY)

        existing = ["research-scientific", "computer-science-ai"]
        suggestions = suggest_collections(chunks, llm, existing_collections=existing)
        assert isinstance(suggestions, list)
        assert len(suggestions) >= 1
        print(f"  With existing collections -> {suggestions}")


@online
class TestEmbeddingClassification:
    """Tests using real OpenAI embeddings (requires API key)."""

    def test_embedding_classification(self, settings):
        """Embedding classifier returns valid taxonomy categories for a real PDF."""
        from langchain_openai import OpenAIEmbeddings
        clear_embedding_cache()

        embeddings = OpenAIEmbeddings(
            model=settings.openai_embedding_model,
            openai_api_key=settings.openai_api_key,
        )
        processor = DocumentProcessor(settings)
        chunks = processor.load_and_split(PDF_AI_SAFETY)

        # LLM fallback mock (in case embedding threshold isn't met)
        fallback_llm = MagicMock()
        fallback_llm.invoke.return_value = MagicMock(content='["other"]')
        result = suggest_collections(chunks, llm=fallback_llm, embeddings=embeddings)
        assert isinstance(result, list)
        assert len(result) >= 1
        # First element should be a valid primary category
        assert result[0] in PRIMARY_CATEGORIES, f"{result[0]} not in taxonomy categories"
        # Additional elements should be valid domains
        for item in result[1:]:
            assert item in ALL_DOMAINS, f"{item} not in taxonomy domains"
        print(f"  AI safety paper (embedding) -> {result}")
        clear_embedding_cache()
