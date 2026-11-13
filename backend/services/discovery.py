import asyncio
import os
import re

import httpx
from fastapi import HTTPException

from services.industries import DEFAULT_INDUSTRY

PLACES_URL = "https://places.googleapis.com/v1/places:searchText"
# Only the fields the app uses. Each field widens the billed SKU, so nothing extra is requested.
FIELD_MASK = (
    "places.id,"
    "places.displayName,"
    "places.formattedAddress,"
    "places.nationalPhoneNumber,"
    "places.websiteUri,"
    "nextPageToken"
)
PAGE_SIZE = 20
RESULT_CEILING = 60
GOOGLE_CACHE_DAYS = 30
NEXT_PAGE_DELAY_SECONDS = 2.0
DEFAULT_TIMEOUT_SECONDS = 15.0


def demo_mode_enabled() -> bool:
    return os.getenv("DEMO_MODE", "true").strip().lower() not in {"false", "0", "no", "off"}


def live_api_key() -> str:
    return os.getenv("GOOGLE_PLACES_API_KEY", "").strip()


def places_result_cap() -> int:
    try:
        configured = int(os.getenv("PLACES_MAX_RESULTS", str(RESULT_CEILING)))
    except ValueError:
        configured = RESULT_CEILING
    return max(1, min(configured, RESULT_CEILING))


def places_timeout() -> float:
    try:
        return max(1.0, float(os.getenv("PLACES_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))))
    except ValueError:
        return DEFAULT_TIMEOUT_SECONDS


def _normalize(place: dict) -> dict:
    display_name = place.get("displayName") or {}
    location = place.get("location") or {}
    return {
        "place_id": place["id"],
        "name": display_name.get("text") or "",
        "address": place.get("formattedAddress"),
        "phone": place.get("nationalPhoneNumber"),
        "website": place.get("websiteUri"),
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "source": "google_places",
    }


def demo_places(city: str, category: str, limit: int, industry: str = DEFAULT_INDUSTRY,
                subcategory_name: str | None = None, country_code: str = "PK",
                country_name: str = "Pakistan") -> list[dict]:
    """Sample records for Demo Mode. Every name starts with [DEMO] so a sample is never mistaken for a real business.

    Pakistan keeps the identifiers it has always had. Other countries add their code, so a sample for one country
    can never collide with a sample for another.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", city.lower()).strip("-")
    country_part = "" if country_code == "PK" else f"{country_code.lower()}-"
    if industry == DEFAULT_INDUSTRY:
        # Restaurant records keep the format they have always had.
        label = "Business" if category == "all" else category.replace("_", " ").title()
        return [
            {
                "place_id": f"demo-{country_part}{slug}-{category}-{index}",
                "name": f"[DEMO] {label} House {index}",
                "address": f"Demo Street {index}, {city}, {country_name}",
                "phone": None,
                "website": None,
                "source": "demo",
            }
            for index in range(1, limit + 1)
        ]
    label = subcategory_name or industry.replace("_", " ").title()
    return [
        {
            "place_id": f"demo-{country_part}{industry}-{slug}-{category}-{index}",
            "name": f"[DEMO] {label} {index}",
            "address": f"Demo Street {index}, {city}, {country_name}",
            "phone": None,
            "website": None,
            "source": "demo",
        }
        for index in range(1, limit + 1)
    ]


def _safe_json(response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _places_error(response: httpx.Response) -> HTTPException:
    status = response.status_code
    error = _safe_json(response).get("error")
    error = error if isinstance(error, dict) else {}
    message = str(error.get("message") or "")
    lowered = message.lower()

    if status == 401 or "api key" in lowered and any(word in lowered for word in ("not valid", "invalid", "expired")):
        return HTTPException(
            503,
            "GOOGLE_PLACES_API_KEY was rejected by Google. Check the key in the backend .env file "
            "and that it is not restricted away from Places API (New).",
        )
    if status == 429 or error.get("status") == "RESOURCE_EXHAUSTED":
        return HTTPException(429, "Google Places quota or rate limit reached. Wait a moment and try again.")
    if status == 403:
        return HTTPException(
            503,
            "Google denied the search. Enable Places API (New) for the key's Google Cloud project "
            "and make sure billing is active.",
        )
    if status == 400:
        detail = message[:200] or "invalid search parameters"
        return HTTPException(400, f"Google rejected the search request: {detail}")
    if status >= 500:
        return HTTPException(502, f"Google Places had a temporary error (HTTP {status}). Try again shortly.")
    return HTTPException(502, f"Unexpected response from Google Places (HTTP {status}).")


async def _post_page(client: httpx.AsyncClient, body: dict, api_key: str) -> dict:
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    try:
        response = await client.post(PLACES_URL, headers=headers, json=body)
    except httpx.TimeoutException:
        raise HTTPException(504, "Google Places did not answer in time. Try again.")
    except httpx.HTTPError:
        raise HTTPException(502, "Could not reach Google Places. Check the server's internet connection.")
    if response.status_code != 200:
        raise _places_error(response)
    return _safe_json(response)


async def search_restaurants(
    query: str,
    max_results: int,
    api_key: str,
    included_type: str | None = None,
    region_code: str = "PK",
) -> list[dict]:
    limit = max(1, min(max_results, RESULT_CEILING))
    body = {
        "textQuery": query,
        "languageCode": "en",
        "regionCode": region_code,
        "maxResultCount": min(PAGE_SIZE, limit),
    }
    if included_type:
        body["includedType"] = included_type

    results: list[dict] = []
    seen: set[str] = set()
    page_token = None
    async with httpx.AsyncClient(timeout=places_timeout()) as client:
        while True:
            page_body = dict(body, pageToken=page_token) if page_token else body
            data = await _post_page(client, page_body, api_key)
            for place in data.get("places") or []:
                if not place.get("id") or place["id"] in seen:
                    continue
                seen.add(place["id"])
                results.append(_normalize(place))
            page_token = data.get("nextPageToken")
            if not page_token or len(results) >= limit:
                break
            await asyncio.sleep(NEXT_PAGE_DELAY_SECONDS)
    return results[:limit]
