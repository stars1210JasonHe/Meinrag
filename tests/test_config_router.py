"""Router settings load from Settings with correct defaults."""
from app.config import Settings


def test_router_settings_default_on():
    """After 2026-04-22 eval: router ships default-on + retrieval_top_k=10."""
    s = Settings(_env_file=None)
    assert s.router_enabled is True
    assert s.router_min_scope == 15
    assert s.router_top_k == 8
    assert s.router_model == "gpt-4o-mini"
    assert s.retrieval_top_k == 10


def test_router_settings_env_override(monkeypatch):
    monkeypatch.setenv("ROUTER_ENABLED", "true")
    monkeypatch.setenv("ROUTER_MIN_SCOPE", "10")
    monkeypatch.setenv("ROUTER_TOP_K", "5")
    monkeypatch.setenv("ROUTER_MODEL", "gpt-4o")
    s = Settings()
    assert s.router_enabled is True
    assert s.router_min_scope == 10
    assert s.router_top_k == 5
    assert s.router_model == "gpt-4o"
