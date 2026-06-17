"""add farbe field to department

Revision ID: c4a8e1f2d3b9
Revises: b3f2a9c5d1e7
Create Date: 2026-06-17 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'c4a8e1f2d3b9'
down_revision: Union[str, Sequence[str], None] = 'b3f2a9c5d1e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add farbe column to department, then seed known colors."""
    with op.batch_alter_table('department', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'farbe',
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default='#9CA3AF',
        ))

    # Data migration: set per-department colors for known department codes
    op.execute("UPDATE department SET farbe = '#FACC15' WHERE code = 'Sec'")
    op.execute("UPDATE department SET farbe = '#F0E6C8' WHERE code = 'CISO'")
    op.execute("UPDATE department SET farbe = '#7DD3FC' WHERE code = 'DP'")
    op.execute("UPDATE department SET farbe = '#A855F7' WHERE code = 'AI'")
    op.execute("UPDATE department SET farbe = '#9CA3AF' WHERE code = 'CP'")
    op.execute("UPDATE department SET farbe = '#FB923C' WHERE code = 'IAM'")
    op.execute("UPDATE department SET farbe = '#1E3A8A' WHERE code = 'DWP'")
    op.execute("UPDATE department SET farbe = '#EF4444' WHERE code = 'OP'")
    op.execute("UPDATE department SET farbe = '#22C55E' WHERE code = 'BA'")
    op.execute("UPDATE department SET farbe = '#F472B6' WHERE code = 'CS'")
    op.execute("UPDATE department SET farbe = '#14B8A6' WHERE code = 'DDAS'")
    op.execute("UPDATE department SET farbe = '#92400E' WHERE code = 'KGaA'")
    op.execute("UPDATE department SET farbe = '#E879F9' WHERE code = 'HR'")
    op.execute("UPDATE department SET farbe = '#FB7185' WHERE code = 'MK'")
    op.execute("UPDATE department SET farbe = '#65A30D' WHERE code = 'FM'")
    op.execute("UPDATE department SET farbe = '#0EA5E9' WHERE code = 'VT'")
    op.execute("UPDATE department SET farbe = '#6366F1' WHERE code = 'BANK'")
    op.execute("UPDATE department SET farbe = '#D97706' WHERE code = 'POST'")
    op.execute("UPDATE department SET farbe = '#84CC16' WHERE code = 'EMP'")


def downgrade() -> None:
    """Downgrade schema: drop farbe column from department."""
    with op.batch_alter_table('department', schema=None) as batch_op:
        batch_op.drop_column('farbe')
