"""Server-side admin sessions (revocable on logout) and a status index for send-time checks.

Revision ID: 0002_auth_sessions
Revises: 0001_initial
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_auth_sessions"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "auth_sessions" not in inspector.get_table_names():
        op.create_table(
            "auth_sessions",
            sa.Column("id", sa.String(64), primary_key=True),
            sa.Column("expires_at", sa.BigInteger(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_auth_sessions_expires", "auth_sessions", ["expires_at"])

    existing = {index["name"] for index in inspector.get_indexes("campaign_recipients")}
    if "ix_campaign_recipients_status" not in existing:
        op.create_index("ix_campaign_recipients_status", "campaign_recipients", ["status"])


def downgrade() -> None:
    op.drop_index("ix_campaign_recipients_status", table_name="campaign_recipients")
    op.drop_index("ix_auth_sessions_expires", table_name="auth_sessions")
    op.drop_table("auth_sessions")
