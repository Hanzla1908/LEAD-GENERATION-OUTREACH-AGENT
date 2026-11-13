"""Bulk email campaigns: eligibility, draft generation, sending, duplicates, failures, tracking.

Nothing here contacts Claude, Google, or an SMTP server. The mock sender is the only provider.
"""
import json
import os
import smtplib
import sqlite3

import httpx
import pytest
from fastapi.testclient import TestClient  # noqa: F401
from tests.account_helpers import signed_in_client

import main
from models import campaign_store
from models.database import save_restaurants
from services import campaigns as campaign_service
from services.email_sender import (
    MockSender, NodemailerSender, SendError, SendOutcomeUnknown, SmtpSender, get_sender,
)
from services.unsubscribe import make_token

SECRET = "test-secret"
BASE_URL = "https://outreach.test"


class HookSender(MockSender):
    def __init__(self, fail_addresses=(), on_send=None):
        super().__init__(fail_addresses)
        self.on_send = on_send

    def send(self, to, subject, body, idempotency_key, **kwargs):
        message_id = super().send(to, subject, body, idempotency_key, **kwargs)
        if self.on_send:
            self.on_send(len(self.outbox))
        return message_id


async def fake_generate(restaurant):
    if restaurant["name"].startswith("Broken"):
        raise ValueError("Claude returned non-JSON output")
    return {
        "subject": f"Idea for {restaurant['name']}",
        "body": f"Hello {restaurant['name']} team, we can help with online ordering.",
        "angle": "ordering_gap",
    }


def _refuse_smtp(*args, **kwargs):
    raise AssertionError("Tests must never open an SMTP connection")


@pytest.fixture
def env(test_db, monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "mock")
    monkeypatch.setenv("EMAIL_PER_MINUTE", "0")
    monkeypatch.setenv("EMAIL_DAILY_LIMIT", "100")
    monkeypatch.setenv("UNSUBSCRIBE_SECRET", SECRET)
    monkeypatch.setenv("PUBLIC_BASE_URL", BASE_URL)
    monkeypatch.delenv("SENDER_ADDRESS", raising=False)
    monkeypatch.setattr(smtplib, "SMTP", _refuse_smtp)
    monkeypatch.setattr(campaign_service, "_spawn", lambda target, *args: target(*args))
    monkeypatch.setattr(campaign_service, "_sleep", lambda seconds: None)
    monkeypatch.setattr(campaign_service, "generate_draft", fake_generate)

    state = {"sender": MockSender()}
    monkeypatch.setattr(campaign_service, "get_sender", lambda: state["sender"])

    def use_sender(sender):
        state["sender"] = sender
        return sender

    state["use"] = use_sender
    return state


@pytest.fixture
def client(env):
    return signed_in_client(main.app)


def _restaurant(name, email="owner@cafe.com", status="qualified", source="google_places",
                opted_out=0, email_status="unverified"):
    rid = save_restaurants([{
        "place_id": f"pid_{name}", "name": name, "address": "1 Main St, Lahore, Pakistan",
        "source": source,
    }])[0]["id"]
    from models.database import execute
    execute(
        "UPDATE restaurants SET contact_email = :email, contact_email_status = :email_status, "
        "lead_status = :status, opted_out = :opted_out WHERE id = :rid",
        {"email": email, "email_status": email_status, "status": status, "opted_out": opted_out, "rid": rid},
    )
    return rid


def _create(client, name, ids):
    return client.post("/campaigns", json={"name": name, "restaurant_ids": ids})


def _send(client, cid):
    detail = client.get(f"/campaigns/{cid}").json()
    ready = [r["draft_id"] for r in detail["recipients"] if r["status"] == "draft" and r["draft_status"] == "approved"]
    if ready:
        client.post(f"/campaigns/{cid}/approve-sending", json={"draft_ids": ready})
    return client.post(f"/campaigns/{cid}/send")


def _recipient(detail, restaurant_id):
    return next(r for r in detail["recipients"] if r["restaurant_id"] == restaurant_id)


def _approve_all(client, detail):
    for r in detail["recipients"]:
        if r["draft_id"] is not None:
            assert client.post(f"/outreach/drafts/{r['draft_id']}/approve").status_code == 200


# ── Eligibility rules ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("overrides, expected", [
    ({}, []),
    ({"email": None}, ["No public email found"]),
    ({"email_status": "invalid"}, ["Contact email is marked invalid"]),
    ({"email": "owner@example.com"}, ["Email is not a valid business address"]),
    ({"source": "demo"}, ["Demo or sample record, not a real business"]),
    ({"opted_out": 1}, ["Business has opted out of outreach"]),
    ({"status": "needs_review"}, ["Not qualified (current status: needs_review)"]),
])
def test_outreach_reasons(test_db, overrides, expected):
    restaurant = {
        "source": "google_places", "contact_email": "owner@cafe.com", "contact_email_status": "unverified",
        "opted_out": 0, "lead_status": "qualified",
    }
    if "email" in overrides:
        restaurant["contact_email"] = overrides["email"]
    if "email_status" in overrides:
        restaurant["contact_email_status"] = overrides["email_status"]
    if "source" in overrides:
        restaurant["source"] = overrides["source"]
    if "opted_out" in overrides:
        restaurant["opted_out"] = overrides["opted_out"]
    if "status" in overrides:
        restaurant["lead_status"] = overrides["status"]
    assert campaign_service.outreach_reasons(restaurant, set()) == expected


def test_suppressed_email_is_ineligible(test_db):
    restaurant = {"source": "google_places", "contact_email": "Owner@Cafe.com", "lead_status": "qualified"}
    campaign_store.add_suppression("owner@cafe.com", "test")
    assert "Email is on the suppression list" in campaign_service.outreach_reasons(
        restaurant, campaign_store.suppressed_emails())


def test_eligibility_endpoint_explains_each_restaurant(client):
    ok = _restaurant("Eligible Cafe")
    demo = _restaurant("Demo Diner", source="demo")
    resp = client.get("/outreach/eligibility")
    assert resp.status_code == 200
    data = resp.json()
    assert data[str(ok)] == {"eligible": True, "reasons": []}
    assert data[str(demo)]["eligible"] is False
    assert "Demo or sample record" in data[str(demo)]["reasons"][0]


# ── Preview and campaign creation ─────────────────────────────────────────────

def test_preview_separates_eligible_and_skipped(client):
    good = _restaurant("Good Grill")
    no_email = _restaurant("Quiet Kitchen", email=None)
    resp = client.post("/campaigns/preview", json={"name": "Spring", "restaurant_ids": [good, no_email]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["eligible_count"] == 1
    assert body["skipped_count"] == 1
    skipped = next(i for i in body["items"] if i["restaurant_id"] == no_email)
    assert skipped["reasons"] == ["No public email found"]


def test_create_campaign_generates_separate_drafts_for_eligible_only(client):
    a = _restaurant("Alpha Karahi")
    b = _restaurant("Beta Biryani", email="hello@beta.com")
    demo = _restaurant("Gamma Demo", source="demo")
    resp = _create(client, "Spring Outreach", [a, b, demo])
    assert resp.status_code == 201, resp.text
    detail = resp.json()
    assert detail["status"] == "review"
    assert detail["counts"]["total_selected"] == 3
    assert detail["counts"]["eligible"] == 2
    assert detail["counts"]["skipped"] == 1
    assert detail["counts"]["drafts_generated"] == 2

    draft_a = _recipient(detail, a)
    draft_b = _recipient(detail, b)
    assert draft_a["draft_id"] != draft_b["draft_id"]
    assert draft_a["subject"] != draft_b["subject"]
    assert draft_a["body"] != draft_b["body"]
    assert "Alpha Karahi" in draft_a["body"]
    assert "Beta Biryani" in draft_b["body"]
    assert _recipient(detail, demo)["status"] == "skipped"


def test_draft_generation_failure_is_reported_per_restaurant(client):
    good = _restaurant("Solid Shawarma")
    broken = _restaurant("Broken Grill", email="grill@broken.com")
    detail = _create(client, "Failures", [good, broken]).json()
    assert detail["counts"]["drafts_generated"] == 1
    assert detail["counts"]["drafts_failed"] == 1
    failed = _recipient(detail, broken)
    assert failed["status"] == "draft_failed"
    assert "non-JSON" in failed["error_reason"]


def test_duplicate_restaurant_ids_create_one_recipient(client):
    rid = _restaurant("Dup Diner")
    detail = _create(client, "Dedupe", [rid, rid]).json()
    assert len(detail["recipients"]) == 1


def test_no_eligible_restaurants_is_rejected(client):
    demo = _restaurant("Only Demo", source="demo")
    resp = _create(client, "Nothing", [demo])
    assert resp.status_code == 422


def test_campaign_name_too_short_is_rejected(client):
    rid = _restaurant("Name Check")
    assert _create(client, "x", [rid]).status_code == 422


def test_pending_draft_in_same_campaign_name_is_skipped(client):
    rid = _restaurant("Repeat Restaurant")
    _create(client, "Repeat", [rid])
    preview = client.post("/campaigns/preview", json={"name": "Repeat", "restaurant_ids": [rid]}).json()
    assert preview["eligible_count"] == 0
    assert any("pending draft" in reason for reason in preview["items"][0]["reasons"])


# ── Drafts: edit, approve, reject, regenerate ─────────────────────────────────

def test_edit_and_regenerate_keep_campaign_tracking(client, monkeypatch):
    rid = _restaurant("Editable Eatery")
    detail = _create(client, "Edits", [rid]).json()
    draft_id = _recipient(detail, rid)["draft_id"]

    edited = client.put(f"/outreach/drafts/{draft_id}", json={"subject": "Custom subject", "body": "Custom body"})
    assert edited.status_code == 200
    assert _recipient(client.get(f"/campaigns/{detail['id']}").json(), rid)["subject"] == "Custom subject"

    async def regenerated(restaurant, instructions=None):
        return {"subject": "Fresh subject", "body": "Fresh body", "angle": "general"}

    monkeypatch.setattr(main, "generate_draft", regenerated)
    new = client.post(f"/outreach/drafts/{draft_id}/regenerate").json()
    current = _recipient(client.get(f"/campaigns/{detail['id']}").json(), rid)
    assert current["draft_id"] == new["id"]
    assert current["subject"] == "Fresh subject"


def test_reject_removes_draft_from_send_queue(client, env):
    rid = _restaurant("Rejected Rolls")
    detail = _create(client, "Reject", [rid]).json()
    client.post(f"/outreach/drafts/{_recipient(detail, rid)['draft_id']}/reject")
    resp = _send(client, detail['id'])
    assert resp.status_code == 409
    assert env["sender"].outbox == []


# ── Sending ───────────────────────────────────────────────────────────────────

def test_send_only_approved_drafts_one_message_each(client, env):
    a = _restaurant("Approved One")
    b = _restaurant("Pending Two", email="two@cafe.com")
    detail = _create(client, "Partial", [a, b]).json()
    client.post(f"/outreach/drafts/{_recipient(detail, a)['draft_id']}/approve")

    resp = _send(client, detail['id'])
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["counts"]["sent"] == 1
    assert _recipient(result, b)["status"] == "draft"

    assert len(env["sender"].outbox) == 1
    message = env["sender"].outbox[0]
    assert message["to"] == ["owner@cafe.com"]
    assert "cc" not in message and "bcc" not in message


def test_every_recipient_gets_its_own_personal_body(client, env):
    ids = [_restaurant("Personal A"), _restaurant("Personal B", email="b@cafe.com")]
    detail = _create(client, "Personal", ids).json()
    _approve_all(client, detail)
    _send(client, detail['id'])
    assert len(env["sender"].outbox) == 2
    assert all(len(m["to"]) == 1 for m in env["sender"].outbox)
    bodies = [m["body"] for m in env["sender"].outbox]
    assert bodies[0] != bodies[1]
    assert "unsubscribe" in bodies[0].lower()


def test_send_without_approved_drafts_is_rejected(client, env):
    rid = _restaurant("Unapproved")
    detail = _create(client, "Nothing approved", [rid]).json()
    resp = _send(client, detail['id'])
    assert resp.status_code == 409
    assert "No approved drafts" in resp.json()["detail"]
    assert env["sender"].outbox == []


def test_second_send_does_not_duplicate_messages(client, env):
    rid = _restaurant("Once Only")
    detail = _create(client, "Once", [rid]).json()
    _approve_all(client, detail)
    _send(client, detail['id'])
    assert len(env["sender"].outbox) == 1

    assert _send(client, detail['id']).status_code == 409
    campaign_service.process_queue(detail["id"])
    assert len(env["sender"].outbox) == 1
    assert client.get(f"/campaigns/{detail['id']}").json()["counts"]["sent"] == 1


def test_suppression_added_after_approval_blocks_send(client, env):
    rid = _restaurant("Later Suppressed")
    detail = _create(client, "Suppression", [rid]).json()
    _approve_all(client, detail)
    client.post("/suppression", json={"email": "owner@cafe.com", "reason": "unsubscribe reply"})

    result = _send(client, detail['id']).json()
    assert env["sender"].outbox == []
    assert _recipient(result, rid)["status"] == "skipped"
    assert "suppression list" in _recipient(result, rid)["skip_reason"]


def test_opt_out_after_approval_blocks_send(client, env):
    rid = _restaurant("Opt Out Later")
    detail = _create(client, "Opt out", [rid]).json()
    _approve_all(client, detail)
    client.post(f"/restaurants/{rid}/opt-out")

    result = _send(client, detail['id']).json()
    assert env["sender"].outbox == []
    assert "opted out" in _recipient(result, rid)["skip_reason"]


def test_suppression_list_rejects_invalid_email(client):
    assert client.post("/suppression", json={"email": "not-an-email"}).status_code == 422


def test_send_failure_is_recorded_and_only_failed_rows_are_retried(client, env):
    ok = _restaurant("Reachable Cafe")
    bad = _restaurant("Bouncing Bakery", email="bounce@bakery.com")
    detail = _create(client, "Failures send", [ok, bad]).json()
    _approve_all(client, detail)

    env["use"](MockSender(fail_addresses=("bounce@bakery.com",)))
    result = _send(client, detail['id']).json()
    assert result["counts"]["sent"] == 1
    assert result["counts"]["failed"] == 1
    failed = _recipient(result, bad)
    assert failed["status"] == "failed"
    assert "rejected" in failed["error_reason"]
    assert failed["provider_message_id"] is None

    env["use"](MockSender())
    retried = client.post(f"/campaigns/{detail['id']}/retry-failed").json()
    assert retried["counts"]["sent"] == 2
    assert retried["counts"]["failed"] == 0
    recipients_sent = [m["to"][0] for m in env["sender"].outbox]
    assert recipients_sent.count("owner@cafe.com") == 0
    assert recipients_sent == ["bounce@bakery.com"]


def test_retry_with_nothing_failed_is_rejected(client, env):
    rid = _restaurant("Nothing To Retry")
    detail = _create(client, "No retry", [rid]).json()
    _approve_all(client, detail)
    _send(client, detail['id'])
    assert client.post(f"/campaigns/{detail['id']}/retry-failed").status_code == 409


def test_pause_stops_queue_and_resume_finishes_it(client, env):
    ids = [_restaurant("Pause A"), _restaurant("Pause B", email="pb@cafe.com"),
           _restaurant("Pause C", email="pc@cafe.com")]
    detail = _create(client, "Pausable", ids).json()
    _approve_all(client, detail)
    cid = detail["id"]

    env["use"](HookSender(on_send=lambda n: campaign_service.pause_sending(cid) if n == 1 else None))
    paused = _send(client, cid).json()
    assert paused["status"] == "paused"
    assert paused["counts"]["sent"] == 1
    assert paused["counts"]["queued"] == 2

    env["use"](MockSender())
    finished = client.post(f"/campaigns/{cid}/resume").json()
    assert finished["status"] == "completed"
    assert finished["counts"]["sent"] == 3
    assert len(env["sender"].outbox) == 2


def test_pause_is_only_allowed_while_sending(client, env):
    rid = _restaurant("Not Sending")
    detail = _create(client, "Pause guard", [rid]).json()
    assert client.post(f"/campaigns/{detail['id']}/pause").status_code == 409


def test_cancel_stops_queued_emails(client, env):
    ids = [_restaurant("Cancel A"), _restaurant("Cancel B", email="cb@cafe.com")]
    detail = _create(client, "Cancellable", ids).json()
    _approve_all(client, detail)
    cid = detail["id"]

    env["use"](HookSender(on_send=lambda n: campaign_service.cancel_campaign(cid) if n == 1 else None))
    result = _send(client, cid).json()
    assert result["status"] == "cancelled"
    assert result["counts"]["sent"] == 1
    assert result["counts"]["cancelled"] == 1
    assert len(env["sender"].outbox) == 1


def test_daily_limit_pauses_campaign(client, env, monkeypatch):
    monkeypatch.setenv("EMAIL_DAILY_LIMIT", "1")
    ids = [_restaurant("Limit A"), _restaurant("Limit B", email="lb@cafe.com")]
    detail = _create(client, "Limited", ids).json()
    _approve_all(client, detail)
    result = _send(client, detail['id']).json()
    assert result["status"] == "paused"
    assert "Daily sending limit" in result["status_note"]
    assert result["counts"]["sent"] == 1
    assert len(env["sender"].outbox) == 1


def test_unexpected_provider_error_is_interrupted_not_retryable(client, env):
    class ExplodingSender(MockSender):
        def send(self, to, subject, body, idempotency_key, **kwargs):
            if to == "boom@cafe.com":
                raise RuntimeError("connection reset")
            return super().send(to, subject, body, idempotency_key, **kwargs)

    ids = [_restaurant("Explode"), _restaurant("Survives", email="boom@cafe.com")]
    detail = _create(client, "Explosions", ids).json()
    _approve_all(client, detail)
    env["use"](ExplodingSender())
    result = _send(client, detail['id']).json()
    assert result["status"] == "completed"
    survivor = _recipient(result, ids[1])
    assert survivor["status"] == "interrupted"
    assert "Send outcome unknown" in survivor["error_reason"]
    assert result["counts"]["retryable"] == 0
    assert client.post(f"/campaigns/{detail['id']}/retry-failed").status_code == 409


def test_restart_marks_unfinished_sends_as_interrupted(test_db, env):
    rid = _restaurant("Crash Test")
    cid = campaign_store.create_campaign("Crash")
    campaign_store.insert_recipient(cid, rid, "owner@cafe.com", "sending")
    campaign_store.set_campaign_status(cid, "sending")

    campaign_service.recover_after_restart()

    detail = campaign_service.campaign_detail(cid)
    assert detail["status"] == "paused"
    assert detail["recipients"][0]["status"] == "interrupted"
    assert detail["counts"]["failed"] == 1


# ── Providers and configuration ───────────────────────────────────────────────

def test_default_provider_is_mock_and_never_smtp(env, monkeypatch):
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)
    from services.email_sender import provider_name, _mock
    assert provider_name() == "mock"
    assert get_sender() is _mock


def test_smtp_without_host_reports_configuration_error(client, env, monkeypatch):
    monkeypatch.setattr(campaign_service, "get_sender", get_sender)
    monkeypatch.setenv("MOCK_EMAIL_MODE", "false")
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    monkeypatch.delenv("SMTP_HOST", raising=False)
    rid = _restaurant("Misconfigured")
    detail = _create(client, "Misconfig", [rid]).json()
    _approve_all(client, detail)
    with pytest.raises(SendError):
        get_sender()
    assert _send(client, detail['id']).status_code == 400


def test_campaign_config_reports_mock_mode(client, env):
    config = client.get("/campaigns/config").json()
    assert config["provider"] == "mock"
    assert config["live_sending"] is False
    assert config["daily_limit"] == 100
    assert config["unsubscribe_ready"] is True


# ── Unsubscribe links ─────────────────────────────────────────────────────────

def test_every_message_carries_its_own_unsubscribe_link(client, env):
    rid = _restaurant("Link Cafe")
    detail = _create(client, "Links", [rid]).json()
    _approve_all(client, detail)
    _send(client, detail['id'])

    recipient_id = _recipient(detail, rid)["id"]
    expected = f"{BASE_URL}/unsubscribe?r={recipient_id}&t={make_token(SECRET, recipient_id)}"
    message = env["sender"].outbox[0]
    assert message["unsubscribe_url"] == expected
    assert expected in message["body"]


def test_unsubscribe_confirm_then_post_suppresses_and_blocks_later_sends(client, env):
    rid = _restaurant("Opt Link Cafe")
    detail = _create(client, "Unsub", [rid]).json()
    _approve_all(client, detail)
    recipient_id = _recipient(detail, rid)["id"]
    token = make_token(SECRET, recipient_id)

    confirm = client.get(f"/unsubscribe?r={recipient_id}&t={token}")
    assert confirm.status_code == 200
    assert "Confirm to stop receiving" in confirm.text

    done = client.post(f"/unsubscribe?r={recipient_id}&t={token}")
    assert done.status_code == 200
    assert "You are unsubscribed" in done.text
    assert "owner@cafe.com" in campaign_store.suppressed_emails()

    result = _send(client, detail['id']).json()
    assert env["sender"].outbox == []
    assert "suppression list" in _recipient(result, rid)["skip_reason"]


def test_unsubscribe_rejects_forged_or_foreign_tokens(client, env):
    rid = _restaurant("Forged Link")
    detail = _create(client, "Forged", [rid]).json()
    recipient_id = _recipient(detail, rid)["id"]

    assert client.post(f"/unsubscribe?r={recipient_id}&t=forged").status_code == 400
    other_token = make_token(SECRET, recipient_id + 999)
    assert client.get(f"/unsubscribe?r={recipient_id}&t={other_token}").status_code == 400
    assert "owner@cafe.com" not in campaign_store.suppressed_emails()


def test_unsubscribe_error_page_does_not_echo_the_query(client, env):
    resp = client.get("/unsubscribe?r=1&t=<script>")
    assert resp.status_code == 400
    assert "<script>" not in resp.text


def test_sending_refuses_without_unsubscribe_settings(client, env, monkeypatch):
    rid = _restaurant("No Settings")
    detail = _create(client, "No settings", [rid]).json()
    _approve_all(client, detail)
    monkeypatch.delenv("UNSUBSCRIBE_SECRET", raising=False)

    resp = _send(client, detail['id'])
    assert resp.status_code == 409
    assert "UNSUBSCRIBE_SECRET" in resp.json()["detail"]
    assert env["sender"].outbox == []
    assert client.get("/campaigns/config").json()["unsubscribe_ready"] is False


def test_smtp_message_carries_list_unsubscribe_headers(monkeypatch):
    captured = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            captured["host"] = host

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            pass

        def login(self, username, password):
            pass

        def send_message(self, message):
            captured["message"] = message

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    sender = SmtpSender("smtp.test", 587, "", "", "outreach@example.org", "Outreach")
    sender.send("owner@cafe.com", "Hello", "Body text", "key-1",
                unsubscribe_url=f"{BASE_URL}/unsubscribe?r=1&t=abc")

    message = captured["message"]
    assert message["To"] == "owner@cafe.com"
    assert message["List-Unsubscribe"] == f"<{BASE_URL}/unsubscribe?r=1&t=abc>"
    assert message["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert message["Cc"] is None
    assert message["Bcc"] is None


# ── Review regressions: retries, duplicates, crashes ──────────────────────────

def test_retry_drafts_recovers_failed_generation(client, env, monkeypatch):
    broken = _restaurant("Broken Oven", email="oven@cafe.com")
    detail = _create(client, "Drafts retry", [broken]).json()
    assert _recipient(detail, broken)["status"] == "draft_failed"

    async def works(restaurant):
        return {"subject": "Fixed subject", "body": "Fixed body", "angle": "general"}

    monkeypatch.setattr(campaign_service, "generate_draft", works)
    retried = client.post(f"/campaigns/{detail['id']}/retry-drafts").json()
    assert retried["status"] == "review"
    assert _recipient(retried, broken)["status"] == "draft"
    assert retried["counts"]["drafts_failed"] == 0


def test_retry_drafts_skips_restaurant_opted_out_since_failure(client, env):
    broken = _restaurant("Broken Grill", email="grill@cafe.com")
    detail = _create(client, "Opt retry", [broken]).json()
    client.post(f"/restaurants/{broken}/opt-out")
    assert client.post(f"/campaigns/{detail['id']}/retry-drafts").status_code == 409
    row = _recipient(client.get(f"/campaigns/{detail['id']}").json(), broken)
    assert row["status"] == "skipped"
    assert "opted out" in row["skip_reason"]


def test_completed_campaign_sends_only_newly_approved_draft(client, env):
    first = _restaurant("First Approved")
    later = _restaurant("Later Approved", email="later@cafe.com")
    detail = _create(client, "Staggered", [first, later]).json()
    client.post(f"/outreach/drafts/{_recipient(detail, first)['draft_id']}/approve")

    sent = _send(client, detail['id']).json()
    assert sent["status"] == "completed"
    assert sent["counts"]["sent"] == 1

    client.post(f"/outreach/drafts/{_recipient(detail, later)['draft_id']}/approve")
    again = _send(client, detail['id']).json()
    assert again["counts"]["sent"] == 2
    assert [m["to"][0] for m in env["sender"].outbox] == ["owner@cafe.com", "later@cafe.com"]


def test_same_address_for_two_restaurants_sends_once(client, env):
    a = _restaurant("Chain Branch One", email="hello@chain.com")
    b = _restaurant("Chain Branch Two", email="hello@chain.com")
    preview = client.post("/campaigns/preview", json={"name": "Chain", "restaurant_ids": [a, b]}).json()
    assert preview["eligible_count"] == 1
    assert any("same address" in r for r in preview["items"][1]["reasons"])

    detail = _create(client, "Chain", [a, b]).json()
    _approve_all(client, detail)
    _send(client, detail['id'])
    assert [m["to"][0] for m in env["sender"].outbox] == ["hello@chain.com"]


def test_address_already_emailed_in_same_named_campaign_is_skipped(client, env):
    first = _restaurant("Repeat Address One", email="shared@cafe.com")
    detail = _create(client, "Quarter", [first]).json()
    _approve_all(client, detail)
    _send(client, detail['id'])

    second = _restaurant("Repeat Address Two", email="shared@cafe.com")
    preview = client.post("/campaigns/preview", json={"name": "Quarter", "restaurant_ids": [second]}).json()
    assert preview["eligible_count"] == 0
    assert any("already received" in r for r in preview["items"][0]["reasons"])


def test_restaurant_emailed_by_one_campaign_is_not_emailed_by_a_differently_named_one(client, env):
    rid = _restaurant("Across Campaigns")
    detail = _create(client, "First round", [rid]).json()
    _approve_all(client, detail)
    _send(client, detail["id"])
    assert len(env["sender"].outbox) == 1

    preview = client.post("/campaigns/preview", json={"name": "Second round", "restaurant_ids": [rid]}).json()
    assert preview["eligible_count"] == 0
    assert any('"First round"' in r for r in preview["items"][0]["reasons"])


def test_address_queued_in_two_campaigns_is_sent_once(client, env):
    first = _restaurant("Early Bird", email="owner@shared.pk")
    second = _restaurant("Late Bird", email="owner@shared.pk")
    early = _create(client, "Early", [first]).json()
    late = _create(client, "Late", [second]).json()  # both campaigns are drafted before either sends
    _approve_all(client, early)
    _approve_all(client, late)

    assert _send(client, early["id"]).status_code == 200
    _send(client, late["id"])

    assert len(env["sender"].outbox) == 1
    skipped = [r for r in client.get(f"/campaigns/{late['id']}").json()["recipients"] if r["status"] == "skipped"]
    assert skipped and "already received campaign" in skipped[0]["skip_reason"]


def test_record_failure_after_delivery_is_never_resent(client, env, monkeypatch):
    rid = _restaurant("Record Fails")
    detail = _create(client, "Record", [rid]).json()
    _approve_all(client, detail)

    def broken_write(*args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(campaign_store, "record_send_success", broken_write)
    result = _send(client, detail['id']).json()
    row = _recipient(result, rid)
    assert row["status"] == "interrupted"
    assert row["provider_message_id"]
    assert "Do not resend" in row["error_reason"]
    assert result["counts"]["retryable"] == 0

    assert client.post(f"/campaigns/{detail['id']}/retry-failed").status_code == 409
    assert len(env["sender"].outbox) == 1


def test_worker_crash_pauses_campaign_and_resume_completes(client, env, monkeypatch):
    ids = [_restaurant("Crash A"), _restaurant("Crash B", email="crash-b@cafe.com")]
    detail = _create(client, "Crash", ids).json()
    _approve_all(client, detail)
    real_process_queue = campaign_service.process_queue

    def exploding(campaign_id):
        raise RuntimeError("disk I/O error")

    monkeypatch.setattr(campaign_service, "process_queue", exploding)
    paused = _send(client, detail['id']).json()
    assert paused["status"] == "paused"
    assert "stopped unexpectedly" in paused["status_note"]

    monkeypatch.setattr(campaign_service, "process_queue", real_process_queue)
    finished = client.post(f"/campaigns/{detail['id']}/resume").json()
    assert finished["status"] == "completed"
    assert finished["counts"]["sent"] == 2
    assert len(env["sender"].outbox) == 2


def test_smtp_refusal_is_retryable_but_lost_connection_is_not(monkeypatch):
    class RefusingSMTP:
        def __init__(self, host, port, timeout):
            pass

        def starttls(self):
            pass

        def send_message(self, message):
            raise smtplib.SMTPRecipientsRefused({"x@y.com": (550, b"no such user")})

    monkeypatch.setattr(smtplib, "SMTP", RefusingSMTP)
    sender = SmtpSender("smtp.test", 587, "", "", "outreach@example.org", "Outreach")
    with pytest.raises(SendError):
        sender.send("x@y.com", "Hi", "Body", "k")

    class DroppedSMTP(RefusingSMTP):
        def send_message(self, message):
            raise smtplib.SMTPServerDisconnected("connection unexpectedly closed")

    monkeypatch.setattr(smtplib, "SMTP", DroppedSMTP)
    with pytest.raises(SendOutcomeUnknown):
        sender.send("x@y.com", "Hi", "Body", "k")

    class UnreachableSMTP:
        def __init__(self, host, port, timeout):
            raise ConnectionRefusedError("refused")

    monkeypatch.setattr(smtplib, "SMTP", UnreachableSMTP)
    with pytest.raises(SendError):
        sender.send("x@y.com", "Hi", "Body", "k")


# ── Phase 8: explicit approval, sending logs, Nodemailer service ─────────────

def test_direct_send_without_campaign_approval_is_refused(client, env):
    rid = _restaurant("Needs Approval")
    detail = _create(client, "Approval gate", [rid]).json()
    client.post(f"/outreach/drafts/{_recipient(detail, rid)['draft_id']}/approve")
    resp = client.post(f"/campaigns/{detail['id']}/send")
    assert resp.status_code == 409
    assert "Approve sending" in resp.json()["detail"]
    assert env["sender"].outbox == []


def test_approval_is_bound_to_the_approved_draft_text(client, env, monkeypatch):
    rid = _restaurant("Bound Approval")
    detail = _create(client, "Bound", [rid]).json()
    first_draft = _recipient(detail, rid)["draft_id"]
    client.post(f"/outreach/drafts/{first_draft}/approve")
    assert client.post(f"/campaigns/{detail['id']}/approve-sending", json={"draft_ids": [first_draft]}).status_code == 200

    async def regenerated(restaurant, instructions=None):
        return {"subject": "Brand new", "body": "Brand new body", "angle": "general"}

    monkeypatch.setattr(main, "generate_draft", regenerated)
    second_draft = client.post(f"/outreach/drafts/{first_draft}/regenerate").json()["id"]
    client.post(f"/outreach/drafts/{second_draft}/approve")
    resp = client.post(f"/campaigns/{detail['id']}/send")
    assert resp.status_code == 409
    assert env["sender"].outbox == []

    assert client.post(f"/campaigns/{detail['id']}/approve-sending",
                       json={"draft_ids": [second_draft]}).status_code == 200
    assert _send(client, detail["id"]).json()["counts"]["sent"] == 1


def test_approve_sending_rejects_drafts_that_are_not_approved(client, env):
    rid = _restaurant("Unapproved Draft")
    detail = _create(client, "Reject approval", [rid]).json()
    draft_id = _recipient(detail, rid)["draft_id"]
    resp = client.post(f"/campaigns/{detail['id']}/approve-sending", json={"draft_ids": [draft_id]})
    assert resp.status_code == 409
    assert client.post(f"/campaigns/{detail['id']}/approve-sending", json={"draft_ids": []}).status_code == 422


def test_send_log_records_each_outcome(client, env):
    ok = _restaurant("Log Ok")
    bad = _restaurant("Log Bad", email="log-bad@cafe.pk")
    detail = _create(client, "Logged", [ok, bad]).json()
    _approve_all(client, detail)
    env["use"](MockSender(fail_addresses=("log-bad@cafe.pk",)))
    _send(client, detail["id"])

    events = [entry["event"] for entry in client.get(f"/campaigns/{detail['id']}/logs").json()]
    assert "approved" in events
    assert "send_started" in events
    assert "sent" in events
    assert "failed" in events
    assert events[-1] == "completed"
    assert client.get("/campaigns/999999/logs").status_code == 404


def test_nodemailer_sends_through_the_service_and_never_resends_unknown_outcomes(client, env, monkeypatch):
    monkeypatch.setenv("SENDER_ADDRESS", "Outreach Team, 12 Main Road, Lahore")  # required for live sending
    ledger = {}
    calls = []

    def service(request):
        if request.method == "GET":
            return httpx.Response(200, json={"status": "ok", "mode": "mock"})
        body = json.loads(request.content)
        key = body["idempotency_key"]
        calls.append(key)
        assert request.headers["x-service-secret"] == "service-secret-0123456789"
        assert set(body) <= {"idempotency_key", "to", "subject", "text", "unsubscribe_url"}
        if key in ledger:
            return httpx.Response(409, json={"error": "unknown outcome", "outcome": "unknown"})
        ledger[key] = "unknown"
        return httpx.Response(502, json={"error": "Delivery outcome is unknown.", "outcome": "unknown"})

    monkeypatch.setattr(
        campaign_service, "get_sender",
        lambda: NodemailerSender("http://email.test", "service-secret-0123456789", transport=httpx.MockTransport(service)),
    )
    rid = _restaurant("Nodemailer Cafe", email="nm@cafe.pk")
    detail = _create(client, "Nodemailer", [rid]).json()
    _approve_all(client, detail)
    result = _send(client, detail["id"]).json()
    row = _recipient(result, rid)
    assert row["status"] == "interrupted"
    assert "unknown" in row["error_reason"].lower()

    _send(client, detail["id"])
    assert calls == [f"campaign-{detail['id']}-recipient-{row['id']}"]


def test_nodemailer_success_marks_rows_sent_with_provider_ids(client, env, monkeypatch):
    monkeypatch.setenv("SENDER_ADDRESS", "Outreach Team, 12 Main Road, Lahore")  # required for live sending
    def service(request):
        if request.method == "GET":
            return httpx.Response(200, json={"status": "ok", "mode": "mock"})
        body = json.loads(request.content)
        return httpx.Response(200, json={"message_id": f"<{body['idempotency_key']}@test>", "duplicate": False})

    monkeypatch.setattr(
        campaign_service, "get_sender",
        lambda: NodemailerSender("http://email.test", "service-secret-0123456789", transport=httpx.MockTransport(service)),
    )
    rid = _restaurant("Nodemailer OK", email="ok@cafe.pk")
    detail = _create(client, "Nodemailer ok", [rid]).json()
    _approve_all(client, detail)
    result = _send(client, detail["id"]).json()
    row = _recipient(result, rid)
    assert row["status"] == "sent"
    assert row["provider_message_id"] == f"<campaign-{detail['id']}-recipient-{row['id']}@test>"


def test_nodemailer_refusal_is_retryable(client, env, monkeypatch):
    monkeypatch.setenv("SENDER_ADDRESS", "Outreach Team, 12 Main Road, Lahore")  # required for live sending
    refuse = {"on": True}

    def service(request):
        if request.method == "GET":
            return httpx.Response(200, json={"status": "ok", "mode": "mock"})
        if refuse["on"]:
            return httpx.Response(422, json={"error": "SMTP server refused the message", "outcome": "not_sent"})
        body = json.loads(request.content)
        return httpx.Response(200, json={"message_id": "<retry@test>", "duplicate": False})

    monkeypatch.setattr(
        campaign_service, "get_sender",
        lambda: NodemailerSender("http://email.test", "service-secret-0123456789", transport=httpx.MockTransport(service)),
    )
    rid = _restaurant("Refused Then Sent", email="refused@cafe.pk")
    detail = _create(client, "Refused", [rid]).json()
    _approve_all(client, detail)
    failed = _send(client, detail["id"]).json()
    assert _recipient(failed, rid)["status"] == "failed"
    assert failed["counts"]["retryable"] == 1

    refuse["on"] = False
    retried = client.post(f"/campaigns/{detail['id']}/retry-failed").json()
    assert _recipient(retried, rid)["status"] == "sent"


def test_nodemailer_unreachable_service_blocks_sending_before_queueing(client, env, monkeypatch):
    monkeypatch.setenv("SENDER_ADDRESS", "Outreach Team, 12 Main Road, Lahore")  # required for live sending
    def down(request):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(
        campaign_service, "get_sender",
        lambda: NodemailerSender("http://email.test", "service-secret-0123456789", transport=httpx.MockTransport(down)),
    )
    rid = _restaurant("Service Down", email="down@cafe.pk")
    detail = _create(client, "Down", [rid]).json()
    _approve_all(client, detail)
    resp = client.post(f"/campaigns/{detail['id']}/approve-sending", json={"draft_ids": [_recipient(detail, rid)["draft_id"]]})
    assert resp.status_code == 200
    resp = client.post(f"/campaigns/{detail['id']}/send")
    assert resp.status_code == 400
    assert "not reachable" in resp.json()["detail"]
    assert client.get(f"/campaigns/{detail['id']}").json()["status"] == "review"


def test_get_sender_needs_service_url_and_long_secret(monkeypatch):
    from services.email_sender import get_sender as real_get_sender
    monkeypatch.setenv("EMAIL_PROVIDER", "nodemailer")
    monkeypatch.setenv("MOCK_EMAIL_MODE", "false")
    monkeypatch.delenv("EMAIL_SERVICE_URL", raising=False)
    with pytest.raises(SendError):
        real_get_sender()
    monkeypatch.setenv("EMAIL_SERVICE_URL", "http://127.0.0.1:3001")
    monkeypatch.setenv("EMAIL_SERVICE_SECRET", "short")
    with pytest.raises(SendError):
        real_get_sender()
    monkeypatch.setenv("EMAIL_SERVICE_SECRET", "service-secret-0123456789")
    assert isinstance(real_get_sender(), NodemailerSender)
