"""B2: Vector Store Operations tests - Requires API key."""
import shutil

import pytest

from app.llm.provider import create_embeddings
from app.services.document_processor import DocumentProcessor
from app.vectorstore.chroma_store import ChromaStoreManager
from tests.conftest import online, TEST_DIR, PDF_AI_SAFETY, PDF_PATTERNS


@pytest.fixture(scope="module")
def vector_env():
    """Set up embeddings, store, and index two PDFs. Shared across module."""
    from app.config import Settings
    settings = Settings()

    store_dir = TEST_DIR / "b2_vectorstore"
    store_dir.mkdir(parents=True, exist_ok=True)

    embeddings = create_embeddings(settings)
    store = ChromaStoreManager(persist_directory=store_dir)
    store.initialize(embeddings)

    processor = DocumentProcessor(settings)

    # Index AI safety paper as "research" collection
    chunks_ai = processor.load_and_split(PDF_AI_SAFETY)
    for chunk in chunks_ai:
        chunk.metadata["collection"] = "research"
    store.add_documents(chunks_ai, doc_id="doc_ai_safety")

    # Index patterns paper as "computer-science" collection
    chunks_pat = processor.load_and_split(PDF_PATTERNS)
    for chunk in chunks_pat:
        chunk.metadata["collection"] = "computer-science"
    store.add_documents(chunks_pat, doc_id="doc_patterns")

    yield {
        "store": store,
        "settings": settings,
        "chunks_ai": chunks_ai,
        "chunks_pat": chunks_pat,
    }

    # Cleanup
    store.delete_document("doc_ai_safety")
    store.delete_document("doc_patterns")
    shutil.rmtree(store_dir, ignore_errors=True)


@online
class TestVectorSearch:
    """B2.1 - B2.2: Basic search."""

    def test_search_returns_results(self, vector_env):
        """B2.1: Documents indexed and searchable."""
        store = vector_env["store"]
        results = store.similarity_search("AI agent safety", k=3)
        assert len(results) > 0

    def test_search_relevant(self, vector_env):
        """B2.2: Top results relate to query."""
        store = vector_env["store"]
        results = store.similarity_search("autonomous AI agents safety benchmark", k=3)
        assert len(results) > 0
        # At least one result should mention AI or agent or safety
        combined = " ".join(r.page_content.lower() for r in results)
        assert any(word in combined for word in ["ai", "agent", "safety", "autonomous"])


@online
class TestVectorFiltering:
    """B2.3 - B2.5: Filtering by doc_ids and collection."""

    def test_filter_by_doc_ids(self, vector_env):
        """B2.3: Only matching doc_id in results."""
        store = vector_env["store"]
        results = store.similarity_search_with_filter(
            "simulation patterns", k=5, doc_ids=["doc_patterns"]
        )
        for doc in results:
            assert doc.metadata.get("doc_id") == "doc_patterns"

    def test_filter_by_doc_ids_specific(self, vector_env):
        """B2.4: Filter by specific doc_ids returns only matching docs."""
        store = vector_env["store"]
        results = store.similarity_search_with_filter(
            "safety evaluation", k=5, doc_ids=["doc_ai_safety"]
        )
        for doc in results:
            assert doc.metadata.get("doc_id") == "doc_ai_safety"

    def test_filter_by_multiple_doc_ids(self, vector_env):
        """B2.5: Filter with multiple doc_ids."""
        store = vector_env["store"]
        results = store.similarity_search_with_filter(
            "benchmark", k=5, doc_ids=["doc_ai_safety", "doc_patterns"]
        )
        for doc in results:
            assert doc.metadata.get("doc_id") in ("doc_ai_safety", "doc_patterns")


@online
class TestVectorDeleteAndEdge:
    """B2.6 - B2.8: Delete and edge cases."""

    def test_get_all_documents(self, vector_env):
        """B2.7: get_all_documents returns all indexed docs."""
        store = vector_env["store"]
        all_docs = store.get_all_documents()
        assert len(all_docs) > 0
        doc_ids = set(d.metadata.get("doc_id") for d in all_docs)
        assert "doc_ai_safety" in doc_ids
        assert "doc_patterns" in doc_ids

    def test_search_no_matching_results(self, vector_env):
        """B2.8: Search with nonexistent doc_ids returns empty."""
        store = vector_env["store"]
        results = store.similarity_search_with_filter(
            "quantum entanglement superconductor", k=3, doc_ids=["nonexistent_doc"]
        )
        assert len(results) == 0
