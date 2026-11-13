"""Relational integrity: foreign keys, composite foreign keys, unique and check constraints, indexes.

Safety rules
- The audit runs first. If any row is an orphan, points at another campaign's recipient, or uses a status
  the application never writes, the migration stops with a report and changes nothing. Nothing is deleted
  or rewritten automatically. A person decides how to fix each row (see scripts/audit_integrity.py).
- ON DELETE is RESTRICT for every link that carries history (drafts, recipients, ledger, events, replies).
  A parent that has history cannot be deleted by accident. Send logs are the one exception: they keep the
  recipient's address as text, so their links are cleared (SET NULL) and the log line survives.
- SQLite cannot add constraints to an existing table, so its tables are rebuilt (copy, then swap). The
  connection runs with foreign keys off during the rebuild and is checked afterwards (see migrations/env.py).
  PostgreSQL adds the constraints in place with ALTER TABLE.

Revision ID: 0007_relational_integrity
Revises: 0006_email_events_and_replies
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "0007_relational_integrity"
down_revision = "0006_email_events_and_replies"
branch_labels = None
depends_on = None

# ── Vocabularies: the values the application writes (checked against the code in Phase 19) ──
CAMPAIGN_STATUS = ("generating", "review", "sending", "paused", "completed", "cancelled")
RECIPIENT_STATUS = ("drafting", "draft_failed", "draft", "skipped", "queued", "sending", "sent", "failed",
                    "interrupted", "cancelled")
DRAFT_STATUS = ("draft", "approved", "rejected")
LEDGER_STATUS = ("reserved", "sent", "failed", "uncertain", "bounced")
EVENT_TYPE = ("delivered", "deferred", "bounced_soft", "bounced_hard", "rejected")
MATCH_STATUS = ("matched", "needs_review", "unmatched", "dismissed")
LEAD_STATUS = ("new", "qualified", "needs_review", "disqualified")
EMAIL_STATUS = ("unverified", "domain_valid", "verified", "invalid", "unknown")
EMAIL_CLASS = ("business", "personal", "disposable", "unknown")


def _in(column: str, values: tuple) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


# ── Audit: each query returns the ids of the rows that break a rule ─────────────────────────

PROBLEM_QUERIES = [
    ("email_drafts.restaurant_id points at no restaurant",
     "SELECT d.id AS id FROM email_drafts d LEFT JOIN restaurants r ON r.id = d.restaurant_id WHERE r.id IS NULL"),
    ("email_drafts.campaign_id points at no campaign",
     "SELECT d.id AS id FROM email_drafts d LEFT JOIN campaigns c ON c.id = d.campaign_id "
     "WHERE d.campaign_id IS NOT NULL AND c.id IS NULL"),
    ("campaign_recipients.campaign_id points at no campaign",
     "SELECT r.id AS id FROM campaign_recipients r LEFT JOIN campaigns c ON c.id = r.campaign_id WHERE c.id IS NULL"),
    ("campaign_recipients.restaurant_id points at no restaurant",
     "SELECT r.id AS id FROM campaign_recipients r LEFT JOIN restaurants x ON x.id = r.restaurant_id WHERE x.id IS NULL"),
    ("campaign_recipients.draft_id points at no draft",
     "SELECT r.id AS id FROM campaign_recipients r LEFT JOIN email_drafts d ON d.id = r.draft_id "
     "WHERE r.draft_id IS NOT NULL AND d.id IS NULL"),
    ("campaign_recipients draft belongs to a different restaurant",
     "SELECT r.id AS id FROM campaign_recipients r JOIN email_drafts d ON d.id = r.draft_id "
     "WHERE d.restaurant_id <> r.restaurant_id"),
    ("campaign_send_logs.campaign_id points at no campaign",
     "SELECT l.id AS id FROM campaign_send_logs l LEFT JOIN campaigns c ON c.id = l.campaign_id WHERE c.id IS NULL"),
    ("campaign_send_logs.recipient_id points at no recipient",
     "SELECT l.id AS id FROM campaign_send_logs l LEFT JOIN campaign_recipients r ON r.id = l.recipient_id "
     "WHERE l.recipient_id IS NOT NULL AND r.id IS NULL"),
    ("campaign_send_logs.restaurant_id points at no restaurant",
     "SELECT l.id AS id FROM campaign_send_logs l LEFT JOIN restaurants x ON x.id = l.restaurant_id "
     "WHERE l.restaurant_id IS NOT NULL AND x.id IS NULL"),
    ("email_send_ledger.campaign_id points at no campaign",
     "SELECT l.id AS id FROM email_send_ledger l LEFT JOIN campaigns c ON c.id = l.campaign_id WHERE c.id IS NULL"),
    ("email_send_ledger.recipient_id points at no recipient",
     "SELECT l.id AS id FROM email_send_ledger l LEFT JOIN campaign_recipients r ON r.id = l.recipient_id "
     "WHERE r.id IS NULL"),
    ("email_send_ledger row belongs to a different campaign than its recipient",
     "SELECT l.id AS id FROM email_send_ledger l JOIN campaign_recipients r ON r.id = l.recipient_id "
     "WHERE r.campaign_id <> l.campaign_id"),
    ("email_send_ledger.restaurant_id points at no restaurant",
     "SELECT l.id AS id FROM email_send_ledger l LEFT JOIN restaurants x ON x.id = l.restaurant_id "
     "WHERE l.restaurant_id IS NOT NULL AND x.id IS NULL"),
    ("email_send_ledger.draft_id points at no draft",
     "SELECT l.id AS id FROM email_send_ledger l LEFT JOIN email_drafts d ON d.id = l.draft_id "
     "WHERE l.draft_id IS NOT NULL AND d.id IS NULL"),
    ("email_events.recipient_id points at no recipient",
     "SELECT e.id AS id FROM email_events e LEFT JOIN campaign_recipients r ON r.id = e.recipient_id "
     "WHERE e.recipient_id IS NOT NULL AND r.id IS NULL"),
    ("email_events.campaign_id points at no campaign",
     "SELECT e.id AS id FROM email_events e LEFT JOIN campaigns c ON c.id = e.campaign_id "
     "WHERE e.campaign_id IS NOT NULL AND c.id IS NULL"),
    ("email_events event belongs to a different campaign than its recipient",
     "SELECT e.id AS id FROM email_events e JOIN campaign_recipients r ON r.id = e.recipient_id "
     "WHERE e.campaign_id IS NOT NULL AND r.campaign_id <> e.campaign_id"),
    ("email_conversations.recipient_id points at no recipient",
     "SELECT c.id AS id FROM email_conversations c LEFT JOIN campaign_recipients r ON r.id = c.recipient_id "
     "WHERE c.recipient_id IS NOT NULL AND r.id IS NULL"),
    ("email_conversations.campaign_id points at no campaign",
     "SELECT c.id AS id FROM email_conversations c LEFT JOIN campaigns x ON x.id = c.campaign_id "
     "WHERE c.campaign_id IS NOT NULL AND x.id IS NULL"),
    ("email_conversations.restaurant_id points at no restaurant",
     "SELECT c.id AS id FROM email_conversations c LEFT JOIN restaurants x ON x.id = c.restaurant_id "
     "WHERE c.restaurant_id IS NOT NULL AND x.id IS NULL"),
    ("email_conversations reply belongs to a different campaign than its recipient",
     "SELECT c.id AS id FROM email_conversations c JOIN campaign_recipients r ON r.id = c.recipient_id "
     "WHERE c.campaign_id IS NOT NULL AND r.campaign_id <> c.campaign_id"),
    ("duplicate active drafts for one restaurant and campaign name",
     "SELECT MIN(id) AS id FROM email_drafts WHERE status = 'draft' GROUP BY restaurant_id, campaign HAVING COUNT(*) > 1"),
    ("duplicate recipients for one campaign and restaurant",
     "SELECT MIN(id) AS id FROM campaign_recipients GROUP BY campaign_id, restaurant_id HAVING COUNT(*) > 1"),
    ("duplicate ledger rows for one campaign recipient",
     "SELECT MIN(id) AS id FROM email_send_ledger GROUP BY campaign_id, recipient_id HAVING COUNT(*) > 1"),
    ("duplicate restaurant place_id",
     "SELECT MIN(id) AS id FROM restaurants GROUP BY place_id HAVING COUNT(*) > 1"),
    ("restaurants.opted_out is not 0 or 1",
     "SELECT id FROM restaurants WHERE opted_out IS NOT NULL AND opted_out NOT IN (0, 1)"),
]

# (table, column, allowed values, nullable). A row with any other value blocks the migration.
VOCABULARY = [
    ("campaigns", "status", CAMPAIGN_STATUS, False),
    ("campaign_recipients", "status", RECIPIENT_STATUS, False),
    ("campaign_recipients", "delivery_status", EVENT_TYPE, True),
    ("email_drafts", "status", DRAFT_STATUS, False),
    ("email_send_ledger", "status", LEDGER_STATUS, False),
    ("email_events", "event_type", EVENT_TYPE, False),
    ("email_conversations", "match_status", MATCH_STATUS, False),
    ("restaurants", "lead_status", LEAD_STATUS, True),
    ("restaurants", "contact_email_status", EMAIL_STATUS, True),
    ("restaurants", "contact_email_classification", EMAIL_CLASS, True),
]


def _count_and_sample(bind, label: str, sql: str, show_samples: bool = True) -> dict | None:
    count = bind.execute(sa.text(f"SELECT COUNT(*) FROM ({sql}) problem_rows")).scalar_one()
    if not count:
        return None
    samples = []
    if show_samples:
        samples = [str(row[0]) for row in bind.execute(sa.text(f"SELECT id FROM ({sql}) problem_rows LIMIT 10"))]
    return {"problem": label, "count": int(count), "sample_ids": samples}


def audit(bind) -> list[dict]:
    """Every rule the new constraints would break. Empty when the data is clean."""
    problems = []
    for label, sql in PROBLEM_QUERIES:
        found = _count_and_sample(bind, label, sql)
        if found:
            problems.append(found)
    for table, column, allowed, nullable in VOCABULARY:
        clause = _in(column, allowed)
        if nullable:
            clause = f"{column} IS NOT NULL AND NOT ({clause})"
        else:
            clause = f"NOT ({clause})"
        found = _count_and_sample(bind, f"{table}.{column} holds a value the application never writes",
                                  f"SELECT id FROM {table} WHERE {clause}")
        if found:
            problems.append(found)
    # Lower-case check on addresses. Samples are withheld because they would be personal data.
    found = _count_and_sample(bind, "suppression_list.email is not stored in lower case",
                              "SELECT email AS id FROM suppression_list WHERE email <> lower(email)", show_samples=False)
    if found:
        problems.append(found)
    return problems


def describe(problems: list[dict]) -> str:
    lines = [f"- {p['problem']}: {p['count']} row(s); sample ids {p['sample_ids'] or 'withheld'}" for p in problems]
    return "\n".join(lines)


# ── Constraint definitions ──────────────────────────────────────────────────────────────────

UNIQUE_OPS = [
    ("campaign_recipients", "uq_campaign_recipients_campaign_id", ["campaign_id", "id"]),
]

# (table, name, local columns, referenced table, referenced columns, ON DELETE)
FK_OPS = [
    ("email_drafts", "fk_email_drafts_restaurant", ["restaurant_id"], "restaurants", ["id"], "RESTRICT"),
    ("email_drafts", "fk_email_drafts_campaign", ["campaign_id"], "campaigns", ["id"], "RESTRICT"),
    ("campaign_recipients", "fk_campaign_recipients_campaign", ["campaign_id"], "campaigns", ["id"], "RESTRICT"),
    ("campaign_recipients", "fk_campaign_recipients_restaurant", ["restaurant_id"], "restaurants", ["id"], "RESTRICT"),
    ("campaign_recipients", "fk_campaign_recipients_draft", ["draft_id"], "email_drafts", ["id"], "RESTRICT"),
    ("campaign_send_logs", "fk_campaign_send_logs_campaign", ["campaign_id"], "campaigns", ["id"], "RESTRICT"),
    ("campaign_send_logs", "fk_campaign_send_logs_recipient", ["recipient_id"], "campaign_recipients", ["id"], "SET NULL"),
    ("campaign_send_logs", "fk_campaign_send_logs_restaurant", ["restaurant_id"], "restaurants", ["id"], "SET NULL"),
    ("email_send_ledger", "fk_email_send_ledger_campaign", ["campaign_id"], "campaigns", ["id"], "RESTRICT"),
    ("email_send_ledger", "fk_email_send_ledger_recipient_pair", ["campaign_id", "recipient_id"],
     "campaign_recipients", ["campaign_id", "id"], "RESTRICT"),
    ("email_send_ledger", "fk_email_send_ledger_restaurant", ["restaurant_id"], "restaurants", ["id"], "RESTRICT"),
    ("email_send_ledger", "fk_email_send_ledger_draft", ["draft_id"], "email_drafts", ["id"], "RESTRICT"),
    ("email_events", "fk_email_events_campaign", ["campaign_id"], "campaigns", ["id"], "RESTRICT"),
    ("email_events", "fk_email_events_recipient_pair", ["campaign_id", "recipient_id"],
     "campaign_recipients", ["campaign_id", "id"], "RESTRICT"),
    ("email_conversations", "fk_email_conversations_campaign", ["campaign_id"], "campaigns", ["id"], "RESTRICT"),
    ("email_conversations", "fk_email_conversations_restaurant", ["restaurant_id"], "restaurants", ["id"], "RESTRICT"),
    ("email_conversations", "fk_email_conversations_recipient_pair", ["campaign_id", "recipient_id"],
     "campaign_recipients", ["campaign_id", "id"], "RESTRICT"),
]

CHECK_OPS = [
    ("campaigns", "ck_campaigns_status", _in("status", CAMPAIGN_STATUS)),
    ("campaign_recipients", "ck_campaign_recipients_status", _in("status", RECIPIENT_STATUS)),
    ("campaign_recipients", "ck_campaign_recipients_delivery_status",
     f"delivery_status IS NULL OR {_in('delivery_status', EVENT_TYPE)}"),
    ("email_drafts", "ck_email_drafts_status", _in("status", DRAFT_STATUS)),
    ("email_send_ledger", "ck_email_send_ledger_status", _in("status", LEDGER_STATUS)),
    ("email_send_ledger", "ck_email_send_ledger_attempts", "attempts >= 1"),
    ("email_events", "ck_email_events_event_type", _in("event_type", EVENT_TYPE)),
    ("email_conversations", "ck_email_conversations_match_status", _in("match_status", MATCH_STATUS)),
    ("email_conversations", "ck_email_conversations_direction", "direction = 'inbound'"),
    ("restaurants", "ck_restaurants_lead_status", f"lead_status IS NULL OR {_in('lead_status', LEAD_STATUS)}"),
    ("restaurants", "ck_restaurants_contact_email_status",
     f"contact_email_status IS NULL OR {_in('contact_email_status', EMAIL_STATUS)}"),
    ("restaurants", "ck_restaurants_contact_email_classification",
     f"contact_email_classification IS NULL OR {_in('contact_email_classification', EMAIL_CLASS)}"),
    ("restaurants", "ck_restaurants_opted_out", "opted_out IS NULL OR opted_out IN (0, 1)"),
]

INDEX_OPS = [
    ("ix_email_drafts_campaign", "email_drafts", ["campaign_id"]),
    ("ix_campaign_recipients_restaurant", "campaign_recipients", ["restaurant_id"]),
    ("ix_campaign_recipients_draft", "campaign_recipients", ["draft_id"]),
    ("ix_campaign_send_logs_recipient", "campaign_send_logs", ["recipient_id"]),
    ("ix_campaign_send_logs_restaurant", "campaign_send_logs", ["restaurant_id"]),
    ("ix_email_send_ledger_restaurant", "email_send_ledger", ["restaurant_id"]),
    ("ix_email_send_ledger_draft", "email_send_ledger", ["draft_id"]),
    ("ix_email_events_campaign", "email_events", ["campaign_id"]),
    ("ix_email_conversations_campaign", "email_conversations", ["campaign_id"]),
    ("ix_email_conversations_restaurant", "email_conversations", ["restaurant_id"]),
]


def _tables_touched() -> list[str]:
    tables = []
    for table in [u[0] for u in UNIQUE_OPS] + [f[0] for f in FK_OPS] + [c[0] for c in CHECK_OPS]:
        if table not in tables:
            tables.append(table)
    return tables


def _add_constraints(sqlite: bool) -> None:
    if not sqlite:
        for table, name, cols in UNIQUE_OPS:
            op.create_unique_constraint(name, table, cols)
        for table, name, cols, ref, ref_cols, on_delete in FK_OPS:
            op.create_foreign_key(name, table, ref, cols, ref_cols, ondelete=on_delete)
        for table, name, condition in CHECK_OPS:
            op.create_check_constraint(name, table, condition)
        return
    for table in _tables_touched():
        with op.batch_alter_table(table, recreate="always") as batch:
            for t, name, cols in UNIQUE_OPS:
                if t == table:
                    batch.create_unique_constraint(name, cols)
            for t, name, cols, ref, ref_cols, on_delete in FK_OPS:
                if t == table:
                    batch.create_foreign_key(name, ref, cols, ref_cols, ondelete=on_delete)
            for t, name, condition in CHECK_OPS:
                if t == table:
                    batch.create_check_constraint(name, condition)


def upgrade() -> None:
    bind = op.get_bind()
    problems = audit(bind)
    if problems:
        raise RuntimeError(
            "Integrity check failed. Nothing was changed. Fix or export these rows, then run the migration again "
            "(scripts/audit_integrity.py lists them):\n" + describe(problems)
        )
    sqlite = bind.dialect.name == "sqlite"
    _add_constraints(sqlite)
    for name, table, cols in INDEX_OPS:
        op.create_index(name, table, cols)


def downgrade() -> None:
    bind = op.get_bind()
    sqlite = bind.dialect.name == "sqlite"
    for name, table, _cols in reversed(INDEX_OPS):
        op.drop_index(name, table_name=table)
    if not sqlite:
        for table, name, _condition in reversed(CHECK_OPS):
            op.drop_constraint(name, table, type_="check")
        for table, name, _cols, _ref, _ref_cols, _on_delete in reversed(FK_OPS):
            op.drop_constraint(name, table, type_="foreignkey")
        for table, name, _cols in reversed(UNIQUE_OPS):
            op.drop_constraint(name, table, type_="unique")
        return
    for table in reversed(_tables_touched()):
        with op.batch_alter_table(table, recreate="always") as batch:
            for t, name, _condition in reversed(CHECK_OPS):
                if t == table:
                    batch.drop_constraint(name, type_="check")
            for t, name, _cols, _ref, _ref_cols, _on_delete in reversed(FK_OPS):
                if t == table:
                    batch.drop_constraint(name, type_="foreignkey")
            for t, name, _cols in reversed(UNIQUE_OPS):
                if t == table:
                    batch.drop_constraint(name, type_="unique")
