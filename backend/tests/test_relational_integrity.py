"""Relational integrity: foreign keys, composite keys, checks, uniqueness, deletion behaviour, the audit and
migration rollback. Runs on SQLite and on PostgreSQL (TEST_POSTGRES_URL).
"""
import importlib.util
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError

from models import campaign_store as store
from models.database import create_draft, execute, fetch_one, get_engine, is_postgres, save_restaurants

BACKEND = Path(__file__).resolve().parent.parent
PREVIOUS = "0006_email_events_and_replies"
HEAD = "0007_relational_integrity"


def _config() -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    return config


def _audit_module():
    spec = importlib.util.spec_from_file_location("relational_integrity", BACKEND / "migrations" / "versions" / f"{HEAD}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sql(statement: str, params: dict | None = None) -> None:
    with get_engine().begin() as conn:
        conn.execute(text(statement), params or {})


def _restaurant(name: str = "Integrity Cafe") -> int:
    return save_restaurants([{"place_id": f"int-{name}", "name": name, "source": "google_places"}])[0]["id"]


def _recipient(campaign_id: int, restaurant_id: int, status: str = "queued") -> int:
    store.insert_recipient(campaign_id, restaurant_id, "owner@integrity.pk", status)
    return next(r for r in store.list_recipients(campaign_id) if r["restaurant_id"] == restaurant_id)["id"]


def _draft(restaurant_id: int, campaign: str = "Integrity") -> int:
    return create_draft(restaurant_id=restaurant_id, campaign=campaign, subject="S", body="B", angle=None)["id"]


# ── Valid relationships and foreign-key enforcement ──────────────────────────

def test_sqlite_enforces_foreign_keys_on_every_checkout(test_db):
    if is_postgres():
        pytest.skip("PostgreSQL always enforces foreign keys")
    for _ in range(3):
        with get_engine().connect() as conn:
            assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_valid_relationships_are_accepted(test_db):
    campaign_id = store.create_campaign("Valid links")
    restaurant_id = _restaurant("Valid Cafe")
    draft_id = _draft(restaurant_id)
    recipient_id = _recipient(campaign_id, restaurant_id)
    _sql("UPDATE campaign_recipients SET draft_id = :d WHERE id = :id", {"d": draft_id, "id": recipient_id})
    store.reserve_send(campaign_id, store.get_recipient(recipient_id))
    store.record_send_success(campaign_id, recipient_id, "<valid@test>")
    assert store.ledger_for(campaign_id, recipient_id)["campaign_id"] == campaign_id


@pytest.mark.parametrize("statement, params", [
    ("INSERT INTO email_drafts (restaurant_id, campaign, subject, body, status) VALUES (999999, 'x', 's', 'b', 'draft')", {}),
    ("INSERT INTO email_drafts (restaurant_id, campaign_id, campaign, subject, body, status) "
     "VALUES ((SELECT MIN(id) FROM restaurants), 999999, 'x', 's', 'b', 'draft')", {}),
    ("INSERT INTO campaign_recipients (campaign_id, restaurant_id, status) VALUES (999999, "
     "(SELECT MIN(id) FROM restaurants), 'queued')", {}),
    ("INSERT INTO campaign_recipients (campaign_id, restaurant_id, status) VALUES "
     "((SELECT MIN(id) FROM campaigns), 999999, 'queued')", {}),
    ("INSERT INTO campaign_send_logs (campaign_id, event) VALUES (999999, 'sent')", {}),
])
def test_references_to_missing_parents_are_rejected(test_db, statement, params):
    _restaurant("Parent Cafe")
    store.create_campaign("Parent campaign")
    with pytest.raises(IntegrityError):
        _sql(statement, params)


def test_ledger_row_cannot_point_at_another_campaigns_recipient(test_db):
    first = store.create_campaign("Ledger first")
    second = store.create_campaign("Ledger second")
    restaurant_id = _restaurant("Cross Ledger")
    recipient_id = _recipient(first, restaurant_id)
    with pytest.raises(IntegrityError):
        _sql(
            "INSERT INTO email_send_ledger (campaign_id, recipient_id, status, idempotency_key) "
            "VALUES (:cid, :rid, 'reserved', 'cross-campaign-key')",
            {"cid": second, "rid": recipient_id},
        )


def test_reply_cannot_point_at_another_campaigns_recipient(test_db):
    first = store.create_campaign("Reply first")
    second = store.create_campaign("Reply second")
    recipient_id = _recipient(first, _restaurant("Cross Reply"))
    with pytest.raises(IntegrityError):
        _sql(
            "INSERT INTO email_conversations (message_key, match_status, campaign_id, recipient_id) "
            "VALUES ('<cross@test>', 'matched', :cid, :rid)",
            {"cid": second, "rid": recipient_id},
        )


def test_event_cannot_point_at_another_campaigns_recipient(test_db):
    first = store.create_campaign("Event first")
    second = store.create_campaign("Event second")
    recipient_id = _recipient(first, _restaurant("Cross Event"))
    with pytest.raises(IntegrityError):
        _sql(
            "INSERT INTO email_events (event_key, source, event_type, campaign_id, recipient_id) "
            "VALUES ('cross-event', 'webhook', 'delivered', :cid, :rid)",
            {"cid": second, "rid": recipient_id},
        )


# ── Check constraints ────────────────────────────────────────────────────────

@pytest.mark.parametrize("statement", [
    "UPDATE campaigns SET status = 'bogus' WHERE id = (SELECT MIN(id) FROM campaigns)",
    "UPDATE campaign_recipients SET status = 'pending' WHERE id = (SELECT MIN(id) FROM campaign_recipients)",
    "UPDATE campaign_recipients SET delivery_status = 'opened' WHERE id = (SELECT MIN(id) FROM campaign_recipients)",
    "UPDATE email_drafts SET status = 'maybe' WHERE id = (SELECT MIN(id) FROM email_drafts)",
    "UPDATE email_send_ledger SET status = 'pending' WHERE id = (SELECT MIN(id) FROM email_send_ledger)",
    "UPDATE email_send_ledger SET attempts = 0 WHERE id = (SELECT MIN(id) FROM email_send_ledger)",
    "UPDATE email_events SET event_type = 'opened' WHERE id = (SELECT MIN(id) FROM email_events)",
    "UPDATE email_conversations SET match_status = 'maybe' WHERE id = (SELECT MIN(id) FROM email_conversations)",
    "UPDATE email_conversations SET direction = 'outbound' WHERE id = (SELECT MIN(id) FROM email_conversations)",
    "UPDATE restaurants SET opted_out = 2 WHERE id = (SELECT MIN(id) FROM restaurants)",
    "UPDATE restaurants SET lead_status = 'hot' WHERE id = (SELECT MIN(id) FROM restaurants)",
    "UPDATE restaurants SET contact_email_status = 'maybe' WHERE id = (SELECT MIN(id) FROM restaurants)",
])
def test_unknown_status_values_are_rejected(test_db, statement):
    campaign_id = store.create_campaign("Checks")
    restaurant_id = _restaurant("Checked Cafe")
    _draft(restaurant_id, "Checks")  # so that the UPDATE on email_drafts has a row to hit
    recipient_id = _recipient(campaign_id, restaurant_id)
    store.reserve_send(campaign_id, store.get_recipient(recipient_id))
    _sql("INSERT INTO email_events (event_key, source, event_type) VALUES ('check-event', 'webhook', 'delivered')")
    _sql("INSERT INTO email_conversations (message_key, match_status, direction) VALUES ('<check@test>', 'matched', 'inbound')")
    with pytest.raises(IntegrityError):
        _sql(statement)


def test_valid_status_values_are_accepted(test_db):
    campaign_id = store.create_campaign("Allowed statuses")
    restaurant_id = _restaurant("Allowed Cafe")
    recipient_id = _recipient(campaign_id, restaurant_id)
    _sql("UPDATE campaign_recipients SET status = 'sent', delivery_status = 'bounced_hard' WHERE id = :id", {"id": recipient_id})
    _sql("UPDATE restaurants SET lead_status = 'needs_review', contact_email_status = 'domain_valid', "
         "contact_email_classification = 'personal', opted_out = 1 WHERE id = :id", {"id": restaurant_id})


# ── Uniqueness ───────────────────────────────────────────────────────────────

def test_duplicate_records_are_rejected(test_db):
    campaign_id = store.create_campaign("Duplicates")
    restaurant_id = _restaurant("Duplicate Cafe")
    _recipient(campaign_id, restaurant_id)
    with pytest.raises(IntegrityError):
        _recipient(campaign_id, restaurant_id)  # same campaign and restaurant twice
    with pytest.raises(IntegrityError):  # the database refuses a second row with the same place_id
        _sql("INSERT INTO restaurants (place_id, name, source) VALUES (:pid, 'Another name', 'google_places')",
             {"pid": "int-Duplicate Cafe"})
    _draft(restaurant_id, "Dup campaign")
    with pytest.raises(ValueError):
        _draft(restaurant_id, "Dup campaign")  # a second active draft for the same restaurant and name
    recipient_id = next(r for r in store.list_recipients(campaign_id))["id"]
    store.reserve_send(campaign_id, store.get_recipient(recipient_id))
    with pytest.raises(IntegrityError):
        _sql("INSERT INTO email_send_ledger (campaign_id, recipient_id, status, idempotency_key) "
             "VALUES (:cid, :rid, 'reserved', 'second-key')", {"cid": campaign_id, "rid": recipient_id})


def test_duplicate_event_keys_and_message_keys_are_rejected(test_db):
    _sql("INSERT INTO email_events (event_key, source, event_type) VALUES ('same-key', 'webhook', 'delivered')")
    with pytest.raises(IntegrityError):
        _sql("INSERT INTO email_events (event_key, source, event_type) VALUES ('same-key', 'webhook', 'deferred')")
    _sql("INSERT INTO email_conversations (message_key, match_status) VALUES ('<same@test>', 'unmatched')")
    with pytest.raises(IntegrityError):
        _sql("INSERT INTO email_conversations (message_key, match_status) VALUES ('<same@test>', 'unmatched')")


# ── Deletion behaviour ───────────────────────────────────────────────────────

def test_parents_of_sending_history_cannot_be_deleted(test_db):
    campaign_id = store.create_campaign("History protected")
    restaurant_id = _restaurant("History Cafe")
    draft_id = _draft(restaurant_id)
    recipient_id = _recipient(campaign_id, restaurant_id)
    _sql("UPDATE campaign_recipients SET draft_id = :d WHERE id = :id", {"d": draft_id, "id": recipient_id})
    store.reserve_send(campaign_id, store.get_recipient(recipient_id))
    store.record_send_success(campaign_id, recipient_id, "<history@test>")
    _sql("INSERT INTO email_events (event_key, source, event_type, campaign_id, recipient_id) "
         "VALUES ('history-event', 'webhook', 'delivered', :cid, :rid)", {"cid": campaign_id, "rid": recipient_id})

    for statement, params in [
        ("DELETE FROM campaigns WHERE id = :id", {"id": campaign_id}),
        ("DELETE FROM restaurants WHERE id = :id", {"id": restaurant_id}),
        ("DELETE FROM email_drafts WHERE id = :id", {"id": draft_id}),
        ("DELETE FROM campaign_recipients WHERE id = :id", {"id": recipient_id}),
    ]:
        with pytest.raises(IntegrityError):
            _sql(statement, params)

    # Nothing was lost: the ledger, the event and the recipient are all still there.
    assert store.ledger_for(campaign_id, recipient_id)["status"] == "sent"
    assert fetch_one("SELECT COUNT(*) AS n FROM email_events WHERE recipient_id = :rid", {"rid": recipient_id})["n"] == 1
    assert store.get_recipient(recipient_id)["status"] == "sent"


def test_send_logs_keep_their_text_when_the_recipient_is_removed(test_db):
    campaign_id = store.create_campaign("Logs survive")
    restaurant_id = _restaurant("Log Cafe")
    recipient_id = _recipient(campaign_id, restaurant_id)  # never sent: no ledger row
    store.add_log(campaign_id, "queued", "Waiting", recipient=store.get_recipient(recipient_id))
    _sql("DELETE FROM campaign_recipients WHERE id = :id", {"id": recipient_id})
    log = fetch_one("SELECT recipient_id, recipient_email, event, detail FROM campaign_send_logs WHERE campaign_id = :cid",
                    {"cid": campaign_id})
    assert log["recipient_id"] is None
    assert log["recipient_email"] == "owner@integrity.pk"
    assert log["event"] == "queued"


def test_restaurant_deletion_is_refused_while_a_draft_points_at_it(test_db):
    restaurant_id = _restaurant("Draft Parent")
    _draft(restaurant_id)
    with pytest.raises(IntegrityError):
        _sql("DELETE FROM restaurants WHERE id = :id", {"id": restaurant_id})
    assert fetch_one("SELECT COUNT(*) AS n FROM restaurants WHERE id = :id", {"id": restaurant_id})["n"] == 1


# ── Audit, migration refusal, rollback ───────────────────────────────────────

def test_audit_is_clean_on_valid_data(test_db):
    campaign_id = store.create_campaign("Audit clean")
    _recipient(campaign_id, _restaurant("Audit Cafe"))
    with get_engine().connect() as conn:
        assert _audit_module().audit(conn) == []


def test_migration_refuses_orphans_and_changes_nothing(test_db):
    command.downgrade(_config(), PREVIOUS)
    _sql("INSERT INTO email_drafts (restaurant_id, campaign, subject, body, status) "
         "VALUES (424242, 'Orphan', 'Lost', 'Parent is gone', 'draft')")
    with get_engine().connect() as conn:
        problems = _audit_module().audit(conn)
    assert any("restaurant_id points at no restaurant" in p["problem"] for p in problems)

    with pytest.raises(RuntimeError, match="Integrity check failed. Nothing was changed"):
        command.upgrade(_config(), "head")
    with get_engine().connect() as conn:
        revision = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        orphan = conn.execute(text("SELECT COUNT(*) FROM email_drafts WHERE restaurant_id = 424242")).scalar_one()
    assert revision == PREVIOUS  # not moved forward
    assert orphan == 1  # the orphan is still there: nothing was silently deleted


def test_migration_rollback_removes_the_constraints_and_reapplying_restores_them(test_db):
    campaign_id = store.create_campaign("Round trip")
    restaurant_id = _restaurant("Round Trip Cafe")
    recipient_id = _recipient(campaign_id, restaurant_id)
    before = fetch_one("SELECT COUNT(*) AS n FROM campaign_recipients")["n"]

    command.downgrade(_config(), PREVIOUS)
    # Rolled back: the old schema accepts what the new one refuses.
    _sql("UPDATE campaigns SET status = 'bogus' WHERE id = :id", {"id": campaign_id})
    _sql("UPDATE campaigns SET status = 'review' WHERE id = :id", {"id": campaign_id})

    command.upgrade(_config(), "head")
    assert fetch_one("SELECT COUNT(*) AS n FROM campaign_recipients")["n"] == before
    assert fetch_one("SELECT campaign_id FROM campaign_recipients WHERE id = :id", {"id": recipient_id})["campaign_id"] == campaign_id
    with pytest.raises(IntegrityError):
        _sql("UPDATE campaigns SET status = 'bogus' WHERE id = :id", {"id": campaign_id})
    with pytest.raises(IntegrityError):
        _sql("INSERT INTO email_drafts (restaurant_id, campaign, subject, body, status) VALUES (999999, 'x', 's', 'b', 'draft')")


def test_the_new_indexes_exist_after_migration(test_db):
    with get_engine().connect() as conn:
        inspector = inspect(conn)
        names = {index["name"] for index in inspector.get_indexes("campaign_recipients")}
        names |= {index["name"] for index in inspector.get_indexes("email_conversations")}
        names |= {index["name"] for index in inspector.get_indexes("campaign_send_logs")}
    assert {"ix_campaign_recipients_restaurant", "ix_email_conversations_restaurant", "ix_campaign_send_logs_recipient"} <= names
