"""Phase 12 launch safety: demo records, opt-outs, duplicate drafts, and mixed selections.

All through the real API with the mock sender. Claude and Google are never called.
"""
import pytest

from models import campaign_store
from models.database import create_draft, execute, save_restaurants
from tests.test_campaigns import _approve_all, _create, _recipient, _restaurant, _send, client, env  # noqa: F401


def _demo_with_email(name: str) -> int:
    """A demo record that somehow has a contact email. It must still never be contacted."""
    rid = save_restaurants([{
        "place_id": f"demo-launch-{name}", "name": f"[DEMO] {name}", "address": "Demo Street 1, Lahore, Pakistan",
        "source": "demo",
    }])[0]["id"]
    execute(
        "UPDATE restaurants SET contact_email = :email, contact_email_status = 'unverified', "
        "lead_status = 'qualified', lead_score = 90 WHERE id = :id",
        {"email": f"demo-{name.lower()}@cafe.pk", "id": rid},
    )
    return rid


def test_demo_record_cannot_get_a_generated_draft(client, env):
    rid = _demo_with_email("Generate")
    resp = client.post("/outreach/generate", json={"restaurant_id": rid})
    assert resp.status_code == 422
    assert "Demo or sample" in resp.json()["detail"]
    assert env["sender"].outbox == []


def test_existing_demo_draft_cannot_be_approved(client, env):
    rid = _demo_with_email("Approve")
    draft = create_draft(restaurant_id=rid, campaign="Launch check", subject="Hello", body="Body", angle=None)
    resp = client.post(f"/outreach/drafts/{draft['id']}/approve")
    assert resp.status_code == 422
    assert "Demo or sample" in resp.json()["detail"]
    assert client.get(f"/outreach/drafts/{draft['id']}").json()["status"] == "draft"


def test_existing_demo_draft_cannot_be_regenerated(client, env):
    rid = _demo_with_email("Regenerate")
    draft = create_draft(restaurant_id=rid, campaign="Launch check", subject="Hello", body="Body", angle=None)
    resp = client.post(f"/outreach/drafts/{draft['id']}/regenerate")
    assert resp.status_code == 422
    assert "Demo or sample" in resp.json()["detail"]


def test_campaign_made_only_of_demo_records_is_refused(client, env):
    demo = _demo_with_email("OnlyDemo")
    resp = _create(client, "Demo only", [demo])
    assert resp.status_code == 422
    assert campaign_store.list_campaigns() == []


def test_mixed_selection_sends_only_the_real_restaurant(client, env):
    real = _restaurant("Launch Real Cafe", email="real-launch@cafe.pk")
    demo = _demo_with_email("Mixed")
    detail = _create(client, "Mixed selection", [real, demo]).json()
    assert _recipient(detail, demo)["status"] == "skipped"
    _approve_all(client, detail)
    _send(client, detail["id"])
    assert [m["to"][0] for m in env["sender"].outbox] == ["real-launch@cafe.pk"]


def test_opted_out_restaurant_gets_no_draft_and_no_campaign(client, env):
    rid = _restaurant("Opted Out Cafe", email="optout-launch@cafe.pk", opted_out=1)
    assert client.post("/outreach/generate", json={"restaurant_id": rid}).status_code == 422
    resp = _create(client, "Opted out", [rid])
    assert resp.status_code == 422
    assert env["sender"].outbox == []


def test_second_active_draft_for_the_same_restaurant_and_campaign_is_refused(client, env):
    rid = _restaurant("Duplicate Draft Cafe", email="dup-launch@cafe.pk")
    create_draft(restaurant_id=rid, campaign="Duplicate check", subject="First", body="Body", angle=None)
    with pytest.raises(ValueError):
        create_draft(restaurant_id=rid, campaign="Duplicate check", subject="Second", body="Body", angle=None)


def test_batch_website_checks_run_concurrently_within_the_bound(client, env, monkeypatch):
    import asyncio

    import main

    ids = [_restaurant(f"Batch Cafe {i}", email=f"batch{i}@cafe.pk") for i in range(12)]
    for rid in ids:
        execute("UPDATE restaurants SET website = :site WHERE id = :id", {"site": f"https://cafe{rid}.example/", "id": rid})

    in_flight = {"now": 0, "max": 0}

    async def fake_check(url):
        in_flight["now"] += 1
        in_flight["max"] = max(in_flight["max"], in_flight["now"])
        await asyncio.sleep(0.05)
        in_flight["now"] -= 1
        return {"website_status": "present", "ordering_status": "not_found", "ordering_evidence": [], "error": None}

    monkeypatch.setattr(main, "check_website", fake_check)
    resp = client.post("/restaurants/check-batch", json={"ids": ids})
    assert resp.status_code == 200
    assert [row["id"] for row in resp.json()] == ids  # request order is kept
    assert 1 < in_flight["max"] <= main.BATCH_CONCURRENCY


def _live_smtp_settings(monkeypatch):
    """Live provider settings. SMTP is never contacted: both tests stop before any connection."""
    from services import campaigns as campaign_service
    from services.email_sender import get_sender as real_get_sender

    monkeypatch.setattr(campaign_service, "get_sender", real_get_sender)  # the env fixture mocks it otherwise
    monkeypatch.setenv("MOCK_EMAIL_MODE", "false")
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("EMAIL_FROM", "sender@example.test")


def test_live_sending_is_refused_without_a_sender_postal_address(client, env, monkeypatch):
    monkeypatch.delenv("SENDER_ADDRESS", raising=False)
    rid = _restaurant("Address Check Cafe", email="address-check@cafe.pk")
    detail = _create(client, "Address check", [rid]).json()
    _live_smtp_settings(monkeypatch)
    resp = client.post(f"/campaigns/{detail['id']}/send")
    assert resp.status_code == 409
    assert "SENDER_ADDRESS" in resp.json()["detail"]
    assert env["sender"].outbox == []


def test_live_sending_passes_the_address_check_once_it_is_set(client, env, monkeypatch):
    monkeypatch.setenv("SENDER_ADDRESS", "Outreach Team, 12 Main Road, Lahore")
    rid = _restaurant("Address Ready Cafe", email="address-ready@cafe.pk")
    detail = _create(client, "Address ready", [rid]).json()
    _live_smtp_settings(monkeypatch)
    resp = client.post(f"/campaigns/{detail['id']}/send")
    # Refused only because nothing is approved yet, not because of the address.
    assert resp.status_code == 409
    assert "SENDER_ADDRESS" not in resp.json()["detail"]
    assert "approved" in resp.json()["detail"].lower()
    assert env["sender"].outbox == []


def test_send_with_no_approval_is_refused_and_nothing_is_sent(client, env):
    rid = _restaurant("Unapproved Cafe", email="unapproved-launch@cafe.pk")
    detail = _create(client, "Unapproved", [rid]).json()
    resp = client.post(f"/campaigns/{detail['id']}/send")
    assert resp.status_code == 409  # refused: nothing is approved to send
    assert "approved" in resp.json()["detail"].lower()
    assert env["sender"].outbox == []
