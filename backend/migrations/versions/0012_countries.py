"""Country support: country_code and country_name on business records.

- country_code: the ISO 3166-1 alpha-2 code of the country a business was discovered in. Existing records are
  Pakistani, so they are assigned PK.
- country_name: the English name for that code. The existing `country` column already holds the name, so it is
  copied here and kept for compatibility.

Nothing is deleted. Campaign, email and draft history is untouched, and records keep the country they were saved with.
"""
import sqlalchemy as sa
from alembic import op

revision = "0012_countries"
down_revision = "0011_draft_edits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("restaurants", sa.Column("country_code", sa.Text(), nullable=False, server_default="PK"))
    op.add_column("restaurants", sa.Column("country_name", sa.Text(), nullable=True))
    op.create_index("ix_restaurants_workspace_country", "restaurants", ["workspace_id", "country_code"])
    # Every record saved before this change was discovered in Pakistan.
    op.execute(sa.text("UPDATE restaurants SET country_code = 'PK' WHERE country_code IS NULL OR country_code = ''"))
    op.execute(sa.text("UPDATE restaurants SET country_name = COALESCE(country, 'Pakistan') WHERE country_name IS NULL"))


def downgrade() -> None:
    op.drop_index("ix_restaurants_workspace_country", table_name="restaurants")
    op.drop_column("restaurants", "country_name")
    op.drop_column("restaurants", "country_code")
