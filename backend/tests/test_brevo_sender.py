import json

import httpx
import pytest

from services import email_sender
from services.email_sender import BrevoSender, SendError, SendOutcomeUnknown


def _sender(handler):
    return BrevoSender(
        api_key="test-brevo-key-not-real",
        from_email="sender@example.com",
        from_name="Outreach Team",
        transport=httpx.MockTransport(handler),
    )


def test_brevo_sends_one_message_with_the_api_key_and_unsubscribe_headers():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(201, json={"messageId": "<abc@brevo>"})

    message_id = _sender(handler).send(
        "owner@karahicorner.pk", "Hello", "Body text", "key-1", "https://example.com/unsubscribe?t=1"
    )

    assert message_id == "<abc@brevo>"
    assert seen["url"] == "https://api.brevo.com/v3/smtp/email"
    assert seen["key"] == "test-brevo-key-not-real"
    body = seen["body"]
    assert body["to"] == [{"email": "owner@karahicorner.pk"}]
    assert body["sender"] == {"name": "Outreach Team", "email": "sender@example.com"}
    assert body["textContent"] == "Body text"
    assert body["headers"]["List-Unsubscribe"] == "<https://example.com/unsubscribe?t=1>"
    assert body["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


def test_a_refused_message_is_retryable_not_sent():
    def handler(request):
        return httpx.Response(400, json={"code": "invalid_parameter", "message": "bad address"})

    with pytest.raises(SendError, match="bad address"):
        _sender(handler).send("owner@karahicorner.pk", "Hello", "Body", "key-2")


def test_a_server_error_is_never_resent_automatically():
    def handler(request):
        return httpx.Response(500, json={"message": "boom"})

    with pytest.raises(SendOutcomeUnknown):
        _sender(handler).send("owner@karahicorner.pk", "Hello", "Body", "key-3")


def test_a_network_failure_is_treated_as_unknown_outcome():
    def handler(request):
        raise httpx.ConnectError("connection reset")

    with pytest.raises(SendOutcomeUnknown):
        _sender(handler).send("owner@karahicorner.pk", "Hello", "Body", "key-4")


def test_brevo_is_chosen_only_when_its_settings_are_present(monkeypatch):
    monkeypatch.setenv("MOCK_EMAIL_MODE", "false")
    monkeypatch.setenv("EMAIL_PROVIDER", "brevo")
    monkeypatch.delenv("BREVO_API_KEY", raising=False)
    monkeypatch.setenv("EMAIL_FROM", "sender@example.com")
    with pytest.raises(SendError, match="BREVO_API_KEY"):
        email_sender.get_sender()

    monkeypatch.setenv("BREVO_API_KEY", "test-brevo-key-not-real")
    sender = email_sender.get_sender()
    assert isinstance(sender, BrevoSender)
    assert sender.from_email == "sender@example.com"
