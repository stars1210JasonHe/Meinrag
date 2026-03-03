from abc import ABC, abstractmethod

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

# Score rescaling constants for text-embedding-3-small.
# Raw cosine similarities typically fall in [0.15, 0.65] for this model.
# We rescale to [0, 1] for user-friendly display.
# Update these if switching to a different embedding model.
_COSINE_FLOOR = 0.15
_COSINE_RANGE = 0.50  # 0.65 - 0.15


def l2sq_to_score(l2_squared_dist: float) -> float:
    """Convert L2² distance to a user-friendly [0, 1] relevance score.

    For unit-normalized vectors (e.g. OpenAI text-embedding-3-small):
        cosine_similarity = 1 - L2²/2   (from |a-b|² = 2 - 2·cos(a,b))

    Then rescale from the model's typical cosine range to [0, 1].
    """
    cosine = 1.0 - l2_squared_dist / 2.0
    return min(1.0, max(0.0, (cosine - _COSINE_FLOOR) / _COSINE_RANGE))


class VectorStoreManager(ABC):
    """Abstract interface for vector store operations."""

    @abstractmethod
    def initialize(self, embeddings: Embeddings) -> None:
        """Initialize or load an existing vector store."""
        ...

    @abstractmethod
    def add_documents(self, documents: list[Document], doc_id: str) -> list[str]:
        """Add documents tagged with a logical document ID. Returns chunk IDs."""
        ...

    @abstractmethod
    def delete_document(self, doc_id: str) -> None:
        """Remove all chunks belonging to a document."""
        ...

    @abstractmethod
    def similarity_search(self, query: str, k: int = 4) -> list[Document]:
        """Return the top-k most similar documents."""
        ...

    @abstractmethod
    def as_retriever(self, **kwargs):
        """Return a LangChain-compatible retriever."""
        ...

    @abstractmethod
    def similarity_search_with_filter(
        self, query: str, k: int, doc_ids: list[str] | None = None,
    ) -> list[Document]:
        """Return top-k documents filtered by doc_ids."""
        ...

    @abstractmethod
    def similarity_search_with_scores(
        self, query: str, k: int, doc_ids: list[str] | None = None,
    ) -> list[tuple[Document, float]]:
        """Return top-k documents with similarity scores (0.0–1.0), optionally filtered by doc_ids."""
        ...

    @abstractmethod
    def get_all_documents(self) -> list[Document]:
        """Return all documents in the store (used for BM25 indexing)."""
        ...

    @abstractmethod
    def get_chunks_by_doc(self, doc_id: str, chunk_indices: list[int] | None = None) -> list[Document]:
        """Return chunks for a doc, optionally filtered by chunk indices. Sorted by chunk_index."""
        ...

    @abstractmethod
    def persist(self) -> None:
        """Persist the store to disk (no-op if auto-persisted)."""
        ...

    @abstractmethod
    def update_document_metadata(self, doc_id: str, metadata_updates: dict) -> None:
        """Update metadata fields on all chunks belonging to a document."""
        ...
