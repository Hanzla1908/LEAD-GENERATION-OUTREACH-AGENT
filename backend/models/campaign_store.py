from sqlalchemy import text

from models.database import (
    execute,
    execute_returning_id,
    fetch_all,
    fetch_one,
    get_engine,
    in_list,
    is_postgres,
    stamp,
    utc_now,
)
from services.tenancy import current_workspace


def add_suppression(email: str, reason: str) -> None:
    execute(
        "INSERT INTO suppression_list (email, reason) VALUES (:email, :reason) ON CONFLICT (email) DO NOTHING",
        {"email": email.strip().lower(), "reason": reason},
    )


def suppressed_emails() -> set[str]:
    return {row["email"] for row in fetch_all("SELECT email FROM suppression_list")}


def list_suppression() -> list[dict]:
    return fetch_all("SELECT email, reason, created_at FROM suppression_list ORDER BY created_at DESC")


def create_campaign(name: str, created_by_user_id: int | None = None) -> int:
    """A campaign in the active workspace, attributed to the account that created it when known."""
    return execute_returning_id(
        "INSERT INTO campaigns (name, workspace_id, created_by_user_id) VALUES (:name, :ws, :actor) RETURNING id",
        {"name": name, "ws": current_workspace(), "actor": created_by_user_id},
    )


def get_campaign(campaign_id: int) -> dict | None:
    """The campaign, if it belongs to the active workspace. Another workspace's id reads as missing."""
    return fetch_one("SELECT * FROM campaigns WHERE id = :id AND workspace_id = :ws",
                     {"id": campaign_id, "ws": current_workspace()})


def list_campaigns() -> list[dict]:
    return fetch_all("SELECT * FROM campaigns WHERE workspace_id = :ws ORDER BY created_at DESC, id DESC",
                     {"ws": current_workspace()})


def set_campaign_status(campaign_id: int, status: str, note: str | None = None) -> None:
    execute(
        "UPDATE campaigns SET status = :status, status_note = :note, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = :id AND workspace_id = :ws",
        {"status": status, "note": note, "id": campaign_id, "ws": current_workspace()},
    )


def set_campaign_approval(campaign_id: int, approved_draft_ids_json: str) -> None:
    execute(
        "UPDATE campaigns SET approved_draft_ids = :ids, approved_at = CURRENT_TIMESTAMP, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = :id AND workspace_id = :ws",
        {"ids": approved_draft_ids_json, "id": campaign_id, "ws": current_workspace()},
    )


def add_log(campaign_id: int, event: str, detail: str | None = None, recipient: dict | None = None) -> None:
    execute(
        """
        INSERT INTO campaign_send_logs
            (campaign_id, recipient_id, restaurant_id, recipient_email, event, detail)
        VALUES (:campaign_id, :recipient_id, :restaurant_id, :recipient_email, :event, :detail)
        """,
        {
            "campaign_id": campaign_id,
            "recipient_id": recipient["id"] if recipient else None,
            "restaurant_id": recipient["restaurant_id"] if recipient else None,
            "recipient_email": recipient["recipient_email"] if recipient else None,
            "event": event,
            "detail": detail,
        },
    )


def list_logs(campaign_id: int) -> list[dict]:
    return fetch_all(
        "SELECT l.* FROM campaign_send_logs l JOIN campaigns c ON c.id = l.campaign_id "
        "WHERE l.campaign_id = :cid AND c.workspace_id = :ws ORDER BY l.id",
        {"cid": campaign_id, "ws": current_workspace()},
    )


def get_campaign_status(campaign_id: int) -> str | None:
    campaign = get_campaign(campaign_id)
    return campaign["status"] if campaign else None


def insert_recipient(campaign_id: int, restaurant_id: int, email: str | None, status: str,
                     skip_reason: str | None = None) -> None:
    execute(
        """
        INSERT INTO campaign_recipients (campaign_id, restaurant_id, recipient_email, status, skip_reason)
        VALUES (:campaign_id, :restaurant_id, :email, :status, :skip_reason)
        """,
        {"campaign_id": campaign_id, "restaurant_id": restaurant_id, "email": email,
         "status": status, "skip_reason": skip_reason},
    )


_RECIPIENT_SELECT = """
    SELECT r.*, rest.name AS restaurant_name, rest.address AS restaurant_address,
           rest.city AS restaurant_city, rest.website AS restaurant_website,
           rest.contact_email AS restaurant_email, rest.contact_email_status AS restaurant_email_status,
           rest.opted_out AS restaurant_opted_out,
           d.subject AS subject, d.body AS body, d.status AS draft_status, d.angle AS angle
    FROM campaign_recipients r
    LEFT JOIN restaurants rest ON rest.id = r.restaurant_id
    LEFT JOIN email_drafts d ON d.id = r.draft_id
"""


_COUNTS_SQL = """
    SELECT r.campaign_id AS campaign_id,
        COUNT(*) AS total,
        SUM(CASE WHEN r.status = 'skipped' THEN 1 ELSE 0 END) AS skipped,
        SUM(CASE WHEN r.draft_id IS NOT NULL THEN 1 ELSE 0 END) AS drafts_generated,
        SUM(CASE WHEN r.status = 'draft_failed' THEN 1 ELSE 0 END) AS drafts_failed,
        SUM(CASE WHEN d.status = 'approved' THEN 1 ELSE 0 END) AS approved,
        SUM(CASE WHEN r.status = 'queued' THEN 1 ELSE 0 END) AS queued,
        SUM(CASE WHEN r.status = 'sent' THEN 1 ELSE 0 END) AS sent,
        SUM(CASE WHEN r.status IN ('failed', 'interrupted') THEN 1 ELSE 0 END) AS failed,
        SUM(CASE WHEN r.status = 'failed' AND r.provider_message_id IS NULL THEN 1 ELSE 0 END) AS retryable,
        SUM(CASE WHEN r.status = 'interrupted' THEN 1 ELSE 0 END) AS interrupted,
        SUM(CASE WHEN r.status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled
    FROM campaign_recipients r
    JOIN campaigns c ON c.id = r.campaign_id
    LEFT JOIN email_drafts d ON d.id = r.draft_id
    WHERE c.workspace_id = :ws
    GROUP BY r.campaign_id
"""


def recipient_counts_by_campaign() -> dict[int, dict]:
    """One aggregate query for every campaign's counters in the active workspace. Same meaning as summarize() in campaigns.py."""
    counts = {}
    for row in fetch_all(_COUNTS_SQL, {"ws": current_workspace()}):
        counts[row["campaign_id"]] = {key: int(value or 0) for key, value in row.items() if key != "campaign_id"}
    return counts


def list_recipients(campaign_id: int) -> list[dict]:
    return fetch_all(_RECIPIENT_SELECT + " WHERE r.campaign_id = :cid ORDER BY r.id", {"cid": campaign_id})


def get_recipient(recipient_id: int) -> dict | None:
    return fetch_one(_RECIPIENT_SELECT + " WHERE r.id = :id", {"id": recipient_id})


_RECIPIENT_FIELDS = frozenset({"status", "draft_id", "skip_reason", "error_reason", "provider_message_id"})


def update_recipient(recipient_id: int, **fields) -> None:
    unknown = set(fields) - _RECIPIENT_FIELDS
    if unknown:
        raise ValueError(f"Unknown recipient field(s): {', '.join(sorted(unknown))}")
    assignments = ", ".join(f"{column} = :{column}" for column in fields)
    execute(
        f"UPDATE campaign_recipients SET {assignments}, updated_at = CURRENT_TIMESTAMP WHERE id = :_id",
        {**fields, "_id": recipient_id},
    )


def sent_addresses(campaign_id: int) -> set[str]:
    """Addresses this campaign has already emailed, or may have emailed after an unknown outcome."""
    rows = fetch_all(
        "SELECT DISTINCT LOWER(recipient_email) AS email FROM campaign_recipients "
        "WHERE campaign_id = :cid AND status IN ('sent', 'interrupted') AND recipient_email IS NOT NULL",
        {"cid": campaign_id},
    )
    return {row["email"] for row in rows if row["email"]}


def mark_sent(recipient_id: int, provider_message_id: str) -> None:
    execute(
        """
        UPDATE campaign_recipients
        SET status = 'sent', provider_message_id = :message_id, sent_at = CURRENT_TIMESTAMP,
            error_reason = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE id = :id
        """,
        {"message_id": provider_message_id, "id": recipient_id},
    )


# ── Persistent send ledger ───────────────────────────────────────────────────
# The application database decides whether a recipient may be sent. Each campaign recipient has at
# most one ledger row (unique constraint). The row is reserved in a transaction BEFORE the provider is
# called, and the outcome is written in the same transaction as the recipient update.

LEDGER_RESERVED = "reserved"
LEDGER_SENT = "sent"
LEDGER_FAILED = "failed"
LEDGER_UNCERTAIN = "uncertain"
RESTART_NOTE = ("The process stopped before the delivery outcome was recorded. Check the provider. "
                "This recipient is never resent automatically.")
BLOCKED_NOTE = "Check the provider before doing anything. This recipient is never resent automatically."


def ledger_key(campaign_id: int, recipient_id: int) -> str:
    return f"campaign-{campaign_id}-recipient-{recipient_id}"


def ledger_for(campaign_id: int, recipient_id: int) -> dict | None:
    return fetch_one(
        "SELECT * FROM email_send_ledger WHERE campaign_id = :cid AND recipient_id = :rid",
        {"cid": campaign_id, "rid": recipient_id},
    )


def _ledger_status(conn, campaign_id: int, recipient_id: int) -> str | None:
    return conn.execute(
        text("SELECT status FROM email_send_ledger WHERE campaign_id = :cid AND recipient_id = :rid"),
        {"cid": campaign_id, "rid": recipient_id},
    ).scalar_one_or_none()


def reserve_send(campaign_id: int, recipient: dict) -> tuple[bool, str]:
    """
    Reserve the right to send one recipient, before the provider is called.

    Returns (True, 'reserved') when this caller may send. Otherwise returns (False, status), where status
    is the existing ledger state: 'sent', 'reserved' (already in flight or interrupted), or 'uncertain'.
    Only 'failed' (the provider refused the message, so nothing was sent) can be reserved again.
    Two concurrent callers cannot both succeed: the insert or the conditional update decides.
    """
    params = {"cid": campaign_id, "rid": recipient["id"], "restaurant": recipient.get("restaurant_id"),
              "draft": recipient.get("draft_id"), "email": recipient.get("recipient_email"),
              "key": ledger_key(campaign_id, recipient["id"])}
    with get_engine().begin() as conn:
        inserted = conn.execute(text(
            "INSERT INTO email_send_ledger (campaign_id, recipient_id, restaurant_id, draft_id, recipient_email, "
            "status, attempts, idempotency_key, reserved_at, updated_at) "
            "VALUES (:cid, :rid, :restaurant, :draft, :email, 'reserved', 1, :key, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) "
            "ON CONFLICT (campaign_id, recipient_id) DO NOTHING"
        ), params).rowcount
        if inserted:
            return True, LEDGER_RESERVED
        status = _ledger_status(conn, campaign_id, recipient["id"])
        if status == LEDGER_FAILED:
            retried = conn.execute(text(
                "UPDATE email_send_ledger SET status = 'reserved', attempts = attempts + 1, failure_detail = NULL, "
                "reserved_at = CURRENT_TIMESTAMP, finished_at = NULL, updated_at = CURRENT_TIMESTAMP "
                "WHERE campaign_id = :cid AND recipient_id = :rid AND status = 'failed'"
            ), params).rowcount
            if retried:
                return True, LEDGER_RESERVED
            status = _ledger_status(conn, campaign_id, recipient["id"])
        return False, status or "missing"


def _finish_reserved(conn, campaign_id: int, recipient_id: int, status: str,
                     message_id: str | None, detail: str | None) -> None:
    updated = conn.execute(text(
        "UPDATE email_send_ledger SET status = :status, provider_message_id = COALESCE(:mid, provider_message_id), "
        "failure_detail = :detail, finished_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
        "WHERE campaign_id = :cid AND recipient_id = :rid AND status = 'reserved'"
    ), {"status": status, "mid": message_id, "detail": detail, "cid": campaign_id, "rid": recipient_id}).rowcount
    if updated != 1:
        raise LookupError(f"No reserved ledger entry for recipient {recipient_id}; nothing was recorded.")


def record_send_success(campaign_id: int, recipient_id: int, message_id: str) -> None:
    with get_engine().begin() as conn:
        _finish_reserved(conn, campaign_id, recipient_id, LEDGER_SENT, message_id, None)
        conn.execute(text(
            "UPDATE campaign_recipients SET status = 'sent', provider_message_id = :mid, sent_at = CURRENT_TIMESTAMP, "
            "error_reason = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = :id"
        ), {"mid": message_id, "id": recipient_id})


def record_send_failure(campaign_id: int, recipient_id: int, detail: str) -> None:
    """The provider refused the message, so nothing was sent and a retry is allowed."""
    with get_engine().begin() as conn:
        _finish_reserved(conn, campaign_id, recipient_id, LEDGER_FAILED, None, detail)
        conn.execute(text(
            "UPDATE campaign_recipients SET status = 'failed', error_reason = :detail, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = :id"
        ), {"detail": detail, "id": recipient_id})


def record_send_uncertain(campaign_id: int, recipient_id: int, detail: str, message_id: str | None = None) -> None:
    """The outcome is unknown. Blocked from automatic retries until a person reviews it. Never downgrades 'sent'."""
    with get_engine().begin() as conn:
        conn.execute(text(
            "UPDATE email_send_ledger SET status = 'uncertain', provider_message_id = COALESCE(:mid, provider_message_id), "
            "failure_detail = :detail, updated_at = CURRENT_TIMESTAMP "
            "WHERE campaign_id = :cid AND recipient_id = :rid AND status <> 'sent'"
        ), {"mid": message_id, "detail": detail, "cid": campaign_id, "rid": recipient_id})
        conn.execute(text(
            "UPDATE campaign_recipients SET status = 'interrupted', provider_message_id = COALESCE(:mid, provider_message_id), "
            "error_reason = :detail, updated_at = CURRENT_TIMESTAMP WHERE id = :id AND status <> 'sent'"
        ), {"mid": message_id, "detail": detail, "id": recipient_id})


def claim_next_queued(campaign_id: int) -> dict | None:
    """Atomically move the next queued recipient to 'sending'. Locked rows are skipped on PostgreSQL."""
    lock = " FOR UPDATE SKIP LOCKED" if is_postgres() else ""
    with get_engine().begin() as conn:
        row = conn.execute(text(
            "SELECT id FROM campaign_recipients WHERE campaign_id = :cid AND status = 'queued' "
            f"ORDER BY id LIMIT 1{lock}"
        ), {"cid": campaign_id}).first()
        if row is None:
            return None
        claimed = conn.execute(text(
            "UPDATE campaign_recipients SET status = 'sending', updated_at = CURRENT_TIMESTAMP "
            "WHERE id = :id AND status = 'queued'"
        ), {"id": row[0]})
        if claimed.rowcount == 0:
            return None
    return get_recipient(row[0])


def promote_approved_drafts(campaign_id: int) -> int:
    return execute(
        """
        UPDATE campaign_recipients SET status = 'queued', updated_at = CURRENT_TIMESTAMP
        WHERE campaign_id = :cid AND status = 'draft'
          AND draft_id IN (SELECT id FROM email_drafts WHERE status = 'approved')
        """,
        {"cid": campaign_id},
    )


def requeue_failed(campaign_id: int) -> int:
    return execute(
        """
        UPDATE campaign_recipients SET status = 'queued', error_reason = NULL, updated_at = CURRENT_TIMESTAMP
        WHERE campaign_id = :cid AND status = 'failed' AND provider_message_id IS NULL
        """,
        {"cid": campaign_id},
    )


def cancel_queued(campaign_id: int) -> None:
    execute(
        "UPDATE campaign_recipients SET status = 'cancelled', updated_at = CURRENT_TIMESTAMP "
        "WHERE campaign_id = :cid AND status = 'queued'",
        {"cid": campaign_id},
    )


def relink_draft(old_draft_id: int, new_draft_id: int) -> None:
    execute(
        "UPDATE campaign_recipients SET draft_id = :new, updated_at = CURRENT_TIMESTAMP WHERE draft_id = :old",
        {"new": new_draft_id, "old": old_draft_id},
    )


def sent_today_count() -> int:
    start = utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
    row = fetch_one(
        "SELECT COUNT(*) AS n FROM campaign_recipients WHERE status = 'sent' AND sent_at >= :start",
        {"start": stamp(start)},
    )
    return int(row["n"]) if row else 0


def restaurants_in_campaign_named(name: str, restaurant_ids: list[int]) -> set[int]:
    """Duplicate protection: restaurants already emailed in a campaign with this name, in this workspace only."""
    if not restaurant_ids:
        return set()
    names, params = in_list("rid", restaurant_ids)
    rows = fetch_all(
        f"""
        SELECT DISTINCT r.restaurant_id FROM campaign_recipients r
        JOIN campaigns c ON c.id = r.campaign_id
        WHERE c.name = :name AND c.workspace_id = :ws AND r.status IN ('queued', 'sending', 'sent', 'interrupted')
          AND r.restaurant_id IN ({names})
        """,
        {"name": name, "ws": current_workspace(), **params},
    )
    return {row["restaurant_id"] for row in rows}


def emails_in_campaign_named(name: str) -> set[str]:
    rows = fetch_all(
        """
        SELECT DISTINCT lower(r.recipient_email) AS email FROM campaign_recipients r
        JOIN campaigns c ON c.id = r.campaign_id
        WHERE c.name = :name AND c.workspace_id = :ws AND r.status IN ('queued', 'sending', 'sent', 'interrupted')
          AND r.recipient_email IS NOT NULL
        """,
        {"name": name, "ws": current_workspace()},
    )
    return {row["email"] for row in rows}


# Statuses that count as "already contacted". Preview (before sending) also counts queued rows, so a second
# campaign cannot be built on an address another campaign is already waiting to send. The send-time check
# counts only rows that are sending, sent or uncertain, so two queued campaigns never block each other.
PREVIEW_CONTACT_STATUSES = ("queued", "sending", "sent", "interrupted")
SEND_CONTACT_STATUSES = ("sending", "sent", "interrupted")


def restaurants_contacted(restaurant_ids: list[int], exclude_campaign_id: int | None = None,
                          statuses: tuple = PREVIEW_CONTACT_STATUSES) -> dict[int, str]:
    """Workspace-wide contact block: restaurant id -> name of another campaign that already emails it.

    Scoped to the active workspace. Campaigns in other workspaces are never consulted (isolation).
    """
    if not restaurant_ids:
        return {}
    names, params = in_list("rid", restaurant_ids)
    status_names, status_params = in_list("st", list(statuses))
    rows = fetch_all(
        f"""
        SELECT r.restaurant_id, c.name AS campaign_name FROM campaign_recipients r
        JOIN campaigns c ON c.id = r.campaign_id
        WHERE c.workspace_id = :ws AND c.id <> :exclude AND r.status IN ({status_names})
          AND r.restaurant_id IN ({names})
        ORDER BY r.id
        """,
        {"ws": current_workspace(), "exclude": -1 if exclude_campaign_id is None else exclude_campaign_id,
         **params, **status_params},
    )
    found: dict[int, str] = {}
    for row in rows:
        found.setdefault(row["restaurant_id"], row["campaign_name"])
    return found


def emails_contacted(exclude_campaign_id: int | None = None,
                     statuses: tuple = PREVIEW_CONTACT_STATUSES) -> dict[str, str]:
    """Workspace-wide contact block: lower-case address -> name of another campaign that already emails it."""
    status_names, status_params = in_list("st", list(statuses))
    rows = fetch_all(
        f"""
        SELECT LOWER(r.recipient_email) AS email, c.name AS campaign_name FROM campaign_recipients r
        JOIN campaigns c ON c.id = r.campaign_id
        WHERE c.workspace_id = :ws AND c.id <> :exclude AND r.status IN ({status_names})
          AND r.recipient_email IS NOT NULL
        ORDER BY r.id
        """,
        {"ws": current_workspace(), "exclude": -1 if exclude_campaign_id is None else exclude_campaign_id,
         **status_params},
    )
    found: dict[str, str] = {}
    for row in rows:
        found.setdefault(row["email"], row["campaign_name"])
    return found


def restaurants_with_pending_draft_named(name: str, restaurant_ids: list[int]) -> set[int]:
    if not restaurant_ids:
        return set()
    names, params = in_list("rid", restaurant_ids)
    rows = fetch_all(
        f"SELECT DISTINCT restaurant_id FROM email_drafts "
        f"WHERE campaign = :name AND status = 'draft' AND workspace_id = :ws AND restaurant_id IN ({names})",
        {"name": name, "ws": current_workspace(), **params},
    )
    return {row["restaurant_id"] for row in rows}


def delivery_counts(campaign_id: int) -> dict:
    """Confirmed delivery events and replies for one campaign's sent emails. Unconfirmed means no event yet:
    it is never shown as delivered."""
    row = fetch_one(
        "SELECT COUNT(*) AS sent, "
        "SUM(CASE WHEN delivery_status IS NULL THEN 1 ELSE 0 END) AS unconfirmed, "
        "SUM(CASE WHEN delivery_status = 'delivered' THEN 1 ELSE 0 END) AS delivered, "
        "SUM(CASE WHEN delivery_status = 'deferred' THEN 1 ELSE 0 END) AS deferred, "
        "SUM(CASE WHEN delivery_status = 'bounced_soft' THEN 1 ELSE 0 END) AS bounced_soft, "
        "SUM(CASE WHEN delivery_status = 'bounced_hard' THEN 1 ELSE 0 END) AS bounced_hard, "
        "SUM(CASE WHEN delivery_status = 'rejected' THEN 1 ELSE 0 END) AS rejected, "
        "SUM(CASE WHEN replied_at IS NOT NULL THEN 1 ELSE 0 END) AS replied "
        "FROM campaign_recipients WHERE campaign_id = :cid AND status = 'sent'",
        {"cid": campaign_id},
    )
    return {key: int((row or {}).get(key) or 0) for key in (
        "sent", "unconfirmed", "delivered", "deferred", "bounced_soft", "bounced_hard", "rejected", "replied")}


def recover_interrupted() -> None:
    """Called at startup: anything that was mid-flight when the process stopped is never resent automatically."""
    # A reservation with no recorded outcome means the provider may already have accepted the message.
    execute(
        "UPDATE email_send_ledger SET status = 'uncertain', failure_detail = :note, updated_at = CURRENT_TIMESTAMP "
        "WHERE status = 'reserved'",
        {"note": RESTART_NOTE},
    )
    execute(
        """
        UPDATE campaign_recipients
        SET status = 'interrupted', error_reason = 'Sending was interrupted. Check the provider before retrying.',
            updated_at = CURRENT_TIMESTAMP
        WHERE status = 'sending'
        """
    )
    execute(
        """
        UPDATE campaign_recipients
        SET status = 'draft_failed', error_reason = 'Draft generation was interrupted. Regenerate to try again.',
            updated_at = CURRENT_TIMESTAMP
        WHERE status = 'drafting'
        """
    )
    execute("UPDATE campaigns SET status = 'paused', updated_at = CURRENT_TIMESTAMP WHERE status = 'sending'")
    execute("UPDATE campaigns SET status = 'review', updated_at = CURRENT_TIMESTAMP WHERE status = 'generating'")
