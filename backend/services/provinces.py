"""Provinces and states a discovery search can be limited to, by country.

The codes are the GeoNames first-level (admin1) codes stored with each city in geo_cities.admin1_code. PK.04 is
Punjab, so it is stored and sent as "04". Only the provinces listed here can be chosen. A city in any other division is
still found when no province is chosen.
"""

PAKISTAN_PROVINCES: dict[str, str] = {
    "02": "Balochistan",
    "03": "Khyber Pakhtunkhwa",
    "04": "Punjab",
    "05": "Sindh",
    "06": "Azad Jammu & Kashmir",
    "07": "Gilgit-Baltistan",
    "08": "Islamabad Capital Territory",
}

_PROVINCES_BY_COUNTRY: dict[str, dict[str, str]] = {"PK": PAKISTAN_PROVINCES}


def province_name(country_code: str, code: str) -> str | None:
    """The display name of a province, or None when the country has no province with that code."""
    return _PROVINCES_BY_COUNTRY.get(country_code, {}).get(code)


def is_known_province(country_code: str, code: str) -> bool:
    return province_name(country_code, code) is not None
