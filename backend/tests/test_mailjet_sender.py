import base64
import json

import httpx
import pytest

from services import email_sender
from services.email_sender import MailjetSender, SendError, SendOutcomeUnknown


def _sender(handler):
    return MailjetSender(
        api_key="test-mailjet-key-not-real",
        api_secret="test-mailjet-secret-not-real",
        from_email="sender@example.com",
        from_name="Outreach Team",
        transport=httpx.MockTransport(handler),
    )


def _accepted(message_id=123456):
    return {"Messages": [{"Status": "success", "To": [{"Email": "owner@karahicorner.pk", "MessageID": message_id}]}]}


def test_mailjet_sends_one_message_with_basic_auth_and_unsubscribe_headers():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_accepted(987))

    message_id = _sender(handler).send(
        "owner@karahicorner.pk", "Hello", "Body text", "key-1", "https://example.com/unsubscribe?t=1"
    )

    assert message_id == "987"
    assert seen["url"] == "https://api.mailjet.com/v3.1/send"
    expected = base64.b64encode(b"test-mailjet-key-not-real:test-mailjet-secret-not-real").decode()
    assert seen["auth"] == f"Basic {expected}"
    message = seen["body"]["Messages"][0]
    assert message["To"] == [{"Email": "owner@karahicorner.pk"}]
    assert message["From"] == {"Email": "sender@example.com", "Name": "Outreach Team"}
    assert message["TextPart"] == "Body text"
    assert message["Headers"]["List-Unsubscribe"] == "<https://example.com/unsubscribe?t=1>"
    assert message["Headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


def test_a_refused_message_is_retryable_not_sent():
    def handler(request):
        return httpx.Response(401, json={"ErrorMessage": "Invalid API credentials"})

    with pytest.raises(SendError, match="Invalid API credentials"):
        _sender(handler).send("owner@karahicorner.pk", "Hello", "Body", "key-2")


def test_a_rejected_message_inside_a_200_is_not_treated_as_sent():
    def handler(request):
        return httpx.Response(200, json={"Messages": [{"Status": "error", "Errors": [{"ErrorMessage": "bad sender"}]}]})

    with pytest.raises(SendError, match="bad sender"):
        _sender(handler).send("owner@karahicorner.pk", "Hello", "Body", "key-3")


def test_a_server_error_is_never_resent_automatically():
    def handler(request):
        return httpx.Response(500, json={"ErrorMessage": "boom"})

    with pytest.raises(SendOutcomeUnknown):
        _sender(handler).send("owner@karahicorner.pk", "Hello", "Body", "key-4")


def test_a_network_failure_is_treated_as_unknown_outcome():
    def handler(request):
        raise httpx.ConnectError("connection reset")

    with pytest.raises(SendOutcomeUnknown):
        _sender(handler).send("owner@karahicorner.pk", "Hello", "Body", "key-5")


def test_mailjet_is_chosen_only_when_its_settings_are_present(monkeypatch):
    monkeypatch.setenv("MOCK_EMAIL_MODE", "false")
    monkeypatch.setenv("EMAIL_PROVIDER", "mailjet")
    monkeypatch.setenv("EMAIL_FROM", "sender@example.com")
    monkeypatch.delenv("MAILJET_API_KEY", raising=False)
    monkeypatch.delenv("MAILJET_API_SECRET", raising=False)
    with pytest.raises(SendError, match="MAILJET_API_KEY"):
        email_sender.get_sender()

    monkeypatch.setenv("MAILJET_API_KEY", "test-mailjet-key-not-real")
    monkeypatch.setenv("MAILJET_API_SECRET", "test-mailjet-secret-not-real")
    sender = email_sender.get_sender()
    assert isinstance(sender, MailjetSender)
    assert sender.from_email == "sender@example.com"
