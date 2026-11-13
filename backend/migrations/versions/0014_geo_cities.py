"""Global city database from GeoNames: geo_cities, geo_city_alternate_names and geo_import_runs.

These tables hold open city data only (GeoNames, CC BY 4.0). They never reference restaurants, leads or Google
Places records, so the restricted Google content stays separate. Rows are written by the import script
(backend/scripts/import_geonames.py); this migration only creates the empty tables and their indexes.
"""
import sqlalchemy as sa
from alembic import op

revision = "0014_geo_cities"
down_revision = "0013_soft_delete_leads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # geonameid from GeoNames is the primary key, so ids stay stable across re-imports.
    op.create_table(
        "geo_cities",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("ascii_name", sa.Text(), nullable=True),
        sa.Column("search_name", sa.Text(), nullable=False),
        sa.Column("admin1_code", sa.Text(), nullable=True),
        sa.Column("admin1_name", sa.Text(), nullable=True),
        sa.Column("population", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("feature_code", sa.Text(), nullable=True),
    )
    # Lookups always start with the country, so each index leads with country_code.
    op.create_index("ix_geo_cities_country_search", "geo_cities", ["country_code", "search_name"])
    op.create_index("ix_geo_cities_country_population", "geo_cities", ["country_code", "population"])

    op.create_table(
        "geo_city_alternate_names",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("city_id", sa.Integer(), sa.ForeignKey("geo_cities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("country_code", sa.String(2), nullable=False),
        sa.Column("alt_name", sa.Text(), nullable=False),
        sa.Column("search_name", sa.Text(), nullable=False),
    )
    op.create_index("ix_geo_alt_country_search", "geo_city_alternate_names", ["country_code", "search_name"])
    op.create_index("ix_geo_alt_city", "geo_city_alternate_names", ["city_id"])

    op.create_table(
        "geo_import_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("file_sha256", sa.Text(), nullable=True),
        sa.Column("city_count", sa.Integer(), nullable=False),
        sa.Column("alternate_name_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("licence", sa.Text(), nullable=False),
        sa.Column("imported_at", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("geo_import_runs")
    op.drop_index("ix_geo_alt_city", table_name="geo_city_alternate_names")
    op.drop_index("ix_geo_alt_country_search", table_name="geo_city_alternate_names")
    op.drop_table("geo_city_alternate_names")
    op.drop_index("ix_geo_cities_country_population", table_name="geo_cities")
    op.drop_index("ix_geo_cities_country_search", table_name="geo_cities")
    op.drop_table("geo_cities")
