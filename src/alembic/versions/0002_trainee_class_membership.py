"""Klassen-Mitgliedschaft pro Lehrjahr + next_class_id

Revision ID: 0002membership
Revises: 0001squashed
Create Date: 2026-06-24 00:00:00.000000

Aenderungen:
- Neue Tabelle trainee_class_membership (trainee_id, schoolyear_id, klasse_id)
  mit UniqueConstraint uq_membership_trainee_year
- Neue nullable Spalte trainee_class.next_class_id (Self-FK, nullable)

Postgres-safe: nur neue Tabelle + nullable Spalte (kein Rewrite noetig).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = '0002membership'
down_revision: Union[str, Sequence[str], None] = '0001squashed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # trainee_class_membership                                             #
    # ------------------------------------------------------------------ #
    op.create_table(
        'trainee_class_membership',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trainee_id', sa.Integer(), nullable=False),
        sa.Column('schoolyear_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('klasse_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['trainee_id'], ['trainee.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['schoolyear_id'], ['schoolyear.id']),
        sa.ForeignKeyConstraint(['klasse_id'], ['trainee_class.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('trainee_id', 'schoolyear_id', name='uq_membership_trainee_year'),
    )
    op.create_index(
        op.f('ix_trainee_class_membership_trainee_id'),
        'trainee_class_membership', ['trainee_id'], unique=False,
    )
    op.create_index(
        op.f('ix_trainee_class_membership_schoolyear_id'),
        'trainee_class_membership', ['schoolyear_id'], unique=False,
    )
    op.create_index(
        op.f('ix_trainee_class_membership_klasse_id'),
        'trainee_class_membership', ['klasse_id'], unique=False,
    )

    # ------------------------------------------------------------------ #
    # trainee_class.next_class_id (nullable Self-FK)                       #
    # batch_alter_table fuer SQLite-Kompatibilitaet (render_as_batch=True) #
    # ------------------------------------------------------------------ #
    with op.batch_alter_table('trainee_class', schema=None) as batch_op:
        batch_op.add_column(sa.Column('next_class_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_trainee_class_next_class_id',
            'trainee_class',
            ['next_class_id'], ['id'],
        )


def downgrade() -> None:
    with op.batch_alter_table('trainee_class', schema=None) as batch_op:
        batch_op.drop_constraint('fk_trainee_class_next_class_id', type_='foreignkey')
        batch_op.drop_column('next_class_id')

    op.drop_index(op.f('ix_trainee_class_membership_klasse_id'), table_name='trainee_class_membership')
    op.drop_index(op.f('ix_trainee_class_membership_schoolyear_id'), table_name='trainee_class_membership')
    op.drop_index(op.f('ix_trainee_class_membership_trainee_id'), table_name='trainee_class_membership')
    op.drop_table('trainee_class_membership')
