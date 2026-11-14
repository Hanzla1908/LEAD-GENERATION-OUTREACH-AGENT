"""Which AI provider the app uses, and the one place that calls it.

Two providers are supported:

- openai (ACTIVE, the default). Uses the OpenAI Responses API with OPENAI_API_KEY and OPENAI_MODEL.
- anthropic (PAUSED). Kept, so it can be switched on later with AI_PROVIDER=anthropic, ANTHROPIC_API_KEY and
  optionally ANTHROPIC_MODEL. While AI_PROVIDER is openai, nothing calls Anthropic and no Anthropic key is needed.

Rules:
- Only the selected provider is called, and only its key is read.
- The app never switches providers on its own. A missing key or an unknown AI_PROVIDER is reported, not replaced.
- Errors carry a short, readable reason. They never contain a key or the raw provider text.

Draft writing (services/outreach.py) and the lead reason (agents/lead_qualifier.py) both call complete_text().
"""

import os

PROVIDERS = ("openai", "anthropic")
DEFAULT_PROVIDER = "openai"
ANTHROPIC_DEFAULT_MODEL = "claude-haiku-4-5"
REQUEST_TIMEOUT_SECONDS = 60.0

GENERIC_FAILURE = "The AI service could not write the draft right now. Try again shortly."
CREDIT_MESSAGE = (
    "The {name} account has no credit left, so drafts cannot be written. "
    "Add billing or credits in the {name} dashboard, then try again."
)


class AIProviderError(ValueError):
    """A readable reason for the screen. It never contains a key or raw provider text."""


def active_provider() -> str:
    """The provider named by AI_PROVIDER. Defaults to openai. Raises for an unknown name."""
    raw = (os.getenv("AI_PROVIDER") or "").strip().lower()
    if not raw:
        return DEFAULT_PROVIDER
    if raw not in PROVIDERS:
        raise AIProviderError(f"AI_PROVIDER must be 'openai' or 'anthropic', not '{raw}'. Fix it in the .env file.")
    return raw


def key_name(provider: str) -> str:
    return f"{provider.upper()}_API_KEY"


def _settings(provider: str) -> tuple[str, str]:
    """(api key, model) for one provider. Raises a readable error when something it needs is missing."""
    key = (os.getenv(key_name(provider)) or "").strip()
    if not key:
        raise AIProviderError(
            f"AI_PROVIDER is {provider}, but {key_name(provider)} is not set in the .env file. "
            "Add the key, or change AI_PROVIDER to use the other provider."
        )
    if provider == "openai":
        model = (os.getenv("OPENAI_MODEL") or "").strip()
        if not model:
            raise AIProviderError("OPENAI_MODEL is not set in the .env file. Set it to a model your OpenAI account can use.")
    else:
        model = (os.getenv("ANTHROPIC_MODEL") or "").strip() or ANTHROPIC_DEFAULT_MODEL
    return key, model


def provider_ready() -> bool:
    """True when the selected provider has what it needs. Used for quiet fallbacks. Never raises."""
    try:
        _settings(active_provider())
    except AIProviderError:
        return False
    return True


def complete_text(system: str, prompt: str, max_tokens: int) -> str:
    """Send one request to the selected provider and return its text. Raises AIProviderError on any failure."""
    provider = active_provider()
    key, model = _settings(provider)
    if provider == "openai":
        return _openai_text(key, model, system, prompt, max_tokens)
    return _anthropic_text(key, model, system, prompt, max_tokens)


# ── OpenAI (active) ───────────────────────────────────────────────────────────

def _openai_client(api_key: str):
    from openai import OpenAI

    return OpenAI(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)


def _openai_text(api_key: str, model: str, system: str, prompt: str, max_tokens: int) -> str:
    import openai

    client = _openai_client(api_key)
    try:
        response = client.responses.create(
            model=model,
            instructions=system,
            input=prompt,
            max_output_tokens=max_tokens,
        )
    except openai.APIError as exc:
        raise AIProviderError(explain_provider_error(exc)) from exc
    text = (response.output_text or "").strip()
    if not text:
        raise AIProviderError("The AI service returned an empty answer. Try again.")
    return text


# ── Anthropic (paused, kept for later) ────────────────────────────────────────

def _anthropic_client(api_key: str):
    import anthropic

    return anthropic.Anthropic(api_key=api_key)


def _anthropic_text(api_key: str, model: str, system: str, prompt: str, max_tokens: int) -> str:
    import anthropic

    client = _anthropic_client(api_key)
    try:
        msg = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.APIError as exc:
        raise AIProviderError(explain_provider_error(exc)) from exc
    return msg.content[0].text.strip()


# ── Readable errors ───────────────────────────────────────────────────────────

def explain_provider_error(exc: Exception) -> str:
    """A short, safe message for the screen, for either provider's exception."""
    module = type(exc).__module__ or ""
    if module.startswith("openai"):
        return _explain_openai(exc)
    if module.startswith("anthropic"):
        return _explain_anthropic(exc)
    return GENERIC_FAILURE


def _explain_openai(exc: Exception) -> str:
    import openai

    text = str(exc).lower()
    if "insufficient_quota" in text or "billing" in text:
        return CREDIT_MESSAGE.format(name="OpenAI")
    if isinstance(exc, openai.AuthenticationError):
        return "OpenAI rejected OPENAI_API_KEY. Check the key in the .env file."
    if isinstance(exc, openai.PermissionDeniedError):
        return "OpenAI refused this request for the configured key. Check the key's permissions and project."
    if isinstance(exc, openai.RateLimitError):
        return "The AI service is busy. Wait a moment and try again."
    if isinstance(exc, openai.APITimeoutError):
        return "The AI service took too long to answer. Try again."
    if isinstance(exc, openai.APIConnectionError):
        return "Could not reach the AI service. Check the internet connection and try again."
    if isinstance(exc, openai.NotFoundError):
        return "OPENAI_MODEL is not available to this account. Choose another model in the .env file."
    return GENERIC_FAILURE


def _explain_anthropic(exc: Exception) -> str:
    import anthropic

    text = str(exc).lower()
    if isinstance(exc, anthropic.AuthenticationError):
        return "The AI service rejected ANTHROPIC_API_KEY. Check the key in the .env file."
    if isinstance(exc, anthropic.PermissionDeniedError):
        return "The AI service refused this request for the configured key. Check the key's permissions."
    if isinstance(exc, anthropic.RateLimitError):
        return "The AI service is busy. Wait a moment and try again."
    if "credit balance" in text or "billing" in text:
        return CREDIT_MESSAGE.format(name="Anthropic")
    return GENERIC_FAILURE
