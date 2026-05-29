from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_match_review_fields"
down_revision = "0002_strike_table_import_fields"
branch_labels = None
depends_on = None


def _add_column_if_missing(table: str, column: sa.Column) -> None:
    bind = op.get_bind()
    existing = {col["name"] for col in sa.inspect(bind).get_columns(table)}
    if column.name not in existing:
        op.add_column(table, column)


def upgrade() -> None:
    _add_column_if_missing("case_matches", sa.Column("review_status", sa.String(), nullable=True, server_default="pending"))
    _add_column_if_missing("case_matches", sa.Column("review_note", sa.Text(), nullable=True))
    _add_column_if_missing("case_matches", sa.Column("score_details_json", sa.Text(), nullable=True))
    _add_column_if_missing("case_matches", sa.Column("reject_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    pass
