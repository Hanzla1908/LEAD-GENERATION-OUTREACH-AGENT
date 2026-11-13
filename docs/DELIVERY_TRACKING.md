# Delivery events, bounces and replies

This covers how the app learns what happened after an email was sent: whether it was delivered, bounced, deferred or rejected, and whether the recipient replied.

## What the current setup can and cannot provide

The app sends through Nodemailer over plain SMTP, or through the Python SMTP sender. Checked against the code:

- **SMTP has no delivery-event webhook.** The SMTP protocol does not report delivery. Nodemailer's SMTP transport does not either.
- **SMTP gives no thread IDs.** Replies can only be linked by the `Message-ID`, `In-Reply-To` and `References` headers.
- **Bounces come back as messages.** A failed delivery returns a delivery-status message (a DSN) to the sending mailbox. The mailbox monitor reads these.
- **Replies arrive in the sending mailbox**, so the mailbox monitor reads them too.

So the app supports two inbound paths:

| Path | Needs | Provides | Status |
|---|---|---|---|
| Mailbox monitor (IMAP) | An IMAP mailbox that holds the sent mail | Bounces (hard, soft, deferred, delivered DSNs) and replies | Implemented and tested with mock mailboxes. Needs credentials. |
| Signed provider webhook | A provider that offers delivery-event webhooks, and its signing secret | Delivered, deferred, soft and hard bounces, rejected | Endpoint and signature check implemented and tested. The provider-specific parser is not written yet, because no provider is chosen. The generic format is implemented. |

If you choose a provider with webhooks, add a parser for its payload in `services/email_events.py` (`ADAPTERS`). Nothing else changes.

## Required credentials and configuration

Set these on the backend only. They are never shown in the dashboard, logged or stored in the database.

| Setting | Needed for | Notes |
|---|---|---|
| `EMAIL_WEBHOOK_SECRET` | Provider webhooks | At least 32 random characters. The provider signs each request with it. Without it the endpoint refuses all requests (HTTP 503). |
| `MAILBOX_IMAP_HOST` | Bounce and reply monitoring | For example `imap.yourprovider.example`. |
| `MAILBOX_IMAP_PORT` | Bounce and reply monitoring | Default 993 (TLS). |
| `MAILBOX_USERNAME` | Bounce and reply monitoring | The sending mailbox. |
| `MAILBOX_PASSWORD` | Bounce and reply monitoring | Use an app password or a dedicated credential, not your main password. |
| `MAILBOX_FOLDER` | Bounce and reply monitoring | Default `INBOX`. |

The IMAP connection verifies the server certificate and opens the mailbox read-only. Messages are read without being marked as seen, moved or deleted.

## How events are applied

- **Idempotency.** Each event has a unique key (the provider's event ID, or the bounce message's ID). A repeated event changes nothing.
- **Hard bounce:** the recipient is marked `bounced_hard`, the ledger row becomes `bounced` (so the address is never sent to again), and the address is added to the suppression list.
- **Soft bounce and deferral:** the recipient is marked as such. The address is not suppressed, and the send is not retried by the app.
- **Delivered:** marked delivered, unless the address has already hard-bounced.
- **Rejected:** recorded on the recipient and the ledger note. The ledger status is unchanged.
- **Unmatched events** (no campaign email carries that message ID) are stored and do not change any recipient.

## What the dashboard shows

- **Campaign page:** a delivery panel with confirmed counts (delivered, deferred, soft bounces, hard bounces, rejected, replied) and a separate "No confirmation yet" count. A sent email with no confirmed event is never shown as delivered.
- **Each recipient:** a delivery badge, and a "Replied" badge once a reply is matched.
- **Leads page:** a **History** button shows a restaurant's delivery events and replies, as plain text.
- **Campaigns page:** the **Replies to review** panel lists uncertain matches and unmatched messages. A person confirms the link to the right recipient, or dismisses the message. Nothing is answered automatically.

## Matching replies

A reply is linked to a recipient only when:

1. its `In-Reply-To` or `References` header names exactly one campaign email, which is **matched**; or
2. it has no thread headers but comes from the address of exactly one sent recipient, which goes to **review**.

If several campaign emails match, the reply goes to review, and confirming it is not possible without choosing a recipient. Automatic replies (out of office and similar) are stored but never count as a reply.

## Manual testing (mocked, no real email)

These steps use mock events and a test mailbox. They send nothing.

1. **Signature check.** Set `EMAIL_WEBHOOK_SECRET` to a 32-character test value. Post a body to `/webhooks/email-events` with no signature. Expect HTTP 401. Then sign the body correctly (see `sign()` in `services/email_events.py`) and expect 200.
2. **Duplicate event.** Send the same signed event twice. The second response reports `duplicate: 1`.
3. **Mailbox sync.** Set the four `MAILBOX_*` values to a test mailbox that holds a bounce message and a reply. Run `python scripts/sync_mailbox.py` from the `backend` folder. Expect counts only, with no message text.
4. **Review.** Open the Campaigns page, check the reply inbox, confirm or dismiss an item, and confirm the campaign's replied count changes.
5. **History.** Open a restaurant's **History** from the Leads page and check that the events and replies appear as plain text.

## Limitations

- The provider-specific webhook parser is not written, because no provider is chosen.
- SMTP-only sending gives no positive delivery confirmation. "No confirmation yet" stays until a bounce or a webhook event arrives, or the sending mailbox reports one.
- The mailbox monitor reads only the mailbox it is given. Replies to a different address are not seen.
- Events are recorded one transaction at a time (about 180 per second in testing). A webhook request carries at most 200 events.
- Replies are matched by headers. A reply that strips all threading headers goes to review only if it comes from a recipient's address.
- Sync is run on demand or by the scheduled script. The app does not poll the mailbox on its own.
