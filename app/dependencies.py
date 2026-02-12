from collections.abc import AsyncGenerator

from fastapi import Depends, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.db.repositories import DocumentRepository, UserRepository, ChatSessionRepository
from app.vectorstore.base import VectorStoreManager
from langchain_core.language_models import BaseChatModel
from langchain_core.embeddings import Embeddings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_vector_store(request: Request) -> VectorStoreManager:
    return request.app.state.vector_store


def get_llm(request: Request) -> BaseChatModel:
    return request.app.state.llm


def get_embeddings(request: Request) -> Embeddings:
    return request.app.state.embeddings


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """Yield a request-scoped database session with auto commit/rollback."""
    session_factory = request.app.state.db_session_factory
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_registry(db: AsyncSession = Depends(get_db)) -> DocumentRepository:
    return DocumentRepository(db)


async def get_memory_manager(
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionRepository:
    return ChatSessionRepository(
        db,
        max_messages=settings.memory_max_messages,
        session_ttl=settings.memory_session_ttl,
    )


async def get_user_registry(db: AsyncSession = Depends(get_db)) -> UserRepository:
    return UserRepository(db)


async def get_current_user(
    settings: Settings = Depends(get_settings),
    user_registry: UserRepository = Depends(get_user_registry),
    x_user_id: str | None = Header(default=None),
) -> str:
    """Resolve current user from X-User-Id header, fallback to default.
    Auto-creates user if they don't exist yet."""
    user_id = x_user_id if x_user_id else settings.default_user
    await user_registry.ensure_exists(user_id, user_id.capitalize())
    return user_id
