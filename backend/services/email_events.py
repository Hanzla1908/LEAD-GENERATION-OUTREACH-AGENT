"""Delivery events: signed webhooks and bounce messages, recorded once and applied to the ledger.

Sources:
- Webhook (POST /webhooks/email-events): for a provider that offers delivery-event webhooks. The request
  must carry X-Event-Timestamp and X-Event-Signature (sha256 HMAC of "<timestamp>.<raw body>" with
  EMAIL_WEBHOOK_SECRET). Stale or unsigned requests are refused before anything is read.
- Mailbox (see services/mailbox_monitor.py): bounce messages that arrive at the sending mailbox. Plain
  SMTP sending has no event webhook, so this is the path that works with the current SMTP setup.

Provider adapters: each provider's payload is converted to the normalised events below by a parser in
ADAPTERS. Only the "generic" format is implemented here, because no provider is configured yet. Adding a
provider means adding one parser; nothing else changes.

Idempotency: every event has an event_key (provider event id, or a mailbox message key). The key is
unique, and the check and the effects run in one transaction, so a repeated delivery changes nothing.
"""

import hashlib
import hmac
import os
import time
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from models.database import get_engine, stamp, utc_now

EVENT_TYPES = ("delivered", "deferred", "bounced_soft", "bounced_hard", "rejected")
WEBHOOK_TOLERANCE_SECONDS = 300
MIN_SECRET_LENGTH = 32
MAX_EVENTS_PER_REQUEST = 200

# Provider wording -> normalised event type. Anything else is ignored and reported.
_TYPE_ALIASES = {
    "delivered": "delivered", "delivery": "delivered",
    "deferred": "deferred", "delayed": "deferred",
    "bounced_soft": "bounced_soft", "soft_bounce": "bounced_soft", "soft-bounce": "bounced_soft",
    "bounced_hard": "bounced_hard", "hard_bounce": "bounced_hard", "hard-bounce": "bounced_hard",
    "rejected": "rejected", "dropped": "rejected",
}


class WebhookError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass(frozen=True)
class DeliveryEvent:
    event_key: str
    source: str
    event_type: str
    provider_message_id: str | None
    recipient_email: str | None
    reason: str | None
    occurred_at: datetime | None


# ── Webhook signatures ───────────────────────────────────────────────────────

def webhook_secret() -> str:
    return os.getenv("EMAIL_WEBHOOK_SECRET", "").strip()


def sign(secret: str, timestamp: str, body: bytes) -> str:
    """The signature a provider (or a test) must send for this body and timestamp."""
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(timestamp: str | None, signature: str | None, body: bytes, now: float | None = None) -> None:
    secret = webhook_secret()
    if len(secret) < MIN_SECRET_LENGTH:
        raise WebhookError(503, "Email webhooks are not configured on the server.")
    if not timestamp or not signature:
        raise WebhookError(401, "Missing signature headers.")
    try:
        sent_at = int(timestamp)
    except ValueError:
        raise WebhookError(401, "Invalid timestamp.")
    current = time.time() if now is None else now
    if abs(current - sent_at) > WEBHOOK_TOLERANCE_SECONDS:
        raise WebhookError(401, "Signature timestamp is outside the allowed window.")
    if not hmac.compare_digest(sign(secret, timestamp, body), signature.strip()):
        raise WebhookError(401, "Signature does not match.")


# ── Provider adapters ────────────────────────────────────────────────────────

def _clean(value, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split())[:limit]
    return cleaned or None


def _parse_time(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def parse_generic(payload: dict) -> tuple[list[DeliveryEvent], int]:
    """Generic format: {"provider": "...", "events": [{"event_id", "type", "message_id", "recipient", "occurred_at", "reason"}]}."""
    provider = _clean(payload.get("provider"), 40) or "generic"
    items = payload.get("events")
    if not isinstance(items, list):
        raise WebhookError(422, "events must be a list.")
    if len(items) > MAX_EVENTS_PER_REQUEST:
        raise WebhookError(422, f"At most {MAX_EVENTS_PER_REQUEST} events per request.")
    events: list[DeliveryEvent] = []
    ignored = 0
    for item in items:
        if not isinstance(item, dict):
            raise WebhookError(422, "Each event must be an object.")
        event_id = _clean(item.get("event_id"), 200)
        event_type = _TYPE_ALIASES.get(str(item.get("type", "")).strip().lower())
        if not event_id or event_type is None:
            ignored += 1
            continue
        recipient = _clean(item.get("recipient"), 254)
        events.append(DeliveryEvent(
            event_key=f"{provider}:{event_id}",
            source="webhook",
            event_type=event_type,
            provider_message_id=_clean(item.get("message_id"), 500),
            recipient_email=recipient.lower() if recipient else None,
            reason=_clean(item.get("reason"), 500),
            occurred_at=_parse_time(item.get("occurred_at")),
        ))
    return events, ignored


ADAPTERS = {"generic": parse_generic}


def parse_webhook(payload) -> tuple[list[DeliveryEvent], int]:
    if not isinstance(payload, dict):
        raise WebhookError(422, "The body must be a JSON object.")
    provider = _clean(payload.get("provider"), 40) or "generic"
    parser = ADAPTERS.get(provider)
    if parser is None:
        raise WebhookError(422, f"No adapter is configured for provider '{provider}'.")
    return parser(payload)


# ── Recording and applying events ────────────────────────────────────────────

def next_delivery_status(current: str | None, event_type: str) -> str | None:
    """A hard bounce is final. Otherwise the newest confirmed event wins, except that a late deferral never
    overrides a confirmed outcome."""
    if current == "bounced_hard":
        return current
    if event_type in ("bounced_hard", "bounced_soft", "rejected", "delivered"):
        return event_type
    if event_type == "deferred":
        return current if current in ("delivered", "bounced_soft", "rejected") else "deferred"
    return current


class _Duplicate(Exception):
    pass


def _match(conn, provider_message_id: str | None, recipient_email: str | None):
    """Find the campaign recipient this event belongs to. Returns (campaign_id, recipient_id, email) or None."""
    if provider_message_id:
        row = conn.execute(text(
            "SELECT campaign_id, recipient_id FROM email_send_ledger WHERE provider_message_id = :mid LIMIT 1"
        ), {"mid": provider_message_id}).first()
        if row is not None:
            recipient = conn.execute(text(
                "SELECT recipient_email FROM campaign_recipients WHERE id = :id"
            ), {"id": row[1]}).scalar()
            return row[0], row[1], recipient
        row = conn.execute(text(
            "SELECT campaign_id, id, recipient_email FROM campaign_recipients WHERE provider_message_id = :mid LIMIT 1"
        ), {"mid": provider_message_id}).first()
        if row is not None:
            return row[0], row[1], row[2]
    return None


def _apply_to_recipient(conn, event: DeliveryEvent, campaign_id: int, recipient_id: int, email: str | None) -> None:
    current = conn.execute(text("SELECT delivery_status FROM campaign_recipients WHERE id = :id"),
                           {"id": recipient_id}).scalar()
    new_status = next_delivery_status(current, event.event_type)
    conn.execute(text(
        "UPDATE campaign_recipients SET delivery_status = :status, delivery_detail = :detail, "
        "delivery_updated_at = :now, updated_at = CURRENT_TIMESTAMP WHERE id = :id"
    ), {"status": new_status, "detail": event.reason, "now": stamp(utc_now()), "id": recipient_id})

    if event.event_type == "bounced_hard":
        conn.execute(text(
            "UPDATE email_send_ledger SET status = 'bounced', failure_detail = :detail, updated_at = CURRENT_TIMESTAMP "
            "WHERE recipient_id = :rid AND status IN ('sent', 'uncertain')"
        ), {"detail": ("Hard bounce: " + (event.reason or "permanent failure"))[:300], "rid": recipient_id})
        if email:
            conn.execute(text(
                "INSERT INTO suppression_list (email, reason) VALUES (:email, 'hard_bounce') "
                "ON CONFLICT (email) DO NOTHING"
            ), {"email": email.strip().lower()})
    elif event.event_type == "rejected":
        conn.execute(text(
            "UPDATE email_send_ledger SET failure_detail = :detail, updated_at = CURRENT_TIMESTAMP "
            "WHERE recipient_id = :rid"
        ), {"detail": ("Rejected by provider: " + (event.reason or "no reason given"))[:300], "rid": recipient_id})
    # Temporary failures (deferred, soft bounce) never suppress the address.


def record_event(event: DeliveryEvent) -> str:
    """Store one event and apply it, in one transaction. Returns 'accepted', 'duplicate' or 'unmatched'."""
    try:
        with get_engine().begin() as conn:
            if conn.execute(text("SELECT 1 FROM email_events WHERE event_key = :key"),
                            {"key": event.event_key}).first():
                raise _Duplicate()
            match = _match(conn, event.provider_message_id, event.recipient_email)
            campaign_id, recipient_id, email = match if match else (None, None, None)
            conn.execute(text(
                "INSERT INTO email_events (event_key, source, event_type, provider_message_id, recipient_email, "
                "recipient_id, campaign_id, reason, occurred_at, received_at) VALUES (:key, :source, :type, :mid, "
                ":email, :rid, :cid, :reason, :occurred, :received)"
            ), {
                "key": event.event_key, "source": event.source, "type": event.event_type,
                "mid": event.provider_message_id, "email": event.recipient_email or email,
                "rid": recipient_id, "cid": campaign_id, "reason": event.reason,
                "occurred": stamp(event.occurred_at) if event.occurred_at else None,
                "received": stamp(utc_now()),
            })
            if recipient_id is None:
                return "unmatched"
            _apply_to_recipient(conn, event, campaign_id, recipient_id, email)
            return "accepted"
    except (_Duplicate, IntegrityError):
        # _Duplicate: already recorded. IntegrityError: a concurrent delivery of the same event won the race.
        return "duplicate"


def ingest(events: list[DeliveryEvent], ignored: int = 0) -> dict:
    counts = {"accepted": 0, "duplicate": 0, "unmatched": 0, "ignored": ignored}
    for event in events:
        counts[record_event(event)] += 1
    return counts
