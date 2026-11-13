"""Soft delete for business leads: restaurants.deleted_at.

A deleted lead is hidden from lists, searches, eligibility and new outreach, and can be restored. Nothing is removed:
campaign recipients, drafts, the email ledger, replies and the audit log keep their rows and references.
"""
import sqlalchemy as sa
from alembic import op

revision = "0013_soft_delete_leads"
down_revision = "0012_countries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("restaurants", sa.Column("deleted_at", sa.Text(), nullable=True))
    op.create_index("ix_restaurants_workspace_deleted", "restaurants", ["workspace_id", "deleted_at"])


def downgrade() -> None:
    op.drop_index("ix_restaurants_workspace_deleted", table_name="restaurants")
    op.drop_column("restaurants", "deleted_at")
