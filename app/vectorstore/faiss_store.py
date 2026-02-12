from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from app.vectorstore.base import VectorStoreManager


class FAISSStoreManager(VectorStoreManager):
    def __init__(self, persist_directory: Path):
        self._persist_dir = Path(persist_directory) / "faiss"
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._store: FAISS | None = None
        self._embeddings: Embeddings | None = None

    def initialize(self, embeddings: Embeddings) -> None:
        self._embeddings = embeddings
        index_file = self._persist_dir / "index.faiss"
        if index_file.exists():
            self._store = FAISS.load_local(
                str(self._persist_dir),
                embeddings,
                index_name="index",
                allow_dangerous_deserialization=True,
            )

    def add_documents(self, documents: list[Document], doc_id: str) -> list[str]:
        for doc in documents:
            doc.metadata["doc_id"] = doc_id

        if self._store is None:
            self._store = FAISS.from_documents(documents, self._embeddings)
        else:
            self._store.add_documents(documents)

        self.persist()
        return [f"{doc_id}_chunk_{i}" for i in range(len(documents))]

    def delete_document(self, doc_id: str) -> None:
        if self._store is None:
            return
        # FAISS lacks metadata-filtered deletion — rebuild without target doc's chunks
        all_docs = []
        for doc_store_id in list(self._store.docstore._dict.keys()):
            doc = self._store.docstore._dict[doc_store_id]
            if doc.metadata.get("doc_id") != doc_id:
                all_docs.append(doc)

        if all_docs:
            self._store = FAISS.from_documents(all_docs, self._embeddings)
        else:
            self._store = None
        self.persist()

    def similarity_search(self, query: str, k: int = 4) -> list[Document]:
        if self._store is None:
            return []
        return self._store.similarity_search(query, k=k)

    def as_retriever(self, **kwargs):
        if self._store is None:
            raise ValueError("FAISS store is empty. Upload documents first.")
        return self._store.as_retriever(**kwargs)

    def similarity_search_with_filter(
        self, query: str, k: int, doc_ids: list[str] | None = None,
    ) -> list[Document]:
        if self._store is None:
            return []
        # Over-fetch then post-filter by doc_ids
        candidates = self._store.similarity_search(query, k=k * 5)
        if doc_ids:
            candidates = [d for d in candidates if d.metadata.get("doc_id") in doc_ids]
        return candidates[:k]

    def get_all_documents(self) -> list[Document]:
        if self._store is None:
            return []
        return list(self._store.docstore._dict.values())

    def persist(self) -> None:
        if self._store is not None:
            self._store.save_local(str(self._persist_dir), index_name="index")

    def update_document_metadata(self, doc_id: str, metadata_updates: dict) -> None:
        """Update metadata on all chunks — FAISS requires rebuild."""
        if self._store is None:
            return
        all_docs = []
        for doc_store_id in list(self._store.docstore._dict.keys()):
            doc = self._store.docstore._dict[doc_store_id]
            if doc.metadata.get("doc_id") == doc_id:
                doc.metadata.update(metadata_updates)
            all_docs.append(doc)

        if all_docs:
            self._store = FAISS.from_documents(all_docs, self._embeddings)
            self.persist()
