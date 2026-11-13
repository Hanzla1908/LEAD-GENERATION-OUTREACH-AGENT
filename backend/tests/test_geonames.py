"""The GeoNames city database: import, country-only search, alternate names, pagination, attribution, and discovery
with a city picked from the database.

The fixtures are real GeoNames rows (CC BY 4.0, see fixtures/geonames/README.txt). Nothing here calls Google, and
discovery runs in Demo Mode with no API key, as the city database must work without Google credentials.
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient  # noqa: F401  (used through signed_in_client)
from sqlalchemy import inspect

import main
from models.database import execute, fetch_all, fetch_one, get_engine, save_restaurants
from services import geonames
from services.geonames import normalize_search, search_cities
from services.geonames_import import import_from_files
from tests.account_helpers import TEST_SESSION_SECRET, signed_in_client

FIXTURES = Path(__file__).parent / "fixtures" / "geonames"
CITIES = FIXTURES / "cities_sample.txt"
ADMIN1 = FIXTURES / "admin1_sample.txt"

SYDNEY_ID = 2147714
FAISALABAD_ID = 1179400


@pytest.fixture
def loaded(test_db):
    """The fixture cities, imported into an isolated database."""
    summary = import_from_files(CITIES, ADMIN1, file_sha256="fixture")
    geonames.clear_cache()
    return summary


@pytest.fixture
def api(loaded, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    return signed_in_client(main.app)


def _names(result: dict) -> list[str]:
    return [item["name"] for item in result["items"]]


# ── Search rules ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("São Paulo", "sao paulo"),
    ("Zürich", "zurich"),
    ("St. John's", "st john s"),
    ("Al-Ain", "al ain"),
    ("  New   York ", "new york"),
])
def test_names_are_compared_without_accents_case_or_punctuation(raw, expected):
    assert normalize_search(raw) == expected


# The five required cities, each in its own country, with the admin division the interface shows.
@pytest.mark.parametrize("code, typed, name, admin", [
    ("PK", "Faisalabad", "Faisalabad", "Punjab"),
    ("US", "New York", "New York City", "New York"),
    ("GB", "London", "London", "England"),
    ("AE", "Dubai", "Dubai", "Dubai"),
    ("AU", "Sydney", "Sydney", "New South Wales"),
])
def test_each_required_city_is_found_in_its_own_country(loaded, code, typed, name, admin):
    result = search_cities(code, typed)
    assert result["source"] == "geonames"
    assert result["items"][0]["name"] == name
    assert result["items"][0]["admin1_name"] == admin
    assert result["items"][0]["country_code"] == code


def test_a_city_name_never_returns_a_city_from_another_country(loaded):
    # London exists in the UK and in Canada. Each search gets only its own country's London.
    assert [(i["name"], i["admin1_name"]) for i in search_cities("GB", "London")["items"]] == [("London", "England")]
    assert [(i["name"], i["admin1_name"]) for i in search_cities("CA", "London")["items"]] == [("London", "Ontario")]
    assert search_cities("PK", "Dubai")["items"] == []
    assert search_cities("US", "Lahore")["items"] == []
    assert search_cities("GB", "Sydney")["items"] == []


def test_alternate_names_find_the_city_and_show_which_name_matched(loaded):
    old_name = search_cities("PK", "Lyallpur")["items"][0]
    assert old_name["name"] == "Faisalabad"
    assert old_name["matched_alias"] == "Lyallpur"
    nickname = search_cities("US", "nyc")["items"][0]
    assert nickname["name"] == "New York City" and nickname["matched_alias"] == "NYC"


def test_a_match_on_the_main_name_shows_no_alias(loaded):
    item = search_cities("PK", "Faisalabad")["items"][0]
    assert item["id"] == FAISALABAD_ID and item["matched_alias"] is None


def test_matching_ignores_case_and_accents_in_the_typed_text(loaded):
    assert _names(search_cities("PK", "LAHORE")) == ["Lahore"]
    assert _names(search_cities("PK", "lah")) == ["Lahore"]


def test_an_empty_query_lists_the_most_populated_cities_of_that_country(loaded):
    assert _names(search_cities("PK", "")) == ["Lahore", "Faisalabad"]


def test_search_results_are_paged(loaded, api):
    first = api.get("/geo/countries/PK/cities", params={"limit": 1, "offset": 0}).json()
    second = api.get("/geo/countries/PK/cities", params={"limit": 1, "offset": 1}).json()
    assert [i["name"] for i in first["items"]] == ["Lahore"] and first["has_more"] is True
    assert [i["name"] for i in second["items"]] == ["Faisalabad"] and second["has_more"] is False


def test_the_endpoint_refuses_oversized_pages_and_unknown_countries(loaded, api):
    assert api.get("/geo/countries/PK/cities", params={"limit": 100}).status_code == 422
    assert api.get("/geo/countries/PK/cities", params={"offset": -1}).status_code == 422
    assert api.get("/geo/countries/PK/cities", params={"q": "x" * 61}).status_code == 422
    assert api.get("/geo/countries/XX/cities").status_code == 422


def test_city_search_needs_no_google_key(loaded, api, monkeypatch):
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    body = api.get("/geo/countries/AU/cities", params={"q": "Syd"}).json()
    assert [i["name"] for i in body["items"]] == ["Sydney"]


def test_repeated_searches_are_served_from_the_cache_until_it_is_cleared(loaded):
    assert _names(search_cities("AE", "Dubai"))
    execute("DELETE FROM geo_cities WHERE name = 'Dubai'")
    assert _names(search_cities("AE", "Dubai")) == ["Dubai"]  # still cached
    geonames.clear_cache()
    assert _names(search_cities("AE", "Dubai")) == []


def test_before_the_import_only_the_builtin_pakistani_list_answers(test_db):
    pakistan = search_cities("PK", "Fais")
    assert pakistan["source"] == "fallback" and _names(pakistan) == ["Faisalabad"]
    assert search_cities("US", "New")["items"] == []


# ── Import ───────────────────────────────────────────────────────────────────

def test_importing_twice_gives_the_same_rows(loaded):
    again = import_from_files(CITIES, ADMIN1, file_sha256="fixture")
    assert again["cities"] == loaded["cities"] == 7
    assert again["alternate_names"] == loaded["alternate_names"]
    assert fetch_one("SELECT COUNT(*) AS n FROM geo_cities")["n"] == 7


def test_rows_for_unknown_countries_are_skipped_and_counted(test_db, tmp_path):
    bogus = tmp_path / "cities.txt"
    # Country code XK is not an ISO country in the registry, so this row must not be imported.
    bogus.write_text("999001\tNowhere\tNowhere\tNowhere\t1.0\t2.0\tP\tPPL\tXK\t\t\t\t\t\t500\t\t\t\tUTC\t2025-01-01\n",
                     encoding="utf-8")
    summary = import_from_files(bogus, ADMIN1, file_sha256="bogus")
    assert summary["cities"] == 0 and summary["skipped"] == 1


def test_import_leaves_restaurants_and_their_records_alone(test_db):
    save_restaurants([{"place_id": "keep-geo-1", "name": "Keep Cafe", "source": "google_places"}],
                     city="Lahore", country="Pakistan", country_code="PK")
    import_from_files(CITIES, ADMIN1, file_sha256="fixture")
    assert fetch_one("SELECT city, country_code FROM restaurants WHERE place_id = 'keep-geo-1'") == {
        "city": "Lahore", "country_code": "PK"}


def test_city_tables_have_no_link_to_restaurants(loaded):
    inspector = inspect(get_engine())
    for table in ("geo_cities", "geo_city_alternate_names", "geo_import_runs"):
        for fk in inspector.get_foreign_keys(table):
            assert fk["referred_table"] in {"geo_cities"}, table


def test_the_lookup_indexes_exist(test_db):
    inspector = inspect(get_engine())
    city_indexes = {ix["name"] for ix in inspector.get_indexes("geo_cities")}
    alt_indexes = {ix["name"] for ix in inspector.get_indexes("geo_city_alternate_names")}
    assert {"ix_geo_cities_country_search", "ix_geo_cities_country_population"} <= city_indexes
    assert "ix_geo_alt_country_search" in alt_indexes


def test_the_migration_downgrades_and_upgrades_cleanly(test_db):
    from alembic import command
    from pathlib import Path as _Path
    from alembic.config import Config
    backend = _Path(__file__).resolve().parent.parent
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "migrations"))
    command.downgrade(config, "0013_soft_delete_leads")
    assert "geo_cities" not in inspect(get_engine()).get_table_names()
    command.upgrade(config, "head")
    assert "geo_cities" in inspect(get_engine()).get_table_names()


# ── Status and attribution ───────────────────────────────────────────────────

def test_status_reports_the_data_and_its_attribution(loaded, api):
    body = api.get("/geo/status").json()
    assert body["loaded"] is True and body["city_count"] == 7
    assert body["licence"] == "CC BY 4.0"
    assert "GeoNames" in body["attribution"] and "CC BY 4.0" in body["attribution"]


def test_status_before_the_import_says_not_loaded(test_db, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    body = signed_in_client(main.app).get("/geo/status").json()
    assert body["loaded"] is False and body["city_count"] == 0


# ── Discovery with a city picked from the database ───────────────────────────

def test_discovery_with_a_picked_city_uses_its_database_name_and_country(api):
    rows = api.post("/restaurants/discover", json={"country_code": "AU", "city_id": SYDNEY_ID,
                                                   "industry": "home_services", "subcategory": "construction",
                                                   "limit": 2}).json()
    assert len(rows) == 2
    assert all(r["city"] == "Sydney" and r["country_code"] == "AU" for r in rows)


def test_a_picked_city_from_another_country_is_refused(api):
    resp = api.post("/restaurants/discover", json={"country_code": "PK", "city_id": SYDNEY_ID, "limit": 1})
    assert resp.status_code == 422
    assert "not in Pakistan" in resp.json()["detail"]


def test_an_unknown_city_id_is_refused(api):
    assert api.post("/restaurants/discover", json={"country_code": "PK", "city_id": 999999, "limit": 1}).status_code == 422


def test_a_typed_custom_city_is_searched_exactly_as_typed(api):
    rows = api.post("/restaurants/discover", json={"country_code": "PK", "city": "Zanzibar Town", "limit": 1}).json()
    assert rows[0]["city"] == "Zanzibar Town"


def test_a_search_with_no_city_or_id_is_refused(api):
    assert api.post("/restaurants/discover", json={"country_code": "US", "limit": 1}).status_code == 422


def test_pakistani_searches_by_typed_name_are_unchanged_when_the_database_is_loaded(api):
    rows = api.post("/restaurants/discover", json={"country_code": "PK", "city": "Faisalabad",
                                                   "category": "biryani", "limit": 1}).json()
    assert rows[0]["place_id"] == "demo-faisalabad-biryani-1"
    assert rows[0]["city"] == "Faisalabad"
