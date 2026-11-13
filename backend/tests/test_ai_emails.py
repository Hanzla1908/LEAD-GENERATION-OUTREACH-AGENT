"""Industry-specific AI email drafts: personalisation, review edits, and regeneration with instructions.

Claude is always stubbed here. The tests check what is sent to it, and what the review workspace records.
"""
import json
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import main
from models.database import create_draft, execute, fetch_one, save_restaurants, update_draft_content
from services import industries
from services.outreach import build_prompt, choose_angle
from tests.account_helpers import TEST_SESSION_SECRET, signed_in_client

SIX = {
    "restaurants_food": ("Gulberg Biryani Point", "biryani", "Biryani"),
    "real_estate": ("Gulberg Homes", "agency", "Property agency"),
    "education": ("City Academy", "school", "Schools and academies"),
    "healthcare": ("Care Clinic", "clinic", "Clinics"),
    "solar_home_services": ("Sun Power Pakistan", "solar_installers", "Solar installers"),
    "manufacturing_wholesale": ("Steel Works Ltd", "manufacturer", "Manufacturers"),
}


def _business(industry: str, name: str, subcategory: str) -> dict:
    return {
        "name": name, "industry": industry, "subcategory": subcategory, "city": "Lahore",
        "address": "1 Main Road, Lahore, Pakistan", "website_status": "present",
        "website_features": {}, "phone": "0300-0000000", "contact_email": "owner@example.pk",
    }


@pytest.mark.parametrize("industry", list(SIX))
def test_each_industry_prompt_names_its_own_business_type_and_services(industry):
    name, subcategory, label = SIX[industry]
    prompt = build_prompt(_business(industry, name, subcategory), "general")
    assert name in prompt
    assert f"Business type: {label}" in prompt
    assert "City: Lahore" in prompt
    for service in industries.outreach(industry)["services"]:
        assert service in prompt


def test_non_restaurant_prompts_never_use_restaurant_wording():
    for industry, (name, subcategory, _) in SIX.items():
        if industry == "restaurants_food":
            continue
        prompt = build_prompt(_business(industry, name, subcategory), "general").lower()
        assert "restaurant" not in prompt, industry
        assert "menu" not in prompt, industry
        assert "food order" not in prompt, industry


def test_the_restaurant_prompt_keeps_restaurant_wording():
    prompt = build_prompt(_business("restaurants_food", "Gulberg Biryani Point", "biryani"), "general")
    assert "restaurant" in prompt.lower()


def test_the_opportunity_drives_the_angle_for_each_industry():
    solar = _business("solar_home_services", "Sun Power", "solar_installers")
    solar["website_features"] = {"quote_request": {"status": "not_found", "evidence": []}}
    assert choose_angle(solar) == "quote_gap"
    estate = _business("real_estate", "Gulberg Homes", "agency")
    estate["website_features"] = {"inquiry_form": {"status": "present", "evidence": ["https://x.pk/enquire"]}}
    assert choose_angle(estate) == "inquiry_upgrade"


def test_tone_and_goals_come_from_the_industry_configuration():
    prompt = build_prompt(_business("solar_home_services", "Sun Power", "solar_installers"), "general")
    assert "Tone: Practical and plain-spoken" in prompt
    assert "Goal of the email:" in prompt


def test_reviewer_instructions_are_added_only_when_given():
    business = _business("education", "City Academy", "school")
    plain = build_prompt(business, "general")
    assert "Reviewer instructions" not in plain
    with_notes = build_prompt(business, "general", "Mention the free admissions counselling")
    assert "Reviewer instructions (follow them, but never invent facts): Mention the free admissions counselling" in with_notes


@pytest.fixture
def api(test_db, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-key")
    return signed_in_client(main.app)


def _reply(subject: str, body: str):
    message = MagicMock()
    message.content = [MagicMock(text=json.dumps({"subject": subject, "body": body}))]
    return message


def _draft_for(place_id: str, name: str, industry: str, subcategory: str) -> tuple[int, int]:
    rid = save_restaurants([{"place_id": place_id, "name": name, "source": "google_places"}])[0]["id"]
    execute("UPDATE restaurants SET industry = :i, subcategory = :s, city = 'Lahore', contact_email = 'owner@ex.pk', "
            "contact_email_status = 'domain_valid', contact_email_classification = 'business' WHERE id = :id",
            {"i": industry, "s": subcategory, "id": rid})
    draft = create_draft(rid, "Spring", "First subject", "First body")
    return rid, draft["id"]


def test_a_changed_draft_records_when_it_was_edited(test_db):
    _, did = _draft_for("edit-1", "Edit Cafe", "restaurants_food", "all")
    assert fetch_one("SELECT edited_at FROM email_drafts WHERE id = :id", {"id": did})["edited_at"] is None
    update_draft_content(did, subject="First subject", body="First body")
    assert fetch_one("SELECT edited_at FROM email_drafts WHERE id = :id", {"id": did})["edited_at"] is None
    update_draft_content(did, body="A better body")
    assert fetch_one("SELECT edited_at FROM email_drafts WHERE id = :id", {"id": did})["edited_at"] is not None


def test_regeneration_passes_the_reviewer_instructions_to_claude(api, monkeypatch):
    rid, did = _draft_for("regen-1", "Sun Power", "solar_home_services", "solar_installers")
    sent = {}
    client = MagicMock()

    def create(**kwargs):
        sent.update(kwargs)
        return _reply("New subject", "New body for the solar company.")

    client.messages.create.side_effect = create
    monkeypatch.setattr("services.outreach.anthropic.Anthropic", lambda api_key: client)
    resp = api.post(f"/outreach/drafts/{did}/regenerate", json={"instructions": "Keep it under 80 words"})
    assert resp.status_code == 200, resp.text
    assert "Keep it under 80 words" in sent["messages"][0]["content"]
    assert fetch_one("SELECT status FROM email_drafts WHERE id = :id", {"id": did})["status"] == "rejected"
    assert resp.json()["status"] == "draft"


def test_regeneration_without_instructions_still_works(api, monkeypatch):
    rid, did = _draft_for("regen-2", "Steel Works", "manufacturing_wholesale", "manufacturer")
    client = MagicMock()
    client.messages.create.return_value = _reply("Quote request", "A short note about quotations.")
    monkeypatch.setattr("services.outreach.anthropic.Anthropic", lambda api_key: client)
    resp = api.post(f"/outreach/drafts/{did}/regenerate")
    assert resp.status_code == 200, resp.text
    assert "Reviewer instructions" not in client.messages.create.call_args.kwargs["messages"][0]["content"]
