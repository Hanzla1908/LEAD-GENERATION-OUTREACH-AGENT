"""Email verification: syntax, DNS and MX evidence, personal and disposable domains, caching, timeouts,
storage, the outreach gates, send-time rechecks and manual review.

No test contacts a DNS server, a mail server or a mailbox. DNS answers are replaced by fakes.
"""
import dns.exception
import dns.resolver
import pytest

from agents.lead_qualifier import compute_score
from models import campaign_store
from models.database import create_draft, execute, fetch_one, get_restaurant_by_id, save_restaurants
from services import email_validator as ev
from services.email_validator import (
    CLASS_BUSINESS, CLASS_DISPOSABLE, CLASS_PERSONAL, CLASS_UNKNOWN,
    STATUS_DOMAIN_VALID, STATUS_INVALID, STATUS_UNKNOWN, STATUS_VERIFIED,
    normalize, verify_address,
)
from tests.test_campaigns import _approve_all, _create, _recipient, _restaurant, _send, client, env  # noqa: F401

# The autouse fixture in conftest.py replaces _query_dns. Keep the real function for the DNS-level tests.
REAL_QUERY_DNS = ev._query_dns


def _set_dns(monkeypatch, answers: dict):
    """Replace the DNS check for named domains. Other domains keep the default mocked MX answer."""
    def fake(domain):
        return answers.get(domain, ("mx", "mocked MX record"))
    monkeypatch.setattr(ev, "_query_dns", fake)
    ev.clear_cache()


# ── Syntax and normalisation ─────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("  Info@KarahiCorner.PK  ", "info@karahicorner.pk"),
    ("owner.name+tag@cafe.com.pk", "owner.name+tag@cafe.com.pk"),
])
def test_valid_syntax_is_normalised(raw, expected):
    assert normalize(raw) == expected


@pytest.mark.parametrize("raw", [
    "", "no-at-sign.pk", "two@@cafe.pk", "space in@cafe.pk", ".leading@cafe.pk", "trailing.@cafe.pk",
    "a..b@cafe.pk", "user@", "@cafe.pk", "user@cafe", "user@cafe.p", "user@-cafe.pk", "user@cafe.pk.",
    "user@cafe_bad.pk", "x" * 65 + "@cafe.pk", None, 12345,
])
def test_invalid_syntax_is_rejected(raw):
    assert normalize(raw) is None


def test_invalid_syntax_verdict_is_invalid_and_never_queries_dns(monkeypatch):
    calls = []
    monkeypatch.setattr(ev, "_query_dns", lambda domain: calls.append(domain) or ("mx", "x"))
    verdict = verify_address("not an email")
    assert verdict.status == STATUS_INVALID
    assert calls == []


# ── Domain DNS evidence (through the real _query_dns with fake resolver answers) ──

class _Answer(list):
    pass


def _fake_resolver(monkeypatch, behaviour: dict):
    """behaviour maps record type -> 'records' | 'nxdomain' | 'nodata' | 'timeout' | 'null-mx'. Records lifetimes."""
    seen = {}

    def resolve(self, domain, rdtype):
        seen["lifetime"] = self.lifetime
        seen["timeout"] = self.timeout
        outcome = behaviour.get(rdtype, "nodata")
        if outcome == "nxdomain":
            raise dns.resolver.NXDOMAIN()
        if outcome == "nodata":
            raise dns.resolver.NoAnswer()
        if outcome == "timeout":
            raise dns.exception.Timeout()
        if outcome == "null-mx":
            return _Answer([_Mx(0, ".")])
        return _Answer([_Mx(10, "mail.cafe.pk.")])

    monkeypatch.setattr(dns.resolver.Resolver, "resolve", resolve)
    return seen


class _Mx:
    def __init__(self, preference, exchange):
        self.preference = preference
        self.exchange = exchange


def test_mx_record_means_the_domain_accepts_mail(monkeypatch):
    _fake_resolver(monkeypatch, {"MX": "records"})
    assert REAL_QUERY_DNS("cafe.pk") == ("mx", "1 MX record(s) found")


def test_missing_mx_with_an_a_record_is_an_implicit_mail_server(monkeypatch):
    _fake_resolver(monkeypatch, {"MX": "nodata", "A": "records"})
    assert REAL_QUERY_DNS("cafe.pk")[0] == "implicit"


def test_missing_mx_and_a_record_means_no_mail_server(monkeypatch):
    _fake_resolver(monkeypatch, {"MX": "nodata", "A": "nodata"})
    assert REAL_QUERY_DNS("cafe.pk")[0] == "none"


def test_nonexistent_domain_is_reported(monkeypatch):
    _fake_resolver(monkeypatch, {"MX": "nxdomain"})
    assert REAL_QUERY_DNS("no-such-domain.example")[0] == "nxdomain"


def test_null_mx_record_means_the_domain_refuses_mail(monkeypatch):
    _fake_resolver(monkeypatch, {"MX": "null-mx"})
    assert REAL_QUERY_DNS("cafe.pk")[0] == "none"


def test_dns_timeout_is_an_error_not_a_negative_answer(monkeypatch):
    _fake_resolver(monkeypatch, {"MX": "timeout"})
    assert REAL_QUERY_DNS("cafe.pk")[0] == "error"


def test_dns_lookups_have_timeouts(monkeypatch):
    seen = _fake_resolver(monkeypatch, {"MX": "records"})
    REAL_QUERY_DNS("cafe.pk")
    assert seen["lifetime"] == ev.DNS_LIFETIME_SECONDS <= 5.0
    assert seen["timeout"] == ev.DNS_TIMEOUT_SECONDS <= 2.0


# ── Verdicts ─────────────────────────────────────────────────────────────────

def test_valid_business_address_matching_the_website(monkeypatch):
    verdict = verify_address("info@karahicorner.pk", "https://www.karahicorner.pk/menu", lookup=lambda d: ("mx", "ok"))
    assert verdict.status == STATUS_DOMAIN_VALID
    assert verdict.classification == CLASS_BUSINESS
    assert verdict.address == "info@karahicorner.pk"


def test_custom_domain_not_matching_the_website_is_unclassified_but_accepts_mail():
    verdict = verify_address("owner@agency.example.pk", "https://karahicorner.pk/", lookup=lambda d: ("mx", "ok"))
    assert verdict.status == STATUS_DOMAIN_VALID
    assert verdict.classification == CLASS_UNKNOWN
    assert any("does not match" in reason for reason in verdict.reasons)


@pytest.mark.parametrize("address", ["owner@gmail.com", "owner@hotmail.com", "owner@outlook.com", "owner@yahoo.com"])
def test_personal_webmail_is_flagged_for_review_not_rejected(address):
    verdict = verify_address(address, "https://karahicorner.pk/", lookup=lambda d: ("mx", "ok"))
    assert verdict.classification == CLASS_PERSONAL
    assert verdict.status == STATUS_DOMAIN_VALID  # not rejected automatically
    assert any("manual review" in reason for reason in verdict.reasons)


def test_missing_mx_record_makes_the_address_invalid():
    verdict = verify_address("info@dead-domain.pk", lookup=lambda d: ("none", "the domain has no MX or A record"))
    assert verdict.status == STATUS_INVALID
    assert any("no MX or A record" in reason for reason in verdict.reasons)


def test_nonexistent_domain_makes_the_address_invalid():
    verdict = verify_address("info@nowhere.example", lookup=lambda d: ("nxdomain", "the domain does not exist"))
    assert verdict.status == STATUS_INVALID


@pytest.mark.parametrize("address", ["x@mailinator.com", "x@yopmail.com", "x@10minutemail.com"])
def test_disposable_domains_are_invalid_and_never_checked_in_dns(address):
    calls = []
    verdict = verify_address(address, lookup=lambda d: calls.append(d) or ("mx", "ok"))
    assert verdict.status == STATUS_INVALID
    assert verdict.classification == CLASS_DISPOSABLE
    assert calls == []


def test_dns_failure_is_unknown_not_valid():
    verdict = verify_address("info@cafe.pk", lookup=lambda d: ("error", "Timeout"))
    assert verdict.status == STATUS_UNKNOWN
    assert verdict.classification == CLASS_UNKNOWN
    assert any("Try again later" in reason for reason in verdict.reasons)


def test_transient_dns_errors_are_not_cached(monkeypatch):
    calls = {"n": 0}

    def flaky(domain):
        calls["n"] += 1
        return ("error", "Timeout") if calls["n"] == 1 else ("mx", "ok")

    monkeypatch.setattr(ev, "_query_dns", flaky)
    ev.clear_cache()
    assert ev.lookup_mail_domain("cafe.pk")[0] == "error"
    assert ev.lookup_mail_domain("cafe.pk")[0] == "mx"
    assert calls["n"] == 2


def test_dns_answers_are_cached_per_domain(monkeypatch):
    calls = {"n": 0}

    def counting(domain):
        calls["n"] += 1
        return ("mx", "ok")

    monkeypatch.setattr(ev, "_query_dns", counting)
    ev.clear_cache()
    for _ in range(5):
        ev.lookup_mail_domain("cafe.pk")
    assert calls["n"] == 1
    ev.lookup_mail_domain("cafe.pk", use_cache=False)
    assert calls["n"] == 2


# ── Storage ──────────────────────────────────────────────────────────────────

def test_verification_is_stored_with_status_reasons_and_check_time(test_db, monkeypatch):
    _set_dns(monkeypatch, {"karahicorner.pk": ("mx", "ok")})
    rid = _restaurant("Stored Check", email="  Info@KarahiCorner.pk ")
    execute("UPDATE restaurants SET website = :w WHERE id = :id", {"w": "https://karahicorner.pk/", "id": rid})
    stored = ev.verify_restaurant_email(rid)
    assert stored["contact_email"] == "info@karahicorner.pk"  # normalised
    assert stored["contact_email_status"] == STATUS_DOMAIN_VALID
    assert stored["contact_email_classification"] == CLASS_BUSINESS
    assert stored["contact_email_mx_state"] == "mx"
    assert stored["contact_email_checked_at"]
    assert isinstance(stored["contact_email_reasons"], list) and stored["contact_email_reasons"]


def test_changing_the_contact_address_clears_earlier_review_and_classification(test_db, monkeypatch):
    rid = _restaurant("Changed Email", email="owner@gmail.com")
    ev.verify_restaurant_email(rid)
    ev.record_review(rid, "approve", "checked by phone")
    from models.database import update_contact_result
    update_contact_result(rid, {"emails": [{"email": "info@cafe.pk", "source_url": "https://cafe.pk/",
                                            "status": "unverified"}]})
    after = get_restaurant_by_id(rid)
    assert after["contact_email_reviewed_at"] is None
    assert after["contact_email_review_decision"] is None
    assert after["contact_email_classification"] is None
    assert after["contact_email_checked_at"] is None


# ── Outreach gates ───────────────────────────────────────────────────────────

def test_personal_address_is_ineligible_until_a_person_reviews_it(client, env):
    rid = _restaurant("Personal Cafe", email="owner.cafe@gmail.com")
    ev.verify_restaurant_email(rid)
    preview = client.post("/campaigns/preview", json={"name": "Personal", "restaurant_ids": [rid]}).json()
    assert preview["eligible_count"] == 0
    assert any("manual review" in reason for reason in preview["items"][0]["reasons"])

    reviewed = client.post(f"/restaurants/{rid}/email-review", json={"decision": "approve", "note": "Owner confirmed"})
    assert reviewed.status_code == 200
    assert reviewed.json()["contact_email_status"] == STATUS_VERIFIED
    assert reviewed.json()["contact_email_review_decision"] == "approved"
    preview = client.post("/campaigns/preview", json={"name": "Personal", "restaurant_ids": [rid]}).json()
    assert preview["eligible_count"] == 1


def test_disposable_address_cannot_get_a_draft(client, env):
    rid = _restaurant("Disposable Cafe", email="throwaway@mailinator.com")
    client.post(f"/restaurants/{rid}/verify-email")
    resp = client.post("/outreach/generate", json={"restaurant_id": rid})
    assert resp.status_code == 422  # refused: the stored check marked it invalid (and disposable)
    assert "invalid" in resp.json()["detail"].lower() or "disposable" in resp.json()["detail"].lower()


def test_invalid_address_cannot_be_approved(client, env, monkeypatch):
    _set_dns(monkeypatch, {"dead-domain.pk": ("none", "the domain has no MX or A record")})
    rid = _restaurant("Dead Domain Cafe", email="info@dead-domain.pk")
    draft = create_draft(restaurant_id=rid, campaign="Approval", subject="Hi", body="Body", angle=None)
    resp = client.post(f"/outreach/drafts/{draft['id']}/approve")
    assert resp.status_code == 422
    assert "no MX or A record" in resp.json()["detail"]
    assert client.get(f"/outreach/drafts/{draft['id']}").json()["status"] == "draft"


def test_unknown_result_blocks_approval_until_checked_again(client, env, monkeypatch):
    _set_dns(monkeypatch, {"flaky.pk": ("error", "Timeout")})
    rid = _restaurant("Flaky Cafe", email="info@flaky.pk")
    draft = create_draft(restaurant_id=rid, campaign="Unknown", subject="Hi", body="Body", angle=None)
    resp = client.post(f"/outreach/drafts/{draft['id']}/approve")
    assert resp.status_code == 422
    assert "could not be verified" in resp.json()["detail"]


def test_manual_rejection_is_never_overturned_by_an_automatic_check(client, env, monkeypatch):
    rid = _restaurant("Rejected Cafe", email="info@rejected-cafe.pk")
    client.post(f"/restaurants/{rid}/email-review", json={"decision": "reject", "note": "wrong business"})
    rejected = get_restaurant_by_id(rid)
    assert rejected["contact_email_status"] == STATUS_INVALID
    ev.verify_restaurant_email(rid)  # the domain is fine, but the decision stands
    assert get_restaurant_by_id(rid)["contact_email_status"] == STATUS_INVALID


def test_approving_an_invalid_address_is_refused(client, env, monkeypatch):
    _set_dns(monkeypatch, {"gone.pk": ("nxdomain", "the domain does not exist")})
    rid = _restaurant("Gone Cafe", email="info@gone.pk")
    resp = client.post(f"/restaurants/{rid}/email-review", json={"decision": "approve"})
    assert resp.status_code == 422
    assert get_restaurant_by_id(rid)["contact_email_review_decision"] is None


def test_verify_endpoint_refuses_a_restaurant_without_an_email(client, env):
    rid = save_restaurants([{"place_id": "no-email-verify", "name": "No Email Verify", "source": "google_places"}])[0]["id"]
    assert client.post(f"/restaurants/{rid}/verify-email").status_code == 422
    assert client.post("/restaurants/999999/verify-email").status_code == 404


def test_review_decision_must_be_approve_or_reject(client, env):
    rid = _restaurant("Bad Decision", email="info@bad-decision.pk")
    assert client.post(f"/restaurants/{rid}/email-review", json={"decision": "maybe"}).status_code == 422


# ── Send-time recheck ────────────────────────────────────────────────────────

def test_domain_that_stops_accepting_mail_blocks_the_send(client, env, monkeypatch):
    rid = _restaurant("Recheck Cafe", email="info@recheck-cafe.pk")
    detail = _create(client, "Recheck", [rid]).json()
    _approve_all(client, detail)  # approved while the domain still accepted mail
    _set_dns(monkeypatch, {"recheck-cafe.pk": ("nxdomain", "the domain does not exist")})
    result = _send(client, detail["id"]).json()
    row = _recipient(result, rid)
    assert row["status"] == "skipped"
    assert "Mail domain check failed" in row["skip_reason"]
    assert env["sender"].outbox == []


def test_send_time_check_ignores_a_cached_answer(client, env, monkeypatch):
    rid = _restaurant("Cached Then Gone", email="info@cached-gone.pk")
    detail = _create(client, "Cached gone", [rid]).json()
    _approve_all(client, detail)
    assert ev.lookup_mail_domain("cached-gone.pk") == ("mx", "mocked MX record")  # cache now holds 'accepts mail'
    # The domain stops accepting mail. The cache still says otherwise, so only a fresh check can catch it.
    monkeypatch.setattr(ev, "_query_dns", lambda domain: ("nxdomain", "the domain does not exist"))
    result = _send(client, detail["id"]).json()
    assert _recipient(result, rid)["status"] == "skipped"
    assert env["sender"].outbox == []


# ── Lead quality ─────────────────────────────────────────────────────────────

def test_an_invalid_email_does_not_earn_email_points():
    base = {"website_status": "present", "ordering_status": "not_found", "phone": "+92 300 0000000"}
    usable_score, usable = compute_score({**base, "contact_email": "info@cafe.pk", "contact_email_status": "domain_valid"})
    invalid_score, invalid = compute_score({**base, "contact_email": "x@bad.pk", "contact_email_status": "invalid"})
    disposable_score, _ = compute_score({**base, "contact_email": "x@mailinator.com",
                                         "contact_email_status": "invalid", "contact_email_classification": "disposable"})
    assert "email_found" in usable and "email_found" not in invalid
    assert usable_score - invalid_score == 25
    assert disposable_score == invalid_score
