"""Tests for the deployment-level CLASSIFICATION_ENABLED switch.

A legal deployment sets CLASSIFICATION_ENABLED=false so the probabilistic
classifier never runs on ingest (doc_type comes from curated folder rules
instead). Default is True -> existing behavior unchanged.

Integration tests reuse the offline TestClient harness from the search-endpoint
suite (real FAISS + fake embeddings/LLM, no API key). Handlers read settings via
get_settings() -> Settings() -> env, so monkeypatch.setenv controls the flag.
ANONYMIZATION_ENABLED is forced off in upload tests to neutralize any local .env
value (which would otherwise trigger the upload anonymization block).
"""
from __future__ import annotations

import os
import tempfile

from fastapi.testclient import TestClient

from app.config import Settings
from tests.test_search_endpoint import _make_search_app


# ── config field ────────────────────────────────────────────────────────────

def test_classification_enabled_default_true(monkeypatch):
    monkeypatch.delenv("CLASSIFICATION_ENABLED", raising=False)
    assert Settings().classification_enabled is True


def test_classification_enabled_env_false(monkeypatch):
    monkeypatch.setenv("CLASSIFICATION_ENABLED", "false")
    assert Settings().classification_enabled is False


# ── integration helpers ─────────────────────────────────────────────────────

class _SpyResult:
    """Stand-in for ClassificationResult so the upload handler can read fields."""
    primary_category = "legal-compliance"
    subtags = ["regulation-policy"]
    collection_suggestions: list = []


def _upload_auto(client, filename, text):
    """Upload leaving auto_suggest at its default (True) — so the only thing
    gating classification is settings.classification_enabled."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
        f.write(text)
        path = f.name
    try:
        with open(path, "rb") as fh:
            return client.post(
                "/documents/upload",
                files={"file": (filename, fh, "text/plain")},
            )
    finally:
        os.unlink(path)


# ── upload gating ───────────────────────────────────────────────────────────

def test_upload_skips_classification_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("CLASSIFICATION_ENABLED", "false")
    monkeypatch.setenv("ANONYMIZATION_ENABLED", "false")  # neutralize local .env
    calls = []
    monkeypatch.setattr(
        "app.services.collection_suggester.classify_document",
        lambda *a, **k: (calls.append(1), _SpyResult())[1],
    )
    app = _make_search_app(tmp_path)
    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            r = _upload_auto(client, "d.txt", "Legal text about contracts and statutes. " * 20)
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    assert calls == []  # classifier never invoked when disabled


def test_upload_runs_classification_when_enabled(tmp_path, monkeypatch):
    monkeypatch.delenv("CLASSIFICATION_ENABLED", raising=False)  # default True
    monkeypatch.setenv("ANONYMIZATION_ENABLED", "false")
    calls = []
    monkeypatch.setattr(
        "app.services.collection_suggester.classify_document",
        lambda *a, **k: (calls.append(1), _SpyResult())[1],
    )
    app = _make_search_app(tmp_path)
    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            r = _upload_auto(client, "d.txt", "Legal text about contracts and statutes. " * 20)
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200, r.text
    assert calls == [1]  # classifier invoked once when enabled (default auto_suggest)


# ── reclassify gating ───────────────────────────────────────────────────────

def test_reclassify_403_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("CLASSIFICATION_ENABLED", "false")
    app = _make_search_app(tmp_path)
    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            r = client.post("/documents/anydoc/reclassify")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 403, r.text


def test_reclassify_passes_guard_when_enabled(tmp_path, monkeypatch):
    """Enabled + missing doc -> guard does NOT block; falls through to the
    normal 404. Proves the 403 is conditional on the flag, not unconditional."""
    monkeypatch.delenv("CLASSIFICATION_ENABLED", raising=False)  # default True
    app = _make_search_app(tmp_path)
    try:
        with TestClient(app, raise_server_exceptions=True) as client:
            r = client.post("/documents/missingdoc/reclassify")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 404, r.text
