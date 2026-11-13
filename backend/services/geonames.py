"""City search over the GeoNames city tables (geo_cities, geo_city_alternate_names).

Used for two things only: suggesting a city in the City field, and giving discovery a canonical city name and admin
division. A city from this table is never a business, and discovery still runs its own search (Google Places or Demo
Mode). Nothing here calls Google.

Search rules:
- Names match by prefix, accent-insensitive and case-insensitive. "Sao" finds São Paulo.
- Alternate names match too, so "Lyallpur" finds Faisalabad. The result shows the name that matched.
- Results are always limited to one country. A query never returns a city from another country.
- Results are paged with limit and offset, capped at MAX_LIMIT.
- Searches are cached in memory for a short time. Import runs in another process, so the cache expires quickly.
"""
import time
import unicodedata
from collections import OrderedDict
from threading import Lock

from models.database import fetch_all, fetch_one
from services import countries
from services.search_profiles import PAKISTAN_CITIES

SOURCE = "GeoNames"
ATTRIBUTION = "City data © GeoNames (https://www.geonames.org/), licensed under CC BY 4.0."
LICENCE = "CC BY 4.0"
SOURCE_URL = "https://www.geonames.org/"

DEFAULT_LIMIT = 10
MAX_LIMIT = 25
MAX_OFFSET = 10_000
MAX_QUERY_LENGTH = 60
CACHE_SECONDS = 600
CACHE_MAX_ENTRIES = 512

_HIGH = "\U0010FFFF"  # sorts after every normal character, so [q, q + _HIGH) is a prefix range
_cache: "OrderedDict[tuple, tuple[float, dict]]" = OrderedDict()
_cache_lock = Lock()


def normalize_search(text: str | None) -> str:
    """Lowercase, accent-free, with hyphens, apostrophes and periods read as spaces and single spaces.

    Stored names and typed queries both pass through here, so they compare the same way.
    """
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    spaced = "".join(" " if ch in "-'’.`" else ch for ch in stripped.casefold())
    return " ".join(spaced.split())


def _cache_get(key: tuple):
    with _cache_lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        expires, value = entry
        if expires < time.monotonic():
            _cache.pop(key, None)
            return None
        _cache.move_to_end(key)
        return value


def _cache_put(key: tuple, value: dict) -> None:
    with _cache_lock:
        _cache[key] = (time.monotonic() + CACHE_SECONDS, value)
        _cache.move_to_end(key)
        while len(_cache) > CACHE_MAX_ENTRIES:
            _cache.popitem(last=False)


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _clamp_limit(limit: int) -> int:
    return max(1, min(int(limit), MAX_LIMIT))


def _clamp_offset(offset: int) -> int:
    return max(0, min(int(offset), MAX_OFFSET))


def imported_city_count(country_code: str | None = None) -> int:
    if country_code:
        row = fetch_one("SELECT COUNT(*) AS n FROM geo_cities WHERE country_code = :cc", {"cc": country_code})
    else:
        row = fetch_one("SELECT COUNT(*) AS n FROM geo_cities")
    return int(row["n"]) if row else 0


def search_cities(country_code: str, query: str | None = "", limit: int = DEFAULT_LIMIT, offset: int = 0) -> dict:
    """Cities in one country whose name (or an alternate name) starts with the query.

    With an empty query the most populated cities come first. Returns:
      {"items": [...], "limit": n, "offset": n, "has_more": bool, "source": "geonames" | "fallback"}
    Each item has id, name, admin1_name, country_code, population, and matched_alias (set when the query matched an
    alternate name instead of the main name).
    """
    code = countries.normalize_code(country_code)
    limit = _clamp_limit(limit)
    offset = _clamp_offset(offset)
    needle = normalize_search(query)[:MAX_QUERY_LENGTH]
    key = (code, needle, limit, offset)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    if imported_city_count(code) == 0 and code == "PK":
        result = _fallback_pakistan(needle, limit, offset)
    else:
        result = _search_imported(code, needle, limit, offset)
    _cache_put(key, result)
    return result


def _search_imported(code: str, needle: str, limit: int, offset: int) -> dict:
    if not needle:
        rows = fetch_all(
            "SELECT id, name, admin1_name, population, NULL AS matched_alias FROM geo_cities "
            "WHERE country_code = :cc ORDER BY population DESC, name ASC LIMIT :lim OFFSET :off",
            {"cc": code, "lim": limit + 1, "off": offset},
        )
    else:
        # Main names and alternate names are scanned as prefix ranges on the indexed search_name column. Rows are
        # grouped per city so each city appears once. An exact match on the main name ranks first, then cities whose
        # main name matches, then by population.
        rows = fetch_all(
            """
            SELECT c.id, c.name, c.admin1_name, c.population,
                   MAX(m.by_name) AS by_name, MAX(m.is_exact) AS is_exact,
                   MIN(CASE WHEN m.by_name = 0 THEN m.alt_text END) AS matched_alias
            FROM (
                SELECT id, 1 AS by_name, CASE WHEN search_name = :q THEN 1 ELSE 0 END AS is_exact, NULL AS alt_text
                FROM geo_cities
                WHERE country_code = :cc AND search_name >= :lo AND search_name < :hi
                UNION ALL
                SELECT a.city_id, 0, CASE WHEN a.search_name = :q THEN 1 ELSE 0 END, a.alt_name
                FROM geo_city_alternate_names a
                WHERE a.country_code = :cc AND a.search_name >= :lo AND a.search_name < :hi
            ) m
            JOIN geo_cities c ON c.id = m.id
            GROUP BY c.id, c.name, c.admin1_name, c.population
            ORDER BY is_exact DESC, by_name DESC, c.population DESC, c.name ASC
            LIMIT :lim OFFSET :off
            """,
            {"cc": code, "q": needle, "lo": needle, "hi": needle + _HIGH, "lim": limit + 1, "off": offset},
        )
    return _page(rows, limit, offset, code, source="geonames")


def _fallback_pakistan(needle: str, limit: int, offset: int) -> dict:
    """Used only when the GeoNames import has not run: the built-in Pakistani list, so Pakistan still works."""
    names = sorted(PAKISTAN_CITIES, key=str.casefold)
    matches = [name for name in names if not needle or normalize_search(name).startswith(needle)]
    window = matches[offset: offset + limit + 1]
    rows = [{"id": None, "name": name, "admin1_name": None, "population": None, "matched_alias": None}
            for name in window]
    return _page(rows, limit, offset, "PK", source="fallback")


def _page(rows: list[dict], limit: int, offset: int, code: str, source: str) -> dict:
    has_more = len(rows) > limit
    items = [
        {
            "id": row["id"],
            "name": row["name"],
            "admin1_name": row["admin1_name"],
            "country_code": code,
            "population": row["population"],
            # An alias is shown only when the query matched no main name for this city.
            "matched_alias": row["matched_alias"] if row.get("by_name") == 0 and row["matched_alias"] else None,
        }
        for row in rows[:limit]
    ]
    return {"items": items, "limit": limit, "offset": offset, "has_more": has_more, "source": source}


def city_by_id(city_id: int) -> dict | None:
    return fetch_one(
        "SELECT id, country_code, name, admin1_name, population FROM geo_cities WHERE id = :id",
        {"id": int(city_id)},
    )


def status() -> dict:
    """Whether city data is loaded, and the attribution the interface must show."""
    count = imported_city_count()
    run = fetch_one("SELECT source, source_url, licence, imported_at, city_count, alternate_name_count "
                    "FROM geo_import_runs ORDER BY id DESC LIMIT 1") if count else None
    return {
        "loaded": count > 0,
        "city_count": count,
        "source": SOURCE,
        "source_url": SOURCE_URL,
        "licence": LICENCE,
        "attribution": ATTRIBUTION,
        "imported_at": run["imported_at"] if run else None,
        "alternate_name_count": run["alternate_name_count"] if run else 0,
    }
