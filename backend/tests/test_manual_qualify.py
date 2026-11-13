"""Marking a lead that needs review as qualified by hand.

Only a needs_review lead changes. The score is kept, the reason records the decision, the action is audited, and
the lead becomes eligible for outreach only when its email is also usable.
"""
import pytest
from fastapi.testclient import TestClient

import main
from models.database import execute, fetch_one, save_restaurants
from services.campaigns import outreach_reasons
from tests.account_helpers import TEST_SESSION_SECRET, login_client, make_account

VIEWER_EMAIL = "viewer.manual@example.test"
VIEWER_PASSWORD = "viewer-passphrase-1"


@pytest.fixture
def api(test_db, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    from tests.account_helpers import signed_in_client
    return signed_in_client(main.app)


def _lead(place_id: str, status: str, email: str | None = "owner@cafe.pk", opted_out: int = 0) -> int:
    rid = save_restaurants([{"place_id": place_id, "name": f"Lead {place_id}", "source": "google_places",
                             "website": "https://cafe.pk/"}])[0]["id"]
    execute("UPDATE restaurants SET lead_status = :s, lead_score = 45, contact_email = :e, "
            "contact_email_status = 'domain_valid', contact_email_classification = 'business', "
            "opted_out = :o WHERE id = :id", {"s": status, "e": email, "o": opted_out, "id": rid})
    return rid


def test_a_needs_review_lead_becomes_qualified_and_keeps_its_score(api):
    rid = _lead("review-1", "needs_review")
    resp = api.post(f"/restaurants/{rid}/manual-qualify", json={"note": "Checked the website by hand"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["lead_status"] == "qualified"
    assert body["lead_score"] == 45
    assert body["lead_reason"] == "Qualified by manual review: Checked the website by hand"


def test_a_qualified_lead_with_a_business_email_is_eligible_for_outreach(api):
    rid = _lead("review-2", "needs_review")
    api.post(f"/restaurants/{rid}/manual-qualify", json={})
    row = fetch_one("SELECT * FROM restaurants WHERE id = :id", {"id": rid})
    assert outreach_reasons(row, set()) == []


def test_other_statuses_are_refused(api):
    qualified = _lead("q-1", "qualified")
    disqualified = _lead("d-1", "disqualified")
    for rid in (qualified, disqualified):
        resp = api.post(f"/restaurants/{rid}/manual-qualify", json={})
        assert resp.status_code == 422
        assert "needs review" in resp.json()["detail"]


def test_an_opted_out_business_is_refused(api):
    rid = _lead("opted-1", "needs_review", opted_out=1)
    resp = api.post(f"/restaurants/{rid}/manual-qualify", json={})
    assert resp.status_code == 422
    assert fetch_one("SELECT lead_status FROM restaurants WHERE id = :id", {"id": rid})["lead_status"] == "needs_review"


def test_an_unknown_business_is_not_found(api):
    assert api.post("/restaurants/999999/manual-qualify", json={}).status_code == 404


def test_the_note_is_limited_in_length(api):
    rid = _lead("note-1", "needs_review")
    assert api.post(f"/restaurants/{rid}/manual-qualify", json={"note": "x" * 301}).status_code == 422


def test_the_decision_is_written_to_the_audit_log(api):
    rid = _lead("audit-1", "needs_review")
    api.post(f"/restaurants/{rid}/manual-qualify", json={"note": "ok"})
    row = fetch_one("SELECT action, detail FROM audit_log WHERE action = 'lead.manually_qualified' "
                    "ORDER BY id DESC LIMIT 1")
    assert row is not None and f"score=45" in row["detail"]


def test_a_viewer_cannot_mark_a_lead_qualified(test_db, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    make_account(VIEWER_EMAIL, "viewer", password=VIEWER_PASSWORD, name="Vera Viewer")
    rid = _lead("viewer-1", "needs_review")
    client = login_client(main.app, VIEWER_EMAIL, VIEWER_PASSWORD)
    assert client.post(f"/restaurants/{rid}/manual-qualify", json={}).status_code == 403
    assert fetch_one("SELECT lead_status FROM restaurants WHERE id = :id", {"id": rid})["lead_status"] == "needs_review"
