"""AI provider selection (services/ai_provider.py).

OpenAI is the active provider. Anthropic is kept but paused. These tests check that the selected provider is the only
one called, that a missing key is reported rather than silently replaced, and that both adapters send the right
request. Every client is a mock. No test reaches a real AI service.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import openai
import pytest

from services import ai_provider
from services.ai_provider import AIProviderError, active_provider, complete_text, provider_ready
from services.outreach import generate_draft

REPLY = {"subject": "Online ordering for Lucky Dragon", "body": "Hello Lucky Dragon team, a short note."}


def _openai_client(text=None, error=None):
    client = MagicMock()
    if error is not None:
        client.responses.create.side_effect = error
    else:
        client.responses.create.return_value = SimpleNamespace(output_text=text if text is not None else json.dumps(REPLY))
    return client


def _anthropic_client_that_must_not_be_used():
    client = MagicMock()
    client.messages.create.side_effect = AssertionError("Anthropic was called, but the OpenAI provider is selected.")
    return client


def _use(monkeypatch, client, provider="openai"):
    """Patch the factory for one provider. The other provider's factory refuses (set by the test fixture)."""
    target = "_openai_client" if provider == "openai" else "_anthropic_client"
    monkeypatch.setattr(ai_provider, target, lambda api_key: client)


# ── Selection ─────────────────────────────────────────────────────────────────

def test_openai_is_the_default_provider(monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    assert active_provider() == "openai"


def test_the_provider_name_is_read_case_insensitively(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", " OpenAI ")
    assert active_provider() == "openai"


def test_an_unknown_provider_is_refused_with_a_clear_message(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "mistral")
    with pytest.raises(AIProviderError, match="AI_PROVIDER must be 'openai' or 'anthropic'"):
        active_provider()


def test_a_missing_openai_key_is_reported_and_nothing_is_called(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    anthropic_client = _anthropic_client_that_must_not_be_used()
    _use(monkeypatch, anthropic_client, provider="anthropic")
    with pytest.raises(AIProviderError, match="OPENAI_API_KEY is not set"):
        complete_text("system", "prompt", 100)
    anthropic_client.messages.create.assert_not_called()


def test_a_missing_openai_model_is_reported(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    with pytest.raises(AIProviderError, match="OPENAI_MODEL is not set"):
        complete_text("system", "prompt", 100)


def test_provider_ready_reflects_the_selected_provider_only(monkeypatch):
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-anthropic")
    assert provider_ready() is False  # the Anthropic key does not make OpenAI ready
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-openai")
    assert provider_ready() is True


# ── OpenAI (active) ───────────────────────────────────────────────────────────

def test_openai_request_uses_the_responses_api_with_the_configured_model(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model-openai")
    client = _openai_client()
    _use(monkeypatch, client, provider="openai")

    text = complete_text("Write as a careful sales writer.", "Facts: Lucky Dragon", 500)

    assert json.loads(text) == REPLY
    kwargs = client.responses.create.call_args.kwargs
    assert kwargs["model"] == "test-model-openai"
    assert kwargs["instructions"] == "Write as a careful sales writer."
    assert kwargs["input"] == "Facts: Lucky Dragon"
    assert kwargs["max_output_tokens"] == 500


@pytest.mark.asyncio
async def test_generate_draft_uses_openai_and_returns_subject_and_body(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client = _openai_client()
    _use(monkeypatch, client, provider="openai")

    result = await generate_draft({"name": "Lucky Dragon", "website_status": "present", "ordering_status": "not_found"})

    assert result["subject"] == REPLY["subject"]
    assert result["body"] == REPLY["body"]
    assert result["angle"] == "ordering_gap"
    client.responses.create.assert_called_once()


def test_an_empty_openai_answer_is_a_readable_error(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    _use(monkeypatch, _openai_client(text="   "), provider="openai")
    with pytest.raises(AIProviderError, match="empty answer"):
        complete_text("system", "prompt", 100)


def test_openai_rate_limit_with_no_credit_is_readable_and_hides_the_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-openai-value")
    error = openai.RateLimitError(
        "You exceeded your current quota, please check your plan and billing details.",
        response=httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com/v1/responses")),
        body={"code": "insufficient_quota"},
    )
    _use(monkeypatch, _openai_client(error=error), provider="openai")
    with pytest.raises(AIProviderError) as caught:
        complete_text("system", "prompt", 100)
    assert "no credit left" in str(caught.value)
    assert "sk-secret-openai-value" not in str(caught.value)


def test_openai_timeout_is_readable(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    error = openai.APITimeoutError(request=httpx.Request("POST", "https://api.openai.com/v1/responses"))
    _use(monkeypatch, _openai_client(error=error), provider="openai")
    with pytest.raises(AIProviderError, match="took too long"):
        complete_text("system", "prompt", 100)


def test_the_lead_reason_uses_openai_when_it_is_selected(monkeypatch):
    from agents.lead_qualifier import _claude_reason

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    client = _openai_client(text="The website is live and an email was found.")
    _use(monkeypatch, client, provider="openai")
    import asyncio

    reason = asyncio.run(_claude_reason({"name": "Cafe", "website_status": "present"}, 70, "qualified", {}, "restaurants_food"))
    assert reason == "The website is live and an email was found."
    client.responses.create.assert_called_once()


def test_the_lead_reason_falls_back_when_openai_is_not_configured(monkeypatch):
    from agents.lead_qualifier import _claude_reason

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    import asyncio

    reason = asyncio.run(_claude_reason({"name": "Cafe"}, 70, "qualified", {}, "restaurants_food"))
    assert isinstance(reason, str) and reason


# ── Anthropic (paused, must not be called while OpenAI is selected) ───────────

def test_anthropic_is_never_called_while_openai_is_selected(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-anthropic")
    anthropic_client = _anthropic_client_that_must_not_be_used()
    _use(monkeypatch, anthropic_client, provider="anthropic")
    openai_client = _openai_client()
    _use(monkeypatch, openai_client, provider="openai")

    complete_text("system", "prompt", 100)

    openai_client.responses.create.assert_called_once()
    anthropic_client.messages.create.assert_not_called()


def test_a_missing_anthropic_key_does_not_affect_openai(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-openai")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = _openai_client(text="ok")
    _use(monkeypatch, client, provider="openai")
    assert complete_text("system", "prompt", 100) == "ok"


def test_anthropic_is_used_only_when_it_is_selected(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-anthropic")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-openai")
    anthropic_client = MagicMock()
    anthropic_client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(text="Anthropic reply.")])
    _use(monkeypatch, anthropic_client, provider="anthropic")
    openai_client = _openai_client()
    _use(monkeypatch, openai_client, provider="openai")

    assert complete_text("system", "prompt", 100) == "Anthropic reply."
    openai_client.responses.create.assert_not_called()
    kwargs = anthropic_client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-haiku-4-5"  # default when ANTHROPIC_MODEL is empty
    assert kwargs["system"] == "system"


def test_anthropic_model_can_be_configured(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-anthropic")
    monkeypatch.setenv("ANTHROPIC_MODEL", "test-model-anthropic")
    anthropic_client = MagicMock()
    anthropic_client.messages.create.return_value = SimpleNamespace(content=[SimpleNamespace(text="ok")])
    _use(monkeypatch, anthropic_client, provider="anthropic")
    complete_text("system", "prompt", 100)
    assert anthropic_client.messages.create.call_args.kwargs["model"] == "test-model-anthropic"


def test_selecting_anthropic_without_its_key_does_not_fall_back_to_openai(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-openai")
    openai_client = _openai_client()
    _use(monkeypatch, openai_client, provider="openai")
    with pytest.raises(AIProviderError, match="ANTHROPIC_API_KEY is not set"):
        complete_text("system", "prompt", 100)
    openai_client.responses.create.assert_not_called()
