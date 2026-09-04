import logging
import os
import shutil
import tempfile
from pathlib import Path

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from app.vectorstore.base import VectorStoreManager, l2sq_to_score

logger = logging.getLogger(__name__)


def _try_gpu_index(store: FAISS) -> bool:
    """Attempt to move FAISS index to GPU. Returns True if successful."""
    try:
        import faiss as faiss_lib
        if not hasattr(faiss_lib, 'StandardGpuResources'):
            return False
        gpu_res = faiss_lib.StandardGpuResources()
        gpu_index = faiss_lib.index_cpu_to_gpu(gpu_res, 0, store.index)
        store.index = gpu_index
        logger.info("FAISS index moved to GPU")
        return True
    except Exception as e:
        logger.info("FAISS GPU not available, using CPU: %s", e)
        return False


class FAISSStoreManager(VectorStoreManager):
    def __init__(self, persist_directory: Path):
        self._persist_dir = Path(persist_directory) / "faiss"
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._store: FAISS | None = None
        self._embeddings: Embeddings | None = None
        self._gpu_enabled: bool = False
        # Lazy doc_id -> [docstore_id] map. Without it every get_chunks_by_doc
        # linearly scans the whole docstore — corpus-linear cost paid several
        # times per query (coverage, visual proximity, graph expansion).
        self._doc_id_index: dict[str, list[str]] | None = None

    def initialize(self, embeddings: Embeddings) -> None:
        self._embeddings = embeddings
        self._doc_id_index = None
        index_file = self._persist_dir / "index.faiss"
        if index_file.exists():
            self._store = FAISS.load_local(
                str(self._persist_dir),
                embeddings,
                index_name="index",
                allow_dangerous_deserialization=True,
            )
            self._gpu_enabled = _try_gpu_index(self._store)

    def add_documents(self, documents: list[Document], doc_id: str) -> list[str]:
        if not documents:
            # An empty batch reaches faiss as a 1-D array and crashes its
            # (n, d) shape unpack — refuse it here, callers get a no-op.
            return []
        for doc in documents:
            doc.metadata["doc_id"] = doc_id

        if self._store is None:
            self._store = FAISS.from_documents(documents, self._embeddings)
            self._gpu_enabled = _try_gpu_index(self._store)
        else:
            # GPU index doesn't support add — copy back to CPU, add, then move back
            if self._gpu_enabled:
                try:
                    import faiss as faiss_lib
                    self._store.index = faiss_lib.index_gpu_to_cpu(self._store.index)
                except Exception:
                    pass
            self._store.add_documents(documents)
            if self._gpu_enabled:
                _try_gpu_index(self._store)

        self._doc_id_index = None
        self.persist()
        return [f"{doc_id}_chunk_{i}" for i in range(len(documents))]

    def delete_document(self, doc_id: str) -> None:
        if self._store is None:
            return
        # Find docstore IDs for this document's chunks
        ids_to_delete = [
            store_id for store_id, doc in self._store.docstore._dict.items()
            if doc.metadata.get("doc_id") == doc_id
        ]
        if ids_to_delete:
            self._store.delete(ids_to_delete)
        # If all documents deleted, reset store
        if not self._store.docstore._dict:
            self._store = None
        self._doc_id_index = None
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
            idset = set(doc_ids)  # collection scopes reach thousands of ids
            candidates = [d for d in candidates if d.metadata.get("doc_id") in idset]
        return candidates[:k]

    def similarity_search_with_scores(
        self, query: str, k: int, doc_ids: list[str] | None = None,
    ) -> list[tuple[Document, float]]:
        if self._store is None:
            return []
        # Over-fetch then post-filter by doc_ids
        fetch_k = k * 5 if doc_ids else k
        results = self._store.similarity_search_with_score(query, k=fetch_k)
        if doc_ids:
            idset = set(doc_ids)
            results = [(d, s) for d, s in results if d.metadata.get("doc_id") in idset]
        return [(doc, l2sq_to_score(dist)) for doc, dist in results[:k]]

    def _get_doc_id_index(self) -> dict[str, list[str]]:
        """Build (once) the doc_id -> docstore-id map; mutators reset it to None."""
        if self._doc_id_index is None:
            index: dict[str, list[str]] = {}
            for store_id, doc in self._store.docstore._dict.items():
                index.setdefault(doc.metadata.get("doc_id"), []).append(store_id)
            self._doc_id_index = index
        return self._doc_id_index

    def get_chunks_by_doc(self, doc_id: str, chunk_indices: list[int] | None = None) -> list[Document]:
        if self._store is None:
            return []
        docstore = self._store.docstore._dict
        docs = []
        for store_id in self._get_doc_id_index().get(doc_id, []):
            doc = docstore.get(store_id)
            if doc is None:
                continue
            if chunk_indices is not None:
                if doc.metadata.get("chunk_index") not in chunk_indices:
                    continue
            docs.append(doc)
        docs.sort(key=lambda d: d.metadata.get("chunk_index", 0))
        return docs

    def get_all_documents(self) -> list[Document]:
        if self._store is None:
            return []
        return list(self._store.docstore._dict.values())

    def _atomic_save(self) -> None:
        """Write the index somewhere else, then rename it into place.

        ``FAISS.save_local`` writes ``index.faiss`` and ``index.pkl`` straight into the
        directory it is given, truncating each before refilling it. Measured on the NAS on
        2026-09-04 while an ingest was running, sampling the live file every 3 seconds for
        7 minutes:

            12.1% of wall clock the file was smaller than its final size
            9 separate episodes, each 3-9 seconds (mean 5.7 s)
            one sample caught it at ZERO bytes
            no temp sibling and no rename - the live file WAS the partial file

        A reader arriving in one of those windows gets ``EOFError: Ran out of input`` from
        ``pickle.load``. That is how this was found. The running service survives it only
        because its store is already in memory: a container restart during an ingest cannot
        load its own index, and the service does not come back. Nothing warns first.

        So the new bytes are built under a temp directory on the same filesystem, flushed,
        and then ``os.replace``d into position. ``os.replace`` is atomic within a
        filesystem, so a concurrent reader sees the whole old file or the whole new one.
        The failure mode also inverts: a save that dies halfway now leaves the previous
        index untouched, where in-place writing had already destroyed it before failing.

        HONEST LIMIT: two files means two renames, so a reader can still catch a new
        ``.faiss`` beside an old ``.pkl`` in the microseconds between them. That is a
        different and far smaller exposure than a multi-second truncation, but it is not
        zero, and closing it would need a directory swap or a symlink flip - a layout change
        that is not worth bundling into a fix for the truncation.
        """
        tmp = Path(tempfile.mkdtemp(prefix=".save-", dir=str(self._persist_dir.parent)))
        try:
            self._store.save_local(str(tmp), index_name="index")
            names = ("index.faiss", "index.pkl")
            for name in names:
                src = tmp / name
                if not src.exists():
                    raise RuntimeError(
                        "save_local produced no %s; refusing to publish a partial index"
                        % name)
                # Flush the DATA before any of it is published under the live name.
                # O_RDWR, not O_RDONLY: Windows FlushFileBuffers needs write access and
                # os.fsync on a read-only handle raises EBADF there. Linux accepts either,
                # so the read-only version would have passed in the container and failed
                # only on a developer machine - the test found it, not production.
                fd = os.open(str(src), os.O_RDWR)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            for name in names:
                os.replace(str(tmp / name), str(self._persist_dir / name))
            if os.name == "posix":
                # Flush the directory ENTRIES too, or the renames can be lost to power loss
                # while the file contents survive. Not possible on Windows, where opening a
                # directory is not permitted; production is a Linux container.
                dfd = os.open(str(self._persist_dir), os.O_RDONLY)
                try:
                    os.fsync(dfd)
                finally:
                    os.close(dfd)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def persist(self) -> None:
        if self._store is not None:
            # GPU index can't be saved directly — copy to CPU first
            if self._gpu_enabled:
                try:
                    import faiss as faiss_lib
                    cpu_index = faiss_lib.index_gpu_to_cpu(self._store.index)
                    self._store.index = cpu_index
                    self._atomic_save()
                    # Move back to GPU
                    _try_gpu_index(self._store)
                    return
                except Exception as e:
                    logger.warning("GPU→CPU persist failed, saving as-is: %s", e)
            self._atomic_save()

    def update_document_metadata(
        self, doc_id: str, metadata_updates: dict, persist: bool = True,
    ) -> None:
        """Update metadata on all chunks — direct docstore update, no rebuild."""
        if self._store is None:
            return
        docstore = self._store.docstore._dict
        updated = False
        for store_id in self._get_doc_id_index().get(doc_id, []):
            doc = docstore.get(store_id)
            if doc is not None:
                doc.metadata.update(metadata_updates)
                updated = True
        if updated and persist:
            self.persist()
