"""EVAL BRANCH ONLY: RERANK_PROVIDER_EVAL in .env must win over RERANK_PROVIDER in the process environment."""
import pytest

from app.config import RerankProvider, Settings


def test_env_var_outranks_dotenv_without_override(tmp_path, monkeypatch):
    # The problem being worked around: a plain RERANK_PROVIDER in .env loses to the container's env var.
    monkeypatch.setenv("RERANK_PROVIDER", "llm")
    env = tmp_path / ".env"
    env.write_text("RERANK_PROVIDER=openrouter\n", encoding="utf-8")
    assert Settings(_env_file=str(env)).rerank_provider == RerankProvider.LLM


def test_eval_override_from_dotenv_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("RERANK_PROVIDER", "llm")
    env = tmp_path / ".env"
    env.write_text("RERANK_PROVIDER_EVAL=openrouter\nRERANK_MODEL=voyageai/rerank-3\n", encoding="utf-8")
    s = Settings(_env_file=str(env))
    assert s.rerank_provider == RerankProvider.OPENROUTER and s.rerank_model == "voyageai/rerank-3"


def test_empty_override_changes_nothing(monkeypatch):
    monkeypatch.setenv("RERANK_PROVIDER", "llm")
    assert Settings(_env_file=None).rerank_provider == RerankProvider.LLM


def test_bad_override_fails_loudly():
    with pytest.raises(Exception):
        Settings(_env_file=None, rerank_provider_eval="nonexistent")
