"""squashed initial schema

Revision ID: 0001squashed
Revises:
Create Date: 2026-06-18 00:00:00.000000

Replaces the previous 5-migration chain (cf3e27b74779 → f5db6557783c →
a7c1e9f4b2d8 → b3f2a9c5d1e7 → c4a8e1f2d3b9) with a single initial
migration that is safe on both SQLite (dev) and PostgreSQL (prod).

All str-enums use native_enum=False so they are stored as VARCHAR on every
backend.  No native PG ENUM type is created, and future enum value additions
never need ALTER TYPE … ADD VALUE.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = '0001squashed'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the full current schema from scratch."""

    # ------------------------------------------------------------------ #
    # schoolyear                                                           #
    # ------------------------------------------------------------------ #
    op.create_table(
        'schoolyear',
        sa.Column('id', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column('start_kw', sa.Integer(), nullable=False),
        sa.Column('start_year', sa.Integer(), nullable=False),
        sa.Column('end_kw', sa.Integer(), nullable=False),
        sa.Column('end_year', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )

    # ------------------------------------------------------------------ #
    # trainee_class                                                        #
    # ------------------------------------------------------------------ #
    op.create_table(
        'trainee_class',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('berufsschule', sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
        sa.Column(
            'unterrichts_typ',
            sa.Enum(
                'BLOCK_FEST', 'DH_PHASEN', 'TAGE_FEST',
                name='unterrichtstyp',
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column('schul_wochentage', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.Column('halbtag_wochentag', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index(op.f('ix_trainee_class_name'), 'trainee_class', ['name'], unique=True)

    # ------------------------------------------------------------------ #
    # department                                                           #
    # ------------------------------------------------------------------ #
    op.create_table(
        'department',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
        sa.Column(
            'kategorie',
            sa.Enum(
                'ITO', 'NON_ITO', 'EXTERN',
                name='departmentkategorie',
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column('ansprechpartner', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.Column('erlaubt_mehrfachbelegung', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('farbe', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default='#9CA3AF'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code'),
    )
    op.create_index(op.f('ix_department_code'), 'department', ['code'], unique=True)

    # ------------------------------------------------------------------ #
    # school_holiday                                                       #
    # ------------------------------------------------------------------ #
    op.create_table(
        'school_holiday',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('schoolyear_id', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('start_kw', sa.Integer(), nullable=False),
        sa.Column('start_year', sa.Integer(), nullable=False),
        sa.Column('end_kw', sa.Integer(), nullable=False),
        sa.Column('end_year', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['schoolyear_id'], ['schoolyear.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_school_holiday_schoolyear_id'), 'school_holiday', ['schoolyear_id'], unique=False)

    # ------------------------------------------------------------------ #
    # school_plan                                                          #
    # ------------------------------------------------------------------ #
    op.create_table(
        'school_plan',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('klasse_id', sa.Integer(), nullable=False),
        sa.Column('schoolyear_id', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.ForeignKeyConstraint(['klasse_id'], ['trainee_class.id']),
        sa.ForeignKeyConstraint(['schoolyear_id'], ['schoolyear.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('klasse_id', 'schoolyear_id', name='uq_plan_klasse_year'),
    )
    op.create_index(op.f('ix_school_plan_klasse_id'), 'school_plan', ['klasse_id'], unique=False)
    op.create_index(op.f('ix_school_plan_schoolyear_id'), 'school_plan', ['schoolyear_id'], unique=False)

    # ------------------------------------------------------------------ #
    # school_plan_week                                                     #
    # ------------------------------------------------------------------ #
    op.create_table(
        'school_plan_week',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('plan_id', sa.Integer(), nullable=False),
        sa.Column('kw', sa.Integer(), nullable=False),
        sa.Column('jahr', sa.Integer(), nullable=False),
        sa.Column(
            'typ',
            sa.Enum(
                'BERUFSSCHULE', 'UNI',
                name='schoolweektyp',
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(['plan_id'], ['school_plan.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('plan_id', 'kw', 'jahr', name='uq_planweek_plan_kw_jahr'),
    )
    op.create_index(op.f('ix_school_plan_week_jahr'), 'school_plan_week', ['jahr'], unique=False)
    op.create_index(op.f('ix_school_plan_week_kw'), 'school_plan_week', ['kw'], unique=False)
    op.create_index(op.f('ix_school_plan_week_plan_id'), 'school_plan_week', ['plan_id'], unique=False)

    # ------------------------------------------------------------------ #
    # trainee                                                              #
    # ------------------------------------------------------------------ #
    op.create_table(
        'trainee',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('vorname', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('nachname', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.Column('klasse_id', sa.Integer(), nullable=True),
        sa.Column(
            'rolle',
            sa.Enum(
                'AZUBI', 'DH_STUDENT', 'PRAKTIKANT', 'UMSCHUELER',
                name='traineeroll',
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column('aktiv', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('notizen', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.Column('share_token', sqlmodel.sql.sqltypes.AutoString(length=36), nullable=True),
        sa.Column('wunsch_notiz', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.ForeignKeyConstraint(['klasse_id'], ['trainee_class.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('share_token'),
    )
    op.create_index(op.f('ix_trainee_klasse_id'), 'trainee', ['klasse_id'], unique=False)
    op.create_index(op.f('ix_trainee_share_token'), 'trainee', ['share_token'], unique=True)

    # ------------------------------------------------------------------ #
    # assignment                                                           #
    # ------------------------------------------------------------------ #
    op.create_table(
        'assignment',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trainee_id', sa.Integer(), nullable=False),
        sa.Column('schoolyear_id', sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column('kw', sa.Integer(), nullable=False),
        sa.Column('jahr', sa.Integer(), nullable=False),
        sa.Column(
            'typ',
            sa.Enum(
                'ABTEILUNG', 'URLAUB', 'BERUFSSCHULE', 'UNI', 'FREI',
                name='assignmenttyp',
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column('abteilung_id', sa.Integer(), nullable=True),
        sa.Column(
            'source',
            sa.Enum(
                'AUTO', 'MANUAL', 'SELBST', 'SAP',
                name='assignmentsource',
                native_enum=False,
            ),
            nullable=False,
            server_default='MANUAL',
        ),
        sa.Column('notiz', sqlmodel.sql.sqltypes.AutoString(), nullable=False, server_default=''),
        sa.ForeignKeyConstraint(['abteilung_id'], ['department.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['schoolyear_id'], ['schoolyear.id']),
        sa.ForeignKeyConstraint(['trainee_id'], ['trainee.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('trainee_id', 'kw', 'jahr', name='uq_assign_trainee_kw_jahr'),
    )
    op.create_index(op.f('ix_assignment_schoolyear_id'), 'assignment', ['schoolyear_id'], unique=False)
    op.create_index(op.f('ix_assignment_trainee_id'), 'assignment', ['trainee_id'], unique=False)
    op.create_index('ix_assign_year_kw_dept', 'assignment', ['schoolyear_id', 'kw', 'abteilung_id'], unique=False)

    # ------------------------------------------------------------------ #
    # trainee_wish                                                         #
    # ------------------------------------------------------------------ #
    op.create_table(
        'trainee_wish',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('trainee_id', sa.Integer(), nullable=False),
        sa.Column('department_id', sa.Integer(), nullable=False),
        sa.Column('prioritaet', sa.Integer(), nullable=False, server_default='2'),
        sa.ForeignKeyConstraint(['department_id'], ['department.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['trainee_id'], ['trainee.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('trainee_id', 'department_id', name='uq_wish_trainee_dept'),
    )
    op.create_index(op.f('ix_trainee_wish_trainee_id'), 'trainee_wish', ['trainee_id'], unique=False)


def downgrade() -> None:
    """Drop all tables in reverse dependency order."""
    op.drop_table('trainee_wish')
    op.drop_index('ix_assign_year_kw_dept', table_name='assignment')
    op.drop_index(op.f('ix_assignment_trainee_id'), table_name='assignment')
    op.drop_index(op.f('ix_assignment_schoolyear_id'), table_name='assignment')
    op.drop_table('assignment')
    op.drop_index(op.f('ix_trainee_share_token'), table_name='trainee')
    op.drop_index(op.f('ix_trainee_klasse_id'), table_name='trainee')
    op.drop_table('trainee')
    op.drop_index(op.f('ix_school_plan_week_plan_id'), table_name='school_plan_week')
    op.drop_index(op.f('ix_school_plan_week_kw'), table_name='school_plan_week')
    op.drop_index(op.f('ix_school_plan_week_jahr'), table_name='school_plan_week')
    op.drop_table('school_plan_week')
    op.drop_index(op.f('ix_school_plan_schoolyear_id'), table_name='school_plan')
    op.drop_index(op.f('ix_school_plan_klasse_id'), table_name='school_plan')
    op.drop_table('school_plan')
    op.drop_index(op.f('ix_school_holiday_schoolyear_id'), table_name='school_holiday')
    op.drop_table('school_holiday')
    op.drop_index(op.f('ix_department_code'), table_name='department')
    op.drop_table('department')
    op.drop_index(op.f('ix_trainee_class_name'), table_name='trainee_class')
    op.drop_table('trainee_class')
    op.drop_table('schoolyear')
