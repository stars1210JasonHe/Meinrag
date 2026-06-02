"""Tests for configurable taxonomy path (multi-deployment support)."""
import json
from pathlib import Path

from app.config import Settings
from app.classification import _resolve_taxonomy_path, _load_taxonomy, _DEFAULT_TAXONOMY


# ── Settings field ────────────────────────────────────────────────────────

def test_taxonomy_path_defaults_to_data_taxonomy(monkeypatch):
    monkeypatch.delenv("TAXONOMY_PATH", raising=False)
    assert Settings().taxonomy_path == Path("data/taxonomy.json")


def test_taxonomy_path_overridden_by_env(monkeypatch):
    monkeypatch.setenv("TAXONOMY_PATH", "data/taxonomy.legal.json")
    assert Settings().taxonomy_path == Path("data/taxonomy.legal.json")


# ── classification path resolution ──────────────────────────────────────────

def test_resolve_taxonomy_path_honors_env(monkeypatch):
    monkeypatch.setenv("TAXONOMY_PATH", "data/taxonomy.legal.json")
    assert _resolve_taxonomy_path() == Path("data/taxonomy.legal.json")


def test_resolve_taxonomy_path_default(monkeypatch):
    monkeypatch.delenv("TAXONOMY_PATH", raising=False)
    assert _resolve_taxonomy_path() == Path("data/taxonomy.json")


def test_load_taxonomy_from_explicit_custom_file(tmp_path):
    custom = {"legal-only": {"statutes": ["national-law", "municipal-rule"]}}
    f = tmp_path / "taxonomy.custom.json"
    f.write_text(json.dumps(custom), encoding="utf-8")
    loaded = _load_taxonomy(f)
    assert loaded == custom


def test_load_taxonomy_writes_default_when_missing(tmp_path):
    # Pointing at a non-existent path returns the built-in default (and writes it).
    missing = tmp_path / "nope" / "taxonomy.json"
    loaded = _load_taxonomy(missing)
    assert loaded == _DEFAULT_TAXONOMY
    assert "legal-compliance" in loaded            # default unchanged
    assert "other" in loaded                       # fallback category present
    assert len(loaded) == 11                       # 10 domain categories + "other"
    assert missing.exists()                        # default was written
