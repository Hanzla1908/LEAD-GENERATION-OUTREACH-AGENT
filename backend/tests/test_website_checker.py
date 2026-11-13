"""
Tests for services/website_checker.py.
All HTTP is mocked — no live network calls.
"""

import socket
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from bs4 import BeautifulSoup

from services.website_checker import (
    check_website,
    find_ordering_evidence,
    get_base_domain,
    is_blocked_ip,
)


# ── unit tests: pure helpers ────────────────────────────────────────────────


def test_get_base_domain_normal():
    assert get_base_domain("www.example.com") == "example.com"


def test_get_base_domain_subdomain():
    assert get_base_domain("order.pizza.restaurant.io") == "restaurant.io"


def test_get_base_domain_bare():
    assert get_base_domain("example.com") == "example.com"


def test_is_blocked_ip_loopback(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, **kw: [(None, None, None, None, ("127.0.0.1", 0))],
    )
    assert is_blocked_ip("localhost") is True


def test_is_blocked_ip_private_rfc1918(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, **kw: [(None, None, None, None, ("192.168.1.1", 0))],
    )
    assert is_blocked_ip("internal.local") is True


def test_is_blocked_ip_public(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda host, port, **kw: [(None, None, None, None, ("93.184.216.34", 0))],
    )
    assert is_blocked_ip("example.com") is False


def test_is_blocked_ip_unresolvable(monkeypatch):
    def raise_gaierror(*a, **kw):
        raise socket.gaierror("name not resolved")
    monkeypatch.setattr(socket, "getaddrinfo", raise_gaierror)
    assert is_blocked_ip("notexist.invalid") is True


# ── unit tests: find_ordering_evidence ─────────────────────────────────────


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def test_find_ordering_evidence_doordash_link():
    html = '<a href="https://www.doordash.com/store/123">Order on DoorDash</a>'
    ev = find_ordering_evidence(_soup(html), "https://example.com")
    assert any("doordash.com" in e for e in ev)


def test_find_ordering_evidence_keyword_in_text():
    html = '<a href="/order">Order Online</a>'
    ev = find_ordering_evidence(_soup(html), "https://example.com")
    assert len(ev) >= 1


def test_find_ordering_evidence_button_keyword():
    html = "<button>Order Now</button>"
    ev = find_ordering_evidence(_soup(html), "https://example.com")
    assert any("order now" in e.lower() for e in ev)


def test_find_ordering_evidence_no_signals():
    html = "<p>Welcome to our restaurant. We are open Mon-Fri.</p>"
    ev = find_ordering_evidence(_soup(html), "https://example.com")
    assert ev == []


def test_find_ordering_evidence_max_10():
    links = "".join(
        f'<a href="https://www.doordash.com/store/{i}">Order</a>' for i in range(20)
    )
    html = f"<html><body>{links}</body></html>"
    ev = find_ordering_evidence(_soup(html), "https://example.com")
    assert len(ev) <= 10


# ── integration tests: check_website ───────────────────────────────────────


def _make_response(status_code: int, text: str = "", url: str = "https://example.com/"):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.url = httpx.URL(url)
    resp.text = text

    async def _aiter_bytes(chunk_size):
        if text:
            yield text.encode()

    resp.aiter_bytes = _aiter_bytes
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


def _patch_blocked_ip(blocked: bool):
    return patch("services.website_checker.is_blocked_ip", return_value=blocked)


def _patch_robots(allowed: bool):
    return patch("services.website_checker.check_robots", new=AsyncMock(return_value=allowed))


def _patch_fetch(status: int, body: str = "", final_url: str = "https://example.com/"):
    return patch(
        "services.website_checker.fetch_page",
        new=AsyncMock(return_value=(status, body.encode(), final_url)),
    )


async def test_blocked_ip_returns_unknown():
    with _patch_blocked_ip(True):
        result = await check_website("https://192.168.1.1/")
    assert result["website_status"] == "unknown"
    assert "private" in (result["error"] or "").lower() or result["error"] is not None


async def test_robots_disallowed_returns_unknown():
    with _patch_blocked_ip(False), _patch_robots(False):
        result = await check_website("https://example.com/")
    assert result["website_status"] == "unknown"
    assert "robots" in (result["error"] or "").lower()


async def test_404_returns_not_found():
    with _patch_blocked_ip(False), _patch_robots(True), _patch_fetch(404):
        result = await check_website("https://example.com/")
    assert result["website_status"] == "not_found"
    assert result["ordering_status"] == "unknown"


async def test_200_no_ordering_signals():
    body = "<html><body><p>Welcome! We serve great food.</p></body></html>"
    with _patch_blocked_ip(False), _patch_robots(True), _patch_fetch(200, body):
        result = await check_website("https://example.com/")
    assert result["website_status"] == "present"
    assert result["ordering_status"] == "not_found"
    assert result["ordering_evidence"] == []


async def test_200_with_ordering_platform_link():
    body = '<html><body><a href="https://www.doordash.com/store/99">Order on DoorDash</a></body></html>'
    with _patch_blocked_ip(False), _patch_robots(True), _patch_fetch(200, body):
        result = await check_website("https://example.com/")
    assert result["website_status"] == "present"
    assert result["ordering_status"] == "present"
    assert len(result["ordering_evidence"]) >= 1


async def test_timeout_returns_unknown():
    with _patch_blocked_ip(False), _patch_robots(True):
        with patch(
            "services.website_checker.fetch_page",
            new=AsyncMock(side_effect=httpx.TimeoutException("timed out")),
        ):
            result = await check_website("https://example.com/")
    assert result["website_status"] == "unknown"
    assert "timed out" in (result["error"] or "").lower()


async def test_connection_error_returns_unknown():
    with _patch_blocked_ip(False), _patch_robots(True):
        with patch(
            "services.website_checker.fetch_page",
            new=AsyncMock(side_effect=httpx.ConnectError("refused")),
        ):
            result = await check_website("https://example.com/")
    assert result["website_status"] == "unknown"
    assert result["error"] is not None


async def test_domain_redirect_to_unrelated_returns_unknown():
    with _patch_blocked_ip(False), _patch_robots(True), _patch_fetch(
        200, "<html/>", final_url="https://www.totallyother.net/"
    ):
        result = await check_website("https://example.com/")
    assert result["website_status"] == "unknown"
    assert "redirect" in (result["error"] or "").lower()


async def test_domain_redirect_to_ordering_platform_returns_present():
    with _patch_blocked_ip(False), _patch_robots(True), _patch_fetch(
        200, "<html/>", final_url="https://www.doordash.com/store/99/"
    ):
        result = await check_website("https://example.com/")
    assert result["website_status"] == "present"
    assert result["ordering_status"] == "present"


async def test_5xx_returns_unknown():
    with _patch_blocked_ip(False), _patch_robots(True), _patch_fetch(503):
        result = await check_website("https://example.com/")
    assert result["website_status"] == "unknown"
    assert "503" in (result["error"] or "")


async def test_invalid_url_returns_unknown():
    result = await check_website("not-a-url")
    assert result["website_status"] == "unknown"
    assert result["error"] is not None
