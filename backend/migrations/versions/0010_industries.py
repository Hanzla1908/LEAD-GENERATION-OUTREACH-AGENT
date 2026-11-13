"""Multi-industry foundation: industry, subcategory, custom fields and website features on business records.

Adds (to restaurants, which holds every business record; the name is kept so existing data and APIs still work)
- industry: the industry key from industries.json. Existing records become restaurants_food.
- subcategory: the subcategory key chosen during discovery. Empty for records saved before this change.
- industry_fields: industry-specific custom values as JSON, limited to the fields the industry declares.
- website_features: per-feature website evidence as JSON: status (present, not_found or unknown) and evidence URLs.

Nothing is deleted or rewritten. Columns are added with ALTER TABLE, so the table's named CHECK and UNIQUE
constraints from earlier migrations are not rebuilt. Campaign and email history are untouched.
"""
import sqlalchemy as sa
from alembic import op

revision = "0010_industries"
down_revision = "0009_workspaces"
branch_labels = None
depends_on = None

DEFAULT_INDUSTRY = "restaurants_food"


def upgrade() -> None:
    op.add_column("restaurants", sa.Column("industry", sa.Text(), nullable=False, server_default=DEFAULT_INDUSTRY))
    op.add_column("restaurants", sa.Column("subcategory", sa.Text(), nullable=True))
    op.add_column("restaurants", sa.Column("industry_fields", sa.Text(), nullable=True))
    op.add_column("restaurants", sa.Column("website_features", sa.Text(), nullable=True))
    op.create_index("ix_restaurants_workspace_industry", "restaurants", ["workspace_id", "industry"])
    # Every record saved before this change is a restaurant.
    op.execute(sa.text("UPDATE restaurants SET industry = :industry WHERE industry IS NULL OR industry = ''")
               .bindparams(industry=DEFAULT_INDUSTRY))


def downgrade() -> None:
    op.drop_index("ix_restaurants_workspace_industry", table_name="restaurants")
    for column in ("website_features", "industry_fields", "subcategory", "industry"):
        op.drop_column("restaurants", column)
