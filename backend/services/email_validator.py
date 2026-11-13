"""Email address checks for restaurant contacts.

What this module does:
- validates syntax and normalises the address (trimmed, lower case);
- checks the mail domain in DNS: an MX record, or (RFC 5321 implicit MX) an A record. A domain that does
  not exist, or has neither record, is invalid. A DNS error is unknown and is never treated as valid;
- classifies the address as business, personal (free webmail), disposable (throwaway provider), or unknown;
- caches DNS answers per domain for a short time, with a timeout on every lookup.

What it does NOT do:
- it never connects to a mail server and never probes a mailbox;
- it never claims that a message will be delivered. "domain_valid" only means the domain accepts mail;
- only a person can set the status "verified", through the manual review endpoint.

Domain lists are maintained by hand in this file. They are not complete. A paid verification provider
could replace them later without changing the statuses.
"""

import json
import re
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from models.database import execute, get_restaurant_by_id
from services.tenancy import current_workspace
from services.website_checker import get_base_domain

# ── Statuses and classifications ─────────────────────────────────────────────

STATUS_INVALID = "invalid"          # bad syntax, no mail domain, or disposable
STATUS_UNVERIFIED = "unverified"    # never checked
STATUS_DOMAIN_VALID = "domain_valid"  # the domain accepts mail (no mailbox check)
STATUS_VERIFIED = "verified"        # a person confirmed the address in manual review
STATUS_UNKNOWN = "unknown"          # the DNS check failed; try again later

CLASS_BUSINESS = "business"
CLASS_PERSONAL = "personal"
CLASS_DISPOSABLE = "disposable"
CLASS_UNKNOWN = "unknown"

MX_NOT_CHECKED = "not_checked"
MX_SKIPPED = "skipped"

# ── Domain lists (maintain by hand; see module docstring) ────────────────────

PERSONAL_DOMAINS = frozenset({
    "gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.uk", "ymail.com", "rocketmail.com",
    "outlook.com", "hotmail.com", "hotmail.co.uk", "live.com", "msn.com", "icloud.com", "me.com",
    "mac.com", "aol.com", "protonmail.com", "proton.me", "pm.me", "gmx.com", "gmx.net", "mail.com",
    "yandex.com", "zoho.com", "rediffmail.com", "qq.com", "163.com",
})

DISPOSABLE_DOMAINS = frozenset({
    "mailinator.com", "guerrillamail.com", "guerrillamail.net", "10minutemail.com", "tempmail.com",
    "temp-mail.org", "yopmail.com", "trashmail.com", "throwawaymail.com", "sharklasers.com",
    "getnada.com", "maildrop.cc", "fakeinbox.com", "mintemail.com", "dispostable.com",
    "mailnesia.com", "mohmal.com", "emailondeck.com", "tempail.com", "burnermail.io", "moakt.com",
})

# ── Syntax ───────────────────────────────────────────────────────────────────

_LOCAL_PART = re.compile(r"^[a-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[a-z0-9!#$%&'*+/=?^_`{|}~-]+)*$")
_DOMAIN_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")
_TOP_LEVEL = re.compile(r"^[a-z]{2,63}$")


def normalize(address) -> str | None:
    """Return the address trimmed and lower-cased, or None when the syntax is not acceptable."""
    if not isinstance(address, str):
        return None
    value = address.strip().lower()
    if len(value) > 254 or value.count("@") != 1:
        return None
    local, domain = value.split("@")
    if not local or len(local) > 64 or not _LOCAL_PART.match(local):
        return None
    labels = domain.split(".")
    if len(labels) < 2 or not all(_DOMAIN_LABEL.match(label) for label in labels):
        return None
    if not _TOP_LEVEL.match(labels[-1]):
        return None
    return f"{local}@{domain}"


# ── DNS (the only network call; isolated so tests can replace it) ────────────

DNS_LIFETIME_SECONDS = 5.0
DNS_TIMEOUT_SECONDS = 2.0
DNS_CACHE_SECONDS = 600.0

_cache: dict[str, tuple[float, tuple[str, str]]] = {}
_cache_lock = threading.Lock()


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _query_dns(domain: str) -> tuple[str, str]:
    """Return (state, detail). State is mx, implicit, none, nxdomain or error."""
    import dns.exception
    import dns.resolver

    resolver = dns.resolver.Resolver(configure=True)
    resolver.lifetime = DNS_LIFETIME_SECONDS
    resolver.timeout = DNS_TIMEOUT_SECONDS
    try:
        answers = resolver.resolve(domain, "MX")
        exchanges = [(record.preference, str(record.exchange)) for record in answers]
        if exchanges == [(0, ".")]:
            return "none", "the domain publishes a null MX record, so it does not accept mail"
        return "mx", f"{len(exchanges)} MX record(s) found"
    except dns.resolver.NXDOMAIN:
        return "nxdomain", "the domain does not exist"
    except dns.resolver.NoAnswer:
        pass
    except dns.exception.DNSException as exc:
        return "error", type(exc).__name__
    try:
        resolver.resolve(domain, "A")
        return "implicit", "no MX record, but the domain has an A record (implicit mail server)"
    except dns.resolver.NXDOMAIN:
        return "nxdomain", "the domain does not exist"
    except dns.resolver.NoAnswer:
        return "none", "the domain has no MX or A record"
    except dns.exception.DNSException as exc:
        return "error", type(exc).__name__


def lookup_mail_domain(domain: str, use_cache: bool = True) -> tuple[str, str]:
    """DNS check, cached per domain. Transient errors are not cached, so the next call retries them.
    use_cache=False asks the network again (used immediately before sending)."""
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(domain) if use_cache else None
        if cached and now - cached[0] < DNS_CACHE_SECONDS:
            return cached[1]
    result = _query_dns(domain)
    if result[0] != "error":
        with _cache_lock:
            _cache[domain] = (now, result)
    return result


# ── Verdicts ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Verdict:
    address: str | None
    status: str
    classification: str
    reasons: tuple[str, ...]
    mx_state: str


def _website_domain(website: str | None) -> str | None:
    if not website:
        return None
    host = urlparse(website).hostname
    return get_base_domain(host) if host else None


def _matches_website(domain: str, website_domain: str | None) -> bool:
    return bool(website_domain) and (domain == website_domain or domain.endswith("." + website_domain))


def verify_address(address, website: str | None = None, lookup=None) -> Verdict:
    """Check one address. Never raises: every outcome is a Verdict."""
    lookup = lookup or lookup_mail_domain
    normalized = normalize(address)
    if normalized is None:
        return Verdict(None, STATUS_INVALID, CLASS_UNKNOWN, ("Not a valid email address format.",), MX_NOT_CHECKED)

    domain = normalized.split("@", 1)[1]
    if domain in DISPOSABLE_DOMAINS:
        return Verdict(normalized, STATUS_INVALID, CLASS_DISPOSABLE,
                       ("Disposable email provider: not accepted for outreach.",), MX_SKIPPED)

    personal = domain in PERSONAL_DOMAINS
    mx_state, detail = lookup(domain)
    reasons: list[str] = []
    if mx_state == "nxdomain" or mx_state == "none":
        status = STATUS_INVALID
        reasons.append(f"Mail domain check failed: {detail}.")
    elif mx_state == "error":
        status = STATUS_UNKNOWN
        reasons.append(f"Mail domain could not be checked ({detail}). Try again later.")
    else:
        status = STATUS_DOMAIN_VALID
        reasons.append("The domain accepts mail (MX record found)." if mx_state == "mx"
                       else "The domain accepts mail (A record, no MX record).")

    if personal:
        classification = CLASS_PERSONAL
        reasons.append("Personal webmail address: flagged for manual review. Not rejected automatically.")
    elif _matches_website(domain, _website_domain(website)):
        classification = CLASS_BUSINESS
        reasons.append("The domain matches the business's website.")
    else:
        classification = CLASS_UNKNOWN
        reasons.append("Custom domain that does not match the business's website. Confirm it belongs to the business.")
    return Verdict(normalized, status, classification, tuple(reasons), mx_state)


# ── Storing results and the outreach gate ────────────────────────────────────

def verify_restaurant_email(restaurant_id: int, *, fresh: bool = False) -> dict | None:
    """Check the stored contact email and save the result, its reasons and the check time.
    fresh=True asks DNS again instead of using the cached answer (used immediately before sending)."""
    restaurant = get_restaurant_by_id(restaurant_id)
    if not restaurant or not restaurant.get("contact_email"):
        return restaurant
    lookup = (lambda domain: lookup_mail_domain(domain, use_cache=False)) if fresh else None
    verdict = verify_address(restaurant["contact_email"], restaurant.get("website"), lookup=lookup)
    status = verdict.status
    decision = restaurant.get("contact_email_review_decision")
    if decision == "rejected":
        status = STATUS_INVALID  # a person rejected this address; automatic checks never overturn that
    elif decision == "approved" and status != STATUS_INVALID:
        status = STATUS_VERIFIED  # a person confirmed this address and it still checks out
    execute(
        """
        UPDATE restaurants SET
            contact_email = :email, contact_email_status = :status,
            contact_email_classification = :classification, contact_email_reasons = :reasons,
            contact_email_mx_state = :mx_state, contact_email_checked_at = CURRENT_TIMESTAMP
        WHERE id = :id AND workspace_id = :ws
        """,
        {"email": verdict.address or restaurant["contact_email"], "status": status,
         "classification": verdict.classification, "reasons": _encode_reasons(verdict.reasons),
         "mx_state": verdict.mx_state, "id": restaurant_id, "ws": current_workspace()},
    )
    return get_restaurant_by_id(restaurant_id)


def _encode_reasons(reasons) -> str:
    return json.dumps(list(reasons))


def gate_reasons(restaurant: dict) -> list[str]:
    """Reasons outreach must not go out, from stored results only. No network."""
    if not restaurant.get("contact_email"):
        return []
    reasons: list[str] = []
    status = restaurant.get("contact_email_status")
    classification = restaurant.get("contact_email_classification")
    if status == STATUS_INVALID:
        stored = " ".join(restaurant.get("contact_email_reasons") or []) or "The address is not usable."
        reasons.append(f"Contact email failed verification. {stored}")
    if classification == CLASS_DISPOSABLE:
        reasons.append("Disposable email address: not accepted for outreach.")
    if classification == CLASS_PERSONAL and not restaurant.get("contact_email_reviewed_at"):
        reasons.append("Personal email address: needs manual review before outreach.")
    return reasons


def ensure_email_gate(restaurant_id: int, *, force: bool = False) -> list[str]:
    """Check the address if it has never been checked (or is unknown, or force is set), then return the gate reasons."""
    restaurant = get_restaurant_by_id(restaurant_id)
    if not restaurant or not restaurant.get("contact_email"):
        return []
    needs_check = (force or not restaurant.get("contact_email_checked_at")
                   or restaurant.get("contact_email_status") in (STATUS_UNVERIFIED, STATUS_UNKNOWN))
    if needs_check:
        restaurant = verify_restaurant_email(restaurant_id, fresh=force) or restaurant
    reasons = gate_reasons(restaurant)
    if restaurant.get("contact_email_status") == STATUS_UNKNOWN:
        reasons.append("Contact email could not be verified because the domain check failed. Check again later.")
    return reasons


def record_review(restaurant_id: int, decision: str, note: str = "") -> dict | None:
    """Save a person's decision. 'approve' sets verified (a person confirmed it); 'reject' sets invalid."""
    if decision == "reject":
        execute(
            "UPDATE restaurants SET contact_email_status = 'invalid', contact_email_review_decision = 'rejected', "
            "contact_email_reviewed_at = CURRENT_TIMESTAMP, contact_email_review_note = :note "
            "WHERE id = :id AND workspace_id = :ws",
            {"note": ("Rejected by manual review. " + note).strip(), "id": restaurant_id, "ws": current_workspace()},
        )
    else:
        execute(
            "UPDATE restaurants SET contact_email_status = 'verified', contact_email_review_decision = 'approved', "
            "contact_email_reviewed_at = CURRENT_TIMESTAMP, contact_email_review_note = :note "
            "WHERE id = :id AND workspace_id = :ws",
            {"note": note.strip() or None, "id": restaurant_id, "ws": current_workspace()},
        )
    return get_restaurant_by_id(restaurant_id)
