"""Google Places (New) live discovery and Demo Mode, with HTTP mocked at the transport layer.

No test contacts Google. Each test queues the responses Google would return.
"""
import json
import os
import sqlite3
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient  # noqa: F401
from tests.account_helpers import signed_in_client

import main
from models.database import save_restaurants
from services import discovery
from services.campaigns import outreach_reasons

KEY = "test-live-key-0123456789"
PLACE_A = {
    "id": "ChIJ-live-a",
    "displayName": {"text": "Live Karahi House"},
    "formattedAddress": "Peoples Colony, Gujrat, Punjab, Pakistan",
    "nationalPhoneNumber": "053 111 0001",
    "websiteUri": "https://liveKarahi.pk/",
}
PLACE_B = {
    "id": "ChIJ-live-b",
    "displayName": {"text": "Live Biryani Point"},
    "formattedAddress": "Civil Lines, Gujrat, Punjab, Pakistan",
}


def _place(index: int) -> dict:
    return {"id": f"ChIJ-page-{index}", "displayName": {"text": f"Page Place {index}"},
            "formattedAddress": f"Street {index}, Lahore, Pakistan"}


@pytest.fixture
def places(test_db, monkeypatch):
    queue: list = []
    requests: list = []
    real_client = httpx.AsyncClient

    async def handler(request: httpx.Request):
        requests.append({
            "body": json.loads(request.content),
            "mask": request.headers.get("x-goog-fieldmask"),
            "key": request.headers.get("x-goog-api-key"),
        })
        item = queue.pop(0) if queue else (200, {"places": []})
        if isinstance(item, Exception):
            raise item
        status, body = item
        return httpx.Response(status, json=body)

    def make_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("services.discovery.httpx.AsyncClient", make_client)
    monkeypatch.setattr(discovery, "NEXT_PAGE_DELAY_SECONDS", 0)
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", KEY)
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.delenv("PLACES_MAX_RESULTS", raising=False)
    return SimpleNamespace(queue=queue, requests=requests)


@pytest.fixture
def client(places):
    return signed_in_client(main.app)


def _search(client, city="Gujrat", category="biryani", limit=10):
    return client.post("/restaurants/discover", json={"city": city, "category": category, "limit": limit})


# ── Demo Mode ─────────────────────────────────────────────────────────────────

def test_demo_mode_is_the_default_and_never_calls_google(client, places, monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    resp = _search(client, city="Lahore", category="karahi", limit=3)
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 3
    assert all(r["source"] == "demo" for r in rows)
    assert all(r["name"].startswith("[DEMO]") for r in rows)
    assert all(r["city"] == "Lahore" and r["country"] == "Pakistan" for r in rows)
    assert places.requests == []


def test_demo_records_are_never_eligible_for_outreach(client, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    rows = _search(client, city="Lahore", category="all", limit=2).json()
    reasons = outreach_reasons({**rows[0], "contact_email": "owner@diner.pk", "lead_status": "qualified"}, set())
    assert any("Demo or sample record" in reason for reason in reasons)


def test_live_mode_without_a_key_explains_how_to_switch(client, places, monkeypatch):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    resp = _search(client)
    assert resp.status_code == 503
    assert "GOOGLE_PLACES_API_KEY" in resp.json()["detail"]
    assert "DEMO_MODE=true" in resp.json()["detail"]
    assert places.requests == []


def test_discovery_mode_reports_flags_without_exposing_the_key(client, monkeypatch):
    body = client.get("/discovery/mode").json()
    assert body == {"demo_mode": False, "live_key_configured": True, "result_limit": 60}
    assert KEY not in client.get("/discovery/mode").text


# ── Live search: request shape and storage ────────────────────────────────────

def test_live_search_sends_city_country_cuisine_and_a_safe_field_mask(client, places):
    places.queue.append((200, {"places": [PLACE_A, PLACE_B]}))
    rows = _search(client, city="Gujrat", category="biryani", limit=10).json()
    assert {r["name"] for r in rows} == {"Live Karahi House", "Live Biryani Point"}

    request = places.requests[0]
    assert request["body"]["textQuery"] == "biryani restaurant in Gujrat, Pakistan"
    assert request["body"]["regionCode"] == "PK"
    assert request["body"]["maxResultCount"] == 10
    assert request["key"] == KEY
    assert "*" not in request["mask"]
    assert "nextPageToken" in request["mask"]
    assert "places.location" not in request["mask"]


def test_custom_pakistani_city_is_searched_and_stored_with_its_name(client, places):
    places.queue.append((200, {"places": [PLACE_A]}))
    _search(client, city="  dera  ghazi khan ", category="all", limit=5)
    assert places.requests[0]["body"]["textQuery"] == "restaurants in Dera Ghazi Khan, Pakistan"
    stored = next(r for r in client.get("/restaurants").json() if r["place_id"] == PLACE_A["id"])
    assert stored["city"] == "Dera Ghazi Khan"
    assert stored["country"] == "Pakistan"


def test_cuisine_without_a_reliable_place_type_uses_text_only(client, places):
    places.queue.append((200, {"places": []}))
    _search(client, category="biryani", limit=5)
    assert "includedType" not in places.requests[0]["body"]


def test_result_limit_is_capped_by_configuration(client, places, monkeypatch):
    monkeypatch.setenv("PLACES_MAX_RESULTS", "5")
    places.queue.append((200, {"places": [_place(i) for i in range(1, 6)]}))
    rows = _search(client, limit=20).json()
    assert len(rows) == 5
    assert places.requests[0]["body"]["maxResultCount"] == 5


# ── Pagination ────────────────────────────────────────────────────────────────

def test_pagination_follows_next_page_token_and_merges_unique_places(client, places):
    places.queue.append((200, {"places": [_place(1), _place(2)], "nextPageToken": "token-2"}))
    places.queue.append((200, {"places": [_place(2), _place(3)]}))
    rows = _search(client, limit=10).json()
    assert [r["place_id"] for r in rows] == ["ChIJ-page-1", "ChIJ-page-2", "ChIJ-page-3"]
    assert len(places.requests) == 2
    assert places.requests[1]["body"]["pageToken"] == "token-2"
    assert "pageToken" not in places.requests[0]["body"]
    assert places.requests[1]["body"]["maxResultCount"] == places.requests[0]["body"]["maxResultCount"]


def test_pagination_stops_once_the_limit_is_reached(client, places):
    places.queue.append((200, {"places": [_place(i) for i in range(1, 4)], "nextPageToken": "more"}))
    rows = _search(client, limit=3).json()
    assert len(rows) == 3
    assert len(places.requests) == 1


def test_empty_results_return_an_empty_list_not_an_error(client, places):
    places.queue.append((200, {}))
    resp = _search(client)
    assert resp.status_code == 200
    assert resp.json() == []


# ── API errors ────────────────────────────────────────────────────────────────

def test_invalid_key_is_reported_as_a_key_problem(client, places):
    places.queue.append((400, {"error": {"status": "INVALID_ARGUMENT", "message": "API key not valid. Please pass a valid API key."}}))
    resp = _search(client)
    assert resp.status_code == 503
    assert "rejected by Google" in resp.json()["detail"]
    assert KEY not in resp.text


def test_api_not_enabled_is_reported_with_setup_hint(client, places):
    places.queue.append((403, {"error": {"status": "PERMISSION_DENIED", "message": "Places API (New) has not been used in project 123."}}))
    resp = _search(client)
    assert resp.status_code == 503
    assert "Enable Places API (New)" in resp.json()["detail"]


def test_quota_exhaustion_returns_429(client, places):
    places.queue.append((429, {"error": {"status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded."}}))
    assert _search(client).status_code == 429


def test_google_server_error_returns_502(client, places):
    places.queue.append((500, {"error": {"status": "INTERNAL", "message": "boom"}}))
    resp = _search(client)
    assert resp.status_code == 502
    assert "temporary error" in resp.json()["detail"]


def test_bad_request_reports_google_message(client, places):
    places.queue.append((400, {"error": {"status": "INVALID_ARGUMENT", "message": "Unsupported regionCode."}}))
    resp = _search(client)
    assert resp.status_code == 400
    assert "Unsupported regionCode" in resp.json()["detail"]


def test_timeout_returns_504(client, places):
    places.queue.append(httpx.ReadTimeout("slow"))
    assert _search(client).status_code == 504


def test_network_failure_returns_502(client, places):
    places.queue.append(httpx.ConnectError("no route"))
    assert _search(client).status_code == 502


# ── Storage policy: place IDs kept, restricted content purged after 30 days ───

def test_expired_google_listing_is_purged_blocked_and_refreshed_on_next_search(client, places):
    places.queue.append((200, {"places": [PLACE_A]}))
    _search(client, city="Gujrat", category="all", limit=5)
    stored = next(r for r in client.get("/restaurants").json() if r["place_id"] == PLACE_A["id"])
    _set_fetch_age(stored["id"], days=31)

    places.queue.append((200, {"places": [PLACE_B]}))
    _search(client, city="Gujrat", category="all", limit=5)

    expired = next(r for r in client.get("/restaurants").json() if r["place_id"] == PLACE_A["id"])
    assert expired["name"] == "Expired Google listing"
    assert expired["address"] is None
    assert expired["phone"] is None
    assert expired["website"] is None
    rules = client.get("/outreach/eligibility").json()
    assert any("listing expired" in reason for reason in rules[str(expired["id"])]["reasons"])

    places.queue.append((200, {"places": [PLACE_A]}))
    _search(client, city="Gujrat", category="all", limit=5)
    refreshed = next(r for r in client.get("/restaurants").json() if r["place_id"] == PLACE_A["id"])
    assert refreshed["name"] == "Live Karahi House"
    assert refreshed["address"] == PLACE_A["formattedAddress"]
    assert refreshed["listing_expired"] == 0


def test_purge_keeps_our_own_data_and_demo_records(client, places):
    save_restaurants([{"place_id": "demo-keep", "name": "[DEMO] Keep", "address": "x", "source": "demo"}])
    places.queue.append((200, {"places": [PLACE_A]}))
    _search(client, city="Gujrat", category="all", limit=5)
    stored = next(r for r in client.get("/restaurants").json() if r["place_id"] == PLACE_A["id"])
    _set(stored["id"], contact_email="info@liveKarahi.pk", contact_email_status="unverified", website_status="present")
    _set_fetch_age(stored["id"], days=45)

    from models.database import purge_expired_google_content
    purge_expired_google_content(30)

    kept = next(r for r in client.get("/restaurants").json() if r["place_id"] == PLACE_A["id"])
    assert kept["contact_email"] == "info@liveKarahi.pk"
    assert kept["website_status"] == "present"
    demo = next(r for r in client.get("/restaurants").json() if r["place_id"] == "demo-keep")
    assert demo["name"] == "[DEMO] Keep"


def test_every_request_is_a_minimal_field_mask(client, places):
    places.queue.append((200, {"places": [PLACE_A]}))
    _search(client)
    assert places.requests[0]["mask"] == discovery.FIELD_MASK
    assert "*" not in discovery.FIELD_MASK


def _set(restaurant_id, **fields):
    from models.database import execute
    assignments = ", ".join(f"{column} = :{column}" for column in fields)
    execute(f"UPDATE restaurants SET {assignments} WHERE id = :_id", {**fields, "_id": restaurant_id})


def _set_fetch_age(restaurant_id, days):
    from datetime import timedelta
    from models.database import execute, stamp, utc_now
    execute("UPDATE restaurants SET google_fetched_at = :ts WHERE id = :id",
            {"ts": stamp(utc_now() - timedelta(days=days)), "id": restaurant_id})
