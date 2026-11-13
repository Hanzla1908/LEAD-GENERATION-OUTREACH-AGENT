import re
from typing import NamedTuple

from services import industries

# Pakistan is the default country. Other countries come from services/countries.py.
COUNTRY = "Pakistan"
REGION_CODE = "PK"

PAKISTAN_CITIES = [
    "Lahore", "Karachi", "Islamabad", "Rawalpindi", "Faisalabad", "Multan",
    "Peshawar", "Quetta", "Sialkot", "Gujranwala", "Hyderabad", "Bahawalpur",
    "Sargodha", "Abbottabad", "Sukkur", "Mardan", "Rahim Yar Khan",
    "Sheikhupura", "Jhelum",
]

# A city name in any language or script: letters, spaces, and the punctuation found in place names.
# Digits and symbols are refused. The name is cleaned and length-checked by the request schema.
CITY_PATTERN = re.compile(r"[^\W\d_](?:[^\W\d_]| |\.|'|’|-){1,59}")

_KNOWN_CITIES = {city.lower(): city for city in PAKISTAN_CITIES}


def canonical_city(name: str) -> str:
    """Known Pakistani cities keep their standard spelling. Any other valid name is accepted as typed, title-cased."""
    words = name.split()
    known = _KNOWN_CITIES.get(" ".join(words).lower())
    if known:
        return known
    return " ".join(word[:1].upper() + word[1:] for word in words)


class CategoryProfile(NamedTuple):
    text: str
    included_type: str | None


# Restaurant categories, read from the restaurants_food profile in industries.json. Kept under the old name so
# existing callers and tests keep working. Text terms are always used; included_type is a Google Places type that
# biases results toward that type. It is not a guarantee that a place serves the cuisine.
CATEGORY_PROFILES: dict[str, CategoryProfile] = {
    sub["key"]: CategoryProfile(sub["search_text"], sub.get("provider_type"))
    for sub in industries.subcategories(industries.DEFAULT_INDUSTRY)
}


def build_text_query(category: str, city: str, country_name: str = COUNTRY) -> str:
    return f"{CATEGORY_PROFILES[category].text} in {city}, {country_name}"


def build_query(industry_key: str, subcategory_key: str, city: str,
                country_name: str = COUNTRY) -> tuple[str, str | None]:
    """The provider search text and the optional provider type for an industry, subcategory, city and country."""
    sub = industries.get_subcategory(industry_key, subcategory_key)
    if sub is None:
        raise KeyError(subcategory_key)
    return f"{sub['search_text']} in {city}, {country_name}", sub.get("provider_type")
