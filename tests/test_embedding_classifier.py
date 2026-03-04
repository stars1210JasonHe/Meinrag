"""Offline tests for embedding-based document classification.

All tests use mocked embeddings — no API key or server needed.
"""
import numpy as np
import pytest
from unittest.mock import MagicMock, patch
from langchain_core.documents import Document

from app.services.embedding_classifier import (
    _build_category_description,
    _build_domain_description,
    _cosine_similarity,
    _extract_smart_sample,
    classify_by_embedding,
    clear_cache,
)


# ── helpers ──────────────────────────────────────────────────────────────

def _make_chunks(texts: list[str], source_file: str = "test.pdf") -> list[Document]:
    return [Document(page_content=t, metadata={"source_file": source_file}) for t in texts]


def _mock_embeddings(query_vec: list[float] | None = None, doc_vecs: list[list[float]] | None = None):
    """Return a mock Embeddings object with controllable vectors."""
    emb = MagicMock()
    emb.__class__.__name__ = "MockEmbeddings"

    if doc_vecs is not None:
        emb.embed_documents.return_value = doc_vecs
    else:
        # Default: return random but deterministic vectors
        rng = np.random.RandomState(42)
        def _embed_docs(texts):
            return [rng.randn(8).tolist() for _ in texts]
        emb.embed_documents.side_effect = _embed_docs

    if query_vec is not None:
        emb.embed_query.return_value = query_vec
    else:
        rng2 = np.random.RandomState(99)
        emb.embed_query.return_value = rng2.randn(8).tolist()

    return emb


@pytest.fixture(autouse=True)
def _clear_embedding_cache():
    """Clear the module-level cache before each test."""
    clear_cache()
    yield
    clear_cache()


# ── TestSmartSampling ────────────────────────────────────────────────────

class TestSmartSampling:

    def test_single_chunk(self):
        chunks = _make_chunks(["Hello world"])
        sample = _extract_smart_sample(chunks)
        assert "Hello world" in sample
        assert "test pdf" in sample.lower()  # filename cleaned

    def test_first_and_last_chunks(self):
        chunks = _make_chunks(["First chunk", "Second chunk", "Third chunk", "Last chunk"])
        sample = _extract_smart_sample(chunks)
        assert "First chunk" in sample
        assert "Second chunk" in sample
        assert "Last chunk" in sample

    def test_filename_included(self):
        chunks = _make_chunks(["content"], source_file="physics_terahertz_spintronic.pdf")
        sample = _extract_smart_sample(chunks)
        assert "physics" in sample.lower()
        assert "terahertz" in sample.lower()

    def test_empty_chunks(self):
        assert _extract_smart_sample([]) == ""

    def test_max_length_cap(self):
        long_text = "x" * 3000
        chunks = _make_chunks([long_text, long_text, long_text])
        sample = _extract_smart_sample(chunks)
        assert len(sample) <= 2000


# ── TestCosineHelper ─────────────────────────────────────────────────────

class TestCosineHelper:

    def test_identical_vectors(self):
        v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        targets = np.array([[1.0, 0.0, 0.0]], dtype=np.float32)
        scores = _cosine_similarity(v, targets)
        assert abs(scores[0] - 1.0) < 1e-5

    def test_orthogonal_vectors(self):
        v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        targets = np.array([[0.0, 1.0, 0.0]], dtype=np.float32)
        scores = _cosine_similarity(v, targets)
        assert abs(scores[0]) < 1e-5

    def test_opposite_vectors(self):
        v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        targets = np.array([[-1.0, 0.0, 0.0]], dtype=np.float32)
        scores = _cosine_similarity(v, targets)
        assert scores[0] < -0.99

    def test_multiple_targets(self):
        v = np.array([1.0, 0.0], dtype=np.float32)
        targets = np.array([
            [1.0, 0.0],   # identical
            [0.0, 1.0],   # orthogonal
            [0.7, 0.7],   # partial match
        ], dtype=np.float32)
        scores = _cosine_similarity(v, targets)
        assert len(scores) == 3
        assert scores[0] > scores[2] > scores[1]


# ── TestDescriptionBuilders ──────────────────────────────────────────────

class TestDescriptionBuilders:

    def test_category_description(self):
        desc = _build_category_description("legal-compliance", {
            "contracts-agreements": ["nda", "sla"],
            "regulation-policy": ["regulatory-guidance"],
        })
        assert "legal compliance" in desc
        assert "contracts agreements" in desc
        assert "nda" in desc

    def test_domain_description(self):
        desc = _build_domain_description(
            "research-scientific",
            "fundamental-science",
            ["physics", "mathematics", "chemistry"],
        )
        assert "research scientific" in desc
        assert "fundamental science" in desc
        assert "physics" in desc
        assert "chemistry" in desc


# ── TestEmbeddingClassification ──────────────────────────────────────────

class TestEmbeddingClassification:

    def test_returns_none_below_threshold(self):
        """When all cosine scores are low, returns None (fallback to LLM)."""
        # Use near-zero query vector so cosine with random targets is ~0
        emb = _mock_embeddings(query_vec=[0.0001] * 8)
        chunks = _make_chunks(["Some text"])
        result = classify_by_embedding(chunks, emb, category_threshold=0.999)
        assert result is None

    def test_returns_category_when_confident(self):
        """When a category matches well, returns category + domains."""
        from app.classification import TAXONOMY

        # Build a mock where we control exactly what vectors are returned
        # We need: embed_documents called twice (categories, then domains),
        #          embed_query called once
        dim = 8
        num_categories = len([c for c in TAXONOMY if c != "other"])
        num_domains = sum(len(d) for c, d in TAXONOMY.items() if c != "other")

        # Make the first category vector match the query perfectly
        cat_vecs = np.random.RandomState(1).randn(num_categories, dim).tolist()
        dom_vecs = np.random.RandomState(2).randn(num_domains, dim).tolist()
        query_vec = cat_vecs[0]  # identical to first category

        call_count = [0]
        def _embed_docs(texts):
            call_count[0] += 1
            if call_count[0] == 1:
                return cat_vecs
            return dom_vecs

        emb = MagicMock()
        emb.__class__.__name__ = "MockConfident"
        emb.embed_documents.side_effect = _embed_docs
        emb.embed_query.return_value = query_vec

        chunks = _make_chunks(["Quantum physics research paper on terahertz emission"])
        result = classify_by_embedding(chunks, emb)

        assert result is not None
        assert len(result) >= 1
        # First element should be a category from our taxonomy
        first_cat = [c for c in TAXONOMY if c != "other"][0]
        assert result[0] == first_cat

    def test_empty_chunks(self):
        emb = _mock_embeddings()
        result = classify_by_embedding([], emb)
        assert result is None

    def test_cache_reuse(self):
        """Second call with same embeddings class doesn't re-embed taxonomy."""
        emb = _mock_embeddings()
        chunks = _make_chunks(["Test doc"])

        classify_by_embedding(chunks, emb, category_threshold=0.0)
        first_embed_count = emb.embed_documents.call_count

        classify_by_embedding(chunks, emb, category_threshold=0.0)
        second_embed_count = emb.embed_documents.call_count

        # embed_documents should NOT have been called again
        assert second_embed_count == first_embed_count


# ── TestSuggestCollectionsIntegration ────────────────────────────────────

class TestSuggestCollectionsIntegration:

    def test_without_embeddings_uses_llm(self):
        """When embeddings=None, LLM path is used (backward compat)."""
        from app.services.collection_suggester import suggest_collections

        llm = MagicMock()
        llm.invoke.return_value = MagicMock(content='["research-scientific", "physics"]')

        chunks = _make_chunks(["Some text about physics"])
        result = suggest_collections(chunks, llm, embeddings=None)
        assert llm.invoke.called
        assert "research-scientific" in result

    def test_with_embeddings_skips_llm_when_confident(self):
        """When embedding classifier returns a result, LLM is never called."""
        from app.services.collection_suggester import suggest_collections

        llm = MagicMock()
        chunks = _make_chunks(["Physics paper"])

        with patch("app.services.embedding_classifier.classify_by_embedding") as mock_cls:
            mock_cls.return_value = ["research-scientific", "fundamental-science"]
            emb = _mock_embeddings()
            result = suggest_collections(chunks, llm, embeddings=emb)

        assert not llm.invoke.called
        assert result == ["research-scientific", "fundamental-science"]

    def test_with_embeddings_falls_back_on_none(self):
        """When embedding classifier returns None, LLM is used as fallback."""
        from app.services.collection_suggester import suggest_collections

        llm = MagicMock()
        llm.invoke.return_value = MagicMock(content='["other"]')
        chunks = _make_chunks(["Ambiguous text"])

        with patch("app.services.embedding_classifier.classify_by_embedding") as mock_cls:
            mock_cls.return_value = None
            emb = _mock_embeddings()
            result = suggest_collections(chunks, llm, embeddings=emb)

        assert llm.invoke.called
        assert result == ["other"]
