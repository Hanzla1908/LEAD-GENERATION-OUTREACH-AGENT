"""Delivery events from signed webhooks: signatures, idempotency, bounces, suppression, failures.

Mocked events only. No provider, mailbox or real address is contacted.
"""
import json
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import main
from models import campaign_store as store
from models import database
from models.database import execute, fetch_all, fetch_one, get_engine, save_restaurants
from services import email_events
from services.email_events import DeliveryEvent, next_delivery_status, parse_webhook, sign, verify_signature
from services.email_events import WebhookError

SECRET = "webhook-secret-0123456789abcdef0123"


@pytest.fixture
def webhook(test_db, monkeypatch):
    monkeypatch.setenv("EMAIL_WEBHOOK_SECRET", SECRET)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD_HASH", raising=False)
    return TestClient(main.app)


def _sent_recipient(email: str, message_id: str) -> tuple[int, int]:
    """A campaign with one emailed recipient, whose ledger row carries the provider message id."""
    campaign_id = store.create_campaign(f"Events {email}")
    restaurant_id = save_restaurants([{"place_id": f"ev-{email}", "name": f"Ev {email}", "source": "google_places"}])[0]["id"]
    store.insert_recipient(campaign_id, restaurant_id, email, "queued")
    row = next(r for r in store.list_recipients(campaign_id) if r["restaurant_id"] == restaurant_id)
    store.reserve_send(campaign_id, row)
    store.record_send_success(campaign_id, row["id"], message_id)
    return campaign_id, row["id"]


def _post(client, payload, *, secret=SECRET, timestamp=None, body=None, signature=None):
    raw = body if body is not None else json.dumps(payload).encode()
    ts = str(int(time.time())) if timestamp is None else timestamp
    sig = signature if signature is not None else sign(secret, ts, raw)
    return client.post("/webhooks/email-events", content=raw,
                       headers={"Content-Type": "application/json", "X-Event-Timestamp": ts, "X-Event-Signature": sig})


def _event(event_id, event_type, message_id="<m1@test>", recipient="owner@cafe.pk", reason=None):
    return {"provider": "generic", "events": [{
        "event_id": event_id, "type": event_type, "message_id": message_id, "recipient": recipient,
        "occurred_at": "2026-11-04T10:00:00Z", "reason": reason,
    }]}


# ── Signatures ───────────────────────────────────────────────────────────────

def test_unsigned_and_forged_requests_are_refused(webhook, test_db):
    _sent_recipient("owner@cafe.pk", "<m1@test>")
    assert _post(webhook, _event("e1", "delivered"), signature="").status_code == 401
    assert _post(webhook, _event("e1", "delivered"), signature="sha256=" + "0" * 64).status_code == 401
    assert _post(webhook, _event("e1", "delivered"), secret="some-other-secret-value-0123456789").status_code == 401
    assert fetch_all("SELECT * FROM email_events") == []


def test_stale_and_future_timestamps_are_refused(webhook, test_db):
    _sent_recipient("owner@cafe.pk", "<m1@test>")
    old = str(int(time.time()) - 3600)
    assert _post(webhook, _event("e2", "delivered"), timestamp=old).status_code == 401
    future = str(int(time.time()) + 3600)
    assert _post(webhook, _event("e2", "delivered"), timestamp=future).status_code == 401


def test_webhook_refuses_everything_when_no_secret_is_configured(test_db, monkeypatch):
    monkeypatch.delenv("EMAIL_WEBHOOK_SECRET", raising=False)
    client = TestClient(main.app)
    response = client.post("/webhooks/email-events", content=b"{}", headers={"X-Event-Timestamp": "1", "X-Event-Signature": "x"})
    assert response.status_code == 503


def test_a_signed_request_is_accepted_without_a_session_or_csrf_header(test_db, monkeypatch):
    monkeypatch.setenv("EMAIL_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("ADMIN_PASSWORD", "correct-horse-battery-staple")
    monkeypatch.setenv("SESSION_SECRET", "session-secret-0123456789abcdefghij")
    _sent_recipient("owner@cafe.pk", "<m1@test>")
    client = TestClient(main.app)
    response = _post(client, _event("e-auth", "delivered"))  # no cookie, no X-Requested-With
    assert response.status_code == 200
    assert response.json()["accepted"] == 1


def test_signature_check_uses_the_exact_body(test_db, monkeypatch):
    monkeypatch.setenv("EMAIL_WEBHOOK_SECRET", SECRET)
    now = time.time()
    body = b'{"events": []}'
    ts = str(int(now))
    verify_signature(ts, sign(SECRET, ts, body), body, now=now)
    with pytest.raises(WebhookError):
        verify_signature(ts, sign(SECRET, ts, body), b'{"events": [1]}', now=now)


# ── Recording and applying events ────────────────────────────────────────────

def test_delivered_event_updates_the_recipient(webhook, test_db):
    campaign_id, recipient_id = _sent_recipient("owner@cafe.pk", "<m1@test>")
    response = _post(webhook, _event("e-delivered", "delivered"))
    assert response.json() == {"accepted": 1, "duplicate": 0, "unmatched": 0, "ignored": 0}
    row = store.get_recipient(recipient_id)
    assert row["delivery_status"] == "delivered"
    assert row["delivery_updated_at"]


def test_the_same_event_is_never_processed_twice(webhook, test_db):
    _sent_recipient("owner@cafe.pk", "<m1@test>")
    first = _post(webhook, _event("e-dup", "delivered"))
    second = _post(webhook, _event("e-dup", "delivered"))
    assert first.json()["accepted"] == 1
    assert second.json()["duplicate"] == 1
    assert fetch_one("SELECT COUNT(*) AS n FROM email_events WHERE event_key = 'generic:e-dup'")["n"] == 1


def test_hard_bounce_is_suppressed_and_blocks_any_resend(webhook, test_db):
    campaign_id, recipient_id = _sent_recipient("hard@cafe.pk", "<hard@test>")
    _post(webhook, _event("e-hard", "bounced_hard", message_id="<hard@test>", recipient="hard@cafe.pk",
                          reason="550 no such user"))
    row = store.get_recipient(recipient_id)
    assert row["delivery_status"] == "bounced_hard"
    assert fetch_one("SELECT status FROM email_send_ledger WHERE recipient_id = :rid", {"rid": recipient_id})["status"] == "bounced"
    assert fetch_one("SELECT reason FROM suppression_list WHERE email = 'hard@cafe.pk'")["reason"] == "hard_bounce"
    assert store.reserve_send(campaign_id, row) == (False, "bounced")


def test_soft_bounce_and_deferral_never_suppress_the_address(webhook, test_db):
    campaign_id, recipient_id = _sent_recipient("soft@cafe.pk", "<soft@test>")
    _post(webhook, _event("e-soft", "bounced_soft", message_id="<soft@test>", recipient="soft@cafe.pk"))
    assert store.get_recipient(recipient_id)["delivery_status"] == "bounced_soft"
    assert fetch_one("SELECT COUNT(*) AS n FROM suppression_list WHERE email = 'soft@cafe.pk'")["n"] == 0
    assert fetch_one("SELECT status FROM email_send_ledger WHERE recipient_id = :rid", {"rid": recipient_id})["status"] == "sent"


def test_deferral_is_temporary_and_does_not_override_a_confirmed_delivery(webhook, test_db):
    _campaign_id, recipient_id = _sent_recipient("defer@cafe.pk", "<defer@test>")
    _post(webhook, _event("e-defer", "deferred", message_id="<defer@test>", recipient="defer@cafe.pk"))
    assert store.get_recipient(recipient_id)["delivery_status"] == "deferred"
    _post(webhook, _event("e-deliv", "delivered", message_id="<defer@test>", recipient="defer@cafe.pk"))
    assert store.get_recipient(recipient_id)["delivery_status"] == "delivered"
    _post(webhook, _event("e-defer2", "deferred", message_id="<defer@test>", recipient="defer@cafe.pk"))
    assert store.get_recipient(recipient_id)["delivery_status"] == "delivered"


def test_provider_rejection_is_recorded_on_the_recipient_and_ledger(webhook, test_db):
    _campaign_id, recipient_id = _sent_recipient("reject@cafe.pk", "<reject@test>")
    _post(webhook, _event("e-reject", "rejected", message_id="<reject@test>", recipient="reject@cafe.pk",
                          reason="policy block"))
    assert store.get_recipient(recipient_id)["delivery_status"] == "rejected"
    assert "policy block" in fetch_one("SELECT failure_detail FROM email_send_ledger WHERE recipient_id = :rid",
                                       {"rid": recipient_id})["failure_detail"]


def test_hard_bounce_is_final_even_when_a_later_event_says_delivered():
    assert next_delivery_status("bounced_hard", "delivered") == "bounced_hard"
    assert next_delivery_status("bounced_soft", "delivered") == "delivered"


def test_unmatched_events_are_stored_without_touching_any_recipient(webhook, test_db):
    response = _post(webhook, _event("e-orphan", "bounced_hard", message_id="<nobody@test>", recipient="x@y.pk"))
    assert response.json()["unmatched"] == 1
    row = fetch_one("SELECT recipient_id, campaign_id, event_type FROM email_events WHERE event_key = 'generic:e-orphan'")
    assert row["recipient_id"] is None and row["campaign_id"] is None
    assert fetch_one("SELECT COUNT(*) AS n FROM suppression_list WHERE email = 'x@y.pk'")["n"] == 0


def test_unknown_event_types_are_ignored_and_reported(webhook, test_db):
    response = _post(webhook, _event("e-odd", "opened"))
    assert response.json()["ignored"] == 1
    assert fetch_one("SELECT COUNT(*) AS n FROM email_events")["n"] == 0


def test_malformed_payloads_are_refused(webhook, test_db):
    assert _post(webhook, None, body=b"not json").status_code == 422
    assert _post(webhook, {"provider": "unknown-provider", "events": []}).status_code == 422
    assert _post(webhook, {"events": "nope"}).status_code == 422
    assert _post(webhook, {"events": [{"event_id": "x", "type": "delivered"}] * 201}).status_code == 422


def test_a_failure_while_applying_an_event_changes_nothing_and_can_be_retried(webhook, test_db, monkeypatch):
    _campaign_id, recipient_id = _sent_recipient("retry@cafe.pk", "<retry@test>")
    original = email_events._apply_to_recipient

    def broken(*args, **kwargs):
        raise RuntimeError("database went away")

    monkeypatch.setattr(email_events, "_apply_to_recipient", broken)
    with pytest.raises(RuntimeError):
        email_events.record_event(DeliveryEvent("generic:e-fail", "webhook", "delivered", "<retry@test>",
                                                "retry@cafe.pk", None, None))
    assert fetch_one("SELECT COUNT(*) AS n FROM email_events WHERE event_key = 'generic:e-fail'")["n"] == 0
    assert store.get_recipient(recipient_id)["delivery_status"] is None  # the recipient is still unconfirmed

    monkeypatch.setattr(email_events, "_apply_to_recipient", original)
    assert _post(webhook, _event("e-fail", "delivered", message_id="<retry@test>", recipient="retry@cafe.pk")).json()["accepted"] == 1
    assert store.get_recipient(recipient_id)["delivery_status"] == "delivered"


def test_webhook_events_appear_in_the_restaurant_history(webhook, test_db):
    _campaign_id, recipient_id = _sent_recipient("history@cafe.pk", "<history@test>")
    restaurant_id = store.get_recipient(recipient_id)["restaurant_id"]
    _post(webhook, _event("e-hist", "delivered", message_id="<history@test>", recipient="history@cafe.pk"))
    from tests.account_helpers import signed_in_client
    history = signed_in_client(main.app).get(f"/restaurants/{restaurant_id}/conversations").json()
    assert [event["event_type"] for event in history["events"]] == ["delivered"]
    assert history["events"][0]["source"] == "webhook"


def test_campaign_detail_separates_confirmed_events_from_unconfirmed_sends(webhook, test_db):
    campaign_id, _ = _sent_recipient("stats-a@cafe.pk", "<stats-a@test>")
    _sent_recipient("stats-b@cafe.pk", "<stats-b@test>")  # the second campaign is separate
    _post(webhook, _event("e-stats", "delivered", message_id="<stats-a@test>", recipient="stats-a@cafe.pk"))
    counts = store.delivery_counts(campaign_id)
    assert counts == {"sent": 1, "unconfirmed": 0, "delivered": 1, "deferred": 0, "bounced_soft": 0,
                      "bounced_hard": 0, "rejected": 0, "replied": 0}
    other = store.create_campaign("Nothing sent")
    assert store.delivery_counts(other)["unconfirmed"] == 0
