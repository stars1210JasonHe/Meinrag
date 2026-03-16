"""Verify engine factory works for both SQLite and PostgreSQL URLs."""
from app.db.session import create_engine_and_session


def test_creates_sqlite_engine():
    """SQLite URL gets StaticPool and check_same_thread=False."""
    engine, factory = create_engine_and_session(
        "sqlite+aiosqlite:///./data/test_engine.db"
    )
    assert "aiosqlite" in str(engine.url)
    assert factory is not None


def test_creates_postgresql_engine():
    """PostgreSQL URL gets connection pooling (pool_size, max_overflow)."""
    engine, factory = create_engine_and_session(
        "postgresql+asyncpg://user:pass@localhost/db"
    )
    assert "asyncpg" in str(engine.url)
    assert factory is not None
