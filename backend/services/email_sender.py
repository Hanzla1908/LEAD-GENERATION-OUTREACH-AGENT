import os
import smtplib
import uuid
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import httpx


class SendError(Exception):
    """The provider refused or failed before accepting the message, so it is safe to retry."""


class SendOutcomeUnknown(Exception):
    """The connection failed after delivery may have started. The message must not be resent automatically."""


class MockSender:
    """Development sender. Records messages in memory and never contacts a mail server."""

    name = "mock"

    def __init__(self, fail_addresses: tuple[str, ...] = ()):
        self.fail_addresses = {a.lower() for a in fail_addresses}
        self.outbox: list[dict] = []

    def send(self, to: str, subject: str, body: str, idempotency_key: str,
             unsubscribe_url: str | None = None) -> str:
        if to.lower() in self.fail_addresses:
            raise SendError("Mock provider rejected this address")
        message_id = f"mock-{uuid.uuid4().hex[:12]}"
        self.outbox.append({"to": [to], "subject": subject, "body": body,
                            "idempotency_key": idempotency_key, "message_id": message_id,
                            "unsubscribe_url": unsubscribe_url})
        return message_id


class SmtpSender:
    name = "smtp"

    def __init__(self, host: str, port: int, username: str, password: str, from_email: str, from_name: str):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_email = from_email
        self.from_name = from_name

    def send(self, to: str, subject: str, body: str, idempotency_key: str,
             unsubscribe_url: str | None = None) -> str:
        message = EmailMessage()
        message["From"] = formataddr((self.from_name, self.from_email))
        message["To"] = to
        message["Subject"] = subject
        message_id = make_msgid(domain=self.from_email.split("@")[-1])
        message["Message-ID"] = message_id
        if unsubscribe_url:
            message["List-Unsubscribe"] = f"<{unsubscribe_url}>"
            message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
        message.set_content(body)
        try:
            server = smtplib.SMTP(self.host, self.port, timeout=20)
        except OSError as exc:
            raise SendError(f"Could not connect to the SMTP server: {exc}") from exc
        try:
            try:
                server.starttls()
                if self.username:
                    server.login(self.username, self.password)
            except (smtplib.SMTPException, OSError) as exc:
                raise SendError(f"SMTP login failed: {exc}") from exc
            try:
                server.send_message(message)
            except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused) as exc:
                raise SendError(f"SMTP server refused the message: {exc}") from exc
            except (smtplib.SMTPException, OSError) as exc:
                raise SendOutcomeUnknown(f"Connection lost while sending: {exc}") from exc
        finally:
            try:
                server.quit()
            except Exception:
                pass
        return message_id


class NodemailerSender:
    """Sends through the internal Node.js email service. The shared secret stays on the server."""

    name = "nodemailer"

    def __init__(self, base_url: str, secret: str, transport: httpx.BaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.secret = secret
        self.transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=30.0, transport=self.transport)

    def check(self) -> None:
        try:
            with self._client() as client:
                response = client.get(f"{self.base_url}/health", headers={"X-Service-Secret": self.secret})
        except httpx.HTTPError as exc:
            raise SendError(f"Email service is not reachable at {self.base_url}. Start it before sending.") from exc
        if response.status_code != 200:
            raise SendError(f"Email service health check failed ({_error_text(response)}). Check EMAIL_SERVICE_SECRET.")

    def send(self, to: str, subject: str, body: str, idempotency_key: str,
             unsubscribe_url: str | None = None) -> str:
        payload = {"idempotency_key": idempotency_key, "to": to, "subject": subject, "text": body}
        if unsubscribe_url:
            payload["unsubscribe_url"] = unsubscribe_url
        try:
            with self._client() as client:
                response = client.post(
                    f"{self.base_url}/send", json=payload, headers={"X-Service-Secret": self.secret},
                )
        except httpx.ConnectError as exc:
            raise SendError("Email service is not reachable; nothing was sent.") from exc
        except httpx.HTTPError as exc:
            raise SendOutcomeUnknown("Email service did not answer; the delivery outcome is unknown.") from exc
        if response.status_code == 200:
            return response.json()["message_id"]
        if response.status_code in (400, 401, 422):
            raise SendError(_error_text(response))
        raise SendOutcomeUnknown(_error_text(response))


def _error_text(response: httpx.Response) -> str:
    try:
        return str(response.json().get("error") or f"HTTP {response.status_code}")
    except ValueError:
        return f"HTTP {response.status_code}"


_mock = MockSender()


def provider_name() -> str:
    return os.getenv("EMAIL_PROVIDER", "mock").strip().lower()


def get_sender():
    from config import mock_email_mode

    provider = provider_name()
    if mock_email_mode() or provider == "mock":
        return _mock
    if provider == "nodemailer":
        url = os.getenv("EMAIL_SERVICE_URL", "").strip()
        secret = os.getenv("EMAIL_SERVICE_SECRET", "").strip()
        if not url or len(secret) < 16:
            raise SendError(
                "Nodemailer is selected but EMAIL_SERVICE_URL or EMAIL_SERVICE_SECRET (16+ characters) is not set."
            )
        if "://" not in url:
            url = "http://" + url
        return NodemailerSender(url, secret)
    if provider == "smtp":
        host = os.getenv("SMTP_HOST", "").strip()
        from_email = os.getenv("EMAIL_FROM", "").strip()
        if not host or not from_email:
            raise SendError("SMTP is selected but SMTP_HOST or EMAIL_FROM is not set.")
        return SmtpSender(
            host=host,
            port=int(os.getenv("SMTP_PORT", "587")),
            username=os.getenv("SMTP_USERNAME", ""),
            password=os.getenv("SMTP_PASSWORD", ""),
            from_email=from_email,
            from_name=os.getenv("EMAIL_FROM_NAME", "Outreach Team"),
        )
    raise SendError(f"Unknown EMAIL_PROVIDER '{provider}'. Use 'mock' or 'smtp'.")
