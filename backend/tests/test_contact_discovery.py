"""
Tests for services/contact_discovery.py.
All HTTP is mocked — no live network calls.
"""

import socket
from unittest.mock import AsyncMock, patch

import pytest

from services.contact_discovery import (
    discover_contact_emails,
    extract_emails_from_html,
    _clean,
)


# ── unit: email extraction ──────────────────────────────────────────────────


def test_extract_mailto_link():
    html = b'<a href="mailto:info@pizza.com">Contact us</a>'
    assert "info@pizza.com" in extract_emails_from_html(html)


def test_extract_email_from_text():
    html = b"<p>Reach us at hello@restaurant.com for bookings.</p>"
    assert "hello@restaurant.com" in extract_emails_from_html(html)


def test_extract_deduplicates():
    html = b"<p>info@place.com and also info@place.com</p>"
    emails = extract_emails_from_html(html)
    assert emails.count("info@place.com") == 1


def test_extract_normalises_to_lowercase():
    html = b"<p>INFO@Restaurant.COM</p>"
    emails = extract_emails_from_html(html)
    assert "info@restaurant.com" in emails


def test_extract_excludes_example_domain():
    html = b"<p>admin@example.com is a placeholder</p>"
    assert extract_emails_from_html(html) == []


def test_extract_excludes_asset_extension():
    html = b"<p>icon@2x.png is not an email</p>"
    # .png domain should be filtered
    emails = extract_emails_from_html(html)
    assert not any(".png" in e for e in emails)


def test_extract_ignores_script_content():
    html = b"<script>var x = 'hidden@secret.com';</script><p>real@cafe.com</p>"
    emails = extract_emails_from_html(html)
    # script content stripped; real visible email should still be found
    assert "real@cafe.com" in emails


def test_extract_no_emails():
    html = b"<html><body><p>No contact info here.</p></body></html>"
    assert extract_emails_from_html(html) == []


# ── unit: _clean ────────────────────────────────────────────────────────────


def test_clean_removes_duplicates():
    result = _clean(["info@a.com", "INFO@A.COM", "info@a.com"])
    assert result == ["info@a.com"]


def test_clean_removes_excluded_domain():
    result = _clean(["test@sentry.io"])
    assert result == []


# ── integration: discover_contact_emails ────────────────────────────────────


def _patch_blocked(blocked: bool):
    return patch("services.contact_discovery.is_blocked_ip", return_value=blocked)


def _patch_robots(allowed: bool):
    return patch("services.contact_discovery.check_robots", new=AsyncMock(return_value=allowed))


def _patch_fetch(pages: dict[str, tuple[int, bytes, str]]):
    """pages: {exact_url: (status, body, final_url)} — longest match wins."""
    async def _fake_fetch(client, url):
        # Sort keys by length descending so more-specific paths match first
        for key in sorted(pages.keys(), key=len, reverse=True):
            if url == key or url.rstrip("/") == key.rstrip("/"):
                return pages[key]
        return (404, b"", url)
    return patch("services.contact_discovery.fetch_page", new=_fake_fetch)


async def test_invalid_url_returns_error():
    result = await discover_contact_emails("not-a-url")
    assert result["error"] is not None
    assert result["emails"] == []


async def test_blocked_ip_returns_error():
    with _patch_blocked(True):
        result = await discover_contact_emails("https://192.168.1.1/")
    assert result["error"] is not None
    assert "blocked" in result["error"].lower()


async def test_robots_disallowed_skips_page():
    with _patch_blocked(False), _patch_robots(False):
        result = await discover_contact_emails("https://example.com/")
    # All pages return None from _fetch_safe → 0 pages checked
    assert result["pages_checked"] == 0
    assert result["emails"] == []


async def test_email_found_on_homepage():
    body = b"<p>Email us at info@bestpizza.com</p>"
    with (
        _patch_blocked(False),
        _patch_robots(True),
        _patch_fetch({"https://example.com/": (200, body, "https://example.com/")}),
    ):
        result = await discover_contact_emails("https://example.com/")
    assert any(e["email"] == "info@bestpizza.com" for e in result["emails"])


async def test_email_found_on_contact_page():
    home_body = b"<p>Visit us</p>"
    contact_body = b'<a href="mailto:order@diner.com">Order</a>'
    pages = {
        "https://example.com/": (200, home_body, "https://example.com/"),
        "https://example.com/contact": (200, contact_body, "https://example.com/contact"),
    }
    with _patch_blocked(False), _patch_robots(True), _patch_fetch(pages):
        result = await discover_contact_emails("https://example.com/")
    assert any(e["email"] == "order@diner.com" for e in result["emails"])


async def test_no_emails_found():
    body = b"<p>Welcome to our restaurant!</p>"
    with (
        _patch_blocked(False),
        _patch_robots(True),
        _patch_fetch({"https://example.com/": (200, body, "https://example.com/")}),
    ):
        result = await discover_contact_emails("https://example.com/")
    assert result["emails"] == []
    assert result["error"] is None


async def test_deduplication_across_pages():
    body = b"<p>info@place.com</p>"
    pages = {
        "https://example.com/": (200, body, "https://example.com/"),
        "https://example.com/contact": (200, body, "https://example.com/contact"),
    }
    with _patch_blocked(False), _patch_robots(True), _patch_fetch(pages):
        result = await discover_contact_emails("https://example.com/")
    emails = [e["email"] for e in result["emails"]]
    assert emails.count("info@place.com") == 1


async def test_email_status_is_unverified():
    body = b"<p>hello@cafe.com</p>"
    with (
        _patch_blocked(False),
        _patch_robots(True),
        _patch_fetch({"https://example.com/": (200, body, "https://example.com/")}),
    ):
        result = await discover_contact_emails("https://example.com/")
    assert all(e["status"] == "unverified" for e in result["emails"])
