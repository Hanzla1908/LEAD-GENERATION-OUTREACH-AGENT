"""
Lead qualification agent (shared by every industry).

Scoring rules are deterministic. Claude cannot alter them. Each industry's weights and thresholds come from its
profile in industries.json; the restaurant profile carries the original values, so restaurant scores are unchanged.

  website present               +30  (website_present)
  website not found             -40  (website_not_found)
  primary feature missing       +25  (the industry's main gap: <feature>_not_found, e.g. ordering_not_found)
  primary feature present       -20  (<feature>_present)
  business email found          +25  (email_found)
  phone present                 +10  (phone_present)

Thresholds (restaurants):
  score >= 55  -> qualified
  score 20-54  -> needs_review
  score <  20  -> disqualified

Every score is explained by its breakdown. Claude may only summarise those facts in one sentence; the score and
status are set before Claude is called, and the fallback sentence is built from the same facts.
"""

from services import industries
from services.ai_provider import complete_text, provider_ready
from services.industries import DEFAULT_INDUSTRY

# Restaurant constants, kept under their old names for existing callers and tests.
SCORE_WEIGHTS: dict[str, int] = {
    "website_present":    +30,
    "ordering_not_found": +25,
    "ordering_present":   -20,
    "email_found":        +25,
    "phone_present":      +10,
    "website_not_found":  -40,
}

QUALIFIED_THRESHOLD = 55
NEEDS_REVIEW_THRESHOLD = 20

_LABELS: dict[str, str] = {
    "website_present":    "website is live",
    "ordering_not_found": "no online ordering yet (outreach opportunity)",
    "ordering_present":   "already uses online ordering",
    "email_found":        "business email found",
    "phone_present":      "phone number available",
    "website_not_found":  "website not reachable",
}


def industry_of(restaurant: dict) -> str:
    """The industry a business record belongs to. Records saved before industries existed are restaurants."""
    key = restaurant.get("industry") or DEFAULT_INDUSTRY
    return key if industries.is_known(key) else DEFAULT_INDUSTRY


def feature_status(restaurant: dict, feature_key: str) -> str:
    """Status of one website feature for a business: present, not_found or unknown."""
    stored = restaurant.get("website_features") or {}
    entry = stored.get(feature_key) if isinstance(stored, dict) else None
    if isinstance(entry, dict) and entry.get("status"):
        return entry["status"]
    if feature_key == "ordering":
        # Records checked before per-feature evidence existed kept their result in ordering_status.
        return restaurant.get("ordering_status", "unknown")
    return "unknown"


def _label(key: str, industry: str) -> str:
    if key in _LABELS:
        return _LABELS[key]
    primary = industries.primary_feature_key(industry)
    feature = industries.feature_by_key(industry, primary) or {"label": primary}
    if key == f"{primary}_not_found":
        return f"no {feature['label'].lower()} found (outreach opportunity)"
    if key == f"{primary}_present":
        return f"already has {feature['label'].lower()}"
    return key


def compute_score(restaurant: dict) -> tuple[int, dict[str, int]]:
    """Return (total_score, breakdown_dict) from the industry's deterministic rules."""
    industry = industry_of(restaurant)
    weights = industries.scoring(industry)
    primary = industries.primary_feature_key(industry)
    breakdown: dict[str, int] = {}

    ws = restaurant.get("website_status", "unknown")
    if ws == "present":
        breakdown["website_present"] = weights["website_present"]
    elif ws == "not_found":
        breakdown["website_not_found"] = weights["website_not_found"]

    primary_state = feature_status(restaurant, primary)
    if primary_state == "not_found":
        breakdown[f"{primary}_not_found"] = weights["primary_missing"]
    elif primary_state == "present":
        breakdown[f"{primary}_present"] = weights["primary_present"]

    # Only a usable address counts: an invalid or disposable one is not an outreach channel (Phase 17).
    usable_email = (
        restaurant.get("contact_email")
        and restaurant.get("contact_email_status") != "invalid"
        and restaurant.get("contact_email_classification") != "disposable"
    )
    if usable_email:
        breakdown["email_found"] = weights["email_found"]

    if restaurant.get("phone"):
        breakdown["phone_present"] = weights["phone_present"]

    return sum(breakdown.values()), breakdown


def score_to_status(score: int, industry: str = DEFAULT_INDUSTRY) -> str:
    limits = industries.thresholds(industry)
    if score >= limits["qualified"]:
        return "qualified"
    if score >= limits["needs_review"]:
        return "needs_review"
    return "disqualified"


def _fallback_reason(status: str, breakdown: dict, industry: str = DEFAULT_INDUSTRY) -> str:
    pos = [_label(k, industry) for k, v in breakdown.items() if v > 0]
    neg = [_label(k, industry) for k, v in breakdown.items() if v < 0]
    parts: list[str] = []
    if pos:
        parts.append(", ".join(pos))
    if neg:
        parts.append("but " + ", ".join(neg))
    if not parts:
        return f"Status is {status} based on available data."
    return "; ".join(parts).capitalize() + "."


def _system_prompt(industry: str) -> str:
    noun = industries.get_industry(industry)["business_noun"]
    return (
        f"You are a lead qualification assistant for {noun} outreach. "
        f"Given the {noun} data below, write ONE sentence (under 120 characters) "
        f"explaining why this {noun} received its qualification status. "
        "Use only the provided data. Do not invent facts. Do not mention scores or recommend actions."
    )


async def _claude_reason(
    restaurant: dict, score: int, status: str, breakdown: dict, industry: str = DEFAULT_INDUSTRY
) -> str:
    # A missing or misconfigured AI provider never blocks qualification: the sentence comes from the facts instead.
    if not provider_ready():
        return _fallback_reason(status, breakdown, industry)

    facts = [
        f"Name: {restaurant.get('name', 'unknown')}",
        f"Website status: {restaurant.get('website_status', 'unknown')}",
    ]
    for feature in industries.features(industry):
        facts.append(f"{feature['label']}: {feature_status(restaurant, feature['key'])}")
    facts.extend([
        f"Email found: {'yes' if restaurant.get('contact_email') else 'no'}",
        f"Phone: {'yes' if restaurant.get('phone') else 'no'}",
        f"Qualification: {status}",
        f"Score factors: {', '.join(f'{_label(k, industry)} ({v:+d})' for k, v in breakdown.items())}",
    ])

    try:
        text = complete_text(
            system=_system_prompt(industry),
            prompt="\n".join(facts) + "\n\nWrite the one-sentence reason.",
            max_tokens=80,
        )
        return text.strip()[:200]
    except Exception:
        return _fallback_reason(status, breakdown, industry)


async def qualify_lead(restaurant: dict) -> dict:
    """
    Qualify a business as a sales lead, using its industry's rules.

    Returns:
        {
            "lead_score":  int,
            "lead_status": "qualified" | "needs_review" | "disqualified",
            "lead_reason": str,
        }
    """
    industry = industry_of(restaurant)
    score, breakdown = compute_score(restaurant)
    status = score_to_status(score, industry)
    reason = await _claude_reason(restaurant, score, status, breakdown, industry)

    return {"lead_score": score, "lead_status": status, "lead_reason": reason}
