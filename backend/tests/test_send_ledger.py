"""Persistent send ledger: reservations, duplicate protection, restarts, concurrency and uncertain outcomes.

Mock delivery only. No real email is sent and no provider is contacted.
"""
import threading

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from models import campaign_store as store
from models import database
from models.database import get_engine, save_restaurants
from services import campaigns as campaign_service
from services.email_sender import MockSender
from tests.test_campaigns import _approve_all, _create, _recipient, _restaurant, _send, client, env  # noqa: F401


def _simulate_restart() -> None:
    """Forget everything held in process memory: engines, worker registry and any in-memory state."""
    database._engines.clear()
    campaign_service._active_workers.clear()


def _queued_recipient(campaign_id: int, email: str = "ledger@cafe.pk") -> dict:
    restaurant_id = save_restaurants([{
        "place_id": f"ledger-{email}", "name": f"Ledger {email}", "source": "google_places",
    }])[0]["id"]
    store.insert_recipient(campaign_id, restaurant_id, email, "queued")
    return next(r for r in store.list_recipients(campaign_id) if r["restaurant_id"] == restaurant_id)


def test_a_recipient_is_reserved_once_and_then_refused_after_success(test_db):
    campaign_id = store.create_campaign("Reserve once")
    row = _queued_recipient(campaign_id)
    assert store.reserve_send(campaign_id, row) == (True, "reserved")
    assert store.reserve_send(campaign_id, row) == (False, "reserved")
    store.record_send_success(campaign_id, row["id"], "<m1@test>")
    assert store.reserve_send(campaign_id, row) == (False, "sent")
    ledger = store.ledger_for(campaign_id, row["id"])
    assert ledger["status"] == "sent"
    assert ledger["provider_message_id"] == "<m1@test>"
    assert ledger["idempotency_key"] == f"campaign-{campaign_id}-recipient-{row['id']}"


def test_database_refuses_a_second_ledger_row_for_the_same_recipient(test_db):
    campaign_id = store.create_campaign("Constraint")
    row = _queued_recipient(campaign_id)
    store.reserve_send(campaign_id, row)
    with pytest.raises(IntegrityError):
        with get_engine().begin() as conn:
            conn.execute(text(
                "INSERT INTO email_send_ledger (campaign_id, recipient_id, status, idempotency_key) "
                "VALUES (:cid, :rid, 'reserved', 'another-key')"
            ), {"cid": campaign_id, "rid": row["id"]})


def test_concurrent_reservations_grant_exactly_one(test_db):
    campaign_id = store.create_campaign("Concurrent")
    row = _queued_recipient(campaign_id)
    results = []
    barrier = threading.Barrier(8)

    def attempt():
        barrier.wait()
        try:
            results.append(store.reserve_send(campaign_id, row))
        except Exception as exc:  # any error is a failure of the test
            results.append(("error", str(exc)))

    threads = [threading.Thread(target=attempt) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not [r for r in results if r[0] == "error"], results
    assert len([r for r in results if r == (True, "reserved")]) == 1
    assert len(results) == 8


def test_sent_history_survives_a_restart(test_db):
    campaign_id = store.create_campaign("Restart history")
    row = _queued_recipient(campaign_id)
    store.reserve_send(campaign_id, row)
    store.record_send_success(campaign_id, row["id"], "<before-restart@test>")

    _simulate_restart()
    campaign_service.recover_after_restart()

    assert store.reserve_send(campaign_id, row) == (False, "sent")
    assert store.ledger_for(campaign_id, row["id"])["provider_message_id"] == "<before-restart@test>"


def test_failed_send_may_be_reserved_again_and_counts_attempts(test_db):
    campaign_id = store.create_campaign("Failed then retried")
    row = _queued_recipient(campaign_id)
    store.reserve_send(campaign_id, row)
    store.record_send_failure(campaign_id, row["id"], "Provider refused the address")
    assert store.reserve_send(campaign_id, row) == (True, "reserved")
    assert store.ledger_for(campaign_id, row["id"])["attempts"] == 2
    assert store.reserve_send(campaign_id, row) == (False, "reserved")


def test_uncertain_outcome_is_never_resent_even_after_a_restart(test_db):
    campaign_id = store.create_campaign("Uncertain")
    row = _queued_recipient(campaign_id)
    store.reserve_send(campaign_id, row)
    store.record_send_uncertain(campaign_id, row["id"], "Connection lost after the request was sent")
    assert store.reserve_send(campaign_id, row) == (False, "uncertain")

    _simulate_restart()
    campaign_service.recover_after_restart()

    assert store.reserve_send(campaign_id, row) == (False, "uncertain")
    recipient = store.get_recipient(row["id"])
    assert recipient["status"] == "interrupted"
    assert "Connection lost" in recipient["error_reason"]


def test_a_crash_before_the_outcome_is_recorded_becomes_uncertain_on_restart(test_db):
    campaign_id = store.create_campaign("Crash mid-send")
    row = _queued_recipient(campaign_id)
    store.update_recipient(row["id"], status="sending")
    assert store.reserve_send(campaign_id, row) == (True, "reserved")

    # The process dies here: the provider may already have accepted the message.
    _simulate_restart()
    campaign_service.recover_after_restart()

    assert store.ledger_for(campaign_id, row["id"])["status"] == "uncertain"
    assert store.get_recipient(row["id"])["status"] == "interrupted"
    assert store.reserve_send(campaign_id, row) == (False, "uncertain")


def test_a_failed_database_write_after_delivery_leaves_the_recipient_blocked(test_db):
    campaign_id = store.create_campaign("Write fails")
    row = _queued_recipient(campaign_id)
    store.reserve_send(campaign_id, row)
    with pytest.raises(LookupError):
        store.record_send_success(campaign_id, 999999, "<unrelated@test>")  # no reservation exists for this id
    store.record_send_uncertain(campaign_id, row["id"], "Delivered but not recorded. Do not resend.", "<m@test>")
    assert store.reserve_send(campaign_id, row) == (False, "uncertain")


class TimeoutSender(MockSender):
    def send(self, to, subject, body, idempotency_key, **kwargs):
        raise RuntimeError("timed out waiting for the provider")


def test_provider_timeout_is_recorded_as_uncertain_and_never_retried(client, env):
    restaurant = _restaurant("Timeout Cafe", email="timeout@cafe.pk")
    detail = _create(client, "Timeout", [restaurant]).json()
    _approve_all(client, detail)
    sender = env["use"](TimeoutSender())
    result = _send(client, detail["id"]).json()
    recipient_id = _recipient(result, restaurant)["id"]

    assert _recipient(result, restaurant)["status"] == "interrupted"
    assert store.ledger_for(detail["id"], recipient_id)["status"] == "uncertain"
    assert client.post(f"/campaigns/{detail['id']}/retry-failed").status_code == 409
    assert store.reserve_send(detail["id"], _recipient(result, restaurant)) == (False, "uncertain")
    assert sender.outbox == []


def test_repeated_send_requests_deliver_each_recipient_once(client, env):
    restaurant = _restaurant("Repeat Requests Cafe", email="repeat@cafe.pk")
    detail = _create(client, "Repeat requests", [restaurant]).json()
    _approve_all(client, detail)
    _send(client, detail["id"])
    client.post(f"/campaigns/{detail['id']}/send")
    client.post(f"/campaigns/{detail['id']}/resume")
    assert [m["to"][0] for m in env["sender"].outbox] == ["repeat@cafe.pk"]


def test_refused_message_is_retried_exactly_once_and_then_never_again(client, env):
    restaurant = _restaurant("Refused Once Cafe", email="refused-once@cafe.pk")
    detail = _create(client, "Refused once", [restaurant]).json()
    _approve_all(client, detail)
    env["sender"].fail_addresses = {"refused-once@cafe.pk"}
    _send(client, detail["id"])
    env["sender"].fail_addresses = set()

    retried = client.post(f"/campaigns/{detail['id']}/retry-failed").json()
    recipient_id = _recipient(retried, restaurant)["id"]
    assert retried["counts"]["sent"] == 1
    assert store.ledger_for(detail["id"], recipient_id)["attempts"] == 2
    assert client.post(f"/campaigns/{detail['id']}/retry-failed").status_code == 409
    assert [m["to"][0] for m in env["sender"].outbox] == ["refused-once@cafe.pk"]


def test_sent_history_blocks_resending_after_a_restart(client, env):
    restaurant = _restaurant("Restart Resend Cafe", email="restart-resend@cafe.pk")
    detail = _create(client, "Restart resend", [restaurant]).json()
    _approve_all(client, detail)
    _send(client, detail["id"])

    _simulate_restart()
    campaign_service.recover_after_restart()
    client.post(f"/campaigns/{detail['id']}/send")
    assert [m["to"][0] for m in env["sender"].outbox] == ["restart-resend@cafe.pk"]
