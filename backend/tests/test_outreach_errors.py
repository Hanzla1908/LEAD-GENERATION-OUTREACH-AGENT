"""Draft generation when the AI service refuses or fails.

The screen should get a short, readable reason (HTTP 503), never a bare 500, and never the key or the raw
provider text. OpenAI is the active provider; the Anthropic cases cover the paused adapter that is kept for later.
"""
import asyncio
from unittest.mock import MagicMock

import anthropic
import httpx
import openai
import pytest
from fastapi.testclient import TestClient  # noqa: F401  (used through signed_in_client)

import main
from models.database import execute, save_restaurants
from services.outreach import explain_ai_error, generate_draft
from tests.account_helpers import TEST_SESSION_SECRET, signed_in_client

OPENAI_URL = "https://api.openai.com/v1/responses"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


def _error(cls, status, message, url=OPENAI_URL, body=None):
    response = httpx.Response(status, request=httpx.Request("POST", url))
    return cls(message, response=response, body=body)


CREDIT = "You exceeded your current quota, please check your plan and billing details."
ANTHROPIC_CREDIT = ("Your credit balance is too low to access the Anthropic API. "
                    "Please go to Plans & Billing to upgrade or purchase credits.")


@pytest.mark.parametrize("exc, expected", [
    (_error(openai.RateLimitError, 429, CREDIT, body={"code": "insufficient_quota"}), "no credit left"),
    (_error(openai.AuthenticationError, 401, "Incorrect API key provided: sk-proj-abc"), "OPENAI_API_KEY"),
    (_error(openai.PermissionDeniedError, 403, "forbidden"), "permissions"),
    (_error(openai.RateLimitError, 429, "Rate limit reached"), "busy"),
    (_error(openai.NotFoundError, 404, "The model does not exist"), "OPENAI_MODEL"),
    (_error(openai.InternalServerError, 500, "boom"), "could not write the draft"),
    (openai.APITimeoutError(request=httpx.Request("POST", OPENAI_URL)), "took too long"),
    (openai.APIConnectionError(request=httpx.Request("POST", OPENAI_URL)), "Could not reach"),
])
def test_known_openai_failures_get_a_readable_reason(exc, expected):
    message = explain_ai_error(exc)
    assert expected in message
    assert "sk-" not in message and "Incorrect API key" not in message


@pytest.mark.parametrize("exc, expected", [
    (_error(anthropic.BadRequestError, 400, ANTHROPIC_CREDIT, url=ANTHROPIC_URL), "no credit left"),
    (_error(anthropic.AuthenticationError, 401, "invalid x-api-key", url=ANTHROPIC_URL), "ANTHROPIC_API_KEY"),
    (_error(anthropic.RateLimitError, 429, "slow down", url=ANTHROPIC_URL), "busy"),
    (_error(anthropic.InternalServerError, 500, "boom", url=ANTHROPIC_URL), "could not write the draft"),
])
def test_known_anthropic_failures_get_a_readable_reason(exc, expected):
    message = explain_ai_error(exc)
    assert expected in message
    assert "sk-" not in message and "x-api-key" not in message


def test_the_api_key_and_raw_text_are_not_shown(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-secret-value")
    client = MagicMock()
    client.responses.create.side_effect = _error(openai.RateLimitError, 429, CREDIT, body={"code": "insufficient_quota"})
    monkeypatch.setattr("services.ai_provider._openai_client", lambda api_key: client)
    with pytest.raises(ValueError) as caught:
        asyncio.run(generate_draft({"name": "Cafe", "industry": "restaurants_food", "contact_email": "owner@cafe.pk"}))
    assert "sk-test-secret-value" not in str(caught.value)
    assert "quota" not in str(caught.value).lower()
    assert "no credit left" in str(caught.value)


@pytest.fixture
def api(test_db, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    return signed_in_client(main.app)


def test_the_draft_route_returns_a_readable_503_when_credit_is_out(api, monkeypatch):
    rid = save_restaurants([{"place_id": "ai-1", "name": "Ai Cafe", "source": "google_places"}])[0]["id"]
    execute("UPDATE restaurants SET contact_email = 'owner@aicafe.pk', contact_email_status = 'domain_valid', "
            "contact_email_classification = 'business' WHERE id = :id", {"id": rid})
    client = MagicMock()
    client.responses.create.side_effect = _error(openai.RateLimitError, 429, CREDIT, body={"code": "insufficient_quota"})
    monkeypatch.setattr("services.ai_provider._openai_client", lambda api_key: client)
    resp = api.post("/outreach/generate", json={"restaurant_id": rid, "campaign": "default"})
    assert resp.status_code == 503, resp.text
    assert "no credit left" in resp.json()["detail"]
