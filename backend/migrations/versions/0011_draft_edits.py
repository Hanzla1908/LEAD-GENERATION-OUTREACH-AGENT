"""Draft edit time: when a person last changed a draft's subject or body.

Adds email_drafts.edited_at. Drafts that were never edited keep NULL. Nothing is deleted or rewritten.
"""
import sqlalchemy as sa
from alembic import op

revision = "0011_draft_edits"
down_revision = "0010_industries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("email_drafts", sa.Column("edited_at", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("email_drafts", "edited_at")
