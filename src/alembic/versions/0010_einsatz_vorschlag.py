"""EinsatzVorschlag-Tabelle (Azubi-Vorschlaege fuer kuenftige Einsaetze)

Revision ID: 0010vorschlag
Revises: 0009feedback
Create Date: 2026-07-21 00:00:00.000000

Aenderungen:
- Neue Tabelle einsatz_vorschlag: Vorschlag eines Azubis (ueber /mein-plan)
  fuer einen kuenftigen KW-Block in einer Abteilung, mit Status
  offen/angenommen/abgelehnt und optionaler Antwort der Planerin.

Postgres-safe: neue Tabelle, keine Aenderung an Bestandstabellen. Textspalten
sind nullable=True OHNE server_default (Anwendungsseite liefert die
Default-Werte "" beim Anlegen).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = '0010vorschlag'
down_revision: Union[str, Sequence[str], None] = '0009feedback'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'einsatz_vorschlag',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trainee_id', sa.Integer(), nullable=False),
        sa.Column('department_id', sa.Integer(), nullable=False),
        sa.Column('schoolyear_id', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column('kw_von', sa.Integer(), nullable=False),
        sa.Column('jahr_von', sa.Integer(), nullable=False),
        sa.Column('kw_bis', sa.Integer(), nullable=False),
        sa.Column('jahr_bis', sa.Integer(), nullable=False),
        sa.Column('kommentar', sa.Text(), nullable=True),
        sa.Column('eingereicht_von_upn', sa.Text(), nullable=True),
        sa.Column('eingereicht_von_name', sa.Text(), nullable=True),
        sa.Column('status', sa.Text(), nullable=True),
        sa.Column('antwort_kommentar', sa.Text(), nullable=True),
        sa.Column('erstellt_am', sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(['department_id'], ['department.id']),
        sa.ForeignKeyConstraint(['schoolyear_id'], ['schoolyear.id']),
        sa.ForeignKeyConstraint(['trainee_id'], ['trainee.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_einsatz_vorschlag_trainee_id'), 'einsatz_vorschlag', ['trainee_id'], unique=False
    )
    op.create_index(
        op.f('ix_einsatz_vorschlag_department_id'), 'einsatz_vorschlag', ['department_id'], unique=False
    )
    op.create_index(
        op.f('ix_einsatz_vorschlag_schoolyear_id'), 'einsatz_vorschlag', ['schoolyear_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_einsatz_vorschlag_schoolyear_id'), table_name='einsatz_vorschlag')
    op.drop_index(op.f('ix_einsatz_vorschlag_department_id'), table_name='einsatz_vorschlag')
    op.drop_index(op.f('ix_einsatz_vorschlag_trainee_id'), table_name='einsatz_vorschlag')
    op.drop_table('einsatz_vorschlag')
