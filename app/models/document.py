import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


class DocumentRegistry:
    """Thread-safe JSON-backed document metadata store."""

    def __init__(self, metadata_file: Path):
        self._file = metadata_file
        self._lock = Lock()
        self._data: dict = self._load()

    def _load(self) -> dict:
        if self._file.exists():
            return json.loads(self._file.read_text(encoding="utf-8"))
        return {"documents": {}}

    def _save(self) -> None:
        self._file.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def add(self, doc_id: str, filename: str, file_type: str, chunk_count: int, collection: str | None = None) -> None:
        with self._lock:
            self._data["documents"][doc_id] = {
                "doc_id": doc_id,
                "filename": filename,
                "file_type": file_type,
                "chunk_count": chunk_count,
                "collection": collection,
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
            }
            self._save()

    def remove(self, doc_id: str) -> bool:
        with self._lock:
            if doc_id in self._data["documents"]:
                del self._data["documents"][doc_id]
                self._save()
                return True
            return False

    def get(self, doc_id: str) -> dict | None:
        return self._data["documents"].get(doc_id)

    def list_all(self) -> list[dict]:
        return list(self._data["documents"].values())

    def list_by_collection(self, collection: str) -> list[dict]:
        return [
            doc for doc in self._data["documents"].values()
            if doc.get("collection") == collection
        ]

    def count(self) -> int:
        return len(self._data["documents"])
