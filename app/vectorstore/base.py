from abc import ABC, abstractmethod

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

def l2sq_to_score(l2_squared_dist: float) -> float:
    """Convert FAISS L2² distance to cosine similarity [0, 1].

    For unit-normalized vectors (e.g. OpenAI text-embedding-3-small):
        cosine_similarity = 1 - L2²/2   (from |a-b|² = 2 - 2·cos(a,b))

    Returns raw cosine similarity — no rescaling.
    """
    return max(0.0, 1.0 - l2_squared_dist / 2.0)


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
    def get_chunks_by_doc(
        self,
        doc_id: str,
        chunk_indices: list[int] | None = None,
        *,
        allowed_doc_ids: set[str] | None,
    ) -> list[Document]:
        """Return chunks for a doc, optionally filtered by chunk indices. Sorted by chunk_index.

        `allowed_doc_ids` is REQUIRED and keyword-only. This method is the common
        throat of every path that returns document content, so it is where the
        ownership decision is cheapest to make once and hardest to forget.

        Pass a set to restrict: a doc_id outside it yields no chunks. Pass None
        to mean "the caller has already established the scope" — legitimate for
        service-layer callers that only ever receive ids an authorised route
        resolved, and each such site says so at the call.

        It has no default ON PURPOSE, and please do not add one. A default would
        let any caller that nobody remembered to update silently keep the
        unscoped behaviour, which is precisely what this parameter exists to
        remove: a gate whose default is "open" is documentation, not a gate.
        Required means a new caller cannot reach content without deciding, and
        the decision shows up in review as an argument rather than as an absence.
        """
        ...

    @staticmethod
    def _scope_denies(doc_id: str, allowed_doc_ids: set[str] | None) -> bool:
        """Single definition of the scope check, shared by every concrete store.

        Two stores each re-implementing this is how one of them ends up without
        it; `tests/test_access_control_doc_scope.py` pins that they agree.
        """
        return allowed_doc_ids is not None and doc_id not in allowed_doc_ids

    @abstractmethod
    def persist(self) -> None:
        """Persist the store to disk (no-op if auto-persisted)."""
        ...

    @abstractmethod
    def update_document_metadata(
        self, doc_id: str, metadata_updates: dict, persist: bool = True,
    ) -> None:
        """Update metadata fields on all chunks belonging to a document.

        ``persist=False`` lets bulk callers batch many updates and call
        ``persist()`` once at the end (a FAISS persist rewrites the whole
        index file; per-doc persists make a 2,000-doc backfill unusable).
        Implementations that auto-persist may ignore the flag.
        """
        ...
