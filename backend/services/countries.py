"""Countries for business discovery: the 249 ISO 3166-1 alpha-2 entries.

The list is data/countries.json. A search always carries a two-letter code. The country name is looked up here,
never taken from the client, so a record's country name always matches its code.
"""
import json
import unicodedata
from functools import lru_cache
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "countries.json"
DEFAULT_COUNTRY_CODE = "PK"
EXPECTED_COUNTRY_COUNT = 249


@lru_cache(maxsize=1)
def _registry() -> dict[str, str]:
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    rows = data["countries"]
    if len(rows) != EXPECTED_COUNTRY_COUNT:
        raise RuntimeError(f"countries.json must list {EXPECTED_COUNTRY_COUNT} countries, found {len(rows)}.")
    return {row["code"]: row["name"] for row in rows}


def all_countries() -> list[dict]:
    """Every country, alphabetically by name, as {code, name}."""
    return sorted(({"code": code, "name": name} for code, name in _registry().items()), key=lambda c: _sort_key(c["name"]))


def _sort_key(name: str) -> str:
    """Alphabetical order that ignores accents, so Åland sorts with A and Côte with C."""
    decomposed = unicodedata.normalize('NFKD', name)
    return ''.join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def normalize_code(code: str | None) -> str:
    return (code or "").strip().upper()


def is_known_country(code: str | None) -> bool:
    return normalize_code(code) in _registry()


def country_name(code: str | None) -> str:
    """The English name for a code. Raises KeyError for an unknown code."""
    return _registry()[normalize_code(code)]
