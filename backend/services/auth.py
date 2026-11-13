"""Sessions for individual user accounts.

A session token is "<session id>.<expires>.<signature>". The signature is an HMAC over the id and the
expiry, keyed with SESSION_SECRET. A token is valid only when the signature checks out, it has not
expired, its row exists in auth_sessions, and the account it belongs to is still active. Logout, password
change and deactivation delete the rows, so a copied token stops working at once.

The token travels in an HttpOnly cookie. It is never placed in localStorage or in the page.
"""
import hashlib
import hmac
import logging
import secrets
import time

from config import session_secret
from models.database import execute, fetch_one

logger = logging.getLogger("app.auth")

COOKIE_NAME = "ro_session"
SESSION_SECONDS = 12 * 60 * 60


def _sign(session_id: str, expires: int) -> str:
    message = f"session:{session_id}:{expires}".encode()
    return hmac.new(session_secret().encode(), message, hashlib.sha256).hexdigest()


def _purge_expired() -> None:
    execute("DELETE FROM auth_sessions WHERE expires_at < :now", {"now": int(time.time())})


def issue_session(user_id: int, workspace_id: int | None = None) -> tuple[str, int]:
    session_id = secrets.token_urlsafe(24)
    expires = int(time.time()) + SESSION_SECONDS
    _purge_expired()
    execute(
        "INSERT INTO auth_sessions (id, user_id, expires_at, workspace_id) "
        "VALUES (:id, :user_id, :expires, :workspace_id)",
        {"id": session_id, "user_id": user_id, "expires": expires, "workspace_id": workspace_id},
    )
    return f"{session_id}.{expires}.{_sign(session_id, expires)}", SESSION_SECONDS


def set_session_workspace(token: str | None, workspace_id: int | None) -> None:
    session_id = session_id_of(token)
    if session_id:
        execute("UPDATE auth_sessions SET workspace_id = :ws WHERE id = :id", {"ws": workspace_id, "id": session_id})


def _parse(token: str | None) -> tuple[str, int, str] | None:
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    session_id, expires_text, signature = parts
    try:
        expires = int(expires_text)
    except ValueError:
        return None
    return session_id, expires, signature


def session_id_of(token: str | None) -> str | None:
    parsed = _parse(token)
    return parsed[0] if parsed else None


def current_user(token: str | None) -> dict | None:
    """The active account behind a valid session, or None. Never raises for a bad or missing token."""
    parsed = _parse(token)
    if parsed is None:
        return None
    session_id, expires, signature = parsed
    if expires < time.time():
        return None
    if not hmac.compare_digest(_sign(session_id, expires), signature):
        return None
    try:
        row = fetch_one(
            "SELECT s.expires_at, s.workspace_id, u.id, u.name, u.email, u.role, u.status "
            "FROM auth_sessions s JOIN users u ON u.id = s.user_id WHERE s.id = :id",
            {"id": session_id},
        )
    except Exception:
        logger.exception("Session lookup failed; denying access")
        return None
    if row is None or int(row["expires_at"]) != expires or row["status"] != "active":
        return None
    return {"id": int(row["id"]), "name": row["name"], "email": row["email"], "role": row["role"],
            "status": row["status"], "session_id": session_id,
            "session_workspace_id": int(row["workspace_id"]) if row["workspace_id"] is not None else None}


def remove_member_sessions(user_id: int, workspace_id: int) -> int:
    """End a person's sessions that were working in one workspace, after they are removed from it."""
    return execute("DELETE FROM auth_sessions WHERE user_id = :user_id AND workspace_id = :ws",
                   {"user_id": user_id, "ws": workspace_id})


def valid_session(token: str | None) -> bool:
    return current_user(token) is not None


def revoke_session(token: str | None) -> None:
    session_id = session_id_of(token)
    if session_id:
        execute("DELETE FROM auth_sessions WHERE id = :id", {"id": session_id})


def revoke_user_sessions(user_id: int, keep_session_id: str | None = None) -> int:
    """End every session of one account, optionally keeping the one the caller is using."""
    if keep_session_id:
        return execute("DELETE FROM auth_sessions WHERE user_id = :user_id AND id <> :keep",
                       {"user_id": user_id, "keep": keep_session_id})
    return execute("DELETE FROM auth_sessions WHERE user_id = :user_id", {"user_id": user_id})
