"""Ersetze Department.kategorie-Enum durch DB-Tabelle department_kategorie

Revision ID: 0003kategorie
Revises: 0002membership
Create Date: 2026-06-29 00:00:00.000000

Aenderungen:
- Neue Tabelle department_kategorie (id, name unique)
- 4 Kategorien per bulk_insert anlegen
- Department.kategorie_id als nullable FK ergaenzen
- Backfill: bestehende kategorie-Werte auf die neue Tabelle abbilden
- Alte Spalte department.kategorie droppen

Postgres- und SQLite-kompatibel (batch_alter_table fuer SQLite).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel  # noqa: F401

# revision identifiers, used by Alembic.
revision: str = '0003kategorie'
down_revision: Union[str, Sequence[str], None] = '0002membership'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Mapping alter Enum-Wert → neuer Kategorie-Name
_ENUM_MAP = {
    'ITO': 'Platform Development',
    'NON_ITO': 'Grenke Digital',
    'EXTERN': 'Grenke AG',
}

_NEW_CATEGORIES = [
    'Platform Development',
    'Customer Service',
    'Grenke AG',
    'Grenke Digital',
]


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. Neue Tabelle department_kategorie anlegen                         #
    # ------------------------------------------------------------------ #
    kat_table = op.create_table(
        'department_kategorie',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index(
        op.f('ix_department_kategorie_name'),
        'department_kategorie', ['name'], unique=True,
    )

    # ------------------------------------------------------------------ #
    # 2. 4 Kategorien einfuegen                                            #
    # ------------------------------------------------------------------ #
    op.bulk_insert(
        kat_table,
        [{'name': name} for name in _NEW_CATEGORIES],
    )

    # ------------------------------------------------------------------ #
    # 3. Neue FK-Spalte kategorie_id in department ergaenzen               #
    #    (nullable, SQLite: batch_alter_table)                             #
    # ------------------------------------------------------------------ #
    with op.batch_alter_table('department', schema=None) as batch_op:
        batch_op.add_column(sa.Column('kategorie_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_department_kategorie_id',
            'department_kategorie',
            ['kategorie_id'], ['id'],
        )
        batch_op.create_index('ix_department_kategorie_id', ['kategorie_id'], unique=False)

    # ------------------------------------------------------------------ #
    # 4. Backfill: alter Enum-Wert → ID der neuen Tabelle                 #
    # ------------------------------------------------------------------ #
    conn = op.get_bind()

    # IDs der neuen Kategorien abfragen
    rows = conn.execute(
        sa.text("SELECT id, name FROM department_kategorie")
    ).fetchall()
    kat_id_by_name = {row[1]: row[0] for row in rows}

    for old_val, new_name in _ENUM_MAP.items():
        new_id = kat_id_by_name.get(new_name)
        if new_id is not None:
            conn.execute(
                sa.text(
                    "UPDATE department SET kategorie_id = :kid "
                    "WHERE kategorie = :old"
                ),
                {"kid": new_id, "old": old_val},
            )

    # ------------------------------------------------------------------ #
    # 5. Alte Spalte department.kategorie droppen                          #
    # ------------------------------------------------------------------ #
    with op.batch_alter_table('department', schema=None) as batch_op:
        batch_op.drop_column('kategorie')


def downgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. Alte Spalte kategorie wieder hinzufuegen (als VARCHAR)            #
    # ------------------------------------------------------------------ #
    with op.batch_alter_table('department', schema=None) as batch_op:
        batch_op.add_column(sa.Column('kategorie', sqlmodel.sql.sqltypes.AutoString(), nullable=True))

    # ------------------------------------------------------------------ #
    # 2. Backfill: kategorie_id → alten Enum-Wert                         #
    # ------------------------------------------------------------------ #
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, name FROM department_kategorie")
    ).fetchall()
    name_to_old = {v: k for k, v in {
        'ITO': 'Platform Development',
        'NON_ITO': 'Grenke Digital',
        'EXTERN': 'Grenke AG',
    }.items()}

    for row in rows:
        kat_id, kat_name = row[0], row[1]
        old_val = name_to_old.get(kat_name)
        if old_val:
            conn.execute(
                sa.text(
                    "UPDATE department SET kategorie = :old "
                    "WHERE kategorie_id = :kid"
                ),
                {"old": old_val, "kid": kat_id},
            )

    # ------------------------------------------------------------------ #
    # 3. FK-Spalte und Index droppen                                       #
    # ------------------------------------------------------------------ #
    with op.batch_alter_table('department', schema=None) as batch_op:
        batch_op.drop_index('ix_department_kategorie_id')
        batch_op.drop_constraint('fk_department_kategorie_id', type_='foreignkey')
        batch_op.drop_column('kategorie_id')

    # ------------------------------------------------------------------ #
    # 4. Tabelle department_kategorie droppen                              #
    # ------------------------------------------------------------------ #
    op.drop_index(op.f('ix_department_kategorie_name'), table_name='department_kategorie')
    op.drop_table('department_kategorie')
