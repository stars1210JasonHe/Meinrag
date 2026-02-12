"""Async PostgreSQL-backed repositories.

Same public interface as the old JSON/in-memory classes,
but all methods are async and use SQLAlchemy sessions.
"""
import logging
from datetime import datetime, timezone

from langchain_core.messages import AIMessage, HumanMessage, BaseMessage
from sqlalchemy import select, delete, func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import (
    DocumentModel,
    DocumentCollectionModel,
    UserModel,
    ChatSessionModel,
    ChatMessageModel,
)

logger = logging.getLogger(__name__)


class DocumentRepository:
    """Async PostgreSQL-backed document metadata store."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(
        self,
        doc_id: str,
        filename: str,
        file_type: str,
        chunk_count: int,
        collections: list[str] | None = None,
        user_id: str = "admin",
        file_hash: str | None = None,
    ) -> None:
        doc = DocumentModel(
            doc_id=doc_id,
            filename=filename,
            file_type=file_type,
            chunk_count=chunk_count,
            user_id=user_id,
            file_hash=file_hash,
        )
        self._session.add(doc)
        for coll_name in (collections or ["other"]):
            self._session.add(
                DocumentCollectionModel(doc_id=doc_id, collection=coll_name)
            )
        await self._session.flush()

    async def remove(self, doc_id: str) -> bool:
        result = await self._session.execute(
            delete(DocumentModel).where(DocumentModel.doc_id == doc_id)
        )
        await self._session.flush()
        return result.rowcount > 0

    async def get(self, doc_id: str) -> dict | None:
        stmt = (
            select(DocumentModel)
            .options(selectinload(DocumentModel.collections))
            .where(DocumentModel.doc_id == doc_id)
        )
        result = await self._session.execute(stmt)
        doc = result.scalar_one_or_none()
        return doc.to_dict() if doc else None

    async def list_all(self, user_id: str | None = None) -> list[dict]:
        stmt = select(DocumentModel).options(selectinload(DocumentModel.collections))
        if user_id:
            stmt = stmt.where(DocumentModel.user_id == user_id)
        result = await self._session.execute(stmt)
        return [doc.to_dict() for doc in result.scalars().all()]

    async def list_by_collection(
        self, collection: str, user_id: str | None = None
    ) -> list[dict]:
        stmt = (
            select(DocumentModel)
            .options(selectinload(DocumentModel.collections))
            .join(DocumentCollectionModel)
            .where(DocumentCollectionModel.collection == collection)
        )
        if user_id:
            stmt = stmt.where(DocumentModel.user_id == user_id)
        result = await self._session.execute(stmt)
        return [doc.to_dict() for doc in result.unique().scalars().all()]

    async def update_collections(self, doc_id: str, collections: list[str]) -> bool:
        result = await self._session.execute(
            select(DocumentModel).where(DocumentModel.doc_id == doc_id)
        )
        if not result.scalar_one_or_none():
            return False
        await self._session.execute(
            delete(DocumentCollectionModel).where(
                DocumentCollectionModel.doc_id == doc_id
            )
        )
        for coll_name in collections:
            self._session.add(
                DocumentCollectionModel(doc_id=doc_id, collection=coll_name)
            )
        await self._session.flush()
        return True

    async def get_all_collections(self, user_id: str | None = None) -> list[str]:
        stmt = select(DocumentCollectionModel.collection).distinct()
        if user_id:
            stmt = stmt.join(DocumentModel).where(DocumentModel.user_id == user_id)
        result = await self._session.execute(stmt)
        return sorted(result.scalars().all())

    async def count(self) -> int:
        result = await self._session.execute(
            select(func.count()).select_from(DocumentModel)
        )
        return result.scalar_one()


class UserRepository:
    """Async PostgreSQL-backed user store."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, user_id: str, display_name: str) -> dict:
        user = UserModel(user_id=user_id, display_name=display_name)
        self._session.add(user)
        await self._session.flush()
        return {
            "user_id": user.user_id,
            "display_name": user.display_name,
            "created_at": user.created_at.isoformat(),
        }

    async def get(self, user_id: str) -> dict | None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.user_id == user_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            return None
        return {
            "user_id": user.user_id,
            "display_name": user.display_name,
            "created_at": user.created_at.isoformat(),
        }

    async def ensure_exists(self, user_id: str, display_name: str) -> None:
        """Create user if not exists. Safe under concurrent access."""
        if await self.exists(user_id):
            return
        try:
            async with self._session.begin_nested():
                self._session.add(
                    UserModel(user_id=user_id, display_name=display_name)
                )
        except IntegrityError:
            pass  # Already exists from concurrent creation

    async def exists(self, user_id: str) -> bool:
        result = await self._session.execute(
            select(func.count()).select_from(UserModel).where(
                UserModel.user_id == user_id
            )
        )
        return result.scalar_one() > 0

    async def list_all(self) -> list[dict]:
        result = await self._session.execute(select(UserModel))
        return [
            {
                "user_id": u.user_id,
                "display_name": u.display_name,
                "created_at": u.created_at.isoformat(),
            }
            for u in result.scalars().all()
        ]


class ChatSessionRepository:
    """Async PostgreSQL-backed chat session store.

    Same interface as SessionMemoryManager: get_history() and add_exchange().
    """

    def __init__(self, session: AsyncSession, max_messages: int = 20, session_ttl: int = 3600):
        self._session = session
        self._max_messages = max_messages
        self._session_ttl = session_ttl

    async def get_history(self, session_id: str) -> list[BaseMessage]:
        # Clean up expired sessions
        await self._cleanup_expired()

        result = await self._session.execute(
            select(ChatSessionModel).where(
                ChatSessionModel.session_id == session_id
            )
        )
        chat_session = result.scalar_one_or_none()
        if not chat_session:
            return []

        # Update last access
        chat_session.last_access = datetime.now(timezone.utc)

        # Fetch messages ordered by created_at
        msg_result = await self._session.execute(
            select(ChatMessageModel)
            .where(ChatMessageModel.session_id == session_id)
            .order_by(ChatMessageModel.created_at)
        )
        messages: list[BaseMessage] = []
        for msg in msg_result.scalars().all():
            if msg.role == "human":
                messages.append(HumanMessage(content=msg.content))
            else:
                messages.append(AIMessage(content=msg.content))
        return messages

    async def add_exchange(self, session_id: str, question: str, answer: str) -> None:
        # Ensure session exists
        result = await self._session.execute(
            select(ChatSessionModel).where(
                ChatSessionModel.session_id == session_id
            )
        )
        chat_session = result.scalar_one_or_none()
        if not chat_session:
            chat_session = ChatSessionModel(session_id=session_id)
            self._session.add(chat_session)
            await self._session.flush()

        # Add the two messages
        now = datetime.now(timezone.utc)
        self._session.add(ChatMessageModel(
            session_id=session_id, role="human", content=question, created_at=now,
        ))
        self._session.add(ChatMessageModel(
            session_id=session_id, role="ai", content=answer, created_at=now,
        ))
        chat_session.last_access = now
        await self._session.flush()

        # Trim to max_messages (keep most recent)
        count_result = await self._session.execute(
            select(func.count()).select_from(ChatMessageModel).where(
                ChatMessageModel.session_id == session_id
            )
        )
        total = count_result.scalar_one()
        if total > self._max_messages:
            # Find the oldest messages to delete
            oldest = await self._session.execute(
                select(ChatMessageModel.id)
                .where(ChatMessageModel.session_id == session_id)
                .order_by(ChatMessageModel.created_at)
                .limit(total - self._max_messages)
            )
            ids_to_delete = [row[0] for row in oldest.all()]
            if ids_to_delete:
                await self._session.execute(
                    delete(ChatMessageModel).where(
                        ChatMessageModel.id.in_(ids_to_delete)
                    )
                )
                await self._session.flush()

    async def _cleanup_expired(self) -> None:
        cutoff = datetime.now(timezone.utc).timestamp() - self._session_ttl
        cutoff_dt = datetime.fromtimestamp(cutoff, tz=timezone.utc)
        await self._session.execute(
            delete(ChatSessionModel).where(
                ChatSessionModel.last_access < cutoff_dt
            )
        )
