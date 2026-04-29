"""add primary_category and subtags to documents

Revision ID: 36101bbfabb3
Revises: dc0e861505bf
Create Date: 2026-04-29 11:51:18.687969

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '36101bbfabb3'
down_revision: Union[str, Sequence[str], None] = 'dc0e861505bf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('primary_category', sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column('subtags', sa.JSON(), server_default='[]', nullable=False))
        batch_op.create_index(batch_op.f('ix_documents_primary_category'), ['primary_category'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_documents_primary_category'))
        batch_op.drop_column('subtags')
        batch_op.drop_column('primary_category')
