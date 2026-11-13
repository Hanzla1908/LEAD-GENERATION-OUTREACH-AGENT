"""
Outreach email draft generation using the Claude API (shared by every industry).

Rules:
- Uses only facts provided by the caller (verified lead data).
- The wording, the instructions and the services offered come from the business's industry profile.
  A restaurant email never reaches a clinic or an agency, and a property email never mentions food.
- Never invents details, never claims a website is absent without evidence.
- Returns raw subject + body for human review. No sending occurs here.
"""

import json
import os

import anthropic

from agents.lead_qualifier import feature_status, industry_of
from services import countries as country_registry
from services import industries
from services.industries import DEFAULT_INDUSTRY

# Restaurant angle texts, kept for existing callers. Each industry's own texts live in industries.json.
_ANGLES: dict[str, str] = {
    "ordering_gap":  "the restaurant has a website but no online ordering — offer online ordering setup",
    "website_gap":   "the restaurant's website was not found or is down — offer website development",
    "ai_assistant":  "the restaurant already has online ordering — offer an AI order-taking assistant upgrade",
    "general":       "offer general digital services tailored to restaurants",
}

DEFAULT_TONE = "Friendly, professional and concise. One clear call to action."

_SYSTEM_TEMPLATE = """\
You are a professional outreach specialist writing a concise, friendly cold email
to the owner or manager of a {noun}, on behalf of a digital services agency.

Strict rules:
1. Use ONLY the facts provided. Never invent details or claim unsupported things.
2. Do NOT state that the business lacks a website unless website_status is explicitly "not_found".
3. Keep the email body under 160 words. Keep the subject under 10 words.
4. Be helpful and conversational, not salesy. One clear call to action.
5. Do not mention pricing.
6. Follow the industry instructions below. Do not use wording from any other industry.
7. Output ONLY valid JSON with exactly these keys: {{"subject": "...", "body": "..."}}.
"""


def _system_prompt(industry: str) -> str:
    return _SYSTEM_TEMPLATE.format(noun=industries.get_industry(industry)["business_noun"])


def choose_angle(restaurant: dict) -> str:
    """The angle key for a business: its website gap, its primary-feature gap, an existing feature, or general."""
    industry = industry_of(restaurant)
    keys = industries.outreach(industry)["angle_keys"]
    primary = industries.primary_feature_key(industry)
    ws = restaurant.get("website_status", "unknown")
    primary_state = feature_status(restaurant, primary)
    if ws == "not_found":
        return keys["website_gap"]
    if ws == "present" and primary_state == "not_found":
        return keys["feature_gap"]
    if primary_state == "present":
        return keys["feature_present"]
    return keys["general"]


def _meaning_for(angle: str, industry: str) -> str:
    keys = industries.outreach(industry)["angle_keys"]
    for meaning, stored in keys.items():
        if stored == angle:
            return meaning
    return "general"


def explain_ai_error(exc: Exception) -> str:
    """A short, safe message for the screen. The API key and the raw provider text are never shown."""
    text = str(exc).lower()
    if isinstance(exc, anthropic.AuthenticationError):
        return "The AI service rejected ANTHROPIC_API_KEY. Check the key in the .env file."
    if isinstance(exc, anthropic.PermissionDeniedError):
        return "The AI service refused this request for the configured key. Check the key's permissions."
    if isinstance(exc, anthropic.RateLimitError):
        return "The AI service is busy. Wait a moment and try again."
    if "credit balance" in text or "billing" in text:
        return ("The AI account has no credit left, so drafts cannot be written. "
                "Add credit in the Anthropic console, then try again.")
    return "The AI service could not write the draft right now. Try again shortly."


def build_prompt(restaurant: dict, angle: str, instructions: str | None = None) -> str:
    industry = industry_of(restaurant)
    profile = industries.get_industry(industry)
    outreach_cfg = profile["outreach"]
    noun = profile["business_noun"]
    primary = industries.primary_feature_key(industry)

    lines = [
        f"{noun.capitalize()} name: {restaurant.get('name', 'the business')}",
        f"Address/city: {restaurant.get('address') or 'not specified'}",
        f"Website status: {restaurant.get('website_status', 'unknown')}",
    ]
    for feature in industries.features(industry):
        lines.append(f"{feature['label']} status: {feature_status(restaurant, feature['key'])}")
    lines.append(f"Phone on file: {'yes' if restaurant.get('phone') else 'no'}")
    lines.append(f"Pitch angle: {outreach_cfg['angles'][_meaning_for(angle, industry)]}")
    subcategory = industries.get_subcategory(industry, restaurant.get("subcategory"))
    if subcategory:
        lines.append(f"Business type: {subcategory['name']}")
    lines.append(f"City: {restaurant.get('city') or 'not specified'}")
    country_code = restaurant.get("country_code") or "PK"
    if country_registry.is_known_country(country_code):
        lines.append(f"Country: {country_registry.country_name(country_code)}")
    lines.append(f"Tone: {outreach_cfg.get('tone') or DEFAULT_TONE}")
    if outreach_cfg.get("goals"):
        lines.append(f"Goal of the email: {outreach_cfg['goals']}")

    evidence = (restaurant.get("website_features") or {}).get(primary, {}).get("evidence") or []
    if not evidence and primary == "ordering":
        evidence = restaurant.get("ordering_evidence") or []
    if evidence:
        primary_label = industries.feature_by_key(industry, primary)["label"]
        lines.append(f"{primary_label} evidence: {', '.join(str(e) for e in evidence[:3])}")

    lines.append(f"Industry instructions: {outreach_cfg['instructions']}")
    if instructions and instructions.strip():
        lines.append(f"Reviewer instructions (follow them, but never invent facts): {instructions.strip()}")
    lines.append(
        "Services you may offer (mention only those that fit the facts): "
        + "; ".join(outreach_cfg["services"])
    )
    return "Facts:\n" + "\n".join(lines) + "\n\nWrite the outreach email JSON."


async def generate_draft(restaurant: dict, instructions: str | None = None) -> dict:
    """
    Generate a personalised email draft for a qualified business lead.

    Returns:
        {"subject": str, "body": str, "angle": str}

    Raises:
        ValueError: if ANTHROPIC_API_KEY missing or Claude returns unusable output.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY is not configured")

    industry = industry_of(restaurant)
    angle = choose_angle(restaurant)
    prompt = build_prompt(restaurant, angle, instructions)

    client = anthropic.Anthropic(api_key=api_key)
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=500,
            system=_system_prompt(industry),
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as exc:
        raise ValueError(explain_ai_error(exc)) from exc

    raw = msg.content[0].text.strip()

    # Strip optional markdown fences
    if "```" in raw:
        raw = raw.split("```")[1].lstrip("json\n").strip()
        if "```" in raw:
            raw = raw.split("```")[0].strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Claude returned non-JSON output: {raw[:300]}") from exc

    subject = str(data.get("subject", "")).strip()[:200]
    body = str(data.get("body", "")).strip()[:3000]

    if not subject or not body:
        raise ValueError("Claude returned an empty subject or body")

    return {"subject": subject, "body": body, "angle": angle}
