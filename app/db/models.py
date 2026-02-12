"""SQLAlchemy ORM models for MEINRAG."""
from datetime import datetime, timezone

from sqlalchemy import (
    String, Text, Integer, DateTime, ForeignKey, CheckConstraint, UniqueConstraint, Index,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class UserModel(Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(50), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    documents: Mapped[list["DocumentModel"]] = relationship(
        back_populates="user", cascade="all, delete-orphan",
    )
    sessions: Mapped[list["ChatSessionModel"]] = relationship(
        back_populates="user",
    )


class DocumentModel(Base):
    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(String(12), primary_key=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), nullable=False)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    user_id: Mapped[str] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    user: Mapped["UserModel"] = relationship(back_populates="documents")
    collections: Mapped[list["DocumentCollectionModel"]] = relationship(
        back_populates="document", cascade="all, delete-orphan",
    )

    def to_dict(self) -> dict:
        """Return dict matching the API response format."""
        result = {
            "doc_id": self.doc_id,
            "filename": self.filename,
            "file_type": self.file_type,
            "chunk_count": self.chunk_count,
            "collections": [dc.collection for dc in self.collections],
            "user_id": self.user_id,
            "uploaded_at": self.uploaded_at.isoformat(),
        }
        if self.file_hash:
            result["file_hash"] = self.file_hash
        return result


class DocumentCollectionModel(Base):
    __tablename__ = "document_collections"

    doc_id: Mapped[str] = mapped_column(
        String(12),
        ForeignKey("documents.doc_id", ondelete="CASCADE"),
        primary_key=True,
    )
    collection: Mapped[str] = mapped_column(String(200), primary_key=True, index=True)

    document: Mapped["DocumentModel"] = relationship(back_populates="collections")


class ChatSessionModel(Base):
    __tablename__ = "chat_sessions"

    session_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        String(50),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    last_access: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    user: Mapped["UserModel | None"] = relationship(back_populates="sessions")
    messages: Mapped[list["ChatMessageModel"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessageModel.created_at",
    )


class ChatMessageModel(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(
        String(100),
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        CheckConstraint("role IN ('human', 'ai')", name="ck_message_role"),
        Index("ix_messages_session_created", "session_id", "created_at"),
    )

    session: Mapped["ChatSessionModel"] = relationship(back_populates="messages")
