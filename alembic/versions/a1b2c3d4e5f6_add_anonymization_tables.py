"""add anonymization tables

Revision ID: a1b2c3d4e5f6
Revises: 36101bbfabb3
Create Date: 2026-05-21 16:00:00.000000

Adds the two tables backing the PII anonymization plugin (Phase 1 of
docs/plans/2026-05-21-anonymization-plugin.md):

  - anonymization_mappings    (reversible pseudonym <-> Fernet-encrypted original)
  - anonymization_audit_log   (append-only compliance trail)

Both tables are inert when ANONYMIZATION_ENABLED=false — no inserts happen.
The migration is safe to apply unconditionally.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "36101bbfabb3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "anonymization_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(length=12),
            sa.ForeignKey("documents.doc_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_text_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("pseudonym", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_anon_mappings_doc",
        "anonymization_mappings",
        ["document_id"],
    )
    op.create_index(
        "ix_anon_mappings_pseudonym",
        "anonymization_mappings",
        ["document_id", "pseudonym"],
    )

    op.create_table(
        "anonymization_audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("document_id", sa.String(length=12), nullable=False),
        sa.Column("user_id", sa.String(length=50), nullable=True),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("entity_count", sa.Integer(), nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("source_deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "action IN ('anonymize', 'deanonymize', 'view')",
            name="ck_anon_audit_action",
        ),
    )
    op.create_index(
        "ix_anon_audit_doc",
        "anonymization_audit_log",
        ["document_id", "timestamp"],
    )


def downgrade() -> None:
    op.drop_index("ix_anon_audit_doc", table_name="anonymization_audit_log")
    op.drop_table("anonymization_audit_log")
    op.drop_index("ix_anon_mappings_pseudonym", table_name="anonymization_mappings")
    op.drop_index("ix_anon_mappings_doc", table_name="anonymization_mappings")
    op.drop_table("anonymization_mappings")
