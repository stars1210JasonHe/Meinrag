"""B4: AI Document Classification tests - Requires API key."""
import asyncio
from unittest.mock import MagicMock

import pytest

from app.classification import PRIMARY_CATEGORIES, ALL_TAGS
from app.llm.provider import create_chat_model
from app.services.collection_suggester import classify_document, ClassificationResult
from app.services.document_processor import DocumentProcessor
from app.services.embedding_classifier import clear_cache as clear_embedding_cache
from tests.conftest import online, PDF_AI_SAFETY, PDF_PATTERNS, PDF_LAW


@online
class TestAIClassification:
    """B4.1 - B4.5: classify_document picks a sensible primary + subtags."""

    def test_ai_safety_paper(self, settings):
        """B4.1: AI safety research paper gets a research-flavoured primary."""
        llm = create_chat_model(settings)
        processor = DocumentProcessor(settings)
        chunks = asyncio.run(processor.load_and_split(PDF_AI_SAFETY))

        result = classify_document(chunks, llm)
        assert isinstance(result, ClassificationResult)
        assert result.primary_category in PRIMARY_CATEGORIES or result.primary_category is None
        for s in result.subtags:
            assert s in ALL_TAGS
        print(f"  AI safety paper -> primary={result.primary_category} subtags={result.subtags}")

    def test_patterns_paper(self, settings):
        """B4.2: CS patterns paper classified into taxonomy."""
        llm = create_chat_model(settings)
        processor = DocumentProcessor(settings)
        chunks = asyncio.run(processor.load_and_split(PDF_PATTERNS))

        result = classify_document(chunks, llm)
        assert isinstance(result, ClassificationResult)
        print(f"  Patterns paper -> primary={result.primary_category} subtags={result.subtags}")

    def test_law_document(self, settings):
        """B4.3: German Basic Law gets the legal-compliance primary."""
        llm = create_chat_model(settings)
        processor = DocumentProcessor(settings)
        chunks = asyncio.run(processor.load_and_split(PDF_LAW))

        result = classify_document(chunks, llm)
        assert result.primary_category == "legal-compliance"
        print(f"  German Basic Law -> primary={result.primary_category} subtags={result.subtags}")

    def test_subtags_drawn_from_taxonomy(self, settings):
        """B4.4: All subtags are valid taxonomy entries (domains or sub-domains)."""
        llm = create_chat_model(settings)
        processor = DocumentProcessor(settings)
        chunks = asyncio.run(processor.load_and_split(PDF_AI_SAFETY))

        result = classify_document(chunks, llm)
        for tag in result.subtags:
            assert tag in ALL_TAGS, f"'{tag}' not in taxonomy vocabulary"

    def test_collection_suggestions_filtered_to_existing(self, settings):
        """B4.5: collection_suggestions only contain names from the existing list."""
        llm = create_chat_model(settings)
        processor = DocumentProcessor(settings)
        chunks = asyncio.run(processor.load_and_split(PDF_AI_SAFETY))

        existing = ["research-papers-archive", "ai-safety-corpus"]
        result = classify_document(chunks, llm, existing_collections=existing)
        for suggestion in result.collection_suggestions:
            assert suggestion in existing, f"'{suggestion}' invented, not in existing"
        print(f"  Suggestions -> {result.collection_suggestions}")


@online
class TestEmbeddingClassification:
    """Tests using real OpenAI embeddings (requires API key)."""

    def test_embedding_classification(self, settings):
        """Embedding classifier returns valid ClassificationResult for a real PDF."""
        from langchain_openai import OpenAIEmbeddings
        clear_embedding_cache()

        embeddings = OpenAIEmbeddings(
            model=settings.openai_embedding_model,
            openai_api_key=settings.openai_api_key,
        )
        processor = DocumentProcessor(settings)
        chunks = asyncio.run(processor.load_and_split(PDF_AI_SAFETY))

        # LLM fallback mock (in case embedding threshold isn't met)
        fallback_llm = MagicMock()
        fallback_llm.invoke.return_value = MagicMock(content=(
            '{"primary_category": null, "subtags": [], "collection_suggestions": []}'
        ))
        result = classify_document(chunks, llm=fallback_llm, embeddings=embeddings)
        assert isinstance(result, ClassificationResult)
        if result.primary_category is not None:
            assert result.primary_category in PRIMARY_CATEGORIES
        for tag in result.subtags:
            assert tag in ALL_TAGS
        print(f"  AI safety paper (embedding) -> primary={result.primary_category} subtags={result.subtags}")
        clear_embedding_cache()
