"""Reply monitoring status: a yes or no, without any mailbox setting in the response."""
import main
from services.mailbox_monitor import mailbox_configured
from tests.account_helpers import TEST_SESSION_SECRET, signed_in_client


def _clear(monkeypatch):
    for name in ("MAILBOX_IMAP_HOST", "MAILBOX_USERNAME", "MAILBOX_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


def test_not_configured_when_the_settings_are_missing(monkeypatch):
    _clear(monkeypatch)
    assert mailbox_configured() is False


def test_configured_when_all_three_settings_are_present(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("MAILBOX_IMAP_HOST", "imap.example.test")
    monkeypatch.setenv("MAILBOX_USERNAME", "replies@example.test")
    monkeypatch.setenv("MAILBOX_PASSWORD", "not-a-real-password")
    assert mailbox_configured() is True


def test_the_status_endpoint_returns_only_a_flag(test_db, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    _clear(monkeypatch)
    monkeypatch.setenv("MAILBOX_IMAP_HOST", "imap.example.test")
    monkeypatch.setenv("MAILBOX_USERNAME", "replies@example.test")
    monkeypatch.setenv("MAILBOX_PASSWORD", "not-a-real-password")
    body = signed_in_client(main.app).get("/email/mailbox-status").json()
    assert body == {"configured": True}
    assert "password" not in str(body).lower() and "example.test" not in str(body)
