"""SQLite to PostgreSQL data copy. Uses TEST_POSTGRES_URL as the target when set, otherwise a second SQLite file."""
import importlib.util
import os
from pathlib import Path

import pytest
from sqlalchemy import text

from models.database import execute, fetch_all, fetch_one, get_engine, init_db, save_restaurants

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "migrate_sqlite_to_postgres.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("migrate_sqlite_to_postgres", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_source(source_file: str, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", source_file)
    init_db()
    restaurant_id = save_restaurants([{
        "place_id": "migrate-1", "name": "Migrated Karahi", "address": "Peoples Colony, Faisalabad",
        "source": "google_places",
    }])[0]["id"]
    execute("UPDATE restaurants SET contact_email = :email, lead_status = 'qualified', lead_score = 90 WHERE id = :id",
            {"email": "owner@migrated.pk", "id": restaurant_id})
    execute("INSERT INTO email_drafts (restaurant_id, campaign, subject, body, status) "
            "VALUES (:rid, 'Migrate', 'Subject', 'Body', 'approved')", {"rid": restaurant_id})
    execute("INSERT INTO suppression_list (email, reason) VALUES ('stop@migrated.pk', 'unsubscribed')")
    return restaurant_id


def test_migration_copies_every_table_and_keeps_the_source(tmp_path, monkeypatch):
    source_file = str(tmp_path / "source.db")
    restaurant_id = _seed_source(source_file, monkeypatch)
    source_size = Path(source_file).stat().st_size

    postgres_url = os.getenv("TEST_POSTGRES_URL", "").strip()
    if postgres_url:
        target = postgres_url
        monkeypatch.setenv("DATABASE_URL", postgres_url)
        with get_engine().begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
        monkeypatch.setenv("DATABASE_URL", source_file)
    else:
        target = str(tmp_path / "target.db")

    migrate = _load_script().migrate
    counts = migrate(source_file, target if "://" in target else f"sqlite:///{target}")
    assert counts["restaurants"] == 1
    assert counts["email_drafts"] == 1
    assert counts["suppression_list"] == 1
    assert Path(source_file).stat().st_size == source_size

    monkeypatch.setenv("DATABASE_URL", target if "://" in target else f"sqlite:///{target}")
    row = fetch_one("SELECT * FROM restaurants WHERE id = :id", {"id": restaurant_id})
    assert row["name"] == "Migrated Karahi"
    assert row["contact_email"] == "owner@migrated.pk"
    assert row["lead_score"] == 90
    assert fetch_one("SELECT COUNT(*) AS n FROM email_drafts WHERE campaign = 'Migrate'")["n"] == 1
    assert fetch_one("SELECT email FROM suppression_list")["email"] == "stop@migrated.pk"


def test_migration_refuses_a_target_that_already_has_data(tmp_path, monkeypatch):
    source_file = str(tmp_path / "source.db")
    _seed_source(source_file, monkeypatch)
    target = str(tmp_path / "busy.db")
    migrate = _load_script().migrate
    migrate(source_file, f"sqlite:///{target}")
    with pytest.raises(SystemExit):
        migrate(source_file, f"sqlite:///{target}")
