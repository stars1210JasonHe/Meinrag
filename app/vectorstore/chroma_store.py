from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from app.vectorstore.base import VectorStoreManager, l2sq_to_score


class ChromaStoreManager(VectorStoreManager):
    def __init__(self, persist_directory: Path, collection_name: str = "meinrag"):
        self._persist_dir = str(persist_directory / "chroma")
        self._collection_name = collection_name
        self._store: Chroma | None = None

    def initialize(self, embeddings: Embeddings) -> None:
        self._store = Chroma(
            collection_name=self._collection_name,
            embedding_function=embeddings,
            persist_directory=self._persist_dir,
        )

    def add_documents(self, documents: list[Document], doc_id: str) -> list[str]:
        for doc in documents:
            doc.metadata["doc_id"] = doc_id
        return self._store.add_documents(documents)

    def delete_document(self, doc_id: str) -> None:
        results = self._store.get(where={"doc_id": doc_id})
        if results and results["ids"]:
            self._store.delete(ids=results["ids"])

    def similarity_search(self, query: str, k: int = 4) -> list[Document]:
        return self._store.similarity_search(query, k=k)

    def as_retriever(self, **kwargs):
        return self._store.as_retriever(**kwargs)

    def similarity_search_with_filter(
        self, query: str, k: int, doc_ids: list[str] | None = None,
    ) -> list[Document]:
        where = None
        if doc_ids:
            where = {"doc_id": {"$in": doc_ids}}
        return self._store.similarity_search(query, k=k, filter=where)

    def similarity_search_with_scores(
        self, query: str, k: int, doc_ids: list[str] | None = None,
    ) -> list[tuple[Document, float]]:
        where = None
        if doc_ids:
            where = {"doc_id": {"$in": doc_ids}}
        results = self._store.similarity_search_with_score(query, k=k, filter=where)
        return [(doc, l2sq_to_score(dist)) for doc, dist in results]

    def get_chunks_by_doc(self, doc_id: str, chunk_indices: list[int] | None = None) -> list[Document]:
        results = self._store.get(
            where={"doc_id": doc_id},
            include=["documents", "metadatas"],
        )
        if not results or not results["documents"]:
            return []
        docs = []
        for content, metadata in zip(results["documents"], results["metadatas"]):
            doc = Document(page_content=content, metadata=metadata or {})
            if chunk_indices is not None:
                idx = (metadata or {}).get("chunk_index")
                if idx not in chunk_indices:
                    continue
            docs.append(doc)
        docs.sort(key=lambda d: d.metadata.get("chunk_index", 0))
        return docs

    def get_all_documents(self) -> list[Document]:
        results = self._store.get(include=["documents", "metadatas"])
        docs = []
        for content, metadata in zip(results["documents"], results["metadatas"]):
            docs.append(Document(page_content=content, metadata=metadata or {}))
        return docs

    def persist(self) -> None:
        pass  # Chroma auto-persists with persist_directory

    def update_document_metadata(
        self, doc_id: str, metadata_updates: dict, persist: bool = True,
    ) -> None:
        """Update metadata on all chunks belonging to a document via ChromaDB's update().

        ``persist`` is ignored — Chroma writes are immediately durable.
        """
        results = self._store.get(where={"doc_id": doc_id}, include=["metadatas"])
        if not results or not results["ids"]:
            return
        # Build updated metadata list
        updated_metadatas = []
        for meta in results["metadatas"]:
            new_meta = {**meta, **metadata_updates}
            updated_metadatas.append(new_meta)
        # ChromaDB collection.update() for metadata-only changes
        self._store._collection.update(
            ids=results["ids"],
            metadatas=updated_metadatas,
        )
