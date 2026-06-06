"""Bug 1: a failed FAISS delete must NOT remove the registry row (else orphans
that the registry-first 404 can never clean)."""
import os
import tempfile

from fastapi.testclient import TestClient

from tests.test_search_endpoint import _make_search_app


def _upload(client, text="some legal content. " * 20):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(text)
        path = f.name
    try:
        with open(path, "rb") as fh:
            return client.post("/documents/upload?auto_suggest=false",
                               files={"file": ("d.txt", fh, "text/plain")}).json()["doc_id"]
    finally:
        os.unlink(path)


def test_delete_keeps_registry_when_faiss_delete_fails(tmp_path, monkeypatch):
    monkeypatch.setenv("ANONYMIZATION_ENABLED", "false")
    app = _make_search_app(tmp_path)
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            doc_id = _upload(client)

            def _boom(*a, **k):
                raise RuntimeError("simulated FAISS failure")
            app.state.vector_store.delete_document = _boom

            r = client.delete(f"/documents/{doc_id}")
            assert r.status_code >= 500                                   # delete refused
            assert client.get(f"/documents/{doc_id}/chunks").status_code != 404  # registry row intact
    finally:
        app.dependency_overrides.clear()


def test_delete_succeeds_normally(tmp_path, monkeypatch):
    monkeypatch.setenv("ANONYMIZATION_ENABLED", "false")
    app = _make_search_app(tmp_path)
    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            doc_id = _upload(client)
            assert client.delete(f"/documents/{doc_id}").status_code == 200
            listing = client.get("/documents").json()["documents"]
            assert all(d["doc_id"] != doc_id for d in listing)
    finally:
        app.dependency_overrides.clear()
