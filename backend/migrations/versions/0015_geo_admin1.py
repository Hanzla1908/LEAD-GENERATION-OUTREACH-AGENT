"""First-level divisions (states, provinces, regions, territories) of every country, in geo_admin1.

Rows are written by the import script (backend/scripts/import_geonames.py) from GeoNames admin1CodesASCII.txt. The
primary key is the country code with the division code, so a code is never confused with the same code in another
country (for example "CA" is California in the US, and a province code elsewhere).

The composite index on geo_cities makes the state filter and the state list fast. Like the other geo_* tables, these
rows never reference restaurants, leads or Google Places records.
"""
import sqlalchemy as sa
from alembic import op

revision = "0015_geo_admin1"
down_revision = "0014_geo_cities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "geo_admin1",
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("ascii_name", sa.Text(), nullable=True),
        sa.Column("geoname_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("country_code", "code"),
    )
    op.create_index("ix_geo_cities_country_admin1_population", "geo_cities",
                    ["country_code", "admin1_code", "population"])


def downgrade() -> None:
    op.drop_index("ix_geo_cities_country_admin1_population", table_name="geo_cities")
    op.drop_table("geo_admin1")
