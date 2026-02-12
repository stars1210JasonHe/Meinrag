"""Initial schema - users, documents, collections, chat sessions, messages.

Revision ID: 001
Revises:
Create Date: 2026-02-11
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(50), primary_key=True),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "documents",
        sa.Column("doc_id", sa.String(12), primary_key=True),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("file_type", sa.String(20), nullable=False),
        sa.Column("chunk_count", sa.Integer, default=0),
        sa.Column("user_id", sa.String(50), sa.ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False),
        sa.Column("file_hash", sa.String(64), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_documents_user_id", "documents", ["user_id"])
    op.create_index("ix_documents_file_hash", "documents", ["file_hash"])

    op.create_table(
        "document_collections",
        sa.Column("doc_id", sa.String(12), sa.ForeignKey("documents.doc_id", ondelete="CASCADE"), nullable=False),
        sa.Column("collection", sa.String(200), nullable=False),
        sa.PrimaryKeyConstraint("doc_id", "collection"),
    )
    op.create_index("ix_dc_collection", "document_collections", ["collection"])

    op.create_table(
        "chat_sessions",
        sa.Column("session_id", sa.String(100), primary_key=True),
        sa.Column("user_id", sa.String(50), sa.ForeignKey("users.user_id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_access", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(100), sa.ForeignKey("chat_sessions.session_id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('human', 'ai')", name="ck_message_role"),
    )
    op.create_index("ix_messages_session_created", "chat_messages", ["session_id", "created_at"])


def downgrade() -> None:
    op.drop_table("chat_messages")
    op.drop_table("chat_sessions")
    op.drop_table("document_collections")
    op.drop_table("documents")
    op.drop_table("users")
