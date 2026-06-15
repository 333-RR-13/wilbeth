"""add TAGE_FEST weekday fields to trainee_class

Revision ID: b3f2a9c5d1e7
Revises: a7c1e9f4b2d8
Create Date: 2026-06-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'b3f2a9c5d1e7'
down_revision: Union[str, Sequence[str], None] = 'a7c1e9f4b2d8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Neue Klassen-Felder fuer Wochentag-Schule (TAGE_FEST).
    # Der Enum-Wert TAGE_FEST braucht keine Schema-Aenderung: die Spalte
    # unterrichts_typ ist VARCHAR (SQLAlchemy-Enum ohne CHECK-Constraint).
    with op.batch_alter_table('trainee_class', schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            'schul_wochentage',
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default='',
        ))
        batch_op.add_column(sa.Column('halbtag_wochentag', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('trainee_class', schema=None) as batch_op:
        batch_op.drop_column('halbtag_wochentag')
        batch_op.drop_column('schul_wochentage')
