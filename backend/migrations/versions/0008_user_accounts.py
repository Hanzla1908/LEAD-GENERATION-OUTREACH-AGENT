"""Individual user accounts, roles, the audit trail, and attribution columns.

Adds
- users: one row per person (name, lower-case unique email, Argon2 password hash, role, status).
- audit_log: who did what, and when, for important actions.
- auth_sessions.user_id: each session belongs to one account. Sessions created before this migration
  have no user and stop working; they are kept, not deleted.
- campaigns.created_by_user_id: the account that created a campaign. Campaigns created before this
  migration keep NULL, which means "recorded before accounts existed".

Nothing is deleted or rewritten. Every new column is nullable, so existing rows stay valid.
The shared admin password is not migrated automatically. Create the first admin with
scripts/create_admin.py (see README).

Revision ID: 0008_user_accounts
Revises: 0007_relational_integrity
Create Date: 2026-11-05
"""
import sqlalchemy as sa
from alembic import op

revision = "0008_user_accounts"
down_revision = "0007_relational_integrity"
branch_labels = None
depends_on = None

ROLES = ("admin", "operator", "viewer")


def _add_user_reference(table: str, column: str, ondelete: str, constraint: str) -> None:
    """Nullable foreign key to users.id. SQLite accepts it in ALTER TABLE, so the table is not rebuilt."""
    if op.get_bind().dialect.name == "sqlite":
        op.execute(f"ALTER TABLE {table} ADD COLUMN {column} INTEGER REFERENCES users(id) ON DELETE {ondelete}")
    else:
        op.add_column(table, sa.Column(column, sa.Integer(), nullable=True))
        op.create_foreign_key(constraint, table, "users", [column], ["id"], ondelete=ondelete)
    op.create_index(f"ix_{table}_{column}", table, [column])


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "users" not in inspector.get_table_names():
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("email", sa.String(254), nullable=False),
            sa.Column("password_hash", sa.String(255), nullable=False),
            sa.Column("role", sa.String(16), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("last_login_at", sa.DateTime(), nullable=True),
            sa.Column("password_changed_at", sa.DateTime(), nullable=True),
            sa.Column("created_by_user_id", sa.Integer(), nullable=True),
            sa.UniqueConstraint("email", name="uq_users_email"),
            sa.CheckConstraint("email = lower(email)", name="ck_users_email_lower"),
            sa.CheckConstraint(f"role IN ({', '.join(repr(r) for r in ROLES)})", name="ck_users_role"),
            sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_users_status"),
            sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name="fk_users_created_by",
                                    ondelete="RESTRICT"),
        )

    if "audit_log" not in inspector.get_table_names():
        op.create_table(
            "audit_log",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("actor_user_id", sa.Integer(), nullable=True),
            sa.Column("action", sa.String(64), nullable=False),
            sa.Column("target_type", sa.String(40), nullable=True),
            sa.Column("target_id", sa.String(64), nullable=True),
            sa.Column("detail", sa.String(500), nullable=True),
            sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name="fk_audit_log_actor", ondelete="RESTRICT"),
        )
        op.create_index("ix_audit_log_created", "audit_log", ["created_at"])
        op.create_index("ix_audit_log_actor", "audit_log", ["actor_user_id"])

    session_columns = {column["name"] for column in inspector.get_columns("auth_sessions")}
    if "user_id" not in session_columns:
        _add_user_reference("auth_sessions", "user_id", "CASCADE", "fk_auth_sessions_user")

    campaign_columns = {column["name"] for column in inspector.get_columns("campaigns")}
    if "created_by_user_id" not in campaign_columns:
        _add_user_reference("campaigns", "created_by_user_id", "RESTRICT", "fk_campaigns_created_by")


def downgrade() -> None:
    op.drop_index("ix_campaigns_created_by_user_id", table_name="campaigns")
    op.drop_index("ix_auth_sessions_user_id", table_name="auth_sessions")
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("campaigns", recreate="always") as batch:
            batch.drop_column("created_by_user_id")
        with op.batch_alter_table("auth_sessions", recreate="always") as batch:
            batch.drop_column("user_id")
    else:
        op.drop_constraint("fk_campaigns_created_by", "campaigns", type_="foreignkey")
        op.drop_column("campaigns", "created_by_user_id")
        op.drop_constraint("fk_auth_sessions_user", "auth_sessions", type_="foreignkey")
        op.drop_column("auth_sessions", "user_id")
    op.drop_index("ix_audit_log_actor", table_name="audit_log")
    op.drop_index("ix_audit_log_created", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("users")
