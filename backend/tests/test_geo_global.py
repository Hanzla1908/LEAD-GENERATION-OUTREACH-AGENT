"""Country → state → city on real GeoNames rows, across the countries the feature must cover.

The fixtures are rows copied unchanged from GeoNames (see tests/fixtures/geonames/README.txt). Discovery runs in live
mode with the Google call replaced by a stub that records the search text, so no network call is made and the demo
sample records are not used.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient  # noqa: F401  (used through signed_in_client)

import main
from models.database import fetch_all
from services import countries as country_registry
from services import geonames
from services.geonames import list_states, search_cities, state_name
from services.geonames_import import import_from_files
from tests.account_helpers import TEST_SESSION_SECRET, signed_in_client

FIXTURES = Path(__file__).parent / "fixtures" / "geonames"
CITIES = FIXTURES / "cities_global_sample.txt"
ADMIN1 = FIXTURES / "admin1_global_sample.txt"

# (country, state code, typed prefix, expected city, expected geonameid). The state codes are GeoNames admin1 codes.
SEVEN_LOCATIONS = [
    ("PK", "04", "Lah", "Lahore", 1172451),              # Pakistan → Punjab → Lahore
    ("PK", "05", "Kar", "Karachi", 1174872),             # Pakistan → Sindh → Karachi
    ("PK", "03", "Pesh", "Peshawar", 1168197),           # Pakistan → Khyber Pakhtunkhwa → Peshawar
    ("US", "CA", "Los", "Los Angeles", 5368361),         # USA → California → Los Angeles
    ("GB", "ENG", "Lond", "London", 2643743),            # UK → England → London
    ("AE", "03", "Dub", "Dubai", 292223),                # UAE → Dubai → Dubai
    ("AU", "02", "Syd", "Sydney", 2147714),              # Australia → New South Wales → Sydney
]


@pytest.fixture
def loaded(test_db):
    """The global sample, imported into an isolated database."""
    summary = import_from_files(CITIES, ADMIN1, file_sha256="global-fixture")
    geonames.clear_cache()
    return summary


@pytest.fixture
def api(loaded, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    return signed_in_client(main.app)


@pytest.fixture
def live_searches(api, monkeypatch):
    """Live discovery with the Google call stubbed. The returned list collects the searches the stub received; the
    stub returns the places in .places (none by default)."""
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-places-key-not-real")

    class Searches(list):
        places: list[dict] = []

    searches = Searches()

    async def fake_search(query, max_results, api_key, included_type, region_code):
        searches.append({"query": query, "region_code": region_code, "max_results": max_results})
        return [dict(place) for place in searches.places]

    monkeypatch.setattr(main, "search_restaurants", fake_search)
    return searches


def _names(result: dict) -> list[str]:
    return [item["name"] for item in result["items"]]


# ── The seven locations ──────────────────────────────────────────────────────

@pytest.mark.parametrize("cc, state, typed, expected, geoname_id", SEVEN_LOCATIONS)
def test_each_location_is_found_within_its_state(loaded, cc, state, typed, expected, geoname_id):
    result = search_cities(cc, typed, admin1=state)
    assert result["source"] == "geonames"
    assert [(i["name"], i["id"], i["admin1_code"], i["country_code"]) for i in result["items"]] == [
        (expected, geoname_id, state, cc)]


@pytest.mark.parametrize("cc, state, typed, expected, geoname_id", SEVEN_LOCATIONS)
def test_each_location_is_found_through_the_endpoint(api, cc, state, typed, expected, geoname_id):
    body = api.get(f"/geo/countries/{cc}/cities", params={"q": typed, "admin1": state}).json()
    assert [i["name"] for i in body["items"]] == [expected]
    assert body["items"][0]["id"] == geoname_id


@pytest.mark.parametrize("cc, state, typed, expected, geoname_id", SEVEN_LOCATIONS)
def test_each_city_is_searched_in_its_state_and_country(live_searches, api, cc, state, typed, expected, geoname_id):
    resp = api.post("/restaurants/discover", json={
        "country_code": cc, "state": state, "city_id": geoname_id, "industry": "restaurants_food",
        "category": "all", "limit": 5,
    })
    assert resp.status_code == 200, resp.text
    country = country_registry.country_name(cc)
    state_label = state_name(cc, state)
    assert len(live_searches) == 1
    assert live_searches[0]["region_code"] == cc
    assert live_searches[0]["query"].endswith(f"in {expected}, {state_label}, {country}")


# ── States of a country ──────────────────────────────────────────────────────

@pytest.mark.parametrize("cc, expected", [
    ("PK", ["Khyber Pakhtunkhwa", "Punjab", "Sindh"]),
    ("US", ["California", "Virginia"]),
    ("GB", ["England"]),
    ("AE", ["Dubai"]),
    ("AU", ["New South Wales"]),
])
def test_the_states_of_a_country_are_the_divisions_that_have_cities(loaded, cc, expected):
    assert [item["name"] for item in list_states(cc)["items"]] == expected


def test_a_country_with_no_divisions_has_no_states_and_its_cities_still_search(api):
    assert api.get("/geo/countries/SG/states").json()["items"] == []
    body = api.get("/geo/countries/SG/cities", params={"q": "Sing"}).json()
    assert [i["name"] for i in body["items"]] == ["Singapore"]
    assert body["items"][0]["admin1_code"] is None


def test_the_states_endpoint_answers_for_a_known_country_only(api):
    assert api.get("/geo/countries/PK/states").status_code == 200
    assert api.get("/geo/countries/XX/states").status_code == 422


def test_states_are_returned_with_their_codes(api):
    body = api.get("/geo/countries/US/states").json()
    assert body["items"] == [{"code": "CA", "name": "California"}, {"code": "VA", "name": "Virginia"}]


# ── Duplicate names are kept apart by state ──────────────────────────────────

def test_two_cities_with_the_same_name_in_different_states_are_distinct(loaded):
    assert search_cities("US", "Rich", admin1="VA")["items"][0]["id"] == 4781708
    assert search_cities("US", "Rich", admin1="CA")["items"][0]["id"] == 5387428
    both = sorted(i["id"] for i in search_cities("US", "Rich")["items"])
    assert both == [4781708, 5387428]


def test_a_city_is_never_returned_for_a_state_it_is_not_in(loaded):
    assert search_cities("PK", "Lah", admin1="05")["items"] == []
    assert search_cities("US", "Los", admin1="VA")["items"] == []


# ── Validation ───────────────────────────────────────────────────────────────

def test_a_state_code_must_exist_for_its_country(api):
    assert api.get("/geo/countries/PK/cities", params={"admin1": "CA"}).status_code == 422
    assert api.get("/geo/countries/US/cities", params={"admin1": "99"}).status_code == 422


def test_a_discovery_state_must_exist_for_its_country(live_searches, api):
    resp = api.post("/restaurants/discover", json={"country_code": "PK", "state": "CA", "limit": 1})
    assert resp.status_code == 422
    assert "Unknown state" in resp.json()["detail"]
    assert live_searches == []


def test_a_city_from_another_state_is_refused_in_discovery(live_searches, api):
    resp = api.post("/restaurants/discover", json={"country_code": "PK", "state": "05", "city_id": 1172451, "limit": 1})
    assert resp.status_code == 422
    assert "not in Sindh" in resp.json()["detail"]
    assert live_searches == []


# ── Discovery for every industry ─────────────────────────────────────────────

def test_a_state_wide_search_names_the_state_as_its_location_and_the_lead_city(live_searches, api):
    live_searches.places = [{"place_id": "geo-global-1", "name": "Global Kitchen", "address": "1 Road, Punjab",
                             "source": "google_places"}]
    resp = api.post("/restaurants/discover", json={"country_code": "PK", "state": "04", "limit": 3})
    assert resp.status_code == 200, resp.text
    assert live_searches[0]["query"].endswith("in Punjab, Pakistan")
    assert resp.json()[0]["city"] == "Punjab"  # the lead records the state as the place it was found in


@pytest.mark.parametrize("industry, subcategory, search_text_fragment", [
    ("home_services", "construction", "in Lahore, Punjab, Pakistan"),
])
def test_other_industries_receive_the_state_and_city_too(live_searches, api, industry, subcategory, search_text_fragment):
    resp = api.post("/restaurants/discover", json={
        "country_code": "PK", "state": "04", "city_id": 1172451, "industry": industry,
        "subcategory": subcategory, "limit": 1,
    })
    assert resp.status_code == 200, resp.text
    assert live_searches[0]["query"].endswith(search_text_fragment)


# ── Import ───────────────────────────────────────────────────────────────────

def test_the_import_writes_one_row_per_division_and_is_repeatable(test_db):
    first = import_from_files(CITIES, ADMIN1, file_sha256="global-fixture")
    again = import_from_files(CITIES, ADMIN1, file_sha256="global-fixture")
    assert first["divisions"] == again["divisions"] == 8
    rows = fetch_all("SELECT country_code, code, name FROM geo_admin1 ORDER BY country_code, code")
    assert {(r["country_code"], r["code"]) for r in rows} == {
        ("AE", "03"), ("AU", "02"), ("GB", "ENG"), ("PK", "03"), ("PK", "04"), ("PK", "05"), ("US", "CA"), ("US", "VA")}
