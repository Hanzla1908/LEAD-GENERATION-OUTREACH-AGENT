"""Deleting demo (sample) business records.

Only source = 'demo' rows are deleted. A demo record that has draft or campaign history is kept and reported.
Real records are never touched, and the delete is limited to the current workspace and to users who can operate.
"""
import pytest
from fastapi.testclient import TestClient

import main
from models.database import create_draft, fetch_one, save_restaurants
from tests.account_helpers import TEST_SESSION_SECRET, login_client, make_account

VIEWER_EMAIL = "viewer.demo@example.test"
VIEWER_PASSWORD = "viewer-passphrase-1"


@pytest.fixture
def api(test_db, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    from tests.account_helpers import signed_in_client
    return signed_in_client(main.app)


def _count(place_id: str) -> int:
    return fetch_one("SELECT COUNT(*) AS n FROM restaurants WHERE place_id = :p", {"p": place_id})["n"]


def _demo(place_id: str, name: str) -> int:
    return save_restaurants([{"place_id": place_id, "name": name, "source": "demo"}])[0]["id"]


def test_demo_records_without_history_are_deleted(api):
    ids = [_demo("demo-a", "[DEMO] A"), _demo("demo-b", "[DEMO] B")]
    resp = api.post("/restaurants/delete-demo", json={"ids": ids})
    assert resp.status_code == 200, resp.text
    assert sorted(resp.json()["deleted"]) == sorted(ids)
    assert resp.json()["kept"] == []
    assert _count("demo-a") == 0 and _count("demo-b") == 0


def test_delete_all_demo_records_when_no_ids_are_given(api):
    _demo("demo-all-1", "[DEMO] 1")
    _demo("demo-all-2", "[DEMO] 2")
    resp = api.post("/restaurants/delete-demo", json={})
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["deleted"]) >= 2
    assert _count("demo-all-1") == 0 and _count("demo-all-2") == 0


def test_real_records_are_never_deleted(api):
    real = save_restaurants([{"place_id": "real-1", "name": "Real Cafe", "source": "google_places"}])[0]["id"]
    manual = save_restaurants([{"place_id": "manual-1", "name": "Typed Cafe", "source": "manual"}])[0]["id"]
    resp = api.post("/restaurants/delete-demo", json={"ids": [real, manual]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["deleted"] == []
    assert _count("real-1") == 1 and _count("manual-1") == 1


def test_a_demo_record_with_a_draft_is_kept_and_reported(api):
    kept_id = _demo("demo-kept", "[DEMO] Kept")
    create_draft(kept_id, "Spring", "Hello", "Body text")
    free_id = _demo("demo-free", "[DEMO] Free")
    resp = api.post("/restaurants/delete-demo", json={"ids": [kept_id, free_id]})
    body = resp.json()
    assert body["deleted"] == [free_id]
    assert [item["id"] for item in body["kept"]] == [kept_id]
    assert "history" in body["kept"][0]["reason"]
    assert _count("demo-kept") == 1


def test_an_empty_id_list_deletes_nothing(api):
    _demo("demo-empty", "[DEMO] Empty")
    resp = api.post("/restaurants/delete-demo", json={"ids": []})
    assert resp.json() == {"deleted": [], "kept": []}
    assert _count("demo-empty") == 1


def test_a_viewer_cannot_delete_demo_records(test_db, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    make_account(VIEWER_EMAIL, "viewer", password=VIEWER_PASSWORD, name="Vera Viewer")
    rid = _demo("demo-viewer", "[DEMO] Viewer")
    client = login_client(main.app, VIEWER_EMAIL, VIEWER_PASSWORD)
    resp = client.post("/restaurants/delete-demo", json={"ids": [rid]})
    assert resp.status_code == 403
    assert _count("demo-viewer") == 1


def test_the_delete_is_written_to_the_audit_log(api):
    _demo("demo-audit", "[DEMO] Audit")
    api.post("/restaurants/delete-demo", json={})
    row = fetch_one("SELECT action, detail FROM audit_log WHERE action = 'restaurant.demo_deleted' "
                    "ORDER BY id DESC LIMIT 1")
    assert row is not None and "deleted=" in row["detail"]


def test_an_invalid_id_list_is_refused(api):
    assert api.post("/restaurants/delete-demo", json={"ids": list(range(1001))}).status_code == 422
