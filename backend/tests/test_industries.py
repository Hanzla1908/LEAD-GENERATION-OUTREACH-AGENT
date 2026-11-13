"""Multi-industry foundation: profiles, discovery, website features, qualification, outreach and migration.

Four industries are exercised end to end (Restaurants & Food, Real Estate, Education and Healthcare), and the
tests check that they really differ: queries, features, scoring explanations and outreach wording.
No network: Google Places, website fetches and Claude are all stubbed.
"""
import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

import main
from agents.lead_qualifier import compute_score, qualify_lead, score_to_status
from models.database import execute, fetch_all, fetch_one, save_restaurants
from services import industries
from services.industries import DEFAULT_INDUSTRY, IndustryConfigError
from services.search_profiles import CATEGORY_PROFILES, build_query
from services.outreach import build_prompt, choose_angle, generate_draft
from services.website_checker import check_website, find_feature_evidence
from tests.account_helpers import TEST_SESSION_SECRET, signed_in_client

BACKEND = Path(__file__).resolve().parent.parent
FOUR = ["restaurants_food", "real_estate", "education", "healthcare"]


# ── 1. Configuration ─────────────────────────────────────────────────────────

def test_the_file_defines_all_ten_industries():
    keys = set(industries.load())
    assert keys == {
        "restaurants_food", "real_estate", "education", "healthcare", "home_services",
        "automotive", "hospitality_travel", "manufacturing_wholesale", "beauty_fitness_wellness",
        "professional_services", "solar_home_services",
    }


def test_restaurant_subcategories_match_the_original_constants():
    legacy = {
        "all": ("restaurants", None), "desi": ("Pakistani restaurant", None),
        "fast_food": ("fast food restaurant", "fast_food_restaurant"),
        "pizza": ("pizza restaurant", "pizza_restaurant"),
        "cafe": ("cafe coffee shop", "cafe"),
    }
    for key, (text, included) in legacy.items():
        assert CATEGORY_PROFILES[key].text == text
        assert CATEGORY_PROFILES[key].included_type == included


def test_every_industry_has_a_primary_feature_and_outreach_text():
    for key, profile in industries.load().items():
        feature_keys = [f["key"] for f in profile["website_features"]]
        assert profile["primary_feature"] in feature_keys, key
        assert profile["outreach"]["instructions"].strip(), key
        assert profile["outreach"]["services"], key


def _config_with(mutate):
    config = json.loads((BACKEND / "industries.json").read_text(encoding="utf-8"))
    mutate(config)
    return config


def test_a_custom_industry_added_through_configuration_loads_without_code_changes():
    def add(config):
        custom = copy.deepcopy(next(i for i in config["industries"] if i["key"] == "real_estate"))
        custom["key"] = "pet_grooming"
        custom["name"] = "Pet grooming"
        custom["business_noun"] = "grooming salon"
        custom["subcategories"] = [{"key": "dog", "name": "Dog grooming", "search_text": "dog grooming salon",
                                    "provider_type": None}]
        config["industries"].append(custom)

    profiles = industries.validate(_config_with(add))
    assert profiles["pet_grooming"]["name"] == "Pet grooming"
    assert profiles["pet_grooming"]["subcategories"][0]["search_text"] == "dog grooming salon"


@pytest.mark.parametrize("mutate, message", [
    (lambda c: c["industries"].append(copy.deepcopy(c["industries"][0])), "more than once"),
    (lambda c: c["industries"][1].update(key="Bad Key"), "lowercase letters"),
    (lambda c: c["industries"][1].update(primary_feature="nope"), "primary_feature"),
    (lambda c: c["industries"][1]["thresholds"].update(qualified=10), "qualified must be higher"),
    (lambda c: c["industries"][1].update(subcategories=[]), "at least one subcategory"),
    (lambda c: c["industries"][1]["outreach"]["angles"].pop("general"), "missing the text"),
    (lambda c: c["industries"].pop(0), "default industry"),
])
def test_an_invalid_configuration_is_rejected_with_a_clear_message(mutate, message):
    with pytest.raises(IndustryConfigError, match=message):
        industries.validate(_config_with(mutate))


def test_custom_fields_keep_only_declared_keys_within_their_limit():
    cleaned = industries.sanitize_custom_fields("real_estate", {
        "property_types": "  Houses   and plots ", "unknown_field": "dropped", "property_types_x": "x",
    })
    assert cleaned == {"property_types": "Houses and plots"}
    with pytest.raises(ValueError, match="120 characters"):
        industries.sanitize_custom_fields("real_estate", {"property_types": "x" * 121})


# ── 2. Discovery: different queries per industry ──────────────────────────────

def test_each_industry_builds_its_own_search_query():
    queries = {ind: build_query(ind, industries.default_subcategory(ind)["key"], "Lahore")[0] for ind in FOUR}
    assert len(set(queries.values())) == len(FOUR)
    assert "restaurant" in queries["restaurants_food"].lower()
    assert "real estate" in queries["real_estate"].lower()
    assert "school" in queries["education"].lower() or "academy" in queries["education"].lower()
    assert "clinic" in queries["healthcare"].lower()


@pytest.fixture
def api(test_db, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    return signed_in_client(main.app)


def test_demo_discovery_works_without_google_credentials_and_labels_samples(api):
    resp = api.post("/restaurants/discover", json={"city": "Lahore", "industry": "real_estate",
                                                   "subcategory": "agency", "limit": 2})
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 2
    assert all(row["name"].startswith("[DEMO]") and row["source"] == "demo" for row in rows)
    assert all(row["industry"] == "real_estate" and row["subcategory"] == "agency" for row in rows)
    assert "Property agency" in rows[0]["name"]


def test_rediscovering_the_same_place_does_not_duplicate_it(api):
    body = {"city": "Lahore", "industry": "education", "subcategory": "school", "limit": 2}
    api.post("/restaurants/discover", json=body)
    api.post("/restaurants/discover", json=body)
    count = fetch_one("SELECT COUNT(*) AS n FROM restaurants WHERE industry = 'education'")["n"]
    assert count == 2


def test_restaurant_requests_without_an_industry_are_restaurants(api):
    resp = api.post("/restaurants/discover", json={"city": "Karachi", "category": "pizza", "limit": 1})
    assert resp.status_code == 200, resp.text
    row = resp.json()[0]
    assert row["industry"] == "restaurants_food"
    assert row["subcategory"] == "pizza"
    assert row["name"].startswith("[DEMO] Pizza")


def test_an_unknown_industry_or_a_foreign_subcategory_is_refused(api):
    assert api.post("/restaurants/discover", json={"city": "Lahore", "industry": "space_tourism"}).status_code == 422
    assert api.post("/restaurants/discover", json={"city": "Lahore", "industry": "real_estate",
                                                   "subcategory": "pizza"}).status_code == 422


def test_live_search_uses_the_industry_query_and_provider_type(api, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-key-not-used")
    captured = {}

    async def fake_search(query, max_results, api_key, included_type=None, region_code="PK"):
        captured.update(query=query, included_type=included_type)
        return []

    with patch.object(main, "search_restaurants", new=fake_search):
        api.post("/restaurants/discover", json={"city": "Lahore", "industry": "healthcare",
                                                "subcategory": "dental", "limit": 3})
    assert captured["query"] == "dental clinic dentist in Lahore, Pakistan"
    assert captured["included_type"] == "dentist"


def test_the_industries_endpoint_lists_profiles_for_the_search_form(api):
    resp = api.get("/industries")
    assert resp.status_code == 200
    by_key = {item["key"]: item for item in resp.json()}
    assert {"restaurants_food", "real_estate", "education", "healthcare"} <= set(by_key)
    assert by_key["real_estate"]["subcategories"][0]["key"] == "agency"
    assert any(f["key"] == "inquiry_form" for f in by_key["real_estate"]["features"])


# ── 3. Website analysis: industry features, never guessed ─────────────────────

REAL_ESTATE_PAGE = """
<html><body>
  <a href="/properties">Properties for sale</a>
  <a href="/enquire">Enquire now</a>
  <a href="/projects">Our projects</a>
</body></html>
"""

HEALTHCARE_PAGE = """
<html><body>
  <a href="/services">Our services</a>
  <button>Book an appointment</button>
</body></html>
"""


def _patch_site(body: str | None, status: int = 200):
    from unittest.mock import patch as _p
    stack = [
        _p("services.website_checker.is_blocked_ip", return_value=False),
        _p("services.website_checker.check_robots", new=AsyncMock(return_value=True)),
    ]
    if body is None:
        stack.append(_p("services.website_checker.fetch_page", new=AsyncMock(side_effect=TimeoutError())))
    else:
        stack.append(_p("services.website_checker.fetch_page",
                        new=AsyncMock(return_value=(status, body.encode(), "https://clinic.example.pk/"))))
    return stack


async def _check(body, industry, status=200):
    patches = _patch_site(body, status)
    for p in patches:
        p.start()
    try:
        return await check_website("https://clinic.example.pk/", industry=industry)
    finally:
        for p in patches:
            p.stop()


async def test_real_estate_features_are_found_with_evidence():
    result = await _check(REAL_ESTATE_PAGE, "real_estate")
    assert result["features"]["listings"]["status"] == "present"
    assert result["features"]["inquiry_form"]["status"] == "present"
    assert result["features"]["inquiry_form"]["evidence"]
    assert result["features"]["project_pages"]["status"] == "present"


async def test_a_feature_absent_from_a_readable_page_is_not_found_but_an_unreadable_one_is_unknown():
    readable = await _check(HEALTHCARE_PAGE, "healthcare")
    assert readable["features"]["appointments"]["status"] == "present"
    assert readable["features"]["doctor_profiles"]["status"] == "not_found"

    unreadable = await _check(None, "healthcare")
    assert all(f["status"] == "unknown" for f in unreadable["features"].values())


async def test_a_404_homepage_is_website_not_found_and_features_stay_unknown():
    result = await _check("", "real_estate", status=404)
    assert result["website_status"] == "not_found"
    assert all(f["status"] == "unknown" for f in result["features"].values())


async def test_restaurant_ordering_detection_is_unchanged():
    page = '<html><body><a href="https://www.toasttab.com/x">Order online</a></body></html>'
    result = await _check(page, DEFAULT_INDUSTRY)
    assert result["ordering_status"] == "present"
    assert result["features"]["ordering"]["status"] == "present"
    assert result["features"]["menu"]["status"] == "not_found"


def test_the_feature_helper_reads_only_the_industry_keywords():
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(HEALTHCARE_PAGE, "html.parser")
    feature = industries.feature_by_key("healthcare", "appointments")
    assert find_feature_evidence(soup, "https://x/", feature)
    assert find_feature_evidence(soup, "https://x/", industries.feature_by_key("real_estate", "listings")) == []


# ── 4. Qualification: industry rules and explained scores ─────────────────────

def _lead(industry, **fields):
    base = {"industry": industry, "website_status": "present", "website_features": {}, "phone": None,
            "contact_email": None, "contact_email_status": "unverified", "contact_email_classification": None}
    base.update(fields)
    return base


def test_a_real_estate_gap_is_scored_on_its_inquiry_form_not_on_ordering():
    lead = _lead("real_estate", website_features={"inquiry_form": {"status": "not_found", "evidence": []}})
    score, breakdown = compute_score(lead)
    assert breakdown == {"website_present": 30, "inquiry_form_not_found": 25}
    assert score == 55


def test_a_restaurant_gap_is_scored_on_ordering():
    lead = _lead(DEFAULT_INDUSTRY, ordering_status="not_found")
    _, breakdown = compute_score(lead)
    assert breakdown == {"website_present": 30, "ordering_not_found": 25}


def test_an_uncertain_feature_is_never_counted_as_a_gap():
    lead = _lead("healthcare", website_features={"appointments": {"status": "unknown", "evidence": []}})
    _, breakdown = compute_score(lead)
    assert "appointments_not_found" not in breakdown
    assert "appointments_present" not in breakdown


def test_uncertain_leads_stay_in_review_rather_than_qualifying():
    lead = _lead("education", website_status="unknown")
    score, breakdown = compute_score(lead)
    assert score == 0 and breakdown == {}
    assert score_to_status(score, "education") == "disqualified"
    # A live website alone scores 30: between the thresholds, so it is kept for manual review.
    borderline = _lead("education", website_status="present")
    assert score_to_status(compute_score(borderline)[0], "education") == "needs_review"


async def test_the_reason_names_the_industry_feature_with_no_claude_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    lead = _lead("real_estate", website_features={"inquiry_form": {"status": "not_found", "evidence": []}})
    result = await qualify_lead(lead)
    assert "inquiry form" in result["lead_reason"].lower()
    assert "restaurant" not in result["lead_reason"].lower()


# ── 5. Outreach: industry-specific wording ───────────────────────────────────

def _captured_draft(monkeypatch, lead):
    seen = {}
    fake_message = MagicMock()
    fake_message.content = [MagicMock(text=json.dumps({"subject": "Hello", "body": "Hi there."}))]

    def fake_client(api_key):
        client = MagicMock()

        def create(**kwargs):
            seen.update(kwargs)
            return fake_message

        client.messages.create.side_effect = create
        return client

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setattr("services.outreach.anthropic.Anthropic", fake_client)
    import asyncio
    asyncio.run(generate_draft(lead))
    return seen


def test_real_estate_drafts_never_use_restaurant_wording(monkeypatch):
    lead = _lead("real_estate", name="Gulberg Homes", website_status="present",
                 website_features={"inquiry_form": {"status": "not_found", "evidence": []}})
    sent = _captured_draft(monkeypatch, lead)
    text = (sent["system"] + sent["messages"][0]["content"]).lower()
    assert "property" in text or "real estate" in text
    assert "restaurant" not in text
    assert "order" not in text and "menu" not in text


def test_each_industry_gets_its_own_outreach_instructions():
    texts = {ind: build_prompt(_lead(ind, name="Example"), "general") for ind in FOUR}
    assert len(set(texts.values())) == len(FOUR)
    assert "Real estate business name" in texts["real_estate"]
    assert "Clinic name" in texts["healthcare"]
    assert "restaurant" not in texts["healthcare"].lower()
    assert "restaurant" in texts["restaurants_food"].lower()


def test_restaurant_angles_are_unchanged():
    assert choose_angle({"website_status": "not_found"}) == "website_gap"
    assert choose_angle({"website_status": "present", "ordering_status": "not_found"}) == "ordering_gap"
    assert choose_angle({"website_status": "present", "ordering_status": "present"}) == "ai_assistant"
    assert choose_angle({"website_status": "unknown", "ordering_status": "unknown"}) == "general"


def test_real_estate_angles_use_their_own_keys():
    assert choose_angle(_lead("real_estate", website_features={
        "inquiry_form": {"status": "not_found", "evidence": []}})) == "inquiry_gap"
    assert choose_angle(_lead("real_estate", website_features={
        "inquiry_form": {"status": "present", "evidence": ["x"]}})) == "inquiry_upgrade"


def test_services_offered_are_the_industry_services_only():
    prompt = build_prompt(_lead("healthcare", name="City Clinic"), "general")
    assert "Online appointment booking" in prompt
    assert "Property listing website" not in prompt


# ── 6. Four industries together ───────────────────────────────────────────────

def test_the_four_industries_differ_in_query_criteria_and_outreach(api):
    differences = {}
    for industry in FOUR:
        sub = industries.default_subcategory(industry)["key"]
        profile = industries.get_industry(industry)
        differences[industry] = (
            build_query(industry, sub, "Lahore")[0],
            profile["primary_feature"],
            tuple(sorted(profile["scoring"].items())),
            build_prompt(_lead(industry, name="X"), "general"),
        )
    assert len({v[0] for v in differences.values()}) == 4
    assert len({v[1] for v in differences.values()}) == 4
    assert len({v[3] for v in differences.values()}) == 4


# ── 7. Migration 0010: existing records become restaurants ───────────────────

def _alembic_config() -> Config:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    return config


def test_existing_records_become_restaurants_and_the_downgrade_keeps_them(test_db):
    command.downgrade(_alembic_config(), "0009_workspaces")
    execute("INSERT INTO restaurants (place_id, name, source, workspace_id) VALUES ('legacy-1', 'Legacy Dhaba', "
            "'google_places', 1)")
    command.upgrade(_alembic_config(), "head")
    row = fetch_one("SELECT name, industry, subcategory FROM restaurants WHERE place_id = 'legacy-1'")
    assert row == {"name": "Legacy Dhaba", "industry": "restaurants_food", "subcategory": None}

    command.downgrade(_alembic_config(), "0009_workspaces")
    columns = {r["name"] for r in fetch_all("PRAGMA table_info(restaurants)")}
    assert "industry" not in columns and "website_features" not in columns
    assert fetch_one("SELECT COUNT(*) AS n FROM restaurants WHERE place_id = 'legacy-1'")["n"] == 1
    command.upgrade(_alembic_config(), "head")


def test_records_saved_without_an_industry_default_to_restaurants(test_db):
    saved = save_restaurants([{"place_id": "plain-1", "name": "Plain Place", "source": "google_places"}])
    assert saved[0]["industry"] == "restaurants_food"
    assert saved[0]["website_features"] == {}
