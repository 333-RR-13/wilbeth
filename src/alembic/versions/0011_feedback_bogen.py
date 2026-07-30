"""FeedbackBogen-Tabelle (Feedbackboegen AUSBILDER/AZUBI zu Abteilungs-Einsaetzen)

Revision ID: 0011bogen
Revises: 0010vorschlag
Create Date: 2026-07-29 00:00:00.000000

Aenderungen:
- Neue Tabelle feedback_bogen: Feedbackbogen zu einem KW-Block eines
  Trainees in einer Abteilung. Zwei Typen (typ: "AUSBILDER"|"AZUBI"),
  Status-Workflow entwurf -> abgeschlossen -> besprochen -> (nur AUSBILDER)
  bestaetigt. Enthaelt JSON-Spalten fuer die variable Lernziel-Liste, die
  Skala-Antworten und die Freitextfelder.

Postgres-safe: neue Tabelle, keine Aenderung an Bestandstabellen. Text-
spalten sind nullable=True OHNE server_default (Anwendungsseite liefert die
Default-Werte "" beim Anlegen), ebenso die Integer- und JSON-Spalten
(nullable=True, kein server_default). Einzige Ausnahme ist die
Boolean-Spalte zugriffe_geloescht: server_default=sa.false() rendert
dialekt-korrekt (PostgreSQL: false, SQLite: 0) -- NIEMALS sa.text('0')
verwenden, das ist PG-inkompatibel.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = '0011bogen'
down_revision: Union[str, Sequence[str], None] = '0010vorschlag'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'feedback_bogen',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('typ', sa.Text(), nullable=True),
        sa.Column('bogen_version', sa.Text(), nullable=True),
        sa.Column('trainee_id', sa.Integer(), nullable=False),
        sa.Column('department_id', sa.Integer(), nullable=False),
        sa.Column('schoolyear_id', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column('kw_von', sa.Integer(), nullable=False),
        sa.Column('jahr_von', sa.Integer(), nullable=False),
        sa.Column('kw_bis', sa.Integer(), nullable=False),
        sa.Column('jahr_bis', sa.Integer(), nullable=False),
        sa.Column('einsatzart', sa.Text(), nullable=True),
        sa.Column('fachausbilder_name', sa.Text(), nullable=True),
        sa.Column('lernziele', sa.JSON(), nullable=True),
        sa.Column('antworten', sa.JSON(), nullable=True),
        sa.Column('freitexte', sa.JSON(), nullable=True),
        sa.Column('fehl_krank', sa.Integer(), nullable=True),
        sa.Column('fehl_urlaub', sa.Integer(), nullable=True),
        sa.Column('fehl_schule', sa.Integer(), nullable=True),
        sa.Column('fehl_sonstige', sa.Integer(), nullable=True),
        sa.Column('weiterer_einsatz', sa.Text(), nullable=True),
        sa.Column(
            'zugriffe_geloescht', sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ),
        sa.Column('status', sa.Text(), nullable=True),
        sa.Column('besprochen_am', sa.Date(), nullable=True),
        sa.Column('bestaetigt_am', sa.Date(), nullable=True),
        sa.Column('erstellt_von_upn', sa.Text(), nullable=True),
        sa.Column('erstellt_am', sa.Date(), nullable=True),
        sa.Column('aktualisiert_am', sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(['department_id'], ['department.id']),
        sa.ForeignKeyConstraint(['schoolyear_id'], ['schoolyear.id']),
        sa.ForeignKeyConstraint(['trainee_id'], ['trainee.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_feedback_bogen_trainee_id'), 'feedback_bogen', ['trainee_id'], unique=False
    )
    op.create_index(
        op.f('ix_feedback_bogen_department_id'), 'feedback_bogen', ['department_id'], unique=False
    )
    op.create_index(
        op.f('ix_feedback_bogen_schoolyear_id'), 'feedback_bogen', ['schoolyear_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_feedback_bogen_schoolyear_id'), table_name='feedback_bogen')
    op.drop_index(op.f('ix_feedback_bogen_department_id'), table_name='feedback_bogen')
    op.drop_index(op.f('ix_feedback_bogen_trainee_id'), table_name='feedback_bogen')
    op.drop_table('feedback_bogen')
