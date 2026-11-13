"""Sending-mailbox monitor: bounce messages and replies, read over IMAP.

Why IMAP: plain SMTP sending gives no delivery-event webhooks and no thread IDs. A bounce comes back as a
delivery-status message in the sending mailbox, and a reply comes back as an ordinary message that quotes
the original Message-ID in In-Reply-To or References. Reading the mailbox is the only route that works with
the current SMTP setup.

Behaviour:
- Read only: messages are fetched with BODY.PEEK and the mailbox is opened read-only, so nothing is marked
  as seen, moved or deleted.
- Every message is processed once (its message key is unique), and the cursor (last UID) advances after
  each message, so a restart resumes where it stopped.
- Bounces become delivery events (services/email_events.py). Replies become conversation records.
- A reply is linked to a recipient only when its thread headers point at exactly one campaign email.
  Anything less certain goes to manual review. Nothing is ever replied to automatically.
- Message content is stored as plain text and shown as text. HTML is converted to text and never rendered.

Credentials come from the environment only: MAILBOX_IMAP_HOST, MAILBOX_IMAP_PORT, MAILBOX_USERNAME,
MAILBOX_PASSWORD, MAILBOX_FOLDER. They are never written to the database, logs or responses.
"""

import email
import hashlib
import imaplib
import logging
import os
import re
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime

from bs4 import BeautifulSoup
from sqlalchemy import text

from models.database import execute, fetch_all, fetch_one, get_engine, stamp, utc_now
from services.email_events import DeliveryEvent, ingest
from services.tenancy import current_workspace, current_workspace_or_none

logger = logging.getLogger("app.mailbox")

MAX_BODY_CHARS = 10000
MAX_MESSAGES_PER_SYNC = 200
CURSOR_KEY = "imap_last_uid"
_MESSAGE_ID = re.compile(r"<[^<>\s]+>")


class MailboxError(Exception):
    """The mailbox is not configured or cannot be reached. Nothing was marked as processed."""


@dataclass(frozen=True)
class MailboxMessage:
    uid: int
    raw: bytes


class ImapMailbox:
    """Read-only IMAP access over TLS with certificate verification."""

    def __init__(self, host: str, port: int, username: str, password: str, folder: str = "INBOX"):
        self.host, self.port, self.username, self.password, self.folder = host, port, username, password, folder

    def fetch_after(self, last_uid: int) -> list[MailboxMessage]:
        try:
            connection = imaplib.IMAP4_SSL(self.host, self.port, timeout=30,
                                           ssl_context=ssl.create_default_context())
            connection.login(self.username, self.password)
            connection.select(self.folder, readonly=True)
            _status, data = connection.uid("SEARCH", None, f"UID {last_uid + 1}:*")
            uids = sorted(int(value) for value in data[0].split() if int(value) > last_uid)[:MAX_MESSAGES_PER_SYNC]
            messages = []
            for uid in uids:
                _status, fetched = connection.uid("FETCH", str(uid), "(BODY.PEEK[])")
                messages.append(MailboxMessage(uid, fetched[0][1]))
            connection.logout()
            return messages
        except (imaplib.IMAP4.error, OSError) as exc:
            raise MailboxError(f"Mailbox could not be read: {type(exc).__name__}") from exc


def mailbox_configured() -> bool:
    """True when the mailbox settings are present. Reads the environment only; no connection is made."""
    return mailbox_from_env() is not None


def mailbox_from_env() -> ImapMailbox | None:
    host = os.getenv("MAILBOX_IMAP_HOST", "").strip()
    username = os.getenv("MAILBOX_USERNAME", "").strip()
    password = os.getenv("MAILBOX_PASSWORD", "")
    if not (host and username and password):
        return None
    port = int(os.getenv("MAILBOX_IMAP_PORT", "993") or 993)
    return ImapMailbox(host, port, username, password, os.getenv("MAILBOX_FOLDER", "INBOX").strip() or "INBOX")


# ── Message parsing ──────────────────────────────────────────────────────────

def _ids(value) -> list[str]:
    return _MESSAGE_ID.findall(value or "")


def _clean_line(value, limit: int) -> str:
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())[:limit]


def _decoded(part) -> str:
    payload = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _body_text(message) -> str:
    plain, html = [], []
    for part in message.walk():
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        kind = part.get_content_type()
        if kind == "text/plain":
            plain.append(_decoded(part))
        elif kind == "text/html":
            soup = BeautifulSoup(_decoded(part), "html.parser")
            for element in soup(["script", "style", "iframe", "object", "embed"]):
                element.decompose()  # scripts and styles never reach the stored text
            html.append(soup.get_text(separator="\n"))
    body = "\n".join(plain) if plain else "\n".join(html)
    body = "".join(ch for ch in body if ch in "\n\t" or ch >= " ")  # drop control characters
    return body.strip()[:MAX_BODY_CHARS]


def _message_key(message, raw: bytes) -> str:
    identifier = _ids(message.get("Message-ID", ""))
    return identifier[0] if identifier else "sha256:" + hashlib.sha256(raw).hexdigest()


def _received_at(message) -> datetime:
    try:
        return parsedate_to_datetime(message.get("Date", "")).astimezone(timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError):
        return utc_now()


def _dsn_events(message, message_key: str) -> list[DeliveryEvent] | None:
    """Delivery status notifications: one event per recipient block. Returns None for ordinary mail."""
    if message.get_content_type() != "multipart/report" or message.get_param("report-type") != "delivery-status":
        return None
    returned_ids: list[str] = []
    status_blocks = []
    for part in message.walk():
        kind = part.get_content_type()
        if kind == "message/delivery-status":
            status_blocks = [block for block in (part.get_payload() or []) if hasattr(block, "get")]
        elif kind == "text/rfc822-headers":
            # The returned headers are plain text inside the part, so read them as a header block.
            returned_ids += _ids(email.message_from_string(str(part.get_payload())).get("Message-ID", ""))
        elif kind == "message/rfc822" and isinstance(part.get_payload(), list) and part.get_payload():
            returned_ids += _ids(part.get_payload()[0].get("Message-ID", ""))
    original = returned_ids[0] if returned_ids else None
    events = []
    for block in status_blocks:
        action = str(block.get("Action", "")).strip().lower()
        status_code = str(block.get("Status", "")).strip()
        recipient = parseaddr(str(block.get("Final-Recipient", "")).split(";", 1)[-1])[1].lower() or None
        reason = _clean_line(block.get("Diagnostic-Code") or status_code or action, 500)
        if action == "failed":
            event_type = "bounced_hard" if status_code.startswith("5.") else "bounced_soft"
        elif action == "delayed":
            event_type = "deferred"
        elif action == "delivered":
            event_type = "delivered"
        else:
            continue
        events.append(DeliveryEvent(
            event_key=f"mailbox-dsn:{message_key}:{recipient or 'unknown'}",
            source="mailbox", event_type=event_type, provider_message_id=original,
            recipient_email=recipient, reason=reason, occurred_at=None,
        ))
    return events


# ── Replies and processing ───────────────────────────────────────────────────

def _classify_reply(conn, message) -> dict:
    """Decide how a reply links to a campaign email. Returns the conversation fields for the decision."""
    referenced = list(dict.fromkeys(_ids(message.get("In-Reply-To", "")) + _ids(message.get("References", ""))))
    sender = parseaddr(message.get("From", ""))[1].lower()
    if referenced:
        placeholders = ", ".join(f":m{i}" for i in range(len(referenced)))
        rows = conn.execute(text(
            "SELECT l.campaign_id, l.recipient_id, l.restaurant_id, c.workspace_id FROM email_send_ledger l "
            "JOIN campaigns c ON c.id = l.campaign_id "
            f"WHERE l.provider_message_id IN ({placeholders})"
        ), {f"m{i}": value for i, value in enumerate(referenced)}).mappings().all()
        candidates = {row["recipient_id"]: row for row in rows}
        if len(candidates) == 1:
            row = next(iter(candidates.values()))
            return {"match_status": "matched", "match_reason": "Replies to a campaign email (thread headers)",
                    "campaign_id": row["campaign_id"], "recipient_id": row["recipient_id"],
                    "restaurant_id": row["restaurant_id"], "workspace_id": row["workspace_id"]}
        if len(candidates) > 1:
            first = next(iter(candidates.values()))
            return {"match_status": "needs_review",
                    "match_reason": "Thread headers point at several campaign emails. A person must choose.",
                    "workspace_id": first["workspace_id"]}
    if sender:
        rows = conn.execute(text(
            "SELECT r.id, r.campaign_id, r.restaurant_id, c.workspace_id FROM campaign_recipients r "
            "JOIN campaigns c ON c.id = r.campaign_id "
            "WHERE LOWER(r.recipient_email) = :email AND r.status = 'sent' ORDER BY r.id DESC LIMIT 2"
        ), {"email": sender}).mappings().all()
        if len(rows) == 1:
            row = rows[0]
            return {"match_status": "needs_review",
                    "match_reason": "The sender matches a campaign recipient, but the message has no thread headers.",
                    "campaign_id": row["campaign_id"], "recipient_id": row["id"], "restaurant_id": row["restaurant_id"],
                    "workspace_id": row["workspace_id"]}
    # Nothing matches, so no workspace owns the message. It is shown only to the workspace that ran the sync.
    return {"match_status": "unmatched", "match_reason": "No campaign email matches this message.",
            "workspace_id": current_workspace_or_none()}


def _store_reply(message, raw: bytes, message_key: str) -> str:
    try:
        with get_engine().begin() as conn:
            if conn.execute(text("SELECT 1 FROM email_conversations WHERE message_key = :key"),
                            {"key": message_key}).first():
                return "duplicate"
            decision = _classify_reply(conn, message)
            automatic = bool(message.get("Auto-Submitted")) and message.get("Auto-Submitted", "").lower() != "no"
            if automatic:
                decision["match_reason"] = "Automatic reply (out of office or similar). Not counted as a reply."
            conn.execute(text(
                "INSERT INTO email_conversations (message_key, direction, match_status, match_reason, campaign_id, "
                "recipient_id, restaurant_id, in_reply_to, references_ids, from_address, subject, body_text, "
                "received_at, workspace_id) VALUES (:key, 'inbound', :status, :reason, :campaign, :recipient, :restaurant, :irt, "
                ":refs, :from_address, :subject, :body, :received, :ws)"
            ), {
                "key": message_key, "status": decision["match_status"], "reason": decision["match_reason"],
                "campaign": decision.get("campaign_id"), "recipient": decision.get("recipient_id"),
                "restaurant": decision.get("restaurant_id"), "ws": decision.get("workspace_id"),
                "irt": _clean_line(message.get("In-Reply-To"), 500), "refs": _clean_line(message.get("References"), 2000),
                "from_address": parseaddr(message.get("From", ""))[1].lower()[:254] or None,
                "subject": _clean_line(message.get("Subject"), 300) or None,
                "body": _body_text(message) or None,
                "received": stamp(_received_at(message)),
            })
            if decision["match_status"] == "matched" and not automatic:
                conn.execute(text(
                    "UPDATE campaign_recipients SET replied_at = COALESCE(replied_at, :now) WHERE id = :id"
                ), {"now": stamp(utc_now()), "id": decision["recipient_id"]})
            return decision["match_status"]
    except Exception:  # never let one message stop the sync
        logger.exception("Mailbox message could not be stored", extra={"event": "mailbox_message_error"})
        return "error"


def process_message(raw: bytes) -> str:
    """Process one raw message. Returns 'event', 'matched', 'needs_review', 'unmatched', 'duplicate' or 'error'."""
    message = email.message_from_bytes(raw)
    message_key = _message_key(message, raw)
    events = _dsn_events(message, message_key)
    if events is not None:
        return _record_dsn(events)
    return _store_reply(message, raw, message_key)


def _record_dsn(events: list[DeliveryEvent]) -> str:
    counts = ingest(events)
    if events and counts["duplicate"] == len(events):
        return "duplicate"
    return "event"


def get_state(key: str) -> str | None:
    row = fetch_one("SELECT value FROM email_sync_state WHERE key = :key", {"key": key})
    return row["value"] if row else None


def set_state(key: str, value: str) -> None:
    updated = execute(
        "UPDATE email_sync_state SET value = :value, updated_at = CURRENT_TIMESTAMP WHERE key = :key",
        {"key": key, "value": value},
    )
    if not updated:
        execute("INSERT INTO email_sync_state (key, value) VALUES (:key, :value)", {"key": key, "value": value})


def sync_mailbox(mailbox=None) -> dict:
    """Read new messages since the cursor and process them. Returns counts only (no message content)."""
    mailbox = mailbox or mailbox_from_env()
    if mailbox is None:
        raise MailboxError("Mailbox monitoring is not configured. Set MAILBOX_IMAP_HOST, MAILBOX_USERNAME and MAILBOX_PASSWORD.")
    last = int(get_state(CURSOR_KEY) or 0)
    counts = {"read": 0, "event": 0, "matched": 0, "needs_review": 0, "unmatched": 0, "duplicate": 0, "error": 0}
    for item in mailbox.fetch_after(last):
        outcome = process_message(item.raw)
        counts["read"] += 1
        counts[outcome if outcome in counts else "error"] += 1
        set_state(CURSOR_KEY, str(item.uid))
    return counts


def review_queue(limit: int = 200) -> list[dict]:
    """Replies a person must look at in the active workspace: uncertain matches and unmatched messages. Text only."""
    return fetch_all(
        "SELECT id, match_status, match_reason, campaign_id, recipient_id, restaurant_id, from_address, subject, "
        "body_text, received_at FROM email_conversations WHERE match_status IN ('needs_review', 'unmatched') "
        "AND workspace_id = :ws ORDER BY received_at DESC, id DESC LIMIT :limit",
        {"limit": limit, "ws": current_workspace()})


def resolve_conversation(conversation_id: int, decision: str) -> dict | None:
    """'confirm' links an uncertain reply to its candidate recipient. 'dismiss' closes it. Nothing is sent."""
    ws = current_workspace()
    with get_engine().begin() as conn:
        row = conn.execute(text(
            "SELECT id, match_status, match_reason, recipient_id FROM email_conversations WHERE id = :id AND workspace_id = :ws"
        ), {"id": conversation_id, "ws": ws}).mappings().first()
        if row is None:
            return None
        if row["match_status"] not in ("needs_review", "unmatched"):
            raise ValueError("This message has already been resolved.")
        now = stamp(utc_now())
        if decision == "confirm":
            if row["match_status"] != "needs_review" or row["recipient_id"] is None:
                raise ValueError("Only an uncertain reply with a candidate recipient can be confirmed.")
            conn.execute(text(
                "UPDATE email_conversations SET match_status = 'matched', match_reason = 'Confirmed by a person', "
                "reviewed_at = :now WHERE id = :id"
            ), {"now": now, "id": conversation_id})
            if "Automatic reply" not in (row["match_reason"] or ""):
                conn.execute(text(
                    "UPDATE campaign_recipients SET replied_at = COALESCE(replied_at, :now) WHERE id = :rid"
                ), {"now": now, "rid": row["recipient_id"]})
        else:
            conn.execute(text(
                "UPDATE email_conversations SET match_status = 'dismissed', reviewed_at = :now WHERE id = :id"
            ), {"now": now, "id": conversation_id})
    return fetch_one("SELECT id, match_status, match_reason, reviewed_at FROM email_conversations WHERE id = :id",
                     {"id": conversation_id})


def restaurant_history(restaurant_id: int) -> dict:
    """Delivery events and replies linked to one restaurant in the active workspace, newest first. Text only."""
    ws = current_workspace()
    events = fetch_all(
        "SELECT e.id, e.event_type, e.source, e.reason, e.recipient_email, e.campaign_id, e.occurred_at, e.received_at "
        "FROM email_events e JOIN campaign_recipients r ON r.id = e.recipient_id "
        "JOIN campaigns c ON c.id = r.campaign_id "
        "WHERE r.restaurant_id = :rid AND c.workspace_id = :ws ORDER BY e.received_at DESC, e.id DESC",
        {"rid": restaurant_id, "ws": ws})
    replies = fetch_all(
        "SELECT id, match_status, match_reason, campaign_id, recipient_id, from_address, subject, body_text, received_at "
        "FROM email_conversations WHERE restaurant_id = :rid AND workspace_id = :ws "
        "AND match_status IN ('matched', 'needs_review') ORDER BY received_at DESC, id DESC",
        {"rid": restaurant_id, "ws": ws})
    return {"events": events, "replies": replies}
