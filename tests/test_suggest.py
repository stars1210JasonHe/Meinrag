"""B4: AI Collection Suggestion tests - Requires API key."""
import pytest

from app.llm.provider import create_chat_model
from app.services.collection_suggester import suggest_collections
from app.services.document_processor import DocumentProcessor
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
