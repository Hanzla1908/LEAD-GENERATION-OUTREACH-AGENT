"""
Phase 5: outreach service and draft CRUD tests — all Claude calls mocked.
"""
import json
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from models.database import (
    init_db,
    save_restaurants,
    mark_opted_out,
    create_draft,
    get_draft,
    list_drafts,
    update_draft_content,
    set_draft_status,
)
from services.outreach import choose_angle, build_prompt, generate_draft


# ── DB fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path, monkeypatch):
    from tests.conftest import use_database
    return use_database(tmp_path, monkeypatch)


@pytest.fixture
def restaurant(db):
    rows = save_restaurants([{
        "place_id": "outreach_place_1",
        "name": "Test Bistro",
        "address": "1 Main St, Testville",
        "phone": "+1-555-0001",
        "website": "https://testbistro.example.com",
        "source": "google_places",
    }])
    return rows[0]


# ── choose_angle ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ws,os_,expected", [
    ("not_found",  "unknown",   "website_gap"),
    ("present",    "not_found", "ordering_gap"),
    ("present",    "present",   "ai_assistant"),
    ("unknown",    "unknown",   "general"),
    ("present",    "unknown",   "general"),
])
def test_choose_angle(ws, os_, expected):
    assert choose_angle({"website_status": ws, "ordering_status": os_}) == expected


# ── build_prompt ──────────────────────────────────────────────────────────────

def test_build_prompt_contains_name():
    r = {"name": "Lucky Dragon", "website_status": "present", "ordering_status": "not_found"}
    prompt = build_prompt(r, "ordering_gap")
    assert "Lucky Dragon" in prompt
    assert "ordering_gap" in prompt or "online ordering" in prompt


# ── generate_draft (mocked) ───────────────────────────────────────────────────

def _mock_anthropic(subject="Act Now!", body="Hello restaurant."):
    mock_client = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=json.dumps({"subject": subject, "body": body}))]
    mock_client.messages.create.return_value = mock_msg
    return mock_client


@pytest.mark.asyncio
async def test_generate_draft_returns_subject_body(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("services.outreach.anthropic.Anthropic", return_value=_mock_anthropic()):
        result = await generate_draft({
            "name": "Test Bistro",
            "website_status": "present",
            "ordering_status": "not_found",
        })
    assert "subject" in result
    assert "body" in result
    assert result["angle"] == "ordering_gap"


@pytest.mark.asyncio
async def test_generate_draft_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        await generate_draft({"name": "X"})


@pytest.mark.asyncio
async def test_generate_draft_raises_on_bad_json(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_client = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text="not json at all")]
    mock_client.messages.create.return_value = mock_msg
    with patch("services.outreach.anthropic.Anthropic", return_value=mock_client):
        with pytest.raises(ValueError, match="non-JSON"):
            await generate_draft({"name": "X"})


@pytest.mark.asyncio
async def test_generate_draft_raises_on_empty_fields(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    mock_client = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=json.dumps({"subject": "", "body": "some body"}))]
    mock_client.messages.create.return_value = mock_msg
    with patch("services.outreach.anthropic.Anthropic", return_value=mock_client):
        with pytest.raises(ValueError, match="empty subject or body"):
            await generate_draft({"name": "X"})


# ── DB: create / get / list ───────────────────────────────────────────────────

def test_create_and_get_draft(restaurant, db):
    draft = create_draft(
        restaurant_id=restaurant["id"],
        campaign="default",
        subject="Test Subject",
        body="Test Body",
        angle="ordering_gap",
    )
    assert draft["id"] is not None
    assert draft["status"] == "draft"
    assert draft["subject"] == "Test Subject"

    fetched = get_draft(draft["id"])
    assert fetched["id"] == draft["id"]
    assert fetched["angle"] == "ordering_gap"


def test_get_draft_not_found(db):
    assert get_draft(99999) is None


def test_list_drafts_empty(db):
    assert list_drafts() == []


def test_list_drafts_filtered(restaurant, db):
    create_draft(restaurant["id"], "campaign_a", "Subject A", "Body A")
    create_draft(restaurant["id"], "campaign_b", "Subject B", "Body B")
    all_drafts = list_drafts(restaurant_id=restaurant["id"])
    assert len(all_drafts) == 2


# ── DB: duplicate prevention ──────────────────────────────────────────────────

def test_duplicate_active_draft_raises(restaurant, db):
    create_draft(restaurant["id"], "default", "First", "Body 1")
    with pytest.raises(ValueError, match="active draft already exists"):
        create_draft(restaurant["id"], "default", "Second", "Body 2")


def test_duplicate_prevention_uses_campaign_key(restaurant, db):
    create_draft(restaurant["id"], "campaign_a", "A", "Body A")
    # Different campaign — should NOT raise
    draft_b = create_draft(restaurant["id"], "campaign_b", "B", "Body B")
    assert draft_b["campaign"] == "campaign_b"


def test_rejected_draft_allows_new_draft(restaurant, db):
    d1 = create_draft(restaurant["id"], "default", "First", "Body 1")
    set_draft_status(d1["id"], "rejected")
    d2 = create_draft(restaurant["id"], "default", "Second", "Body 2")
    assert d2["id"] != d1["id"]


# ── DB: update_draft_content ──────────────────────────────────────────────────

def test_update_draft_content(restaurant, db):
    draft = create_draft(restaurant["id"], "default", "Old Subject", "Old Body")
    updated = update_draft_content(draft["id"], subject="New Subject", body="New Body")
    assert updated["subject"] == "New Subject"
    assert updated["body"] == "New Body"


def test_update_draft_partial(restaurant, db):
    draft = create_draft(restaurant["id"], "default", "Subject", "Original Body")
    updated = update_draft_content(draft["id"], body="Changed Body")
    assert updated["subject"] == "Subject"
    assert updated["body"] == "Changed Body"


def test_update_draft_not_found(db):
    assert update_draft_content(99999, subject="X") is None


# ── DB: status transitions ────────────────────────────────────────────────────

def test_approve_draft(restaurant, db):
    draft = create_draft(restaurant["id"], "default", "S", "B")
    updated = set_draft_status(draft["id"], "approved")
    assert updated["status"] == "approved"


def test_reject_draft(restaurant, db):
    draft = create_draft(restaurant["id"], "default", "S", "B")
    updated = set_draft_status(draft["id"], "rejected")
    assert updated["status"] == "rejected"


def test_list_drafts_by_status(restaurant, db):
    d1 = create_draft(restaurant["id"], "c1", "S1", "B1")
    d2 = create_draft(restaurant["id"], "c2", "S2", "B2")
    set_draft_status(d1["id"], "approved")
    approved = list_drafts(status="approved")
    assert len(approved) == 1
    assert approved[0]["id"] == d1["id"]
    pending = list_drafts(status="draft")
    assert len(pending) == 1
    assert pending[0]["id"] == d2["id"]


# ── Opt-out ───────────────────────────────────────────────────────────────────

def test_mark_opted_out(restaurant, db):
    from models.database import get_restaurant_by_id
    mark_opted_out(restaurant["id"])
    r = get_restaurant_by_id(restaurant["id"])
    assert r["opted_out"] == 1


# ── FastAPI endpoint integration ──────────────────────────────────────────────

from fastapi.testclient import TestClient
from main import app

client = None


@pytest.fixture(autouse=True)
def _signed_in(test_db):
    """Each test gets a fresh database and a client signed in as the default admin."""
    global client
    from tests.account_helpers import signed_in_client

    client = signed_in_client(app)


@pytest.fixture
def api_restaurant(db, monkeypatch):
    """Save a restaurant with a contact email for API tests."""
    rows = save_restaurants([{
        "place_id": "api_outreach_place",
        "name": "API Bistro",
        "address": "42 Test Ave",
        "source": "google_places",
    }])
    rid = rows[0]["id"]
    # Manually set contact email via DB (mimicking Phase 4 contact discovery)
    from models.database import execute
    execute(
        "UPDATE restaurants SET contact_email = :email, contact_email_status = :status WHERE id = :rid",
        {"email": "owner@apibistro.example.com", "status": "unverified", "rid": rid},
    )
    return rid


def test_api_list_drafts_empty(db):
    resp = client.get("/outreach/drafts")
    assert resp.status_code == 200
    assert resp.json() == []


def test_api_generate_draft(api_restaurant, db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("services.outreach.anthropic.Anthropic", return_value=_mock_anthropic("Subject!", "Body text.")):
        resp = client.post("/outreach/generate", json={"restaurant_id": api_restaurant, "campaign": "default"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "draft"
    assert data["restaurant_id"] == api_restaurant


def test_api_generate_duplicate_returns_409(api_restaurant, db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("services.outreach.anthropic.Anthropic", return_value=_mock_anthropic()):
        client.post("/outreach/generate", json={"restaurant_id": api_restaurant, "campaign": "default"})
    with patch("services.outreach.anthropic.Anthropic", return_value=_mock_anthropic()):
        resp = client.post("/outreach/generate", json={"restaurant_id": api_restaurant, "campaign": "default"})
    assert resp.status_code == 409


def test_api_generate_no_contact_returns_422(db):
    rows = save_restaurants([{"place_id": "no_contact_place", "name": "No Email", "source": "google_places"}])
    rid = rows[0]["id"]
    resp = client.post("/outreach/generate", json={"restaurant_id": rid})
    assert resp.status_code == 422


def test_api_generate_opted_out_returns_422(api_restaurant, db):
    mark_opted_out(api_restaurant)
    resp = client.post("/outreach/generate", json={"restaurant_id": api_restaurant})
    assert resp.status_code == 422


def test_api_approve_draft(api_restaurant, db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("services.outreach.anthropic.Anthropic", return_value=_mock_anthropic()):
        gen = client.post("/outreach/generate", json={"restaurant_id": api_restaurant, "campaign": "approve_test"})
    draft_id = gen.json()["id"]
    resp = client.post(f"/outreach/drafts/{draft_id}/approve")
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


def test_api_reject_draft(api_restaurant, db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("services.outreach.anthropic.Anthropic", return_value=_mock_anthropic()):
        gen = client.post("/outreach/generate", json={"restaurant_id": api_restaurant, "campaign": "reject_test"})
    draft_id = gen.json()["id"]
    resp = client.post(f"/outreach/drafts/{draft_id}/reject")
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"


def test_api_edit_draft(api_restaurant, db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("services.outreach.anthropic.Anthropic", return_value=_mock_anthropic()):
        gen = client.post("/outreach/generate", json={"restaurant_id": api_restaurant, "campaign": "edit_test"})
    draft_id = gen.json()["id"]
    resp = client.put(f"/outreach/drafts/{draft_id}", json={"subject": "New Subject", "body": "New Body"})
    assert resp.status_code == 200
    assert resp.json()["subject"] == "New Subject"


def test_api_regenerate_draft(api_restaurant, db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("services.outreach.anthropic.Anthropic", return_value=_mock_anthropic("First", "First body")):
        gen = client.post("/outreach/generate", json={"restaurant_id": api_restaurant, "campaign": "regen_test"})
    old_id = gen.json()["id"]
    with patch("services.outreach.anthropic.Anthropic", return_value=_mock_anthropic("Second", "Second body")):
        resp = client.post(f"/outreach/drafts/{old_id}/regenerate")
    assert resp.status_code == 200
    new_draft = resp.json()
    assert new_draft["id"] != old_id
    assert new_draft["status"] == "draft"
    # Old draft should be rejected
    old = client.get(f"/outreach/drafts/{old_id}").json()
    assert old["status"] == "rejected"


def test_api_opt_out(api_restaurant, db):
    resp = client.post(f"/restaurants/{api_restaurant}/opt-out")
    assert resp.status_code == 200
    assert resp.json()["opted_out"] == 1


def test_api_approve_opted_out_returns_422(api_restaurant, db, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with patch("services.outreach.anthropic.Anthropic", return_value=_mock_anthropic()):
        gen = client.post("/outreach/generate", json={"restaurant_id": api_restaurant, "campaign": "opt_approve"})
    draft_id = gen.json()["id"]
    mark_opted_out(api_restaurant)
    resp = client.post(f"/outreach/drafts/{draft_id}/approve")
    assert resp.status_code == 422
