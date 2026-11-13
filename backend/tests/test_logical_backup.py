"""Logical backup and restore: round trip, checksum protection, and refusal to overwrite data.

Runs on SQLite by default and on PostgreSQL when TEST_POSTGRES_URL is set (the source is then PostgreSQL
and the restore target is a SQLite file).
"""
import importlib.util
import json
from pathlib import Path

import pytest

from models.database import execute, fetch_one, get_engine, is_postgres, save_restaurants

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "logical_backup.py"


def _load():
    spec = importlib.util.spec_from_file_location("logical_backup", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed() -> int:
    restaurant_id = save_restaurants([{
        "place_id": "backup-1", "name": "Backup Karahi", "address": "Peoples Colony, Faisalabad",
        "source": "google_places",
    }])[0]["id"]
    execute("UPDATE restaurants SET contact_email = :email, lead_status = 'qualified', lead_score = 88 WHERE id = :id",
            {"email": "owner@backup.pk", "id": restaurant_id})
    execute("INSERT INTO email_drafts (restaurant_id, campaign, subject, body, status) "
            "VALUES (:rid, 'Backup', 'Subject', 'Body', 'approved')", {"rid": restaurant_id})
    execute("INSERT INTO suppression_list (email, reason) VALUES ('stop@backup.pk', 'unsubscribed')")
    return restaurant_id


def test_backup_restores_every_table_and_is_lossless(test_db, tmp_path, monkeypatch):
    lb = _load()
    source_is_sqlite = not is_postgres()  # decided before DATABASE_URL points at the restore target
    restaurant_id = _seed()
    source_manifest = lb.export_database(str(tmp_path / "source"))
    assert source_manifest["tables"]["restaurants"]["rows"] == 1
    assert source_manifest["tables"]["email_drafts"]["rows"] == 1
    assert source_manifest["tables"]["suppression_list"]["rows"] == 1

    target = tmp_path / "restored.db"
    counts = lb.restore_database(str(tmp_path / "source"), f"sqlite:///{target}")
    assert counts == {table: source_manifest["tables"][table]["rows"] for table in lb.TABLES}

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{target}")
    row = fetch_one("SELECT name, contact_email, lead_score FROM restaurants WHERE id = :id", {"id": restaurant_id})
    assert row == {"name": "Backup Karahi", "contact_email": "owner@backup.pk", "lead_score": 88}

    if source_is_sqlite:
        # Exporting the restored copy gives byte-identical table files, so nothing was lost or altered.
        restored_manifest = lb.export_database(str(tmp_path / "restored"))
        for table in lb.TABLES:
            assert restored_manifest["tables"][table]["sha256"] == source_manifest["tables"][table]["sha256"], table


def test_tampered_backup_is_refused_before_anything_is_written(test_db, tmp_path):
    lb = _load()
    _seed()
    folder = tmp_path / "bk"
    lb.export_database(str(folder))
    path = folder / "restaurants.jsonl"
    path.write_text(path.read_text(encoding="utf-8").replace("Backup Karahi", "Changed Name"), encoding="utf-8")

    target = tmp_path / "target.db"
    with pytest.raises(lb.BackupError, match="Checksum mismatch"):
        lb.restore_database(str(folder), f"sqlite:///{target}")
    assert not target.exists()  # verification runs before the target is created or written


def test_incomplete_backup_is_refused(test_db, tmp_path):
    lb = _load()
    _seed()
    folder = tmp_path / "bk"
    lb.export_database(str(folder))
    (folder / "manifest.json").unlink()
    with pytest.raises(lb.BackupError, match="manifest.json is missing"):
        lb.restore_database(str(folder), f"sqlite:///{tmp_path / 'target.db'}")


def test_restore_refuses_a_target_that_already_has_data(test_db, tmp_path):
    lb = _load()
    _seed()
    folder = tmp_path / "bk"
    lb.export_database(str(folder))
    with pytest.raises(lb.BackupError, match="already has"):
        lb.restore_database(str(folder), test_db if "://" in test_db else f"sqlite:///{test_db}")


def test_manifest_lists_every_exported_table(test_db, tmp_path):
    lb = _load()
    _seed()
    manifest = lb.export_database(str(tmp_path / "bk"))
    listed = json.loads((tmp_path / "bk" / "manifest.json").read_text(encoding="utf-8"))
    assert set(listed["tables"]) == set(lb.TABLES) == set(manifest["tables"])
    assert "auth_sessions" not in listed["tables"]
