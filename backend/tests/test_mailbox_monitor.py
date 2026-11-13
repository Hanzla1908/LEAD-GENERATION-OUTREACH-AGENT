"""Mailbox monitor: bounce messages, replies, correlation, manual review, cursor and TLS.

A fake mailbox supplies raw messages. No IMAP server, mailbox or address is contacted.
"""
import ssl

import pytest

from models import campaign_store as store
from models.database import execute, fetch_one, save_restaurants
from services import mailbox_monitor as mm
from services.mailbox_monitor import ImapMailbox, MailboxError, MailboxMessage, resolve_conversation, sync_mailbox


class FakeMailbox:
    """Serves messages with UIDs above the cursor, the same way the IMAP search does."""

    def __init__(self, messages):
        self.messages = list(messages)  # list of (uid, raw bytes)

    def fetch_after(self, last_uid):
        return [MailboxMessage(uid, raw) for uid, raw in self.messages if uid > last_uid]


def _sent(email: str, message_id: str) -> tuple[int, int]:
    campaign_id = store.create_campaign(f"Mail {email}")
    restaurant_id = save_restaurants([{"place_id": f"mail-{email}", "name": f"Mail {email}", "source": "google_places"}])[0]["id"]
    store.insert_recipient(campaign_id, restaurant_id, email, "queued")
    row = next(r for r in store.list_recipients(campaign_id) if r["restaurant_id"] == restaurant_id)
    store.reserve_send(campaign_id, row)
    store.record_send_success(campaign_id, row["id"], message_id)
    return campaign_id, row["id"]


def _reply(message_id: str, sender: str, in_reply_to: str | None = None, references: str | None = None,
           subject: str = "Re: your menu", body: str = "Yes, please call us.", extra: str = "",
           content_type: str = "text/plain") -> bytes:
    headers = [f"Message-ID: {message_id}", f"From: {sender}", "To: outreach@sender.pk", f"Subject: {subject}",
               "Date: Wed, 04 Nov 2026 10:00:00 +0500", f"Content-Type: {content_type}; charset=utf-8"]
    if in_reply_to:
        headers.append(f"In-Reply-To: {in_reply_to}")
    if references:
        headers.append(f"References: {references}")
    if extra:
        headers.append(extra)
    return ("\r\n".join(headers) + "\r\n\r\n" + body + "\r\n").encode()


def _dsn(message_id: str, action: str, status: str, recipient: str, original_id: str) -> bytes:
    boundary = "dsnboundary"
    text = (
        f"Message-ID: {message_id}\r\nFrom: MAILER-DAEMON@mail.example\r\nTo: outreach@sender.pk\r\n"
        f"Subject: Delivery Status Notification (Failure)\r\nDate: Wed, 04 Nov 2026 10:05:00 +0500\r\n"
        f'MIME-Version: 1.0\r\nContent-Type: multipart/report; report-type=delivery-status; boundary="{boundary}"\r\n\r\n'
        f"--{boundary}\r\nContent-Type: text/plain\r\n\r\nThe message could not be delivered.\r\n\r\n"
        f"--{boundary}\r\nContent-Type: message/delivery-status\r\n\r\n"
        f"Reporting-MTA: dns; mail.example\r\n\r\n"
        f"Final-Recipient: rfc822; {recipient}\r\nAction: {action}\r\nStatus: {status}\r\n"
        f"Diagnostic-Code: smtp; {status} recipient rejected\r\n\r\n"
        f"--{boundary}\r\nContent-Type: text/rfc822-headers\r\n\r\n"
        f"Message-ID: {original_id}\r\nSubject: Our menu\r\n\r\n"
        f"--{boundary}--\r\n"
    )
    return text.encode()


# ── Bounce messages ──────────────────────────────────────────────────────────

def test_hard_bounce_message_is_recorded_suppressed_and_blocks_resend(test_db):
    campaign_id, recipient_id = _sent("bounce-hard@cafe.pk", "<orig-hard@sender.pk>")
    raw = _dsn("<dsn-1@mail.example>", "failed", "5.1.1", "bounce-hard@cafe.pk", "<orig-hard@sender.pk>")
    counts = sync_mailbox(FakeMailbox([(1, raw)]))
    assert counts["event"] == 1
    assert store.get_recipient(recipient_id)["delivery_status"] == "bounced_hard"
    assert fetch_one("SELECT reason FROM suppression_list WHERE email = 'bounce-hard@cafe.pk'")["reason"] == "hard_bounce"
    assert store.reserve_send(campaign_id, store.get_recipient(recipient_id)) == (False, "bounced")


def test_soft_bounce_message_is_not_suppressed(test_db):
    _campaign_id, recipient_id = _sent("bounce-soft@cafe.pk", "<orig-soft@sender.pk>")
    raw = _dsn("<dsn-2@mail.example>", "failed", "4.4.1", "bounce-soft@cafe.pk", "<orig-soft@sender.pk>")
    sync_mailbox(FakeMailbox([(1, raw)]))
    assert store.get_recipient(recipient_id)["delivery_status"] == "bounced_soft"
    assert fetch_one("SELECT COUNT(*) AS n FROM suppression_list WHERE email = 'bounce-soft@cafe.pk'")["n"] == 0


def test_delayed_and_delivered_status_messages_are_recorded(test_db):
    _c1, delayed = _sent("delayed@cafe.pk", "<orig-delay@sender.pk>")
    _c2, delivered = _sent("delivered@cafe.pk", "<orig-deliv@sender.pk>")
    sync_mailbox(FakeMailbox([
        (1, _dsn("<dsn-3@mail.example>", "delayed", "4.0.0", "delayed@cafe.pk", "<orig-delay@sender.pk>")),
        (2, _dsn("<dsn-4@mail.example>", "delivered", "2.0.0", "delivered@cafe.pk", "<orig-deliv@sender.pk>")),
    ]))
    assert store.get_recipient(delayed)["delivery_status"] == "deferred"
    assert store.get_recipient(delivered)["delivery_status"] == "delivered"


def test_the_same_bounce_message_is_never_processed_twice(test_db):
    _sent("twice@cafe.pk", "<orig-twice@sender.pk>")
    raw = _dsn("<dsn-5@mail.example>", "failed", "5.1.1", "twice@cafe.pk", "<orig-twice@sender.pk>")
    first = sync_mailbox(FakeMailbox([(1, raw)]))
    again = mm.process_message(raw)
    assert first["event"] == 1
    assert again == "duplicate"
    assert fetch_one("SELECT COUNT(*) AS n FROM email_events WHERE recipient_email = 'twice@cafe.pk'")["n"] == 1


# ── Replies ──────────────────────────────────────────────────────────────────

def test_reply_threaded_to_a_campaign_email_is_matched_and_marks_the_recipient(test_db):
    campaign_id, recipient_id = _sent("reply@cafe.pk", "<orig-reply@sender.pk>")
    raw = _reply("<reply-1@cafe.pk>", "Owner <reply@cafe.pk>", in_reply_to="<orig-reply@sender.pk>")
    counts = sync_mailbox(FakeMailbox([(1, raw)]))
    assert counts["matched"] == 1
    row = store.get_recipient(recipient_id)
    assert row["replied_at"]
    conversation = fetch_one("SELECT * FROM email_conversations WHERE message_key = '<reply-1@cafe.pk>'")
    assert conversation["match_status"] == "matched"
    assert conversation["campaign_id"] == campaign_id and conversation["recipient_id"] == recipient_id
    assert conversation["body_text"] == "Yes, please call us."
    assert conversation["from_address"] == "reply@cafe.pk"


def test_reply_matched_only_by_references_header(test_db):
    _c, recipient_id = _sent("refs@cafe.pk", "<orig-refs@sender.pk>")
    raw = _reply("<reply-refs@cafe.pk>", "refs@cafe.pk", references="<older@x> <orig-refs@sender.pk>")
    assert sync_mailbox(FakeMailbox([(1, raw)]))["matched"] == 1
    assert store.get_recipient(recipient_id)["replied_at"]


def test_reply_from_a_recipient_without_thread_headers_goes_to_review(test_db):
    _c, recipient_id = _sent("nohead@cafe.pk", "<orig-nohead@sender.pk>")
    raw = _reply("<reply-nohead@cafe.pk>", "nohead@cafe.pk")
    assert sync_mailbox(FakeMailbox([(1, raw)]))["needs_review"] == 1
    assert store.get_recipient(recipient_id)["replied_at"] is None  # never marked before a person confirms
    queue = mm.review_queue()
    assert [item["match_status"] for item in queue] == ["needs_review"]


def test_confirming_an_uncertain_reply_links_it_and_marks_the_recipient(test_db):
    _c, recipient_id = _sent("confirm@cafe.pk", "<orig-confirm@sender.pk>")
    sync_mailbox(FakeMailbox([(1, _reply("<reply-confirm@cafe.pk>", "confirm@cafe.pk"))]))
    conversation_id = mm.review_queue()[0]["id"]
    resolved = resolve_conversation(conversation_id, "confirm")
    assert resolved["match_status"] == "matched"
    assert store.get_recipient(recipient_id)["replied_at"]
    with pytest.raises(ValueError):
        resolve_conversation(conversation_id, "dismiss")  # already resolved


def test_unmatched_message_can_be_dismissed_but_not_confirmed(test_db):
    sync_mailbox(FakeMailbox([(1, _reply("<stranger@x.pk>", "stranger@example.org"))]))
    item = mm.review_queue()[0]
    assert item["match_status"] == "unmatched"
    with pytest.raises(ValueError):
        resolve_conversation(item["id"], "confirm")
    assert resolve_conversation(item["id"], "dismiss")["match_status"] == "dismissed"
    assert mm.review_queue() == []


def test_reply_matching_several_campaign_emails_is_sent_to_review(test_db):
    _c1, first = _sent("several-a@cafe.pk", "<orig-a@sender.pk>")
    _c2, second = _sent("several-b@cafe.pk", "<orig-b@sender.pk>")
    raw = _reply("<reply-several@x.pk>", "someone@x.pk", in_reply_to="<orig-a@sender.pk> <orig-b@sender.pk>")
    assert sync_mailbox(FakeMailbox([(1, raw)]))["needs_review"] == 1
    assert store.get_recipient(first)["replied_at"] is None and store.get_recipient(second)["replied_at"] is None
    with pytest.raises(ValueError):
        resolve_conversation(mm.review_queue()[0]["id"], "confirm")  # no single candidate to confirm


def test_automatic_replies_are_stored_but_do_not_count_as_replies(test_db):
    _c, recipient_id = _sent("ooo@cafe.pk", "<orig-ooo@sender.pk>")
    raw = _reply("<ooo-1@cafe.pk>", "ooo@cafe.pk", in_reply_to="<orig-ooo@sender.pk>",
                 extra="Auto-Submitted: auto-replied", subject="Out of office")
    sync_mailbox(FakeMailbox([(1, raw)]))
    assert store.get_recipient(recipient_id)["replied_at"] is None
    assert "Automatic reply" in fetch_one("SELECT match_reason FROM email_conversations WHERE message_key = '<ooo-1@cafe.pk>'")["match_reason"]


def test_a_reply_is_stored_once_even_if_processed_again(test_db):
    _sent("again@cafe.pk", "<orig-again@sender.pk>")
    raw = _reply("<again-1@cafe.pk>", "again@cafe.pk", in_reply_to="<orig-again@sender.pk>")
    assert sync_mailbox(FakeMailbox([(1, raw)]))["matched"] == 1
    assert mm.process_message(raw) == "duplicate"
    assert fetch_one("SELECT COUNT(*) AS n FROM email_conversations")["n"] == 1


def test_html_only_replies_are_stored_as_text_without_scripts(test_db):
    _sent("html@cafe.pk", "<orig-html@sender.pk>")
    body = "<html><body><p>Call us</p><script>alert('x')</script><style>p{}</style></body></html>"
    raw = _reply("<html-1@cafe.pk>", "html@cafe.pk", in_reply_to="<orig-html@sender.pk>",
                 content_type="text/html", body=body)
    sync_mailbox(FakeMailbox([(1, raw)]))
    stored = fetch_one("SELECT body_text FROM email_conversations WHERE message_key = '<html-1@cafe.pk>'")["body_text"]
    assert "Call us" in stored
    assert "alert" not in stored and "<script" not in stored and "p{}" not in stored


def test_reply_subject_cannot_inject_header_lines(test_db):
    _sent("inject@cafe.pk", "<orig-inject@sender.pk>")
    raw = _reply("<inject-1@cafe.pk>", "inject@cafe.pk", in_reply_to="<orig-inject@sender.pk>",
                 subject="Hello\r\nBcc: attacker@evil.example")
    sync_mailbox(FakeMailbox([(1, raw)]))
    subject = fetch_one("SELECT subject FROM email_conversations WHERE message_key = '<inject-1@cafe.pk>'")["subject"]
    assert "\n" not in subject and "\r" not in subject


# ── Cursor, configuration and TLS ────────────────────────────────────────────

def test_sync_resumes_after_the_last_message_it_processed(test_db):
    _sent("cursor@cafe.pk", "<orig-cursor@sender.pk>")
    mailbox = FakeMailbox([(1, _reply("<c1@x.pk>", "other@x.pk")), (2, _reply("<c2@x.pk>", "other@x.pk"))])
    assert sync_mailbox(mailbox)["read"] == 2
    assert sync_mailbox(mailbox)["read"] == 0  # nothing new
    mailbox.messages.append((3, _reply("<c3@x.pk>", "other@x.pk")))
    assert sync_mailbox(mailbox)["read"] == 1
    assert mm.get_state(mm.CURSOR_KEY) == "3"


def test_sync_without_configuration_says_so_and_reads_nothing(test_db, monkeypatch):
    for name in ("MAILBOX_IMAP_HOST", "MAILBOX_USERNAME", "MAILBOX_PASSWORD"):
        monkeypatch.delenv(name, raising=False)
    assert mm.mailbox_from_env() is None
    with pytest.raises(MailboxError, match="not configured"):
        sync_mailbox()


def test_imap_connection_verifies_the_server_certificate(monkeypatch):
    captured = {}

    class FakeIMAP:
        def __init__(self, host, port, timeout, ssl_context):
            captured["context"] = ssl_context
            captured["host"] = host

        def login(self, user, password):
            captured["login"] = (user, password)

        def select(self, folder, readonly):
            captured["readonly"] = readonly

        def uid(self, command, *args):
            if command == "SEARCH":
                return "OK", [b""]
            return "OK", []

        def logout(self):
            pass

    monkeypatch.setattr(mm.imaplib, "IMAP4_SSL", FakeIMAP)
    ImapMailbox("imap.example.test", 993, "outreach@sender.pk", "pw", "INBOX").fetch_after(0)
    context = captured["context"]
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    assert captured["readonly"] is True  # the mailbox is opened read-only


def test_mailbox_connection_errors_are_reported_without_details(monkeypatch):
    class BrokenIMAP:
        def __init__(self, *args, **kwargs):
            raise OSError("connection reset with secret-host-details")

    monkeypatch.setattr(mm.imaplib, "IMAP4_SSL", BrokenIMAP)
    with pytest.raises(MailboxError) as raised:
        ImapMailbox("imap.example.test", 993, "u", "p").fetch_after(0)
    assert "secret-host-details" not in str(raised.value)


def test_sync_endpoint_refuses_when_mailbox_is_not_configured(test_db, monkeypatch):
    from fastapi.testclient import TestClient
    import main
    for name in ("MAILBOX_IMAP_HOST", "MAILBOX_USERNAME", "MAILBOX_PASSWORD", "ADMIN_PASSWORD", "ADMIN_PASSWORD_HASH"):
        monkeypatch.delenv(name, raising=False)
    from tests.account_helpers import signed_in_client
    response = signed_in_client(main.app).post("/email/sync")
    assert response.status_code == 503


def test_review_resolution_endpoint_validates_the_decision(test_db):
    from tests.account_helpers import signed_in_client
    import main
    client = signed_in_client(main.app)
    assert client.post("/email/conversations/1/resolve", json={"decision": "maybe"}).status_code == 422
    assert client.post("/email/conversations/999999/resolve", json={"decision": "dismiss"}).status_code == 404
