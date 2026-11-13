import hashlib
import hmac
import os
from urllib.parse import urlparse

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def unsubscribe_settings() -> tuple[str, str] | None:
    secret = os.getenv("UNSUBSCRIBE_SECRET", "").strip()
    base_url = os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/")
    if not secret or not base_url:
        return None
    return secret, base_url


def is_local_address(base_url: str) -> bool:
    """True when a base URL points at this machine. A recipient on another device cannot open such a link."""
    host = (urlparse(base_url).hostname or "").lower()
    return host in LOCAL_HOSTS or host.endswith(".localhost")


def make_token(secret: str, recipient_id: int) -> str:
    message = f"unsubscribe:recipient:{recipient_id}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_token(secret: str, recipient_id: int, token: str | None) -> bool:
    return hmac.compare_digest(make_token(secret, recipient_id), token or "")


def unsubscribe_url(secret: str, base_url: str, recipient_id: int) -> str:
    return f"{base_url}/unsubscribe?r={recipient_id}&t={make_token(secret, recipient_id)}"
