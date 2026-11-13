"""Migration 0004: existing campaign history is backfilled into the send ledger, and the change is reversible."""
from pathlib import Path

from alembic import command
from alembic.config import Config

from models import campaign_store as store
from models.database import execute_returning_id, fetch_one, save_restaurants

BACKEND = Path(__file__).resolve().parent.parent


def _alembic_config() -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    return config


# The helpers below write the legacy rows with plain SQL. They run while the schema is at 0003, before the
# workspace columns and the store functions that use them exist.

def _legacy_campaign(name: str) -> int:
    return execute_returning_id("INSERT INTO campaigns (name, status) VALUES (:name, 'review') RETURNING id",
                                {"name": name})


def _legacy_recipient(campaign_id: int, email: str, status: str, provider_message_id: str | None = None,
                      error_reason: str | None = None) -> int:
    restaurant_id = execute_returning_id(
        "INSERT INTO restaurants (place_id, name, source) VALUES (:place, :name, 'google_places') RETURNING id",
        {"place": f"legacy-{email}", "name": f"Legacy {email}"},
    )
    return execute_returning_id(
        "INSERT INTO campaign_recipients (campaign_id, restaurant_id, recipient_email, status, provider_message_id, "
        "error_reason) VALUES (:campaign, :restaurant, :email, :status, :mid, :error) RETURNING id",
        {"campaign": campaign_id, "restaurant": restaurant_id, "email": email, "status": status,
         "mid": provider_message_id, "error": error_reason},
    )


def test_existing_campaign_history_is_backfilled_into_the_ledger(test_db):
    command.downgrade(_alembic_config(), "0003_list_indexes")  # back to the schema before the ledger

    campaign_id = _legacy_campaign("Legacy history")
    sent = _legacy_recipient(campaign_id, "legacy-sent@cafe.pk", "sent", provider_message_id="<legacy-sent@test>")
    refused = _legacy_recipient(campaign_id, "legacy-refused@cafe.pk", "failed", error_reason="Refused")
    unknown = _legacy_recipient(campaign_id, "legacy-unknown@cafe.pk", "interrupted",
                                provider_message_id="<legacy-unknown@test>")
    queued = _legacy_recipient(campaign_id, "legacy-queued@cafe.pk", "queued")

    command.upgrade(_alembic_config(), "head")

    assert store.ledger_for(campaign_id, sent)["status"] == "sent"
    assert store.ledger_for(campaign_id, sent)["provider_message_id"] == "<legacy-sent@test>"
    assert store.ledger_for(campaign_id, refused)["status"] == "failed"  # retry allowed, as before
    assert store.ledger_for(campaign_id, unknown)["status"] == "uncertain"  # never resent automatically
    assert store.ledger_for(campaign_id, queued) is None  # never reached the provider


def test_backfilled_history_still_blocks_resending(test_db):
    command.downgrade(_alembic_config(), "0003_list_indexes")
    campaign_id = _legacy_campaign("Legacy blocks")
    sent = _legacy_recipient(campaign_id, "already-sent@cafe.pk", "sent", provider_message_id="<old@test>")
    command.upgrade(_alembic_config(), "head")

    recipient = store.get_recipient(sent)
    assert store.reserve_send(campaign_id, recipient) == (False, "sent")


def test_migration_downgrade_and_upgrade_round_trip(test_db):
    command.downgrade(_alembic_config(), "0003_list_indexes")
    command.upgrade(_alembic_config(), "head")
    campaign_id = store.create_campaign("Round trip")
    save_restaurants([{"place_id": "round-trip-place", "name": "Round Trip", "source": "google_places"}])
    restaurant_id = fetch_one("SELECT id FROM restaurants WHERE place_id = 'round-trip-place'")["id"]
    store.insert_recipient(campaign_id, restaurant_id, "round-trip@cafe.pk", "queued")
    recipient = next(r for r in store.list_recipients(campaign_id) if r["restaurant_id"] == restaurant_id)["id"]
    assert store.reserve_send(campaign_id, store.get_recipient(recipient)) == (True, "reserved")
