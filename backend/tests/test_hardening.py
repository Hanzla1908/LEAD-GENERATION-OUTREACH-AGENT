"""Phase 11 hardening: SSRF pinning and redirects, password hashing, sessions, request limits,
client addresses, unsubscribe tokens, pagination and send-time safety checks.

Nothing here reaches the internet, DNS or an email provider. DNS and HTTP are replaced by fakes.
"""
import ipaddress
import socket

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from starlette.requests import Request as StarletteRequest

import main
from config import production_problems
from models import campaign_store
from services import campaigns as campaign_service
from services import rate_limit
from services import website_checker as wc
from services.auth import COOKIE_NAME
from services.http_security import BodyLimitMiddleware, BodyTooLarge, _body_too_large
from tests.test_campaigns import _approve_all, _create, _recipient, _restaurant, _send, client, env  # noqa: F401

PASSWORD = "correct-horse-battery-staple"
SESSION_SECRET = "session-secret-0123456789abcdefghij"


# ── Fakes for DNS and HTTP ────────────────────────────────────────────────────

def fake_dns(mapping, counter=None):
    def getaddrinfo(host, port, *args, **kwargs):
        if counter is not None:
            counter["n"] += 1
        ips = mapping.get(host)
        if ips is None:
            try:
                ips = [str(ipaddress.ip_address(host))]  # like the real resolver, IP literals resolve to themselves
            except ValueError:
                raise socket.gaierror("no such host")
        results = []
        for ip in ips:
            if ":" in ip:
                results.append((socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, 0, 0, 0)))
            else:
                results.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0)))
        return results
    return getaddrinfo


class FakeResponse:
    def __init__(self, status, headers=None, body=b""):
        self.status_code = status
        self.headers = httpx.Headers(headers or {})
        self._body = body

    async def aiter_bytes(self, chunk_size=8192):
        yield self._body


class _Stream:
    def __init__(self, response):
        self._response = response

    async def __aenter__(self):
        return self._response

    async def __aexit__(self, *exc_info):
        return False


class FakeClient:
    """Records every request. `respond(url, headers)` decides the response."""

    def __init__(self, respond):
        self.respond = respond
        self.requests = []

    def stream(self, method, url, headers=None, extensions=None, follow_redirects=False):
        self.requests.append({
            "url": url, "headers": dict(headers or {}), "extensions": dict(extensions or {}),
            "follow_redirects": follow_redirects,
        })
        return _Stream(self.respond(url, headers or {}))


class _ClientContext:
    def __init__(self, client):
        self.client = client

    async def __aenter__(self):
        return self.client

    async def __aexit__(self, *exc_info):
        return False


PUBLIC = {"cafe.example": ["93.184.216.34"]}


# ── SSRF: addresses ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.1.2.3", "172.16.5.5", "192.168.1.1", "169.254.169.254", "0.0.0.0", "100.64.1.1",
    "::1", "::", "fe80::1", "fd00::1", "224.0.0.1",
    "::ffff:127.0.0.1", "::ffff:10.1.2.3", "::ffff:169.254.169.254",  # IPv4-mapped IPv6 bypasses
    "64:ff9b::a00:1", "2002:c0a8:101::1",                             # NAT64 and 6to4 wrappers
])
def test_internal_addresses_are_blocked(address):
    import ipaddress
    assert wc.ip_is_blocked(ipaddress.ip_address(address)) is True


@pytest.mark.parametrize("address", ["93.184.216.34", "8.8.8.8", "2606:4700:4700::1111"])
def test_public_addresses_are_allowed(address):
    import ipaddress
    assert wc.ip_is_blocked(ipaddress.ip_address(address)) is False


# ── SSRF: URL syntax ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "ftp://cafe.example/menu",
    "http://cafe.example:8080/",
    "http://cafe.example:22/",
    "http://user:secret@cafe.example/",
    "http:///no-host",
])
def test_unsafe_url_syntax_is_refused_without_a_lookup(url):
    with pytest.raises(wc.UnsafeTarget):
        wc.validate_url_syntax(url)


def test_standard_ports_are_allowed():
    assert wc.validate_url_syntax("https://cafe.example:443/menu").hostname == "cafe.example"
    assert wc.validate_url_syntax("http://cafe.example/").hostname == "cafe.example"


# ── SSRF: fetching ────────────────────────────────────────────────────────────

async def test_redirect_to_loopback_is_refused_before_any_request(monkeypatch):
    dns = {"cafe.example": ["93.184.216.34"], "internal.example": ["127.0.0.1"]}
    monkeypatch.setattr(wc.socket, "getaddrinfo", fake_dns(dns))

    def respond(url, headers):
        if url.startswith("http://93.184.216.34"):
            return FakeResponse(302, {"location": "http://internal.example/admin"})
        raise AssertionError("the internal address must never be requested")

    client = FakeClient(respond)
    with pytest.raises(wc.UnsafeTarget):
        await wc.fetch_page(client, "http://cafe.example/")
    assert [r["url"] for r in client.requests] == ["http://93.184.216.34/"]


async def test_requests_are_pinned_to_the_validated_address(monkeypatch):
    monkeypatch.setattr(wc.socket, "getaddrinfo", fake_dns(PUBLIC))
    client = FakeClient(lambda url, headers: FakeResponse(200, body=b"<html></html>"))
    _status, _body, final_url = await wc.fetch_page(client, "https://cafe.example/menu?x=1")
    request = client.requests[0]
    assert request["url"] == "https://93.184.216.34/menu?x=1"
    assert request["headers"]["Host"] == "cafe.example"
    assert request["extensions"] == {"sni_hostname": "cafe.example"}
    assert request["follow_redirects"] is False
    assert final_url == "https://cafe.example/menu?x=1"


async def test_dns_rebinding_cannot_swap_the_address_after_validation(monkeypatch):
    counter = {"n": 0}

    def rebinding(host, port, *args, **kwargs):
        counter["n"] += 1
        ip = "93.184.216.34" if counter["n"] == 1 else "127.0.0.1"
        return fake_dns({host: [ip]})(host, port)

    monkeypatch.setattr(wc.socket, "getaddrinfo", rebinding)
    client = FakeClient(lambda url, headers: FakeResponse(200, body=b"ok"))
    await wc.fetch_page(client, "http://cafe.example/")
    assert counter["n"] == 1
    assert client.requests[0]["url"] == "http://93.184.216.34/"


async def test_redirect_loop_is_bounded(monkeypatch):
    monkeypatch.setattr(wc.socket, "getaddrinfo", fake_dns(PUBLIC))
    client = FakeClient(lambda url, headers: FakeResponse(301, {"location": "/again"}))
    with pytest.raises(httpx.TooManyRedirects):
        await wc.fetch_page(client, "http://cafe.example/")
    assert len(client.requests) == wc.MAX_REDIRECTS + 1


async def test_robots_txt_on_an_internal_address_stops_the_check(monkeypatch):
    monkeypatch.setattr(wc.socket, "getaddrinfo", fake_dns(PUBLIC))

    def respond(url, headers):
        if url.endswith("/robots.txt"):
            return FakeResponse(302, {"location": "http://127.0.0.1/robots.txt"})
        raise AssertionError("no page may be fetched after an unsafe robots.txt")

    client = FakeClient(respond)
    monkeypatch.setattr(wc, "make_client", lambda timeout: _ClientContext(client))
    result = await wc.check_website("https://cafe.example/")
    assert result["website_status"] == "unknown"
    assert "Blocked" in result["error"]


async def test_check_website_refuses_a_redirect_to_an_internal_name(monkeypatch):
    dns = {"cafe.example": ["93.184.216.34"], "intranet.example": ["10.0.0.7"]}
    monkeypatch.setattr(wc.socket, "getaddrinfo", fake_dns(dns))

    def respond(url, headers):
        if url.endswith("/robots.txt"):
            return FakeResponse(404)
        return FakeResponse(302, {"location": "http://intranet.example/"})

    client = FakeClient(respond)
    monkeypatch.setattr(wc, "make_client", lambda timeout: _ClientContext(client))
    result = await wc.check_website("https://cafe.example/")
    assert result["website_status"] == "unknown"
    assert "Blocked" in result["error"]
    assert all("10.0.0.7" not in r["url"] for r in client.requests)


def test_website_client_ignores_proxy_environment(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.internal:3128")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.internal:3128")
    client = wc.make_client(httpx.Timeout(5.0))
    assert client._trust_env is False


async def test_contact_discovery_does_not_fetch_internal_pages(monkeypatch):
    from services import contact_discovery

    dns = {"cafe.example": ["93.184.216.34"]}
    monkeypatch.setattr(wc.socket, "getaddrinfo", fake_dns(dns))

    def respond(url, headers):
        if url.endswith("/robots.txt"):
            return FakeResponse(302, {"location": "http://192.168.0.1/robots.txt"})
        return FakeResponse(200, body=b'<a href="mailto:owner@cafe.example">mail</a>')

    client = FakeClient(respond)
    monkeypatch.setattr(contact_discovery, "make_client", lambda timeout: _ClientContext(client))
    result = await contact_discovery.discover_contact_emails("https://cafe.example/")
    assert result["emails"] == []
    assert all("192.168.0.1" not in r["url"] for r in client.requests)


# ── Request size limits ───────────────────────────────────────────────────────

def test_declared_oversized_body_is_refused_before_it_is_read(test_db):
    resp = TestClient(main.app).post(
        "/auth/login", content=b"x" * 200_000,
        headers={"Content-Type": "application/json", "X-Requested-With": "t"},
    )
    assert resp.status_code == 413
    assert resp.json()["detail"] == "Request body is too large."


def test_chunked_body_over_the_limit_is_refused():
    app = FastAPI()
    app.add_middleware(BodyLimitMiddleware, max_bytes=1024)
    app.add_exception_handler(BodyTooLarge, _body_too_large)

    @app.post("/echo")
    async def echo(request: Request):
        return {"size": len((await request.body()))}

    small_client = TestClient(app)
    assert small_client.post("/echo", content=b"a" * 100).json() == {"size": 100}

    def chunks():
        for _ in range(3):
            yield b"b" * 600

    assert small_client.post("/echo", content=chunks()).status_code == 413


# ── Unsubscribe and pagination ────────────────────────────────────────────────

@pytest.fixture
def unsubscribe_env(monkeypatch):
    monkeypatch.setenv("UNSUBSCRIBE_SECRET", "unsubscribe-secret-0123")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://outreach.test")
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD_HASH", raising=False)


@pytest.mark.parametrize("token", ["<script>alert(1)</script>", "A" * 64, "a" * 63, "g" * 64, ""])
def test_malformed_unsubscribe_tokens_are_rejected(test_db, unsubscribe_env, token):
    client = TestClient(main.app)
    get = client.get("/unsubscribe", params={"r": 1, "t": token})
    post = client.post("/unsubscribe", params={"r": 1, "t": token})
    assert get.status_code == 400 and post.status_code == 400
    assert "<script>" not in get.text


def test_list_endpoints_reject_unbounded_pages(test_db):
    from tests.account_helpers import signed_in_client
    client = signed_in_client(main.app)
    assert client.get("/restaurants", params={"limit": 5000}).status_code == 422
    assert client.get("/restaurants", params={"offset": -1}).status_code == 422
    assert client.get("/outreach/drafts", params={"limit": 0}).status_code == 422


def test_pages_are_sliced_by_limit_and_offset(client, env):
    for index in range(4):
        _restaurant(f"Paged Cafe {index}", email=f"paged{index}@cafe.com")
    everything = client.get("/restaurants").json()
    page = client.get("/restaurants", params={"limit": 2, "offset": 1}).json()
    assert [r["id"] for r in page] == [r["id"] for r in everything[1:3]]


# ── Sending safety ────────────────────────────────────────────────────────────

def test_a_later_campaign_does_not_email_the_same_address_again(client, env):
    # Workspace-wide rule: an address already emailed by any campaign in the workspace is not contacted again,
    # even by a campaign with a different name.
    first = _restaurant("Follow One", email="follow@cafe.com")
    second = _restaurant("Follow Two", email="follow@cafe.com")
    spring = _create(client, "Spring", [first]).json()
    _approve_all(client, spring)
    _send(client, spring["id"])

    summer = _create(client, "Summer", [second])
    assert summer.status_code == 422

    assert [m["to"][0] for m in env["sender"].outbox] == ["follow@cafe.com"]


def test_address_changed_after_approval_is_not_sent_twice_in_one_campaign(client, env):
    from models.database import execute

    first = _restaurant("Changed One", email="first@cafe.com")
    second = _restaurant("Changed Two", email="second@cafe.com")
    detail = _create(client, "Changed", [first, second]).json()
    _approve_all(client, detail)
    # After approval, the second restaurant's address is changed to match the first one.
    execute("UPDATE restaurants SET contact_email = 'first@cafe.com' WHERE id = :id", {"id": second})
    _send(client, detail["id"])

    assert [m["to"][0] for m in env["sender"].outbox] == ["first@cafe.com"]
    row = _recipient(client.get(f"/campaigns/{detail['id']}").json(), second)
    assert row["status"] == "skipped"
    assert "changed" in row["skip_reason"] or "already received" in row["skip_reason"]


def test_each_send_checks_that_its_draft_was_approved_for_this_campaign(test_db, monkeypatch):
    row = {"campaign_id": 1, "restaurant_id": 1, "draft_id": 7, "recipient_email": "owner@cafe.com"}
    restaurant = {
        "id": 1, "name": "Cafe", "source": "google_places", "contact_email": "owner@cafe.com",
        "contact_email_status": "unverified", "lead_status": "qualified", "opted_out": 0, "listing_expired": 0,
    }
    monkeypatch.setattr(campaign_service, "get_restaurant_by_id", lambda rid: restaurant)
    monkeypatch.setattr(campaign_service, "get_draft", lambda did: {"id": did, "status": "approved"})

    not_approved = campaign_service._send_reasons(row, set(), approved_ids=set(), sent=set())
    assert any("not approved for sending in this campaign" in reason for reason in not_approved)
    assert campaign_service._send_reasons(row, set(), {7}, set()) == []
    already = campaign_service._send_reasons(row, set(), {7}, {"owner@cafe.com"})
    assert any("already received" in reason for reason in already)


def test_campaign_list_counts_match_the_detail_counts(client, env):
    # The list uses one grouped query; the detail uses per-recipient counting. They must agree.
    a = _restaurant("Count One", email="count1@cafe.com")
    b = _restaurant("Count Two", email="count2@cafe.com")
    no_email = _restaurant("Count Three", email=None)
    detail = _create(client, "Counted", [a, b, no_email]).json()
    _approve_all(client, detail)
    _send(client, detail["id"])
    listed = next(item for item in client.get("/campaigns").json() if item["id"] == detail["id"])
    full = client.get(f"/campaigns/{detail['id']}").json()
    assert listed["counts"] == full["counts"]
    assert full["counts"]["sent"] == 2 and full["counts"]["skipped"] == 1


def test_recipient_updates_accept_only_known_columns(test_db):
    with pytest.raises(ValueError):
        campaign_store.update_recipient(1, recipient_email="someone@cafe.com")
    with pytest.raises(ValueError):
        campaign_store.update_recipient(1, **{"status = 'sent', id": 2})
