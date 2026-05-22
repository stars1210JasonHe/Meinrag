"""When ANONYMIZATION_ENABLED=true, BM25 must be turned off — anonymized
chunks contain typed placeholders that cannot match the user's raw query
tokens. Vector retrieval + reranker still run normally.
"""
import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.rag.chain import _should_use_bm25


def test_bm25_off_when_anonymization_enabled():
    s = Settings(
        hybrid_search_enabled=True,
        anonymization_enabled=True,
        anonymization_encryption_key=Fernet.generate_key().decode(),
        openai_api_key="x",
    )
    assert _should_use_bm25(s) is False


def test_bm25_on_when_only_hybrid_enabled():
    s = Settings(
        hybrid_search_enabled=True,
        anonymization_enabled=False,
        openai_api_key="x",
    )
    assert _should_use_bm25(s) is True


def test_bm25_off_when_hybrid_off():
    s = Settings(
        hybrid_search_enabled=False,
        anonymization_enabled=False,
        openai_api_key="x",
    )
    assert _should_use_bm25(s) is False
