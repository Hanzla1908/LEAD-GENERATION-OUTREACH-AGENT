"""Delivery events, reply conversations, recipient delivery state and the mailbox sync cursor.

- email_events: one row per delivery event (delivered, deferred, bounced_soft, bounced_hard, rejected).
  event_key is unique, so the same provider event is never processed twice.
- email_conversations: inbound replies and unmatched inbound messages. message_key is unique, so the
  same mailbox message is never stored twice. match_status says how it was linked: matched, needs_review
  (uncertain, waiting for a person), or unmatched.
- campaign_recipients gains delivery_status (NULL = no confirmed event yet), delivery_detail,
  delivery_updated_at and replied_at. Existing rows keep NULL, which means "unknown".
- email_sync_state holds the mailbox cursor (last IMAP UID processed).

Revision ID: 0006_email_events_and_replies
Revises: 0005_email_verification
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_email_events_and_replies"
down_revision = "0005_email_verification"
branch_labels = None
depends_on = None

RECIPIENT_COLUMNS = [
    ("delivery_status", sa.Text()),
    ("delivery_detail", sa.Text()),
    ("delivery_updated_at", sa.DateTime()),
    ("replied_at", sa.DateTime()),
]


def upgrade() -> None:
    op.create_table(
        "email_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_key", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("provider_message_id", sa.Text(), nullable=True),
        sa.Column("recipient_email", sa.Text(), nullable=True),
        sa.Column("recipient_id", sa.Integer(), sa.ForeignKey("campaign_recipients.id"), nullable=True),
        sa.Column("campaign_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("event_key", name="uq_email_events_key"),
    )
    op.create_index("ix_email_events_message", "email_events", ["provider_message_id"])
    op.create_index("ix_email_events_recipient", "email_events", ["recipient_id"])

    op.create_table(
        "email_conversations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("message_key", sa.Text(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False, server_default=sa.text("'inbound'")),
        sa.Column("match_status", sa.Text(), nullable=False),
        sa.Column("match_reason", sa.Text(), nullable=True),
        sa.Column("campaign_id", sa.Integer(), nullable=True),
        sa.Column("recipient_id", sa.Integer(), sa.ForeignKey("campaign_recipients.id"), nullable=True),
        sa.Column("restaurant_id", sa.Integer(), nullable=True),
        sa.Column("in_reply_to", sa.Text(), nullable=True),
        sa.Column("references_ids", sa.Text(), nullable=True),
        sa.Column("from_address", sa.Text(), nullable=True),
        sa.Column("subject", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("message_key", name="uq_email_conversations_key"),
    )
    op.create_index("ix_email_conversations_recipient", "email_conversations", ["recipient_id"])
    op.create_index("ix_email_conversations_status", "email_conversations", ["match_status"])

    op.create_table(
        "email_sync_state",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True, server_default=sa.text("CURRENT_TIMESTAMP")),
    )

    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns("campaign_recipients")}
    for name, column_type in RECIPIENT_COLUMNS:
        if name not in existing:
            op.add_column("campaign_recipients", sa.Column(name, column_type, nullable=True))

    indexes = {index["name"] for index in inspector.get_indexes("email_send_ledger")}
    if "ix_email_send_ledger_provider_message" not in indexes:
        op.create_index("ix_email_send_ledger_provider_message", "email_send_ledger", ["provider_message_id"])


def downgrade() -> None:
    op.drop_index("ix_email_send_ledger_provider_message", table_name="email_send_ledger")
    for name, _column_type in reversed(RECIPIENT_COLUMNS):
        op.drop_column("campaign_recipients", name)
    op.drop_table("email_sync_state")
    op.drop_index("ix_email_conversations_status", table_name="email_conversations")
    op.drop_index("ix_email_conversations_recipient", table_name="email_conversations")
    op.drop_table("email_conversations")
    op.drop_index("ix_email_events_recipient", table_name="email_events")
    op.drop_index("ix_email_events_message", table_name="email_events")
    op.drop_table("email_events")
