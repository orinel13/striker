"""Add analysis batches.

Revision ID: 0004_batches
Revises: 0003_match_review_fields
Create Date: 2026-05-29
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_batches"
down_revision = "0003_match_review_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "case_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("source_filename", sa.String(), nullable=True),
        sa.Column("original_path", sa.String(), nullable=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=True),
        sa.Column("period_end", sa.Date(), nullable=True),
        sa.Column("night_mode", sa.Boolean(), nullable=True),
        sa.Column("rollover_hour", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("cases_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("matches_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("approved_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("pending_count", sa.Integer(), nullable=True, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.add_column("cases", sa.Column("batch_id", sa.Integer(), sa.ForeignKey("case_batches.id"), nullable=True))
    op.add_column("jobs", sa.Column("batch_id", sa.Integer(), sa.ForeignKey("case_batches.id"), nullable=True))
    op.add_column("exports", sa.Column("batch_id", sa.Integer(), sa.ForeignKey("case_batches.id"), nullable=True))
    op.add_column("evidence_files", sa.Column("batch_id", sa.Integer(), sa.ForeignKey("case_batches.id"), nullable=True))
    op.add_column("firms_points", sa.Column("batch_id", sa.Integer(), sa.ForeignKey("case_batches.id"), nullable=True))
    op.execute(
        "INSERT INTO case_batches (created_at, updated_at, source_filename, title, status, night_mode, cases_count, matches_count, approved_count, pending_count) "
        "SELECT CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'legacy', 'Legacy imported cases', 'active', 0, 0, 0, 0, 0 "
        "WHERE EXISTS (SELECT 1 FROM cases WHERE batch_id IS NULL)"
    )
    op.execute("UPDATE cases SET batch_id = (SELECT id FROM case_batches WHERE source_filename='legacy' ORDER BY id LIMIT 1) WHERE batch_id IS NULL")
    op.create_index("ix_cases_batch_id", "cases", ["batch_id"])
    op.create_index("ix_exports_batch_id", "exports", ["batch_id"])
    op.create_index("ix_jobs_batch_id", "jobs", ["batch_id"])


def downgrade() -> None:
    op.drop_index("ix_jobs_batch_id", table_name="jobs")
    op.drop_index("ix_exports_batch_id", table_name="exports")
    op.drop_index("ix_cases_batch_id", table_name="cases")
    op.drop_column("firms_points", "batch_id")
    op.drop_column("evidence_files", "batch_id")
    op.drop_column("exports", "batch_id")
    op.drop_column("jobs", "batch_id")
    op.drop_column("cases", "batch_id")
    op.drop_table("case_batches")
