"""Multi-user workspaces: workspaces, memberships, invitations, and workspace ownership of records.

Adds
- workspaces: one row per team workspace.
- workspace_members: a user's role inside a workspace (admin, operator or viewer). Unique per user and
  workspace.
- workspace_invitations: invitations with a hashed token and an expiry. The plain token is never stored.
- workspace_id on restaurants, email_drafts and campaigns (NOT NULL, foreign key to workspaces).
- workspace_id on auth_sessions (the workspace the signed-in person is working in) and audit_log.

Migration of existing data
- A "Default workspace" is created. Every existing restaurant, draft and campaign is assigned to it.
- Every existing user becomes a member of the default workspace with the role they already had.
- Nothing is deleted or rewritten, apart from the new columns.

Campaign children (recipients, send logs, the send ledger, delivery events and replies) belong to a
campaign, so they are isolated through campaigns.workspace_id and need no column of their own.
suppression_list stays instance-wide on purpose: an address that opted out must never be emailed by any
workspace.

Revision ID: 0009_workspaces
Revises: 0008_user_accounts
Create Date: 2026-11-06
"""
import re

import sqlalchemy as sa
from alembic import op

revision = "0009_workspaces"
down_revision = "0008_user_accounts"
branch_labels = None
depends_on = None

ROLES = ("admin", "operator", "viewer")
DEFAULT_NAME = "Default workspace"


def _add_workspace_column(table: str, default_id: int, nullable: bool = False) -> None:
    """Adds workspace_id with a foreign key. Every existing row gets the default workspace.

    SQLite cannot add a REFERENCES column with a non-NULL default while foreign keys are on. The migration
    environment turns them off for the run and checks them afterwards (migrations/env.py).
    """
    if op.get_bind().dialect.name == "sqlite":
        null_clause = "" if nullable else "NOT NULL "
        op.execute(
            f"ALTER TABLE {table} ADD COLUMN workspace_id INTEGER {null_clause}DEFAULT {default_id} "
            f"REFERENCES workspaces(id) ON DELETE RESTRICT"
        )
    else:
        op.add_column(table, sa.Column("workspace_id", sa.Integer(), nullable=nullable,
                                       server_default=None if nullable else str(default_id)))
        op.create_foreign_key(f"fk_{table}_workspace", table, "workspaces", ["workspace_id"], ["id"],
                              ondelete="RESTRICT")
        if not nullable:
            op.alter_column(table, "workspace_id", server_default=None)
    op.create_index(f"ix_{table}_workspace_id", table, ["workspace_id"])


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    op.create_table(
        "workspaces",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_workspaces_status"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name="fk_workspaces_created_by",
                                ondelete="RESTRICT"),
    )

    op.create_table(
        "workspace_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("added_by_user_id", sa.Integer(), nullable=True),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_workspace_user"),
        sa.CheckConstraint(f"role IN ({', '.join(repr(r) for r in ROLES)})", name="ck_workspace_members_role"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_workspace_members_workspace",
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_workspace_members_user", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["added_by_user_id"], ["users.id"], name="fk_workspace_members_added_by",
                                ondelete="RESTRICT"),
    )
    op.create_index("ix_workspace_members_user_id", "workspace_members", ["user_id"])

    op.create_table(
        "workspace_invitations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("accepted_user_id", sa.Integer(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_workspace_invitations_token_hash"),
        sa.CheckConstraint(f"role IN ({', '.join(repr(r) for r in ROLES)})", name="ck_workspace_invitations_role"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], name="fk_workspace_invitations_workspace",
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name="fk_workspace_invitations_created_by",
                                ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["accepted_user_id"], ["users.id"], name="fk_workspace_invitations_accepted_by",
                                ondelete="RESTRICT"),
    )
    op.create_index("ix_workspace_invitations_workspace_id", "workspace_invitations", ["workspace_id"])
    op.create_index("ix_workspace_invitations_email", "workspace_invitations", ["email"])

    # The default workspace: its id is read back, so PostgreSQL's sequence is never guessed.
    bind.execute(sa.text(f"INSERT INTO workspaces (name) VALUES ('{DEFAULT_NAME}')"))
    default_id = bind.execute(sa.text("SELECT id FROM workspaces WHERE name = :name ORDER BY id"),
                              {"name": DEFAULT_NAME}).scalars().first()

    # Every existing user keeps the role they already had, inside the default workspace.
    bind.execute(sa.text(
        "INSERT INTO workspace_members (workspace_id, user_id, role, created_at) "
        "SELECT :ws, id, role, CURRENT_TIMESTAMP FROM users"
    ), {"ws": default_id})

    _add_workspace_column("restaurants", default_id)
    _add_workspace_column("email_drafts", default_id)
    _add_workspace_column("campaigns", default_id)
    _add_workspace_column("email_conversations", default_id)
    _add_workspace_column("auth_sessions", default_id, nullable=True)
    _add_workspace_column("audit_log", default_id, nullable=True)
    _replace_place_uniqueness()


# CHECK constraints the restaurants table gained in 0007. A SQLite table rebuild does not carry them over,
# so they are written again after the rebuild. Values match the application (see migration 0007).
RESTAURANT_CHECKS = (
    ("ck_restaurants_lead_status",
     "lead_status IS NULL OR lead_status IN ('new', 'qualified', 'needs_review', 'disqualified')"),
    ("ck_restaurants_contact_email_status",
     "contact_email_status IS NULL OR contact_email_status IN "
     "('unverified', 'domain_valid', 'verified', 'invalid', 'unknown')"),
    ("ck_restaurants_contact_email_classification",
     "contact_email_classification IS NULL OR contact_email_classification IN "
     "('business', 'personal', 'disposable', 'unknown')"),
    ("ck_restaurants_opted_out", "opted_out IS NULL OR opted_out IN (0, 1)"),
)


# The global place_id rule. Named on databases created by the current schema, but unnamed on databases that were
# migrated before the name was introduced; SQLite cannot drop an unnamed constraint, so the rule is matched by its
# columns instead.
_GLOBAL_PLACE_UNIQUE = re.compile(r",\s*(CONSTRAINT\s+\w+\s+)?UNIQUE\s*\(\s*place_id\s*\)", re.IGNORECASE)
_RESTAURANTS_CREATE = re.compile(r"^\s*CREATE\s+TABLE\s+\"?restaurants\"?\s*\(", re.IGNORECASE)


def _rebuild_sqlite_restaurants(bind) -> None:
    """Rebuild restaurants from its own CREATE statement, replacing the global place_id rule with a per-workspace one.

    Every other column, default, CHECK and index is copied exactly as it is, so nothing is lost and nothing has to be
    restated by hand. The whole change happens in one place, and it refuses to run if the rule is not found.
    """
    create_sql = bind.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'restaurants'").scalar()
    index_sql = [row[0] for row in bind.exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'restaurants' AND sql IS NOT NULL").all()]
    body, removed = _GLOBAL_PLACE_UNIQUE.subn("", create_sql, count=1)
    body = body.rstrip()
    if removed != 1 or not body.endswith(")") or not _RESTAURANTS_CREATE.match(body):
        raise RuntimeError("The global place_id rule on restaurants was not found; nothing was changed.")
    body = body[:-1] + ", CONSTRAINT uq_restaurants_workspace_place UNIQUE (workspace_id, place_id))"
    body = _RESTAURANTS_CREATE.sub("CREATE TABLE restaurants_new (", body, count=1)
    columns = ", ".join(row[1] for row in bind.exec_driver_sql("PRAGMA table_info(restaurants)").all())
    bind.exec_driver_sql(body)
    bind.exec_driver_sql(f"INSERT INTO restaurants_new ({columns}) SELECT {columns} FROM restaurants")
    bind.exec_driver_sql("DROP TABLE restaurants")
    bind.exec_driver_sql("ALTER TABLE restaurants_new RENAME TO restaurants")
    for statement in index_sql:
        bind.exec_driver_sql(statement)


def _replace_place_uniqueness() -> None:
    """A Google place can be saved once per workspace, not once for the whole instance."""
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        _rebuild_sqlite_restaurants(bind)
    else:
        op.drop_constraint("uq_restaurants_place_id", "restaurants", type_="unique")
        op.create_unique_constraint("uq_restaurants_workspace_place", "restaurants", ["workspace_id", "place_id"])


def _restore_place_uniqueness() -> None:
    duplicates = op.get_bind().execute(sa.text(
        "SELECT place_id FROM restaurants GROUP BY place_id HAVING COUNT(*) > 1 LIMIT 1")).first()
    if duplicates:
        raise RuntimeError(
            "The same Google place is saved in more than one workspace, so the previous rule cannot be restored. "
            "Nothing was changed. Keep this revision, or export the duplicate rows first."
        )
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("restaurants", recreate="always") as batch:
            batch.drop_constraint("uq_restaurants_workspace_place", type_="unique")
            batch.create_unique_constraint("uq_restaurants_place_id", ["place_id"])
            for name, condition in RESTAURANT_CHECKS:
                batch.create_check_constraint(name, condition)
    else:
        op.drop_constraint("uq_restaurants_workspace_place", "restaurants", type_="unique")
        op.create_unique_constraint("uq_restaurants_place_id", "restaurants", ["place_id"])


SCOPED_TABLES = ("audit_log", "auth_sessions", "email_conversations", "campaigns", "email_drafts", "restaurants")


def downgrade() -> None:
    _restore_place_uniqueness()
    for table in SCOPED_TABLES:
        op.drop_index(f"ix_{table}_workspace_id", table_name=table)
    if op.get_bind().dialect.name == "sqlite":
        for table in SCOPED_TABLES:
            with op.batch_alter_table(table, recreate="always") as batch:
                batch.drop_column("workspace_id")
    else:
        for table in SCOPED_TABLES:
            op.drop_constraint(f"fk_{table}_workspace", table, type_="foreignkey")
            op.drop_column(table, "workspace_id")
    op.drop_index("ix_workspace_invitations_email", table_name="workspace_invitations")
    op.drop_index("ix_workspace_invitations_workspace_id", table_name="workspace_invitations")
    op.drop_table("workspace_invitations")
    op.drop_index("ix_workspace_members_user_id", table_name="workspace_members")
    op.drop_table("workspace_members")
    op.drop_table("workspaces")
