"""Setup safeguards: live sending refuses localhost unsubscribe links, the settings are read as expected, and the example
environment file carries no real keys. Nothing is sent: live senders are replaced by fakes, and mock sending is used
for the rest.
"""
from pathlib import Path

import pytest

from services import campaigns
from services.unsubscribe import is_local_address, unsubscribe_settings, unsubscribe_url

SECRET = "setup-safeguard-secret-0123456789"


@pytest.mark.parametrize("url", [
    "http://localhost:8000", "http://127.0.0.1:8000", "http://[::1]:8000", "http://0.0.0.0:8000",
    "http://api.localhost:8000",
])
def test_local_addresses_are_recognised(url):
    assert is_local_address(url) is True


@pytest.mark.parametrize("url", [
    "https://outreach.example.com", "https://app.example.pk/path", "https://localhost.example.com",
])
def test_public_addresses_are_not_local(url):
    assert is_local_address(url) is False


def test_settings_strip_a_trailing_slash_and_link_builds_from_them(monkeypatch):
    monkeypatch.setenv("UNSUBSCRIBE_SECRET", SECRET)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://outreach.example.com/")
    secret, base = unsubscribe_settings()
    assert base == "https://outreach.example.com"
    link = unsubscribe_url(secret, base, 7)
    assert link.startswith("https://outreach.example.com/unsubscribe?r=7&t=")
    assert len(link.split("&t=")[1]) == 64


def test_missing_settings_are_reported_as_none(monkeypatch):
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    monkeypatch.setenv("UNSUBSCRIBE_SECRET", SECRET)
    assert unsubscribe_settings() is None


def _review_campaign(monkeypatch):
    monkeypatch.setattr(campaigns.store, "get_campaign", lambda campaign_id: {"id": 1, "status": "review"})


class _FakeLiveSender:
    name = "smtp"

    def check(self):
        return None


class _Sentinel(Exception):
    """Raised by a stub after the unsubscribe gate has passed, so the test can see the gate let sending continue."""


def _stop_after_gate(campaign_id):
    raise _Sentinel()


class _FakeMockSender:
    name = "mock"


def test_live_sending_refuses_a_localhost_public_url(monkeypatch):
    _review_campaign(monkeypatch)
    monkeypatch.setattr(campaigns, "get_sender", lambda: _FakeLiveSender())
    monkeypatch.setenv("SENDER_ADDRESS", "Test Business, 1 Example Road, Lahore")
    monkeypatch.setenv("UNSUBSCRIBE_SECRET", SECRET)
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    with pytest.raises(ValueError, match="localhost"):
        campaigns.start_sending(1)


def test_live_sending_proceeds_past_the_gate_with_a_public_url(monkeypatch):
    _review_campaign(monkeypatch)
    monkeypatch.setattr(campaigns, "get_sender", lambda: _FakeLiveSender())
    monkeypatch.setattr(campaigns.store, "list_recipients", _stop_after_gate)
    monkeypatch.setenv("SENDER_ADDRESS", "Test Business, 1 Example Road, Lahore")
    monkeypatch.setenv("UNSUBSCRIBE_SECRET", SECRET)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://outreach.example.com")
    with pytest.raises(_Sentinel):
        campaigns.start_sending(1)


def test_mock_sending_may_use_a_local_address(monkeypatch):
    _review_campaign(monkeypatch)
    monkeypatch.setattr(campaigns, "get_sender", lambda: _FakeMockSender())
    monkeypatch.setattr(campaigns.store, "list_recipients", _stop_after_gate)
    monkeypatch.setenv("UNSUBSCRIBE_SECRET", SECRET)
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://127.0.0.1:8000")
    with pytest.raises(_Sentinel):
        campaigns.start_sending(1)


def test_the_example_environment_file_holds_no_real_keys():
    example = Path(__file__).resolve().parents[2] / ".env.example"
    values = {}
    for line in example.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.strip()] = value.strip()
    assert values["ANTHROPIC_API_KEY"] == ""
    assert values["GOOGLE_PLACES_API_KEY"] == ""
    assert values["UNSUBSCRIBE_SECRET"] == ""
    assert values["PUBLIC_BASE_URL"] == ""
    assert values["DEMO_MODE"] == "true"
    assert values["MOCK_EMAIL_MODE"] == "true"
