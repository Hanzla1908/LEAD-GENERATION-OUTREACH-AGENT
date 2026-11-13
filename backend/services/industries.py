"""Industry profiles: the configuration that the shared agents read.

Profiles live in backend/industries.json. Adding an industry, a subcategory, a website signal, a scoring
weight, a service or an outreach instruction is a configuration change. The shared agents (discovery, website
analysis, qualification, outreach) never hardcode an industry: they ask this module for the profile.

The file is loaded and validated once. An invalid file stops the server at startup with a clear message,
rather than failing in the middle of a search.
"""
import json
import re
from pathlib import Path

PROFILE_PATH = Path(__file__).resolve().parent.parent / "industries.json"
DEFAULT_INDUSTRY = "restaurants_food"

_KEY = re.compile(r"^[a-z][a-z0-9_]{1,39}$")
_REQUIRED_SCORING = (
    "website_present", "website_not_found", "primary_missing", "primary_present", "email_found", "phone_present",
)
_ANGLE_MEANINGS = ("website_gap", "feature_gap", "feature_present", "general")
_CUSTOM_FIELD_TYPES = ("text",)


class IndustryConfigError(ValueError):
    """The industry configuration file is invalid. The message names the problem."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise IndustryConfigError(message)


def _validate_industry(profile: dict, seen: set[str]) -> None:
    key = profile.get("key", "")
    _require(isinstance(key, str) and _KEY.match(key) is not None,
             f"Industry key {key!r} must be lowercase letters, digits and underscores, starting with a letter.")
    _require(key not in seen, f"Industry key {key!r} is defined more than once.")
    seen.add(key)
    _require(bool(str(profile.get("name", "")).strip()), f"Industry {key!r} needs a name.")
    _require(bool(str(profile.get("business_noun", "")).strip()), f"Industry {key!r} needs a business_noun.")

    subs = profile.get("subcategories") or []
    _require(bool(subs), f"Industry {key!r} needs at least one subcategory.")
    sub_keys: set[str] = set()
    for sub in subs:
        sk = sub.get("key", "")
        _require(isinstance(sk, str) and _KEY.match(sk) is not None,
                 f"Subcategory key {sk!r} in {key!r} must be lowercase letters, digits and underscores.")
        _require(sk not in sub_keys, f"Subcategory {sk!r} is defined more than once in {key!r}.")
        sub_keys.add(sk)
        _require(bool(str(sub.get("name", "")).strip()), f"Subcategory {sk!r} in {key!r} needs a name.")
        _require(bool(str(sub.get("search_text", "")).strip()),
                 f"Subcategory {sk!r} in {key!r} needs search_text for discovery.")

    features = profile.get("website_features") or []
    _require(bool(features), f"Industry {key!r} needs at least one website feature.")
    feature_keys = [f.get("key", "") for f in features]
    for fk in feature_keys:
        _require(isinstance(fk, str) and _KEY.match(fk) is not None,
                 f"Website feature key {fk!r} in {key!r} must be lowercase letters, digits and underscores.")
    _require(len(set(feature_keys)) == len(feature_keys), f"Website feature keys in {key!r} must be unique.")
    for feature in features:
        _require(bool(feature.get("keywords") or feature.get("domains")),
                 f"Website feature {feature.get('key')!r} in {key!r} needs keywords or domains to detect it.")
    primary = profile.get("primary_feature", "")
    _require(primary in feature_keys,
             f"primary_feature {primary!r} in {key!r} must be one of its website features.")

    scoring = profile.get("scoring") or {}
    for name in _REQUIRED_SCORING:
        _require(isinstance(scoring.get(name), int), f"Scoring weight {name!r} in {key!r} must be a whole number.")

    thresholds = profile.get("thresholds") or {}
    _require(isinstance(thresholds.get("qualified"), int) and isinstance(thresholds.get("needs_review"), int),
             f"Thresholds in {key!r} need whole numbers for qualified and needs_review.")
    _require(thresholds["qualified"] > thresholds["needs_review"],
             f"Thresholds in {key!r}: qualified must be higher than needs_review.")

    outreach = profile.get("outreach") or {}
    angle_keys = outreach.get("angle_keys") or {}
    angles = outreach.get("angles") or {}
    for meaning in _ANGLE_MEANINGS:
        _require(meaning in angle_keys, f"outreach.angle_keys in {key!r} is missing {meaning!r}.")
        stored = angle_keys[meaning]
        _require(bool(str(angles.get(meaning, "")).strip()),
                 f"outreach.angles in {key!r} is missing the text for {meaning!r}.")
        _require(isinstance(stored, str) and _KEY.match(stored) is not None,
                 f"Angle key {stored!r} in {key!r} must be lowercase letters, digits and underscores.")
    _require(bool(str(outreach.get("instructions", "")).strip()),
             f"Industry {key!r} needs outreach.instructions for personalised emails.")
    _require(bool(outreach.get("services")), f"Industry {key!r} needs at least one outreach service.")

    for field in profile.get("custom_fields") or []:
        fk = field.get("key", "")
        _require(isinstance(fk, str) and _KEY.match(fk) is not None,
                 f"Custom field key {fk!r} in {key!r} must be lowercase letters, digits and underscores.")
        _require(field.get("type", "text") in _CUSTOM_FIELD_TYPES,
                 f"Custom field {fk!r} in {key!r} has an unsupported type.")
        _require(isinstance(field.get("max_length", 120), int) and 1 <= field.get("max_length", 120) <= 500,
                 f"Custom field {fk!r} in {key!r} needs a max_length between 1 and 500.")


def validate(config: dict) -> dict[str, dict]:
    """Validate a parsed configuration and return the profiles keyed by industry key."""
    _require(isinstance(config, dict) and isinstance(config.get("industries"), list),
             "industries.json must be an object with an 'industries' list.")
    seen: set[str] = set()
    for profile in config["industries"]:
        _validate_industry(profile, seen)
    profiles = {p["key"]: p for p in config["industries"]}
    _require(DEFAULT_INDUSTRY in profiles, f"The default industry {DEFAULT_INDUSTRY!r} must be defined.")
    return profiles


_cache: dict[str, dict] | None = None


def load(path: Path | None = None) -> dict[str, dict]:
    """Read and validate the profiles. The result is cached; call reload() after the file changes."""
    global _cache
    if _cache is None or path is not None:
        target = path or PROFILE_PATH
        try:
            config = json.loads(target.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise IndustryConfigError(f"Industry profile file not found: {target}") from exc
        except json.JSONDecodeError as exc:
            raise IndustryConfigError(f"Industry profile file is not valid JSON: {exc}") from exc
        profiles = validate(config)
        if path is not None:
            return profiles
        _cache = profiles
    return _cache


def reload() -> dict[str, dict]:
    global _cache
    _cache = None
    return load()


def all_industries(enabled_only: bool = True) -> list[dict]:
    profiles = load().values()
    return [p for p in profiles if p.get("enabled", True) or not enabled_only]


def get_industry(key: str | None) -> dict:
    """The profile for a key. None means the default industry (existing restaurant records)."""
    profiles = load()
    profile = profiles.get(key or DEFAULT_INDUSTRY)
    if profile is None:
        raise KeyError(key)
    if not profile.get("enabled", True):
        raise KeyError(key)
    return profile


def is_known(key: str | None) -> bool:
    try:
        get_industry(key)
        return True
    except KeyError:
        return False


def subcategories(industry_key: str | None) -> list[dict]:
    return list(get_industry(industry_key)["subcategories"])


def get_subcategory(industry_key: str | None, subcategory_key: str | None) -> dict | None:
    """The subcategory, or None when the key is not part of the industry."""
    for sub in subcategories(industry_key):
        if sub["key"] == subcategory_key:
            return sub
    return None


def default_subcategory(industry_key: str | None) -> dict:
    return subcategories(industry_key)[0]


def features(industry_key: str | None) -> list[dict]:
    return list(get_industry(industry_key)["website_features"])


def feature_by_key(industry_key: str | None, feature_key: str) -> dict | None:
    for feature in features(industry_key):
        if feature["key"] == feature_key:
            return feature
    return None


def primary_feature_key(industry_key: str | None) -> str:
    return get_industry(industry_key)["primary_feature"]


def scoring(industry_key: str | None) -> dict:
    return dict(get_industry(industry_key)["scoring"])


def thresholds(industry_key: str | None) -> dict:
    return dict(get_industry(industry_key)["thresholds"])


def outreach(industry_key: str | None) -> dict:
    return get_industry(industry_key)["outreach"]


def custom_fields(industry_key: str | None) -> list[dict]:
    return list(get_industry(industry_key).get("custom_fields") or [])


def sanitize_custom_fields(industry_key: str | None, raw: dict | None) -> dict[str, str]:
    """Keep only the fields the industry declares, as plain text within each field's length limit."""
    if not raw:
        return {}
    cleaned: dict[str, str] = {}
    for field in custom_fields(industry_key):
        if field["key"] not in raw:
            continue
        value = " ".join(str(raw[field["key"]] or "").split())
        limit = int(field.get("max_length", 120))
        if len(value) > limit:
            raise ValueError(f"{field['label']} must be {limit} characters or fewer.")
        if value:
            cleaned[field["key"]] = value
    return cleaned
