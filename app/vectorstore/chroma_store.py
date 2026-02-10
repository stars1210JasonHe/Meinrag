from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from app.vectorstore.base import VectorStoreManager


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
        self, query: str, k: int, doc_ids: list[str] | None = None, collection: str | None = None
    ) -> list[Document]:
        where = None
        if doc_ids and collection:
            # Both filters: combine with $and
            where = {"$and": [{"doc_id": {"$in": doc_ids}}, {"collection": collection}]}
        elif doc_ids:
            where = {"doc_id": {"$in": doc_ids}}
        elif collection:
            where = {"collection": collection}

        return self._store.similarity_search(query, k=k, filter=where)

    def get_all_documents(self) -> list[Document]:
        results = self._store.get(include=["documents", "metadatas"])
        docs = []
        for content, metadata in zip(results["documents"], results["metadatas"]):
            docs.append(Document(page_content=content, metadata=metadata or {}))
        return docs

    def persist(self) -> None:
        pass  # Chroma auto-persists with persist_directory
