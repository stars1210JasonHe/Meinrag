"""Async database engine and session factory."""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool


def create_engine_and_session(database_url: str, echo: bool = False):
    """Create async engine and session factory.

    Auto-detects SQLite vs PostgreSQL from the URL and applies
    the appropriate pool configuration.

    Returns (engine, session_factory) tuple.
    """
    is_sqlite = database_url.startswith("sqlite")

    engine_kwargs = {"echo": echo}
    if is_sqlite:
        engine_kwargs["poolclass"] = StaticPool
        engine_kwargs["connect_args"] = {"check_same_thread": False}
    else:
        engine_kwargs["pool_size"] = 5
        engine_kwargs["max_overflow"] = 10

    engine = create_async_engine(database_url, **engine_kwargs)
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return engine, session_factory
