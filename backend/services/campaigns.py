import asyncio
import json
import os
import re
import threading
import time

from models import campaign_store as store
from models.database import create_draft, get_draft, get_restaurant_by_id
from services.email_sender import SendError, SendOutcomeUnknown, get_sender, provider_name
from services.email_validator import ensure_email_gate
from services.outreach import generate_draft
from services.tenancy import current_workspace_or_none, workspace_scope
from services.unsubscribe import is_local_address, unsubscribe_settings, unsubscribe_url

PLACEHOLDER_DOMAINS = {
    "example.com", "example.org", "example.net", "test.com", "domain.com", "email.com", "localhost",
}
EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")

_sleep = time.sleep
_active_workers: set[int] = set()
_workers_lock = threading.Lock()
# Held for the whole "check limit, claim, check eligibility, send, record" step, so two campaign
# workers in this process cannot both pass the daily limit or send to the same address.
_SEND_LOCK = threading.Lock()


def per_minute_limit() -> int:
    return int(os.getenv("EMAIL_PER_MINUTE", "5"))


def daily_limit() -> int:
    return int(os.getenv("EMAIL_DAILY_LIMIT", "100"))


def is_valid_business_email(email: str | None) -> bool:
    if not email or not EMAIL_PATTERN.match(email):
        return False
    return email.rsplit("@", 1)[1].lower() not in PLACEHOLDER_DOMAINS


def outreach_reasons(restaurant: dict, suppressed: set[str]) -> list[str]:
    reasons = []
    if restaurant.get("source") != "google_places":
        reasons.append("Demo or sample record, not a real business")
    if restaurant.get("listing_expired"):
        reasons.append("Google listing expired; search again to refresh it before emailing")
    if restaurant.get("opted_out"):
        reasons.append("Business has opted out of outreach")
    email = restaurant.get("contact_email")
    if not email:
        reasons.append("No public email found")
    elif restaurant.get("contact_email_status") == "invalid":
        reasons.append("Contact email is marked invalid")
    elif not is_valid_business_email(email):
        reasons.append("Email is not a valid business address")
    elif email.lower() in suppressed:
        reasons.append("Email is on the suppression list")
    if email and restaurant.get("contact_email_classification") == "disposable":
        reasons.append("Disposable email address: not accepted for outreach")
    if email and restaurant.get("contact_email_classification") == "personal" and not restaurant.get("contact_email_reviewed_at"):
        reasons.append("Personal email address: needs manual review before outreach")
    if restaurant.get("lead_status") != "qualified":
        status = restaurant.get("lead_status") or "new"
        reasons.append(f"Not qualified (current status: {status})")
    return reasons


def preview(name: str, restaurant_ids: list[int]) -> dict:
    suppressed = store.suppressed_emails()
    already_sent = store.restaurants_in_campaign_named(name, restaurant_ids)
    pending_drafts = store.restaurants_with_pending_draft_named(name, restaurant_ids)
    emails_sent = store.emails_in_campaign_named(name)
    # Workspace-wide: a restaurant or address already emailed by any other campaign is not emailed again.
    contacted_restaurants = store.restaurants_contacted(restaurant_ids)
    contacted_emails = store.emails_contacted()
    seen_emails: set[str] = set()
    items = []
    for rid in restaurant_ids:
        restaurant = get_restaurant_by_id(rid)
        if restaurant is None:
            items.append({"restaurant_id": rid, "restaurant_name": None, "email": None,
                          "eligible": False, "reasons": ["Business not found"]})
            continue
        reasons = outreach_reasons(restaurant, suppressed)
        if rid in already_sent:
            reasons.append(f'Already emailed in campaign "{name}"')
        elif rid in contacted_restaurants:
            reasons.append(f'Already emailed in campaign "{contacted_restaurants[rid]}"')
        if rid in pending_drafts:
            reasons.append(f'Already has a pending draft in campaign "{name}"')
        email_key = (restaurant.get("contact_email") or "").strip().lower()
        if email_key and email_key in emails_sent:
            reasons.append(f'This address already received campaign "{name}"')
        elif email_key and email_key in contacted_emails:
            reasons.append(f'This address already received campaign "{contacted_emails[email_key]}"')
        elif email_key and email_key in seen_emails:
            reasons.append("Another business in this selection uses the same address")
        if not reasons and email_key:
            seen_emails.add(email_key)
        items.append({
            "restaurant_id": rid,
            "restaurant_name": restaurant["name"],
            "email": restaurant.get("contact_email"),
            "eligible": not reasons,
            "reasons": reasons,
        })
    eligible = sum(1 for i in items if i["eligible"])
    return {"eligible_count": eligible, "skipped_count": len(items) - eligible, "items": items}


def create_campaign(name: str, restaurant_ids: list[int], created_by_user_id: int | None = None) -> dict:
    plan = preview(name, restaurant_ids)
    if plan["eligible_count"] == 0:
        raise ValueError("None of the selected businesses are eligible for this campaign.")
    campaign_id = store.create_campaign(name, created_by_user_id)
    for item in plan["items"]:
        if item["eligible"]:
            store.insert_recipient(campaign_id, item["restaurant_id"], item["email"], "drafting")
        else:
            store.insert_recipient(campaign_id, item["restaurant_id"], item["email"], "skipped",
                                   "; ".join(item["reasons"]))
    _spawn(run_draft_generation, campaign_id)
    return campaign_detail(campaign_id)


def run_draft_generation(campaign_id: int) -> None:
    campaign = store.get_campaign(campaign_id)
    for row in store.list_recipients(campaign_id):
        if store.get_campaign_status(campaign_id) == "cancelled":
            break
        if row["status"] != "drafting":
            continue
        restaurant = get_restaurant_by_id(row["restaurant_id"])
        try:
            data = asyncio.run(generate_draft(restaurant))
            draft = create_draft(
                restaurant_id=row["restaurant_id"],
                campaign=campaign["name"],
                subject=data["subject"],
                body=data["body"],
                angle=data.get("angle"),
                campaign_id=campaign_id,
            )
            store.update_recipient(row["id"], status="draft", draft_id=draft["id"])
        except Exception as exc:
            store.update_recipient(row["id"], status="draft_failed", error_reason=str(exc)[:300])
    if store.get_campaign_status(campaign_id) == "generating":
        store.set_campaign_status(campaign_id, "review")


def approved_draft_ids(campaign: dict) -> set[int]:
    raw = campaign.get("approved_draft_ids")
    return set(json.loads(raw)) if raw else set()


def approve_sending(campaign_id: int, draft_ids: list[int]) -> dict:
    campaign = _require_campaign(campaign_id)
    if campaign["status"] not in {"review", "paused", "completed"}:
        raise ValueError(
            f"Campaign is '{campaign['status']}'; sending can be approved only when it is ready for review."
        )
    ready = {
        r["draft_id"]: r for r in store.list_recipients(campaign_id)
        if r["status"] == "draft" and r["draft_status"] == "approved"
    }
    requested = set(draft_ids)
    if not requested:
        raise ValueError("Select at least one approved draft.")
    if not requested <= set(ready):
        raise ValueError("Some drafts are not approved for this campaign. Refresh the page and try again.")
    merged = sorted(approved_draft_ids(campaign) | requested)
    store.set_campaign_approval(campaign_id, json.dumps(merged))
    for draft_id in sorted(requested):
        store.add_log(campaign_id, "approved", f"Draft {draft_id} approved for sending", recipient=ready[draft_id])
    return campaign_detail(campaign_id)


def start_sending(campaign_id: int, retry_failed: bool = False) -> dict:
    campaign = store.get_campaign(campaign_id)
    if campaign is None:
        raise LookupError("Campaign not found.")
    if campaign["status"] not in {"review", "paused", "completed"}:
        raise ValueError(f"Campaign is '{campaign['status']}' and cannot be sent right now.")
    sender = get_sender()
    # A live provider must put a real postal address in every email (marketing law). Mock sending needs none.
    if getattr(sender, "name", "mock") != "mock" and not sender_address():
        raise ValueError("Set SENDER_ADDRESS (your business name and postal address) in .env before live sending.")
    check = getattr(sender, "check", None)
    if check is not None:
        check()
    settings = unsubscribe_settings()
    if settings is None:
        raise ValueError("Set UNSUBSCRIBE_SECRET and PUBLIC_BASE_URL in .env before sending.")
    # Live mail must carry links that work for real recipients. Mock sending may use a local address.
    if getattr(sender, "name", "mock") != "mock" and is_local_address(settings[1]):
        raise ValueError("PUBLIC_BASE_URL points to localhost, so recipients could not open unsubscribe links. "
                         "Set it to your public app address before live sending.")

    recipients = store.list_recipients(campaign_id)
    ready = [r for r in recipients if r["status"] == "draft" and r["draft_status"] == "approved"]
    queued = [r for r in recipients if r["status"] == "queued"]
    failed = [r for r in recipients if r["status"] == "failed" and r["provider_message_id"] is None]
    if retry_failed and not failed:
        raise ValueError("There are no failed emails to retry.")
    if not ready and not queued and not (retry_failed and failed):
        raise ValueError("No approved drafts are waiting to be sent.")

    required = {r["draft_id"] for r in ready + queued + (failed if retry_failed else [])}
    missing = required - approved_draft_ids(campaign)
    if missing:
        raise ValueError(
            f"Approve sending for {len(missing)} draft(s) first. Review the recipients and confirm again."
        )

    if retry_failed:
        store.requeue_failed(campaign_id)
    store.promote_approved_drafts(campaign_id)
    _queue_checks(campaign_id)
    if not _has_queued(campaign_id):
        store.set_campaign_status(campaign_id, "completed", "No approved emails remained after eligibility checks")
        store.add_log(campaign_id, "completed", "No approved emails remained after eligibility checks")
        return campaign_detail(campaign_id)
    store.set_campaign_status(campaign_id, "sending")
    store.add_log(campaign_id, "send_started", "Sending started")
    _spawn_worker(campaign_id)
    return campaign_detail(campaign_id)


def _queue_checks(campaign_id: int) -> None:
    campaign = store.get_campaign(campaign_id)
    suppressed = store.suppressed_emails()
    sent = store.sent_addresses(campaign_id)
    approved = approved_draft_ids(campaign)
    for row in store.list_recipients(campaign_id):
        if row["status"] != "queued":
            continue
        reasons = _send_reasons(row, suppressed, approved, sent)
        if reasons:
            store.update_recipient(row["id"], status="skipped", skip_reason="; ".join(reasons))


def _has_queued(campaign_id: int) -> bool:
    return any(r["status"] == "queued" for r in store.list_recipients(campaign_id))


def pause_sending(campaign_id: int) -> dict:
    campaign = _require_campaign(campaign_id)
    if campaign["status"] != "sending":
        raise ValueError("Only a sending campaign can be paused.")
    store.set_campaign_status(campaign_id, "paused", "Paused by user")
    store.add_log(campaign_id, "paused", "Paused by user")
    return campaign_detail(campaign_id)


def cancel_campaign(campaign_id: int) -> dict:
    campaign = _require_campaign(campaign_id)
    if campaign["status"] in {"completed", "cancelled"}:
        raise ValueError(f"Campaign is already {campaign['status']}.")
    store.cancel_queued(campaign_id)
    store.set_campaign_status(campaign_id, "cancelled", "Cancelled by user; queued emails were not sent")
    store.add_log(campaign_id, "cancelled", "Cancelled by user; queued emails were not sent")
    return campaign_detail(campaign_id)


def _require_campaign(campaign_id: int) -> dict:
    campaign = store.get_campaign(campaign_id)
    if campaign is None:
        raise LookupError("Campaign not found.")
    return campaign


def _spawn(target, *args) -> None:
    """Run target in a background thread, inside the workspace that started it.

    Threads do not inherit the request's context, so the workspace is captured here and re-entered in the
    thread. Without this, the worker's queries would have no workspace and would fail closed.
    """
    workspace = current_workspace_or_none()

    def run() -> None:
        with workspace_scope(workspace):
            target(*args)

    threading.Thread(target=run, daemon=True).start()


def _spawn_worker(campaign_id: int) -> None:
    with _workers_lock:
        if campaign_id in _active_workers:
            return
        _active_workers.add(campaign_id)
    _spawn(_run_worker, campaign_id)


def _run_worker(campaign_id: int) -> None:
    finished = False
    try:
        process_queue(campaign_id)
        finished = True
    except Exception as exc:
        note = f"Sending stopped unexpectedly: {exc}"[:300]
        store.set_campaign_status(campaign_id, "paused", note)
        store.add_log(campaign_id, "paused", note)
    finally:
        with _workers_lock:
            _active_workers.discard(campaign_id)
    if finished and store.get_campaign_status(campaign_id) == "sending":
        _spawn_worker(campaign_id)


def _send_reasons(row: dict, suppressed: set[str], approved_ids: set[int], sent: set[str]) -> list[str]:
    restaurant = get_restaurant_by_id(row["restaurant_id"])
    if restaurant is None:
        return ["Business record missing"]
    reasons = outreach_reasons(restaurant, suppressed)
    draft = get_draft(row["draft_id"]) if row["draft_id"] else None
    if draft is None or draft["status"] != "approved":
        reasons.append("Draft is not approved")
    if row["draft_id"] not in approved_ids:
        reasons.append("Draft was not approved for sending in this campaign")
    if (restaurant.get("contact_email") or "").strip().lower() != (row["recipient_email"] or "").strip().lower():
        reasons.append("Recipient email changed after the draft was created")
    address = (row["recipient_email"] or "").strip().lower()
    if address and address in sent:
        reasons.append("This address already received an outreach email; it is not sent again")
    # Workspace-wide: nothing is sent to an address or restaurant that another campaign in this workspace has sent.
    elsewhere_emails = store.emails_contacted(
        exclude_campaign_id=row["campaign_id"], statuses=store.SEND_CONTACT_STATUSES)
    if address and address not in sent and address in elsewhere_emails:
        reasons.append(f'This address already received campaign "{elsewhere_emails[address]}"; it is not sent again')
    elsewhere_restaurants = store.restaurants_contacted(
        [row["restaurant_id"]], exclude_campaign_id=row["campaign_id"], statuses=store.SEND_CONTACT_STATUSES)
    other_campaign = elsewhere_restaurants.get(row["restaurant_id"])
    if other_campaign:
        reasons.append(f'This business was already emailed in campaign "{other_campaign}"; it is not sent again')
    # Re-checked immediately before sending: a domain that stopped accepting mail blocks this send.
    reasons.extend(r for r in ensure_email_gate(restaurant["id"], force=True) if r not in reasons)
    return reasons


def process_queue(campaign_id: int) -> None:
    try:
        sender = get_sender()
    except SendError as exc:
        store.set_campaign_status(campaign_id, "paused", str(exc))
        return
    while True:
        with _SEND_LOCK:
            campaign = store.get_campaign(campaign_id)
            if campaign is None or campaign["status"] != "sending":
                return
            if store.sent_today_count() >= daily_limit():
                note = f"Daily sending limit of {daily_limit()} reached. Resume tomorrow or raise EMAIL_DAILY_LIMIT."
                store.set_campaign_status(campaign_id, "paused", note)
                store.add_log(campaign_id, "paused", note)
                return
            row = store.claim_next_queued(campaign_id)
            if row is None:
                store.set_campaign_status(campaign_id, "completed")
                store.add_log(campaign_id, "completed", "All queued emails were processed")
                return
            _send_one(campaign_id, row, sender, approved_draft_ids(campaign))
            outcome = store.get_recipient(row["id"])
        detail = outcome["error_reason"] or outcome["skip_reason"] or outcome["provider_message_id"]
        store.add_log(campaign_id, outcome["status"], detail, recipient=outcome)
        rate = per_minute_limit()
        if rate > 0:
            _sleep(60 / rate)


def _send_one(campaign_id: int, row: dict, sender, approved_ids: set[int]) -> None:
    # Eligibility is evaluated again here, immediately before the provider is called.
    reasons = _send_reasons(row, store.suppressed_emails(), approved_ids, store.sent_addresses(campaign_id))
    if reasons:
        store.update_recipient(row["id"], status="skipped", skip_reason="; ".join(reasons))
        return
    draft = get_draft(row["draft_id"])
    settings = unsubscribe_settings()
    if settings is None:
        store.update_recipient(row["id"], status="failed", error_reason="Unsubscribe settings are missing; nothing was sent.")
        return
    secret, base_url = settings

    # Persistent ledger: reserve this recipient in the database BEFORE the provider is called.
    reserved, state = store.reserve_send(campaign_id, row)
    if not reserved:
        if state == store.LEDGER_SENT:
            # Already delivered earlier (for example before a restart). Record it, never send again.
            ledger = store.ledger_for(campaign_id, row["id"])
            store.mark_sent(row["id"], ledger["provider_message_id"] if ledger else None)
            return
        store.update_recipient(
            row["id"], status="interrupted",
            error_reason=f"Blocked from automatic sending (ledger status: {state}). {store.BLOCKED_NOTE}",
        )
        return

    link = unsubscribe_url(secret, base_url, row["id"])
    try:
        message_id = sender.send(
            to=row["recipient_email"],
            subject=draft["subject"],
            body=draft["body"] + _footer(link),
            idempotency_key=store.ledger_key(campaign_id, row["id"]),
            unsubscribe_url=link,
        )
    except SendError as exc:
        # The provider refused the message, so nothing was sent and a retry is allowed.
        store.record_send_failure(campaign_id, row["id"], str(exc)[:300])
        return
    except Exception as exc:
        store.record_send_uncertain(
            campaign_id, row["id"],
            f"Send outcome unknown ({str(exc)[:200]}). Check the provider before retrying.",
        )
        return
    try:
        store.record_send_success(campaign_id, row["id"], message_id)
    except Exception as exc:
        store.record_send_uncertain(
            campaign_id, row["id"],
            f"Delivered but not recorded ({str(exc)[:200]}). Do not resend.",
            message_id=message_id,
        )


def _footer(unsubscribe_link: str) -> str:
    lines = [
        "",
        "--",
        "You are receiving this because your business is listed publicly online.",
        f"To stop receiving these emails, open this link: {unsubscribe_link}",
    ]
    address = sender_address()
    if address:
        lines.append(address)
    return "\n".join(lines)


def sender_address() -> str:
    """The sender's postal address, printed in every live email. Read from SENDER_ADDRESS."""
    return os.getenv("SENDER_ADDRESS", "").strip()


def retry_failed(campaign_id: int) -> dict:
    return start_sending(campaign_id, retry_failed=True)


def retry_failed_drafts(campaign_id: int) -> dict:
    campaign = _require_campaign(campaign_id)
    if campaign["status"] not in {"review", "completed"}:
        raise ValueError(f"Campaign is '{campaign['status']}'; drafts can be retried once it is ready for review.")
    suppressed = store.suppressed_emails()
    retried = 0
    for row in store.list_recipients(campaign_id):
        if row["status"] != "draft_failed":
            continue
        restaurant = get_restaurant_by_id(row["restaurant_id"])
        reasons = outreach_reasons(restaurant, suppressed) if restaurant else ["Business record missing"]
        if reasons:
            store.update_recipient(row["id"], status="skipped", skip_reason="; ".join(reasons), error_reason=None)
        else:
            store.update_recipient(row["id"], status="drafting", error_reason=None)
            retried += 1
    if retried == 0:
        raise ValueError("There are no failed drafts to retry.")
    store.set_campaign_status(campaign_id, "generating")
    _spawn(run_draft_generation, campaign_id)
    return campaign_detail(campaign_id)


def summarize(recipients: list[dict]) -> dict:
    def count(predicate) -> int:
        return sum(1 for r in recipients if predicate(r))

    skipped = count(lambda r: r["status"] == "skipped")
    return {
        "total_selected": len(recipients),
        "eligible": len(recipients) - skipped,
        "drafts_generated": count(lambda r: r["draft_id"] is not None),
        "drafts_failed": count(lambda r: r["status"] == "draft_failed"),
        "approved": count(lambda r: r["draft_status"] == "approved"),
        "queued": count(lambda r: r["status"] == "queued"),
        "sent": count(lambda r: r["status"] == "sent"),
        "failed": count(lambda r: r["status"] in {"failed", "interrupted"}),
        "retryable": count(lambda r: r["status"] == "failed" and r["provider_message_id"] is None),
        "interrupted": count(lambda r: r["status"] == "interrupted"),
        "skipped": skipped,
        "cancelled": count(lambda r: r["status"] == "cancelled"),
    }


def campaign_detail(campaign_id: int) -> dict:
    campaign = _require_campaign(campaign_id)
    recipients = store.list_recipients(campaign_id)
    return {
        **campaign,
        "counts": summarize(recipients),
        "delivery": store.delivery_counts(campaign_id),
        "recipients": recipients,
        "provider": provider_name(),
        "live_sending": provider_name() != "mock",
    }


_EMPTY_COUNTS = {
    "total": 0, "skipped": 0, "drafts_generated": 0, "drafts_failed": 0, "approved": 0,
    "queued": 0, "sent": 0, "failed": 0, "retryable": 0, "interrupted": 0, "cancelled": 0,
}


def _counts_from_aggregate(raw: dict) -> dict:
    """Maps the grouped SQL counters to the same keys summarize() returns."""
    row = {**_EMPTY_COUNTS, **raw}
    return {
        "total_selected": row["total"],
        "eligible": row["total"] - row["skipped"],
        "drafts_generated": row["drafts_generated"],
        "drafts_failed": row["drafts_failed"],
        "approved": row["approved"],
        "queued": row["queued"],
        "sent": row["sent"],
        "failed": row["failed"],
        "retryable": row["retryable"],
        "interrupted": row["interrupted"],
        "skipped": row["skipped"],
        "cancelled": row["cancelled"],
    }


def campaign_list() -> list[dict]:
    # One grouped query for all campaigns, instead of loading every recipient row per campaign.
    aggregates = store.recipient_counts_by_campaign()
    return [
        {**campaign, "counts": _counts_from_aggregate(aggregates.get(campaign["id"], {}))}
        for campaign in store.list_campaigns()
    ]


def sending_config() -> dict:
    return {
        "provider": provider_name(),
        "live_sending": provider_name() != "mock",
        "per_minute": per_minute_limit(),
        "daily_limit": daily_limit(),
        "sent_today": store.sent_today_count(),
        "unsubscribe_ready": unsubscribe_settings() is not None,
    }


def recover_after_restart() -> None:
    store.recover_interrupted()
