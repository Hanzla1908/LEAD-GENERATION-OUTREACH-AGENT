"""Tests for the Google Places discovery service and DB persistence."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx

from services.discovery import search_restaurants, _normalize
from main import app

api_client = None


@pytest.fixture(autouse=True)
def _signed_in(test_db):
    """Each test gets a fresh database and a client signed in as the default admin."""
    global api_client
    from tests.account_helpers import signed_in_client

    api_client = signed_in_client(app)


@pytest.fixture(autouse=True)
def live_mode(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "false")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_PLACE = {
    "id": "ChIJtest123",
    "displayName": {"text": "Test Trattoria", "languageCode": "en"},
    "formattedAddress": "123 Main St, Chicago, IL 60601",
    "nationalPhoneNumber": "(312) 555-0100",
    "websiteUri": "https://testtrattoria.com",
    "location": {"latitude": 41.8781, "longitude": -87.6298},
}


def _mock_client(status_code: int, body: dict | None = None, raise_error: bool = False):
    """Build a patched httpx.AsyncClient that returns the given status + body."""
    mock_response = MagicMock()
    mock_response.status_code = status_code

    if raise_error:
        request = httpx.Request("POST", "https://example.com")
        response = httpx.Response(status_code, request=request)
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}", request=request, response=response
        )
    else:
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = body or {}

    mock_instance = AsyncMock()
    mock_instance.post = AsyncMock(return_value=mock_response)

    mock_class = MagicMock()
    mock_class.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
    mock_class.return_value.__aexit__ = AsyncMock(return_value=None)
    return mock_class


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def test_normalize_full_place():
    result = _normalize(SAMPLE_PLACE)
    assert result["place_id"] == "ChIJtest123"
    assert result["name"] == "Test Trattoria"
    assert result["address"] == "123 Main St, Chicago, IL 60601"
    assert result["phone"] == "(312) 555-0100"
    assert result["website"] == "https://testtrattoria.com"
    assert result["latitude"] == pytest.approx(41.8781)
    assert result["longitude"] == pytest.approx(-87.6298)
    assert result["source"] == "google_places"


def test_normalize_missing_optional_fields():
    minimal = {"id": "abc", "displayName": {"text": "Cafe"}}
    result = _normalize(minimal)
    assert result["place_id"] == "abc"
    assert result["name"] == "Cafe"
    assert result["phone"] is None
    assert result["website"] is None
    assert result["latitude"] is None


# ---------------------------------------------------------------------------
# search_restaurants — HTTP layer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_search_returns_normalized_results():
    mock_class = _mock_client(200, body={"places": [SAMPLE_PLACE]})
    with patch("services.discovery.httpx.AsyncClient", mock_class):
        results = await search_restaurants("Italian restaurants in Chicago", 5, "key")
    assert len(results) == 1
    assert results[0]["name"] == "Test Trattoria"
    assert results[0]["place_id"] == "ChIJtest123"


@pytest.mark.asyncio
async def test_search_empty_places_returns_empty_list():
    mock_class = _mock_client(200, body={"places": []})
    with patch("services.discovery.httpx.AsyncClient", mock_class):
        results = await search_restaurants("restaurants in Nowheresville", 5, "key")
    assert results == []


@pytest.mark.asyncio
async def test_search_missing_places_key_returns_empty_list():
    mock_class = _mock_client(200, body={})
    with patch("services.discovery.httpx.AsyncClient", mock_class):
        results = await search_restaurants("restaurants in Nowheresville", 5, "key")
    assert results == []


@pytest.mark.asyncio
async def test_search_rate_limit_raises_429():
    mock_class = _mock_client(429, raise_error=True)
    with patch("services.discovery.httpx.AsyncClient", mock_class):
        with pytest.raises(HTTPException) as exc_info:
            await search_restaurants("q", 5, "key")
    assert exc_info.value.status_code == 429


@pytest.mark.asyncio
async def test_search_invalid_key_raises_503():
    mock_class = _mock_client(403, raise_error=True)
    with patch("services.discovery.httpx.AsyncClient", mock_class):
        with pytest.raises(HTTPException) as exc_info:
            await search_restaurants("q", 5, "bad_key")
    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_search_bad_params_raises_400():
    mock_class = _mock_client(400, raise_error=True)
    with patch("services.discovery.httpx.AsyncClient", mock_class):
        with pytest.raises(HTTPException) as exc_info:
            await search_restaurants("", 5, "key")
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Database — deduplication
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# API endpoint — key presence checks
# ---------------------------------------------------------------------------

def test_discover_endpoint_missing_key_returns_503(test_db, monkeypatch):
    """Endpoint must return 503 when GOOGLE_PLACES_API_KEY is absent."""
    monkeypatch.delenv("GOOGLE_PLACES_API_KEY", raising=False)
    resp = api_client.post("/restaurants/discover", json={"city": "Lahore"})
    assert resp.status_code == 503
    assert "GOOGLE_PLACES_API_KEY" in resp.json()["detail"]


def test_discover_endpoint_empty_key_returns_503(test_db, monkeypatch):
    """An empty string key (GOOGLE_PLACES_API_KEY=) must also return 503."""
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "")
    resp = api_client.post("/restaurants/discover", json={"city": "Lahore"})
    assert resp.status_code == 503


def test_discover_endpoint_configured_key_calls_service(test_db, monkeypatch):
    """When the key is present the endpoint calls the Places service."""
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-key")
    mock_class = _mock_client(200, body={"places": [SAMPLE_PLACE]})
    with patch("services.discovery.httpx.AsyncClient", mock_class):
        resp = api_client.post("/restaurants/discover", json={"city": "Lahore"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "Test Trattoria"


# ---------------------------------------------------------------------------
# Database — deduplication
# ---------------------------------------------------------------------------

def test_save_restaurants_deduplicates_by_place_id(test_db):
    from models.database import save_restaurants, list_restaurants

    place = {
        "place_id": "ChIJdup",
        "name": "Dup Diner",
        "address": "1 Dup St",
        "phone": None,
        "website": None,
        "latitude": 1.0,
        "longitude": 2.0,
        "source": "google_places",
    }
    save_restaurants([place])
    save_restaurants([place])  # second insert should be ignored

    saved = list_restaurants()
    assert len(saved) == 1
    assert saved[0]["place_id"] == "ChIJdup"


def test_save_restaurants_returns_saved_rows(test_db):
    from models.database import save_restaurants

    places = [
        {"place_id": "A", "name": "Alpha", "address": None, "phone": None,
         "website": None, "latitude": None, "longitude": None, "source": "google_places"},
        {"place_id": "B", "name": "Beta",  "address": None, "phone": None,
         "website": None, "latitude": None, "longitude": None, "source": "google_places"},
    ]
    rows = save_restaurants(places)
    assert len(rows) == 2
    names = {r["name"] for r in rows}
    assert names == {"Alpha", "Beta"}


# ---------------------------------------------------------------------------
# Pakistan city and category searches
# ---------------------------------------------------------------------------

def _sent_body(mock_class) -> dict:
    """Return the JSON body the mocked Places client was asked to POST."""
    instance = mock_class.return_value.__aenter__.return_value
    return instance.post.call_args.kwargs["json"]


def _search(city: str, category: str, monkeypatch) -> dict:
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-key")
    mock_class = _mock_client(200, body={"places": [SAMPLE_PLACE]})
    with patch("services.discovery.httpx.AsyncClient", mock_class):
        resp = api_client.post("/restaurants/discover", json={"city": city, "category": category, "limit": 5})
    assert resp.status_code == 200, resp.text
    return _sent_body(mock_class)


def test_faisalabad_fast_food_query(test_db, monkeypatch):
    body = _search("Faisalabad", "fast_food", monkeypatch)
    assert body["textQuery"] == "fast food restaurant in Faisalabad, Pakistan"
    assert body["includedType"] == "fast_food_restaurant"
    assert body["regionCode"] == "PK"
    assert body["maxResultCount"] == 5


def test_lahore_desi_query(test_db, monkeypatch):
    body = _search("Lahore", "desi", monkeypatch)
    assert body["textQuery"] == "Pakistani restaurant in Lahore, Pakistan"
    assert "includedType" not in body


def test_karachi_cafe_query(test_db, monkeypatch):
    body = _search("Karachi", "cafe", monkeypatch)
    assert body["textQuery"] == "cafe coffee shop in Karachi, Pakistan"
    assert body["includedType"] == "cafe"


def test_all_restaurants_query(test_db, monkeypatch):
    body = _search("Islamabad", "all", monkeypatch)
    assert body["textQuery"] == "restaurants in Islamabad, Pakistan"
    assert "includedType" not in body


def test_changing_category_changes_query(test_db, monkeypatch):
    first = _search("Multan", "biryani", monkeypatch)
    second = _search("Multan", "bbq", monkeypatch)
    assert first["textQuery"] != second["textQuery"]
    assert first["textQuery"].endswith("in Multan, Pakistan")
    assert second["textQuery"].endswith("in Multan, Pakistan")
    assert second["includedType"] == "barbecue_restaurant"


def test_city_name_is_canonicalised_and_stored_with_country(test_db, monkeypatch):
    _search("  faisalabad ", "fast_food", monkeypatch)
    from models.database import list_restaurants
    stored = list_restaurants()
    assert stored[0]["city"] == "Faisalabad"
    assert stored[0]["country"] == "Pakistan"


def test_other_city_is_accepted_and_title_cased(test_db, monkeypatch):
    body = _search("gujrat", "all", monkeypatch)
    assert body["textQuery"] == "restaurants in Gujrat, Pakistan"


@pytest.mark.parametrize("city", ["L", "Lahore123", "Lahore; DROP", "<script>"])
def test_invalid_city_returns_422(test_db, monkeypatch, city):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-key")
    resp = api_client.post("/restaurants/discover", json={"city": city, "category": "all"})
    assert resp.status_code == 422


def test_unknown_category_returns_422(test_db, monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-key")
    resp = api_client.post("/restaurants/discover", json={"city": "Lahore", "category": "sushi-only"})
    assert resp.status_code == 422


def test_empty_results_returns_empty_list(test_db, monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-key")
    mock_class = _mock_client(200, body={})
    with patch("services.discovery.httpx.AsyncClient", mock_class):
        resp = api_client.post("/restaurants/discover", json={"city": "Sukkur", "category": "tea"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_places_quota_error_is_reported(test_db, monkeypatch):
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-key")
    mock_class = _mock_client(429, raise_error=True)
    with patch("services.discovery.httpx.AsyncClient", mock_class):
        resp = api_client.post("/restaurants/discover", json={"city": "Quetta", "category": "pizza"})
    assert resp.status_code == 429
    assert "rate limit" in resp.json()["detail"].lower()
