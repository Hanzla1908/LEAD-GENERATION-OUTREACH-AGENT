"""Deleting business leads: soft delete, bulk delete, restore, workspace isolation, history and campaign safety.

Nothing is sent, and no real email or Google request is made.
"""
import pytest
from fastapi.testclient import TestClient

import main
from models.database import create_draft, execute, fetch_one, get_restaurant_by_id, save_restaurants
from tests.account_helpers import TEST_SESSION_SECRET, login_client, make_account, signed_in_client

VIEWER_EMAIL = "viewer.delete@example.test"
VIEWER_PASSWORD = "viewer-passphrase-1"


@pytest.fixture
def api(test_db, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    return signed_in_client(main.app)


def _lead(place_id: str, name: str = None, email: str = "owner@cafe.pk") -> int:
    rid = save_restaurants([{"place_id": place_id, "name": name or f"Lead {place_id}", "source": "google_places",
                             "website": "https://cafe.pk/"}])[0]["id"]
    execute("UPDATE restaurants SET lead_status = 'qualified', lead_score = 80, contact_email = :e, "
            "contact_email_status = 'domain_valid', contact_email_classification = 'business' WHERE id = :id",
            {"e": email, "id": rid})
    return rid


def _listed_ids(api) -> set[int]:
    return {row["id"] for row in api.get("/restaurants").json()}


def _deleted_at(rid: int):
    return fetch_one("SELECT deleted_at FROM restaurants WHERE id = :id", {"id": rid})["deleted_at"]


def test_deleting_a_lead_hides_it_but_keeps_the_row(api):
    rid = _lead("del-1")
    assert rid in _listed_ids(api)
    resp = api.delete(f"/restaurants/{rid}")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"deleted": [rid]}
    assert rid not in _listed_ids(api)
    assert _deleted_at(rid) is not None
    assert get_restaurant_by_id(rid) is None


def test_a_deleted_lead_is_missing_from_eligibility_and_the_campaign_preview(api):
    rid = _lead("del-2")
    api.delete(f"/restaurants/{rid}")
    assert str(rid) not in api.get("/outreach/eligibility").json()
    preview = api.post("/campaigns/preview", json={"name": "After delete", "restaurant_ids": [rid]}).json()
    assert preview["eligible_count"] == 0
    assert any("not found" in reason.lower() for reason in preview["items"][0]["reasons"])


def test_a_deleted_lead_cannot_start_a_campaign(api):
    rid = _lead("del-3")
    api.delete(f"/restaurants/{rid}")
    resp = api.post("/campaigns", json={"name": "Blocked", "restaurant_ids": [rid]})
    assert resp.status_code in (409, 422)
    assert fetch_one("SELECT COUNT(*) AS n FROM campaigns WHERE name = 'Blocked'")["n"] == 0


def test_a_draft_for_a_deleted_lead_cannot_be_approved(api):
    rid = _lead("del-4")
    draft = create_draft(rid, "Spring", "Subject", "Body text")
    api.delete(f"/restaurants/{rid}")
    resp = api.post(f"/outreach/drafts/{draft['id']}/approve")
    assert resp.status_code == 404
    assert fetch_one("SELECT status FROM email_drafts WHERE id = :id", {"id": draft["id"]})["status"] == "draft"


def test_bulk_delete_reports_the_missing_ids(api):
    a, b = _lead("bulk-a"), _lead("bulk-b")
    resp = api.post("/restaurants/bulk-delete", json={"ids": [a, b, 999999]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert sorted(body["deleted"]) == sorted([a, b])
    assert body["missing"] == [999999]
    assert a not in _listed_ids(api) and b not in _listed_ids(api)


def test_deleting_an_already_deleted_lead_is_not_found(api):
    rid = _lead("twice-1")
    api.delete(f"/restaurants/{rid}")
    assert api.delete(f"/restaurants/{rid}").status_code == 404


def test_the_deleted_view_lists_deleted_leads_only(api):
    kept, gone = _lead("view-kept"), _lead("view-gone")
    api.delete(f"/restaurants/{gone}")
    ids = {row["id"] for row in api.get("/restaurants/deleted").json()}
    assert gone in ids and kept not in ids


def test_restoring_brings_the_lead_back(api):
    rid = _lead("restore-1")
    api.delete(f"/restaurants/{rid}")
    resp = api.post(f"/restaurants/{rid}/restore")
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == rid
    assert rid in _listed_ids(api)
    assert _deleted_at(rid) is None
    assert api.post(f"/restaurants/{rid}/restore").status_code == 404


def test_restored_lead_is_eligible_again(api):
    rid = _lead("restore-2")
    api.delete(f"/restaurants/{rid}")
    api.post(f"/restaurants/{rid}/restore")
    assert api.get("/outreach/eligibility").json()[str(rid)]["eligible"] is True


def test_history_is_kept_when_a_lead_is_deleted(api):
    rid = _lead("history-1")
    draft = create_draft(rid, "Spring", "Subject", "Body text")
    before = fetch_one("SELECT COUNT(*) AS n, MAX(status) AS s FROM email_drafts WHERE restaurant_id = :id", {"id": rid})
    api.delete(f"/restaurants/{rid}")
    after = fetch_one("SELECT COUNT(*) AS n, MAX(status) AS s FROM email_drafts WHERE restaurant_id = :id", {"id": rid})
    assert before == after
    assert fetch_one("SELECT id FROM email_drafts WHERE id = :id", {"id": draft["id"]}) is not None
    assert fetch_one("SELECT COUNT(*) AS n FROM restaurants WHERE id = :id", {"id": rid})["n"] == 1


def test_deleting_is_written_to_the_audit_log(api):
    rid = _lead("audit-del")
    api.delete(f"/restaurants/{rid}")
    row = fetch_one("SELECT action, target_id FROM audit_log WHERE action = 'lead.deleted' "
                    "ORDER BY id DESC LIMIT 1")
    assert row is not None and str(row["target_id"]) == str(rid)


def test_a_viewer_cannot_delete_bulk_delete_or_restore(test_db, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    make_account(VIEWER_EMAIL, "viewer", password=VIEWER_PASSWORD, name="Vera Viewer")
    rid = _lead("viewer-del")
    client = login_client(main.app, VIEWER_EMAIL, VIEWER_PASSWORD)
    assert client.delete(f"/restaurants/{rid}").status_code == 403
    assert client.post("/restaurants/bulk-delete", json={"ids": [rid]}).status_code == 403
    assert _deleted_at(rid) is None
    execute("UPDATE restaurants SET deleted_at = CURRENT_TIMESTAMP WHERE id = :id", {"id": rid})
    assert client.post(f"/restaurants/{rid}/restore").status_code == 403


def test_another_workspaces_lead_cannot_be_deleted_or_restored(api):
    execute("INSERT INTO workspaces (name, created_by_user_id) VALUES ('Other workspace', NULL)")
    other_ws = fetch_one("SELECT id FROM workspaces WHERE name = 'Other workspace'")["id"]
    execute("INSERT INTO restaurants (place_id, name, source, workspace_id, country, country_code, lead_status) "
            "VALUES ('foreign-1', 'Foreign Cafe', 'google_places', :ws, 'Pakistan', 'PK', 'qualified')", {"ws": other_ws})
    foreign = fetch_one("SELECT id FROM restaurants WHERE place_id = 'foreign-1'")["id"]
    assert api.delete(f"/restaurants/{foreign}").status_code == 404
    assert api.post("/restaurants/bulk-delete", json={"ids": [foreign]}).json()["missing"] == [foreign]
    assert _deleted_at(foreign) is None
    assert api.post(f"/restaurants/{foreign}/restore").status_code == 404
    assert foreign not in {row["id"] for row in api.get("/restaurants/deleted").json()}


# ── Sending safety: a deleted lead is skipped even when its draft was approved ───────────────────

from tests.test_campaigns import _approve_all, _create, _restaurant, _send, client, env  # noqa: E402,F401


def test_a_lead_deleted_after_its_draft_was_approved_is_never_emailed(client, env):
    deleted = _restaurant("Deleted Before Send", email="deleted-before@cafe.com")
    kept = _restaurant("Kept For Send", email="kept-for@cafe.com")
    detail = _create(client, "Delete before send", [deleted, kept]).json()
    _approve_all(client, detail)
    assert client.delete(f"/restaurants/{deleted}").status_code == 200
    _send(client, detail["id"])
    sent_to = [message["to"][0] for message in env["sender"].outbox]
    assert "deleted-before@cafe.com" not in sent_to
    assert "kept-for@cafe.com" in sent_to
