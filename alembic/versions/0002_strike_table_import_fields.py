from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_strike_table_import_fields"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    bind = op.get_bind()
    existing = {col["name"] for col in sa.inspect(bind).get_columns(table)}
    if column.name not in existing:
        op.add_column(table, column)


def upgrade() -> None:
    _add_column_if_missing("cases", sa.Column("oblast", sa.String(), nullable=True))
    _add_column_if_missing("cases", sa.Column("reference_text", sa.Text(), nullable=True))
    _add_column_if_missing("cases", sa.Column("raw_grid_northing", sa.String(), nullable=True))
    _add_column_if_missing("cases", sa.Column("raw_grid_easting", sa.String(), nullable=True))
    _add_column_if_missing("cases", sa.Column("coordinate_source", sa.String(), nullable=True))
    _add_column_if_missing("cases", sa.Column("parser_warnings", sa.Text(), nullable=True))
    _add_column_if_missing("jobs", sa.Column("params_json", sa.Text(), nullable=True))


def downgrade() -> None:
    # SQLite column drops require table rebuilds; leave runtime data intact.
    pass
