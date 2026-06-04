"""LLM/embedding calls must be bounded — no call may use the OpenAI client
default (~600s), or one hang deadlocks ingest and starves /search."""
from app.config import Settings


def test_llm_timeout_defaults():
    s = Settings(_env_file=None, openai_api_key="sk-test")
    assert s.llm_timeout == 60.0
    assert s.llm_max_retries == 2


def test_llm_timeout_env_override(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT", "45")
    monkeypatch.setenv("LLM_MAX_RETRIES", "1")
    s = Settings(_env_file=None, openai_api_key="sk-test")
    assert s.llm_timeout == 45.0
    assert s.llm_max_retries == 1


from app.llm.provider import create_chat_model, create_embeddings


def test_chat_model_is_bounded():
    s = Settings(_env_file=None, openai_api_key="sk-test")
    m = create_chat_model(s)
    # langchain_openai aliases the `timeout` ctor arg to `request_timeout`
    assert m.request_timeout == s.llm_timeout
    assert m.max_retries == s.llm_max_retries


def test_embeddings_are_bounded():
    s = Settings(_env_file=None, openai_api_key="sk-test")
    e = create_embeddings(s)
    assert e.request_timeout == s.llm_timeout
    assert e.max_retries == s.llm_max_retries
