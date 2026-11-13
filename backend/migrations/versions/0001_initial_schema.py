"""Initial schema: restaurants, drafts, campaigns, suppression, send logs.

Safe on an empty PostgreSQL database and on the existing local SQLite file:
tables that already exist are left alone and only missing columns are added.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

INTEGER = sa.Integer()
TEXT = sa.Text()
FLOAT = sa.Float()
TIMESTAMP = sa.DateTime()
NOW = "CURRENT_TIMESTAMP"

# name, type, server default (SQL text or None), nullable
TABLES = {
    "restaurants": {
        "columns": [
            ("id", INTEGER, None, False),
            ("place_id", TEXT, None, False),
            ("name", TEXT, None, False),
            ("address", TEXT, None, True),
            ("phone", TEXT, None, True),
            ("website", TEXT, None, True),
            ("latitude", FLOAT, None, True),
            ("longitude", FLOAT, None, True),
            ("source", TEXT, "'google_places'", True),
            ("website_status", TEXT, "'unknown'", True),
            ("ordering_status", TEXT, "'unknown'", True),
            ("ordering_evidence", TEXT, None, True),
            ("website_checked_at", TIMESTAMP, None, True),
            ("website_error", TEXT, None, True),
            ("contact_email", TEXT, None, True),
            ("contact_email_source", TEXT, None, True),
            ("contact_email_status", TEXT, "'unverified'", True),
            ("contact_discovered_at", TIMESTAMP, None, True),
            ("lead_score", INTEGER, None, True),
            ("lead_status", TEXT, "'new'", True),
            ("lead_reason", TEXT, None, True),
            ("lead_qualified_at", TIMESTAMP, None, True),
            ("opted_out", INTEGER, "0", True),
            ("created_at", TIMESTAMP, NOW, True),
            ("city", TEXT, None, True),
            ("country", TEXT, "'Pakistan'", True),
            ("google_fetched_at", TIMESTAMP, None, True),
            ("listing_expired", INTEGER, "0", True),
        ],
        "primary_key": ("id",),
        "unique": [("place_id",)],
    },
    "leads": {
        "columns": [
            ("id", INTEGER, None, False),
            ("name", TEXT, None, False),
            ("address", TEXT, None, True),
            ("phone", TEXT, None, True),
            ("email", TEXT, None, True),
            ("website", TEXT, None, True),
            ("status", TEXT, "'new'", True),
            ("created_at", TIMESTAMP, NOW, True),
        ],
        "primary_key": ("id",),
        "unique": [],
    },
    "email_drafts": {
        "columns": [
            ("id", INTEGER, None, False),
            ("restaurant_id", INTEGER, None, False),
            ("campaign", TEXT, "'default'", False),
            ("subject", TEXT, None, False),
            ("body", TEXT, None, False),
            ("status", TEXT, "'draft'", False),
            ("angle", TEXT, None, True),
            ("created_at", TIMESTAMP, NOW, True),
            ("updated_at", TIMESTAMP, NOW, True),
            ("campaign_id", INTEGER, None, True),
        ],
        "primary_key": ("id",),
        "unique": [],
    },
    "campaigns": {
        "columns": [
            ("id", INTEGER, None, False),
            ("name", TEXT, None, False),
            ("status", TEXT, "'generating'", False),
            ("status_note", TEXT, None, True),
            ("created_at", TIMESTAMP, NOW, True),
            ("updated_at", TIMESTAMP, NOW, True),
            ("approved_draft_ids", TEXT, None, True),
            ("approved_at", TIMESTAMP, None, True),
        ],
        "primary_key": ("id",),
        "unique": [],
    },
    "campaign_recipients": {
        "columns": [
            ("id", INTEGER, None, False),
            ("campaign_id", INTEGER, None, False),
            ("restaurant_id", INTEGER, None, False),
            ("recipient_email", TEXT, None, True),
            ("draft_id", INTEGER, None, True),
            ("status", TEXT, None, False),
            ("skip_reason", TEXT, None, True),
            ("error_reason", TEXT, None, True),
            ("provider_message_id", TEXT, None, True),
            ("sent_at", TIMESTAMP, None, True),
            ("created_at", TIMESTAMP, NOW, True),
            ("updated_at", TIMESTAMP, NOW, True),
        ],
        "primary_key": ("id",),
        "unique": [("campaign_id", "restaurant_id")],
    },
    "suppression_list": {
        "columns": [
            ("email", TEXT, None, False),
            ("reason", TEXT, None, True),
            ("created_at", TIMESTAMP, NOW, True),
        ],
        "primary_key": ("email",),
        "unique": [],
    },
    "campaign_send_logs": {
        "columns": [
            ("id", INTEGER, None, False),
            ("campaign_id", INTEGER, None, False),
            ("recipient_id", INTEGER, None, True),
            ("restaurant_id", INTEGER, None, True),
            ("recipient_email", TEXT, None, True),
            ("event", TEXT, None, False),
            ("detail", TEXT, None, True),
            ("created_at", TIMESTAMP, NOW, True),
        ],
        "primary_key": ("id",),
        "unique": [],
    },
}

INDEXES = [
    ("campaign_recipients", "ix_campaign_recipients_campaign", ["campaign_id"]),
    ("email_drafts", "ix_email_drafts_restaurant", ["restaurant_id"]),
    ("campaign_send_logs", "ix_campaign_send_logs_campaign", ["campaign_id"]),
]


def _column(name, column_type, default, nullable, primary_key=False):
    server_default = sa.text(default) if default is not None else None
    return sa.Column(name, column_type, nullable=nullable, server_default=server_default,
                     primary_key=primary_key, autoincrement=primary_key and name == "id")


def _create_or_extend(inspector, table: str, spec: dict) -> None:
    if table in inspector.get_table_names():
        existing = {column["name"] for column in inspector.get_columns(table)}
        for name, column_type, default, nullable in spec["columns"]:
            if name not in existing:
                op.add_column(table, _column(name, column_type, default, True))
        return
    primary = set(spec["primary_key"])
    columns = [_column(name, column_type, default, nullable, name in primary)
               for name, column_type, default, nullable in spec["columns"]]
    constraints = [sa.UniqueConstraint(*fields, name=f"uq_{table}_{'_'.join(fields)}") for fields in spec["unique"]]
    op.create_table(table, *columns, *constraints)


def _has_duplicate_active_drafts() -> bool:
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT restaurant_id, campaign FROM email_drafts WHERE status = 'draft' "
        "GROUP BY restaurant_id, campaign HAVING COUNT(*) > 1"
    )).fetchall()
    return bool(rows)


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    for table, spec in TABLES.items():
        _create_or_extend(inspector, table, spec)

    inspector = sa.inspect(op.get_bind())
    for table, index_name, columns in INDEXES:
        existing = {index["name"] for index in inspector.get_indexes(table)}
        if index_name not in existing:
            op.create_index(index_name, table, columns)

    existing = {index["name"] for index in inspector.get_indexes("email_drafts")}
    if "uq_email_drafts_active" not in existing and not _has_duplicate_active_drafts():
        op.create_index(
            "uq_email_drafts_active", "email_drafts", ["restaurant_id", "campaign"], unique=True,
            sqlite_where=sa.text("status = 'draft'"), postgresql_where=sa.text("status = 'draft'"),
        )


def downgrade() -> None:
    raise NotImplementedError("The initial schema is not downgraded. Restore from a backup instead.")
