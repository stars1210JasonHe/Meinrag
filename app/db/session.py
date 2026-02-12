"""Async database engine and session factory."""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession


def create_engine_and_session(database_url: str, echo: bool = False):
    """Create async engine and session factory.

    Returns (engine, session_factory) tuple.
    """
    engine = create_async_engine(
        database_url,
        echo=echo,
        pool_size=5,
        max_overflow=10,
    )
    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return engine, session_factory
