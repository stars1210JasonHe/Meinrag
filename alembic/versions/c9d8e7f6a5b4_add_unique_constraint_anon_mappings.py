"""add unique constraint on anonymization_mappings(document_id, pseudonym)

Revision ID: c9d8e7f6a5b4
Revises: a1b2c3d4e5f6
Create Date: 2026-05-22 00:00:00.000000

Adds a UNIQUE constraint on (document_id, pseudonym) so that re-processing a
document via save_batch cannot create duplicate rows. Without this, the dict
comprehension in get_by_doc would silently drop earlier values, and a caller
calling save_batch twice would accumulate stale rows.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d8e7f6a5b4"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_anon_mappings_doc_pseudonym",
        "anonymization_mappings",
        ["document_id", "pseudonym"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_anon_mappings_doc_pseudonym",
        "anonymization_mappings",
        type_="unique",
    )
