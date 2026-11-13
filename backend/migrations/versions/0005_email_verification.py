"""Email verification results on restaurants: classification, reasons, check time and manual review.

Existing rows keep their values. New columns start empty, so every restaurant is re-checked the first time
it is approved or sent to (contact_email_checked_at is empty).

Revision ID: 0005_email_verification
Revises: 0004_email_send_ledger
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "0005_email_verification"
down_revision = "0004_email_send_ledger"
branch_labels = None
depends_on = None

NEW_COLUMNS = [
    ("contact_email_classification", sa.Text()),
    ("contact_email_reasons", sa.Text()),
    ("contact_email_mx_state", sa.Text()),
    ("contact_email_checked_at", sa.DateTime()),
    ("contact_email_reviewed_at", sa.DateTime()),
    ("contact_email_review_decision", sa.Text()),  # 'approved' or 'rejected'
    ("contact_email_review_note", sa.Text()),
]


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing = {column["name"] for column in inspector.get_columns("restaurants")}
    for name, column_type in NEW_COLUMNS:
        if name not in existing:
            op.add_column("restaurants", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    for name, _column_type in reversed(NEW_COLUMNS):
        op.drop_column("restaurants", name)
