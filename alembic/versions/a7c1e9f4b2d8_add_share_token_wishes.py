"""add share_token + wunsch_notiz to trainee, add trainee_wish

Revision ID: a7c1e9f4b2d8
Revises: f5db6557783c
Create Date: 2026-06-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel


# revision identifiers, used by Alembic.
revision: str = 'a7c1e9f4b2d8'
down_revision: Union[str, Sequence[str], None] = 'f5db6557783c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'trainee_wish',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trainee_id', sa.Integer(), nullable=False),
        sa.Column('department_id', sa.Integer(), nullable=False),
        sa.Column('prioritaet', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['department_id'], ['department.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['trainee_id'], ['trainee.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('trainee_id', 'department_id', name='uq_wish_trainee_dept'),
    )
    op.create_index('ix_trainee_wish_trainee_id', 'trainee_wish', ['trainee_id'], unique=False)

    with op.batch_alter_table('trainee', schema=None) as batch_op:
        batch_op.add_column(sa.Column('share_token', sqlmodel.sql.sqltypes.AutoString(length=36), nullable=True))
        batch_op.add_column(sa.Column('wunsch_notiz', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''))
        batch_op.create_index('ix_trainee_share_token', ['share_token'], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('trainee', schema=None) as batch_op:
        batch_op.drop_index('ix_trainee_share_token')
        batch_op.drop_column('wunsch_notiz')
        batch_op.drop_column('share_token')

    op.drop_index('ix_trainee_wish_trainee_id', table_name='trainee_wish')
    op.drop_table('trainee_wish')
