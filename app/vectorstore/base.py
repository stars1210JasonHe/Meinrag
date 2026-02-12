from abc import ABC, abstractmethod

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings


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
    def get_all_documents(self) -> list[Document]:
        """Return all documents in the store (used for BM25 indexing)."""
        ...

    @abstractmethod
    def persist(self) -> None:
        """Persist the store to disk (no-op if auto-persisted)."""
        ...

    @abstractmethod
    def update_document_metadata(self, doc_id: str, metadata_updates: dict) -> None:
        """Update metadata fields on all chunks belonging to a document."""
        ...
