"""Persistent email send ledger in the application database.

One row per campaign recipient records whether the send was reserved, sent, failed (the provider
definitely refused it, so a retry is allowed), or uncertain (the outcome is unknown, so it is never
retried automatically and waits for manual review).

Backfill: existing campaign history becomes ledger rows so that recipients that were already emailed
can never be emailed again by this ledger:
  sent                                  -> sent
  failed with no provider message id   -> failed (retry allowed, as before)
  anything else that reached the sending step (sending, interrupted, failed with an id)
                                        -> uncertain (manual review; never resent automatically)
Queued, draft and skipped recipients never reached the provider, so they get no row.

Revision ID: 0004_email_send_ledger
Revises: 0003_list_indexes
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "0004_email_send_ledger"
down_revision = "0003_list_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_send_ledger",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("campaign_id", sa.Integer(), nullable=False),
        sa.Column("recipient_id", sa.Integer(), sa.ForeignKey("campaign_recipients.id"), nullable=False),
        sa.Column("restaurant_id", sa.Integer(), nullable=True),
        sa.Column("draft_id", sa.Integer(), nullable=True),
        sa.Column("recipient_email", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("provider_message_id", sa.Text(), nullable=True),
        sa.Column("failure_detail", sa.Text(), nullable=True),
        sa.Column("reserved_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("campaign_id", "recipient_id", name="uq_email_send_ledger_recipient"),
        sa.UniqueConstraint("idempotency_key", name="uq_email_send_ledger_key"),
    )
    op.create_index("ix_email_send_ledger_campaign", "email_send_ledger", ["campaign_id"])
    op.create_index("ix_email_send_ledger_status", "email_send_ledger", ["status"])

    op.execute(sa.text("""
        INSERT INTO email_send_ledger
            (campaign_id, recipient_id, restaurant_id, draft_id, recipient_email, status, attempts,
             idempotency_key, provider_message_id, failure_detail, reserved_at, finished_at, created_at, updated_at)
        SELECT r.campaign_id, r.id, r.restaurant_id, r.draft_id, r.recipient_email,
               CASE WHEN r.status = 'sent' THEN 'sent'
                    WHEN r.status = 'failed' AND r.provider_message_id IS NULL THEN 'failed'
                    ELSE 'uncertain' END,
               1,
               'campaign-' || CAST(r.campaign_id AS TEXT) || '-recipient-' || CAST(r.id AS TEXT),
               r.provider_message_id,
               r.error_reason,
               r.created_at,
               CASE WHEN r.status = 'sent' THEN r.sent_at ELSE NULL END,
               r.created_at,
               r.updated_at
        FROM campaign_recipients r
        WHERE r.status IN ('sent', 'failed', 'interrupted', 'sending')
    """))


def downgrade() -> None:
    op.drop_index("ix_email_send_ledger_status", table_name="email_send_ledger")
    op.drop_index("ix_email_send_ledger_campaign", table_name="email_send_ledger")
    op.drop_table("email_send_ledger")
