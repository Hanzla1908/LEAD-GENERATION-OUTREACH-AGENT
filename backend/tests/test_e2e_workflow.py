"""End-to-end workflow from Pakistan discovery to campaign sending.

Only external services are mocked: Google Places, website and contact page fetches, Claude,
and the mail provider (mock sender). The database is a temporary file per test.
"""
import os
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient  # noqa: F401
from tests.account_helpers import signed_in_client

import main
from models import campaign_store
from models.database import save_restaurants
from services import campaigns as campaign_service
from services.email_sender import MockSender
from services.unsubscribe import make_token

SECRET = "e2e-secret"
BASE_URL = "https://outreach.test"

PLACES = [
    {"id": "ChIJ-karahi", "displayName": {"text": "Karahi Corner"},
     "formattedAddress": "Peoples Colony, Faisalabad, Punjab, Pakistan",
     "nationalPhoneNumber": "041 111 0001", "websiteUri": "https://karahicorner.pk/",
     "location": {"latitude": 31.41, "longitude": 73.09}},
    {"id": "ChIJ-kebab", "displayName": {"text": "Kebab Point"},
     "formattedAddress": "Susan Road, Faisalabad, Punjab, Pakistan",
     "nationalPhoneNumber": "041 111 0002", "websiteUri": "https://kebabpoint.pk/",
     "location": {"latitude": 31.42, "longitude": 73.10}},
    {"id": "ChIJ-optout", "displayName": {"text": "Opt Out Grill"},
     "formattedAddress": "Jail Road, Faisalabad, Punjab, Pakistan",
     "nationalPhoneNumber": "041 111 0003", "websiteUri": "https://optoutgrill.pk/",
     "location": {"latitude": 31.43, "longitude": 73.11}},
    {"id": "ChIJ-nomail", "displayName": {"text": "Quiet Bistro"},
     "formattedAddress": "D Ground, Faisalabad, Punjab, Pakistan",
     "nationalPhoneNumber": "041 111 0004", "websiteUri": "https://quietbistro.pk/",
     "location": {"latitude": 31.44, "longitude": 73.12}},
    {"id": "ChIJ-chaat", "displayName": {"text": "Chaat Corner"},
     "formattedAddress": "Civil Lines, Faisalabad, Punjab, Pakistan",
     "websiteUri": "https://chaatcorner.pk/", "location": {"latitude": 31.45, "longitude": 73.13}},
    {"id": "ChIJ-burger", "displayName": {"text": "Burger Stop"},
     "formattedAddress": "Canal Road, Faisalabad, Punjab, Pakistan",
     "location": {"latitude": 31.46, "longitude": 73.14}},
]

PAGES = {
    "https://karahicorner.pk/": b'<html><body><h1>Karahi Corner</h1><a href="mailto:info@karahicorner.pk">Email</a></body></html>',
    "https://kebabpoint.pk/": b'<html><body><h1>Kebab Point</h1><a href="mailto:orders@kebabpoint.pk">Email</a></body></html>',
    "https://optoutgrill.pk/": b'<html><body><h1>Opt Out Grill</h1><a href="mailto:hello@optoutgrill.pk">Email</a></body></html>',
    "https://quietbistro.pk/": b"<html><body><h1>Quiet Bistro</h1><p>Open daily.</p></body></html>",
    "https://chaatcorner.pk/": b'<html><body><h1>Chaat Corner</h1><a href="/order">Order Online</a></body></html>',
    "https://keepcafe.pk/": b'<html><body><a href="mailto:info@keepcafe.pk">Email</a></body></html>',
}


async def _fake_fetch(client, url):
    body = PAGES.get(url)
    if body is None:
        return 404, b"", url
    return 200, body, url


def _places_client(places):
    response = MagicMock()
    response.status_code = 200
    response.raise_for_status = MagicMock()
    response.json.return_value = {"places": places}
    instance = AsyncMock()
    instance.post = AsyncMock(return_value=response)
    client_class = MagicMock()
    client_class.return_value.__aenter__ = AsyncMock(return_value=instance)
    client_class.return_value.__aexit__ = AsyncMock(return_value=None)
    return client_class, instance


async def _fake_draft(restaurant):
    return {
        "subject": f"Idea for {restaurant['name']}",
        "body": f"Hello {restaurant['name']} team, here is an idea for online ordering.",
        "angle": "ordering_gap",
    }


@pytest.fixture
def world(test_db, monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "mock")
    monkeypatch.setenv("EMAIL_PER_MINUTE", "0")
    monkeypatch.setenv("EMAIL_DAILY_LIMIT", "100")
    monkeypatch.setenv("UNSUBSCRIBE_SECRET", SECRET)
    monkeypatch.setenv("PUBLIC_BASE_URL", BASE_URL)
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-places-key")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    sender = MockSender()
    monkeypatch.setattr(campaign_service, "get_sender", lambda: sender)
    monkeypatch.setattr(campaign_service, "_spawn", lambda target, *args: target(*args))
    monkeypatch.setattr(campaign_service, "_sleep", lambda seconds: None)
    monkeypatch.setattr(campaign_service, "generate_draft", _fake_draft)
    monkeypatch.setattr(main, "generate_draft", _fake_draft)

    places_class, places_instance = _places_client(PLACES)
    with patch("services.discovery.httpx.AsyncClient", places_class), \
            patch("services.website_checker.is_blocked_ip", return_value=False), \
            patch("services.website_checker.check_robots", new=AsyncMock(return_value=True)), \
            patch("services.website_checker.fetch_page", new=_fake_fetch), \
            patch("services.contact_discovery.is_blocked_ip", return_value=False), \
            patch("services.contact_discovery.check_robots", new=AsyncMock(return_value=True)), \
            patch("services.contact_discovery.fetch_page", new=_fake_fetch):
        yield {"sender": sender, "places": places_instance}


@pytest.fixture
def client(world):
    return signed_in_client(main.app)


def _by_name(rows, name):
    return next(r for r in rows if r["name"] == name)


def _send(client, cid):
    detail = client.get(f"/campaigns/{cid}").json()
    ready = [r["draft_id"] for r in detail["recipients"] if r["status"] == "draft" and r["draft_status"] == "approved"]
    if ready:
        client.post(f"/campaigns/{cid}/approve-sending", json={"draft_ids": ready})
    return client.post(f"/campaigns/{cid}/send")


def test_full_workflow_from_pakistan_search_to_campaign_sending(client, world, monkeypatch):
    # 1. Pakistani city and cuisine search
    resp = client.post("/restaurants/discover", json={"city": "faisalabad", "category": "fast_food", "limit": 10})
    assert resp.status_code == 200, resp.text
    discovered = resp.json()
    assert len(discovered) == len(PLACES)
    assert {r["city"] for r in discovered} == {"Faisalabad"}
    assert {r["country"] for r in discovered} == {"Pakistan"}
    sent_body = world["places"].post.call_args.kwargs["json"]
    assert sent_body["textQuery"] == "fast food restaurant in Faisalabad, Pakistan"
    assert sent_body["includedType"] == "fast_food_restaurant"
    assert sent_body["regionCode"] == "PK"

    # 2. Discovery stores each place once, even when the same search repeats
    again = client.post("/restaurants/discover", json={"city": "faisalabad", "category": "fast_food", "limit": 10})
    assert again.status_code == 200
    assert len(client.get("/restaurants").json()) == len(PLACES)

    ids = {r["name"]: r["id"] for r in client.get("/restaurants").json()}

    # 3. Website and online-ordering detection
    with_site = [ids[n] for n in ("Karahi Corner", "Kebab Point", "Opt Out Grill", "Quiet Bistro", "Chaat Corner")]
    checked = client.post("/restaurants/check-batch", json={"ids": with_site})
    assert checked.status_code == 200
    rows = {r["name"]: r for r in checked.json()}
    assert rows["Karahi Corner"]["website_status"] == "present", rows["Karahi Corner"]["website_error"]
    assert rows["Karahi Corner"]["ordering_status"] == "not_found"
    assert rows["Chaat Corner"]["ordering_status"] == "present"
    assert rows["Quiet Bistro"]["website_status"] == "present"
    assert rows["Quiet Bistro"]["ordering_status"] == "not_found"

    # 4. Public business email discovery
    contacts = client.post("/restaurants/discover-contacts-batch", json={"ids": with_site})
    assert contacts.status_code == 200
    emails = {r["name"]: r["contact_email"] for r in contacts.json()}
    assert emails["Karahi Corner"] == "info@karahicorner.pk"
    assert emails["Kebab Point"] == "orders@kebabpoint.pk"
    assert emails["Quiet Bistro"] is None
    # Discovery now checks each address (mocked DNS here): the domain accepts mail, but no person has verified it.
    assert all(r["contact_email_status"] == "domain_valid" and r["contact_email_checked_at"]
               for r in contacts.json() if r["contact_email"])

    # 5. Lead scoring and qualification (deterministic; no Claude key in this test)
    qualified = client.post("/restaurants/qualify-batch", json={"ids": list(ids.values())})
    assert qualified.status_code == 200
    leads = {r["name"]: r for r in qualified.json()}
    assert leads["Karahi Corner"]["lead_status"] == "qualified"
    assert leads["Karahi Corner"]["lead_score"] == 90
    assert leads["Chaat Corner"]["lead_status"] == "disqualified"
    assert leads["Burger Stop"]["lead_status"] == "disqualified"
    assert leads["Karahi Corner"]["lead_reason"]

    # Demo records never qualify for outreach, even when they look complete
    save_restaurants([{"place_id": "demo-diner", "name": "Demo Diner", "address": "Demo Street, Lahore, Pakistan",
                       "source": "demo"}])
    _set(os.environ["DATABASE_URL"], "Demo Diner", contact_email="demo@diner.pk",
         lead_status="qualified", contact_email_status="unverified")
    rules = client.get("/outreach/eligibility").json()
    demo_id = next(r["id"] for r in client.get("/restaurants").json() if r["name"] == "Demo Diner")
    assert rules[str(demo_id)]["eligible"] is False
    assert "Demo or sample" in rules[str(demo_id)]["reasons"][0]

    # Eligibility: real leads with a valid email are eligible; others explain why
    rules = client.get("/outreach/eligibility").json()
    assert rules[str(ids["Karahi Corner"])]["eligible"] is True
    assert rules[str(ids["Kebab Point"])]["eligible"] is True
    assert "No public email found" in rules[str(ids["Quiet Bistro"])]["reasons"]
    assert rules[str(ids["Chaat Corner"])]["eligible"] is False
    assert rules[str(ids["Burger Stop"])]["eligible"] is False

    # 6. Personalized draft generation and editing (single restaurant)
    single = client.post("/outreach/generate", json={"restaurant_id": ids["Karahi Corner"], "campaign": "default"})
    assert single.status_code == 200, single.text
    draft_id = single.json()["id"]
    edited = client.put(f"/outreach/drafts/{draft_id}", json={"subject": "Edited subject", "body": "Edited body"})
    assert edited.status_code == 200
    assert edited.json()["subject"] == "Edited subject"
    assert client.post(f"/outreach/drafts/{draft_id}/reject").json()["status"] == "rejected"

    # Invalid and missing contacts cannot get a draft
    assert client.post("/outreach/generate", json={"restaurant_id": ids["Quiet Bistro"]}).status_code == 422

    # 7. Individual and bulk selection feed the campaign; duplicate ids are collapsed
    selection = [ids["Karahi Corner"], ids["Kebab Point"], ids["Opt Out Grill"], ids["Quiet Bistro"],
                 ids["Chaat Corner"], ids["Burger Stop"], demo_id, ids["Karahi Corner"]]
    preview = client.post("/campaigns/preview", json={"name": "Faisalabad Fast Food", "restaurant_ids": selection})
    assert preview.status_code == 200
    body = preview.json()
    assert body["eligible_count"] == 3
    reasons = {i["restaurant_id"]: i["reasons"] for i in body["items"]}
    assert reasons[demo_id] and "Demo or sample" in reasons[demo_id][0]
    assert "No public email found" in reasons[ids["Quiet Bistro"]]
    assert any("Not qualified" in r for r in reasons[ids["Chaat Corner"]])

    # 8. Campaign creation generates one draft per eligible restaurant
    created = client.post("/campaigns", json={"name": "Faisalabad Fast Food", "restaurant_ids": selection})
    assert created.status_code == 201, created.text
    campaign = created.json()
    cid = campaign["id"]
    assert campaign["status"] == "review"
    assert campaign["counts"]["total_selected"] == 7
    assert campaign["counts"]["eligible"] == 3
    assert campaign["counts"]["drafts_generated"] == 3
    karahi_row = next(r for r in campaign["recipients"] if r["restaurant_name"] == "Karahi Corner")
    kebab_row = next(r for r in campaign["recipients"] if r["restaurant_name"] == "Kebab Point")
    optout_row = next(r for r in campaign["recipients"] if r["restaurant_name"] == "Opt Out Grill")
    assert len({karahi_row["subject"], kebab_row["subject"], optout_row["subject"]}) == 3

    # A restaurant opts out after its draft exists: its draft must never be sent
    assert client.post(f"/restaurants/{ids['Opt Out Grill']}/opt-out").status_code == 200
    blocked = client.post(f"/outreach/drafts/{optout_row['draft_id']}/approve")
    assert blocked.status_code == 422

    # 9. Only approved drafts are sent
    client.post(f"/outreach/drafts/{karahi_row['draft_id']}/approve")
    client.post(f"/outreach/drafts/{kebab_row['draft_id']}/approve")
    sent = _send(client, cid)
    assert sent.status_code == 200, sent.text
    result = sent.json()
    assert result["status"] == "completed"
    assert result["counts"]["sent"] == 2
    assert result["counts"]["approved"] == 2
    assert result["counts"]["skipped"] == 4
    recipients = [m["to"][0] for m in world["sender"].outbox]
    assert recipients == ["info@karahicorner.pk", "orders@kebabpoint.pk"]
    for message in world["sender"].outbox:
        assert "cc" not in message and "bcc" not in message
        assert message["unsubscribe_url"] in message["body"]
    karahi_token = make_token(SECRET, karahi_row["id"])
    assert f"r={karahi_row['id']}&t={karahi_token}" in world["sender"].outbox[0]["unsubscribe_url"]

    # 10. Campaign analytics and the list view
    listing = client.get("/campaigns").json()
    summary = next(c for c in listing if c["id"] == cid)
    assert summary["counts"]["sent"] == 2
    detail = client.get(f"/campaigns/{cid}").json()
    assert detail["counts"]["failed"] == 0
    assert next(r for r in detail["recipients"] if r["id"] == optout_row["id"])["status"] == "draft"

    # Duplicate campaign: the same name cannot email the same address again
    dup = client.post("/campaigns/preview", json={"name": "Faisalabad Fast Food",
                                                  "restaurant_ids": [ids["Karahi Corner"]]}).json()
    assert dup["eligible_count"] == 0
    assert any("already received" in r or "Already emailed" in r for r in dup["items"][0]["reasons"])

    # 11. Failed send, then safe retry, in a follow-up campaign. Karahi Corner was already emailed above, and a
    # restaurant already emailed by another campaign is never contacted again, so the follow-up uses a new lead.
    from models.database import execute, fetch_one
    workspace_id = fetch_one("SELECT MIN(id) AS id FROM workspaces")["id"]
    execute(
        "INSERT INTO restaurants (place_id, name, address, source, website, contact_email, contact_email_status, "
        "contact_email_classification, lead_status, lead_score, workspace_id) VALUES "
        "('p-retry', 'Retry Grill', 'Civil Lines, Faisalabad, Pakistan', 'google_places', 'https://retrygrill.pk/', "
        "'retry@grill.pk', 'domain_valid', 'business', 'qualified', 80, :ws)",
        {"ws": workspace_id},
    )
    retry_id = fetch_one("SELECT id FROM restaurants WHERE place_id = 'p-retry'")["id"]
    follow = client.post("/campaigns", json={"name": "Faisalabad Follow-up", "restaurant_ids": [retry_id]}).json()
    follow_id = follow["id"]
    follow_draft = follow["recipients"][0]["draft_id"]
    client.post(f"/outreach/drafts/{follow_draft}/approve")
    world["sender"].fail_addresses = {"retry@grill.pk"}
    failed = _send(client, follow_id).json()
    assert failed["counts"]["failed"] == 1
    assert failed["counts"]["retryable"] == 1
    assert failed["recipients"][0]["error_reason"]

    world["sender"].fail_addresses = set()
    retried = client.post(f"/campaigns/{follow_id}/retry-failed").json()
    assert retried["counts"]["sent"] == 1
    assert retried["counts"]["failed"] == 0
    assert [m["to"][0] for m in world["sender"].outbox].count("retry@grill.pk") == 1
    again = client.post(f"/campaigns/{follow_id}/retry-failed")
    assert again.status_code == 409
    assert len(world["sender"].outbox) == 3

    # 12. Unsubscribe suppresses the address everywhere
    token = make_token(SECRET, karahi_row["id"])
    assert client.get(f"/unsubscribe?r={karahi_row['id']}&t={token}").status_code == 200
    assert client.post(f"/unsubscribe?r={karahi_row['id']}&t={token}").status_code == 200
    later = client.post("/campaigns/preview", json={"name": "Spring Check",
                                                   "restaurant_ids": [ids["Karahi Corner"]]}).json()
    assert later["eligible_count"] == 0
    assert any("suppression" in r for r in later["items"][0]["reasons"])


def test_failed_contact_search_keeps_previously_found_email(client, world):
    keep = save_restaurants([{"place_id": "p-keep", "name": "Keep Cafe", "address": "Civil Lines, Faisalabad, Pakistan",
                              "website": "https://keepcafe.pk/", "source": "google_places"}])[0]["id"]
    assert client.post(f"/restaurants/{keep}/discover-contact").json()["contact_email"] == "info@keepcafe.pk"

    async def site_down(client_, url):
        return 503, b"", url

    with patch("services.contact_discovery.fetch_page", new=site_down):
        after = client.post(f"/restaurants/{keep}/discover-contact").json()
    assert after["contact_email"] == "info@keepcafe.pk"
    assert after["contact_discovered_at"] is not None


def test_malformed_email_cannot_get_a_draft_or_approval(client, world):
    rid = save_restaurants([{"place_id": "p-malformed", "name": "Malformed Mail Cafe",
                             "address": "Peoples Colony, Faisalabad, Pakistan", "source": "google_places"}])[0]["id"]
    _set(os.environ["DATABASE_URL"], "Malformed Mail Cafe", contact_email="owner@cafe",
         lead_status="qualified", contact_email_status="unverified")

    rules = client.get("/outreach/eligibility").json()
    assert rules[str(rid)]["reasons"] == ["Email is not a valid business address"]
    assert client.post("/outreach/generate", json={"restaurant_id": rid}).status_code == 422

    _set(os.environ["DATABASE_URL"], "Malformed Mail Cafe", contact_email="owner@cafe.pk")
    draft = client.post("/outreach/generate", json={"restaurant_id": rid}).json()
    _set(os.environ["DATABASE_URL"], "Malformed Mail Cafe", contact_email="owner@cafe")
    assert client.post(f"/outreach/drafts/{draft['id']}/approve").status_code == 422
    assert client.post(f"/outreach/drafts/{draft['id']}/regenerate").status_code == 422


def _set(db_path, name, **fields):
    from models.database import execute
    assignments = ", ".join(f"{column} = :{column}" for column in fields)
    execute(f"UPDATE restaurants SET {assignments} WHERE name = :_name", {**fields, "_name": name})
