"""Global country and location support: the registry, city input, country-specific discovery and deduplication.

Google Places is always stubbed. Demo Mode needs no credentials. The five required searches are covered in both modes.
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import main
from models.database import execute, fetch_all, fetch_one, save_restaurants
from services import countries
from services.search_profiles import CITY_PATTERN, canonical_city
from tests.account_helpers import TEST_SESSION_SECRET, signed_in_client

# (country code, city, industry, subcategory, expected country name, expected query fragment)
SCENARIOS = [
    ("PK", "Faisalabad", "restaurants_food", "all", "Pakistan", "restaurants in Faisalabad, Pakistan"),
    ("US", "New York", "real_estate", "agency", "United States", "real estate agency in New York, United States"),
    ("GB", "London", "education", "school", "United Kingdom", "private school academy in London, United Kingdom"),
    ("AE", "Dubai", "healthcare", "clinic", "United Arab Emirates", "clinic medical centre in Dubai, United Arab Emirates"),
    ("AU", "Sydney", "home_services", "construction", "Australia", "construction contractor in Sydney, Australia"),
]


# ── Registry ─────────────────────────────────────────────────────────────────

def test_the_registry_holds_all_249_iso_countries_in_alphabetical_order():
    listed = countries.all_countries()
    assert len(listed) == 249
    names = [c["name"] for c in listed]
    assert names == sorted(names, key=lambda n: countries._sort_key(n))
    assert len({c["code"] for c in listed}) == 249


def test_pakistan_is_the_default_and_codes_are_normalised():
    assert countries.DEFAULT_COUNTRY_CODE == "PK"
    assert countries.country_name("pk") == "Pakistan"
    assert countries.country_name(" us ") == "United States"


@pytest.mark.parametrize("code", ["XK", "VD", "ZZ", "UK", "EU", "XX", ""])
def test_codes_that_are_not_iso_countries_are_refused(code):
    assert countries.is_known_country(code) is False


def test_the_country_list_endpoint_is_alphabetical_and_complete(test_db, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    body = signed_in_client(main.app).get("/countries").json()
    assert len(body) == 249
    assert {"code": "PK", "name": "Pakistan"} in body


# ── City input ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("city", ["New York", "São Paulo", "Zürich", "Al-Ain", "St. John's", "Dubai"])
def test_city_names_in_any_language_are_accepted(city):
    assert CITY_PATTERN.fullmatch(city)


@pytest.mark.parametrize("city", ["R4m", "Lahore!", "123"])
def test_city_names_with_digits_or_symbols_are_refused(city):
    assert not CITY_PATTERN.fullmatch(city)


def test_known_pakistani_cities_keep_their_standard_spelling_and_others_are_title_cased():
    assert canonical_city("karachi") == "Karachi"
    assert canonical_city("new york") == "New York"


# ── Discovery: the five required searches, in Demo Mode ───────────────────────

@pytest.fixture
def api(test_db, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    return signed_in_client(main.app)


@pytest.mark.parametrize("code, city, industry, sub, country_name, _query", SCENARIOS)
def test_demo_discovery_for_each_required_search(api, code, city, industry, sub, country_name, _query):
    resp = api.post("/restaurants/discover", json={
        "country_code": code, "city": city, "industry": industry, "subcategory": sub, "limit": 2,
    })
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len(rows) == 2
    for row in rows:
        assert row["source"] == "demo" and row["name"].startswith("[DEMO]")
        assert row["country_code"] == code
        assert row["country_name"] == country_name
        assert row["city"] == city
        assert country_name in row["address"]


def test_pakistan_demo_identifiers_are_unchanged(api):
    rows = api.post("/restaurants/discover", json={"country_code": "PK", "city": "Faisalabad",
                                                   "category": "biryani", "limit": 1}).json()
    assert rows[0]["place_id"] == "demo-faisalabad-biryani-1"


def test_other_countries_add_their_code_to_demo_identifiers(api):
    rows = api.post("/restaurants/discover", json={"country_code": "US", "city": "New York",
                                                   "industry": "real_estate", "subcategory": "agency",
                                                   "limit": 1}).json()
    assert rows[0]["place_id"].startswith("demo-us-real_estate-new-york-")


def test_the_same_city_name_in_two_countries_gives_two_separate_records(api):
    api.post("/restaurants/discover", json={"country_code": "PK", "city": "London", "category": "all", "limit": 1})
    api.post("/restaurants/discover", json={"country_code": "GB", "city": "London", "category": "all", "limit": 1})
    countries_found = {r["country_code"] for r in fetch_all(
        "SELECT country_code FROM restaurants WHERE city = 'London' AND source = 'demo'")}
    assert countries_found == {"PK", "GB"}


def test_an_unknown_country_code_is_refused(api):
    resp = api.post("/restaurants/discover", json={"country_code": "XK", "city": "Pristina", "limit": 1})
    assert resp.status_code == 422


def test_a_city_with_digits_is_refused(api):
    resp = api.post("/restaurants/discover", json={"country_code": "US", "city": "New York 2", "limit": 1})
    assert resp.status_code == 422


# ── Discovery: the live query, region code and country name, with Google stubbed ─

@pytest.mark.parametrize("code, city, industry, sub, country_name, query_fragment", SCENARIOS)
def test_live_search_sends_the_country_query_and_region_code(api, monkeypatch, code, city, industry, sub,
                                                             country_name, query_fragment):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-key-not-used")
    captured = {}

    async def fake_search(query, max_results, api_key, included_type=None, region_code="PK"):
        captured.update(query=query, region_code=region_code)
        return [{"place_id": f"google-{code}-1", "name": f"Real {city} business", "address": f"1 Street, {city}",
                 "phone": None, "website": None, "source": "google_places"}]

    with patch.object(main, "search_restaurants", new=fake_search):
        resp = api.post("/restaurants/discover", json={"country_code": code, "city": city, "industry": industry,
                                                       "subcategory": sub, "limit": 1})
    assert resp.status_code == 200, resp.text
    assert captured["query"].endswith(query_fragment)
    assert captured["region_code"] == code
    row = resp.json()[0]
    assert row["country_code"] == code and row["country_name"] == country_name


def test_changing_the_country_changes_the_query_sent_to_google(api, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-key-not-used")
    seen = []

    async def fake_search(query, max_results, api_key, included_type=None, region_code="PK"):
        seen.append((query, region_code))
        return []

    with patch.object(main, "search_restaurants", new=fake_search):
        api.post("/restaurants/discover", json={"country_code": "PK", "city": "Lahore", "category": "all", "limit": 1})
        api.post("/restaurants/discover", json={"country_code": "AE", "city": "Lahore", "category": "all", "limit": 1})
    assert seen[0] != seen[1]
    assert seen[0][1] == "PK" and seen[1][1] == "AE"


# ── Deduplication and country-specific results ───────────────────────────────

def test_a_place_found_twice_in_one_country_is_one_record():
    place = {"place_id": "google-dup-1", "name": "Dup Cafe", "source": "google_places"}
    save_restaurants([place], city="Dubai", country="United Arab Emirates", country_code="AE")
    save_restaurants([place], city="Dubai", country="United Arab Emirates", country_code="AE")
    assert fetch_one("SELECT COUNT(*) AS n FROM restaurants WHERE place_id = 'google-dup-1'")["n"] == 1


def test_a_place_saved_under_one_country_is_not_returned_for_another():
    place = {"place_id": "google-cross-1", "name": "Cross Cafe", "source": "google_places"}
    saved_us = save_restaurants([place], city="Austin", country="United States", country_code="US")
    assert saved_us[0]["country_code"] == "US"
    saved_gb = save_restaurants([place], city="Austin", country="United Kingdom", country_code="GB")
    assert saved_gb == []
    assert fetch_one("SELECT country_code FROM restaurants WHERE place_id = 'google-cross-1'")["country_code"] == "US"


def test_city_suggestions_are_refused_for_unknown_countries(api):
    # City suggestions come from the city database (tests/test_geonames.py). Only the country check is covered here.
    assert api.get("/geo/countries/XX/cities").status_code == 422
    assert api.get("/geo/countries/PK/cities").status_code == 200


# ── Prompt and migration ─────────────────────────────────────────────────────

def test_the_outreach_prompt_names_the_country():
    from services.outreach import build_prompt
    prompt = build_prompt({"name": "Harbour Clinic", "industry": "healthcare", "city": "Sydney",
                           "country_code": "AU", "subcategory": "clinic", "website_features": {}}, "general")
    assert "Country: Australia" in prompt


def _alembic_config():
    from pathlib import Path
    from alembic.config import Config
    backend = Path(__file__).resolve().parent.parent
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "migrations"))
    return config


def test_existing_records_become_pakistani_and_the_downgrade_keeps_them(test_db):
    from alembic import command
    command.downgrade(_alembic_config(), "0011_draft_edits")
    execute("INSERT INTO restaurants (place_id, name, source, workspace_id, country) "
            "VALUES ('legacy-pk', 'Legacy Dhaba', 'google_places', 1, 'Pakistan')")
    command.upgrade(_alembic_config(), "head")
    row = fetch_one("SELECT country_code, country_name FROM restaurants WHERE place_id = 'legacy-pk'")
    assert row == {"country_code": "PK", "country_name": "Pakistan"}
    command.downgrade(_alembic_config(), "0011_draft_edits")
    assert fetch_one("SELECT COUNT(*) AS n FROM restaurants WHERE place_id = 'legacy-pk'")["n"] == 1
    command.upgrade(_alembic_config(), "head")
