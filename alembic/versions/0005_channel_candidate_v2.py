"""Channel candidate v2 fields and username uniqueness.

Revision ID: 0005_channel_candidate_v2
Revises: 0004_batches
Create Date: 2026-05-29
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_channel_candidate_v2"
down_revision = "0004_batches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("channel_candidates") as batch:
        batch.add_column(sa.Column("last_seen_message_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("first_seen_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("last_seen_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("sample_texts_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("source_messages_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("notes", sa.Text(), nullable=True))
    op.execute("DELETE FROM channel_candidates WHERE username IS NULL OR trim(username) = ''")
    op.execute("UPDATE channel_candidates SET username = lower(ltrim(replace(replace(username, 'https://t.me/', ''), 'http://t.me/', ''), '@'))")
    op.execute(
        """
        UPDATE channel_candidates
        SET mentions_count = (
            SELECT SUM(COALESCE(c2.mentions_count, 0)) FROM channel_candidates c2 WHERE c2.username = channel_candidates.username
        ),
        thematic_score = (
            SELECT MAX(COALESCE(c2.thematic_score, 0)) FROM channel_candidates c2 WHERE c2.username = channel_candidates.username
        ),
        status = (
            SELECT c3.status FROM channel_candidates c3
            WHERE c3.username = channel_candidates.username
            ORDER BY CASE c3.status WHEN 'approved' THEN 4 WHEN 'rejected' THEN 3 WHEN 'pending' THEN 2 WHEN 'archived' THEN 1 ELSE 0 END DESC,
                     COALESCE(c3.mentions_count, 0) DESC,
                     c3.updated_at DESC
            LIMIT 1
        )
        WHERE username IN (SELECT username FROM channel_candidates GROUP BY username HAVING COUNT(*) > 1)
        """
    )
    op.execute(
        """
        DELETE FROM channel_candidates
        WHERE id NOT IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY username
                    ORDER BY CASE status WHEN 'approved' THEN 4 WHEN 'rejected' THEN 3 WHEN 'pending' THEN 2 WHEN 'archived' THEN 1 ELSE 0 END DESC,
                             COALESCE(mentions_count, 0) DESC,
                             updated_at DESC
                ) AS rn
                FROM channel_candidates
            ) ranked
            WHERE rn = 1
        )
        """
    )
    op.create_index("ux_channel_candidates_username", "channel_candidates", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index("ux_channel_candidates_username", table_name="channel_candidates")
    with op.batch_alter_table("channel_candidates") as batch:
        batch.drop_column("notes")
        batch.drop_column("source_messages_json")
        batch.drop_column("sample_texts_json")
        batch.drop_column("last_seen_at")
        batch.drop_column("first_seen_at")
        batch.drop_column("last_seen_message_id")
