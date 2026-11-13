"""Sessions, CSRF, rate limits, security headers, logging and readiness."""
import json
import logging

import pytest
from fastapi.testclient import TestClient

import main
from config import production_problems
from tests.account_helpers import ADMIN_EMAIL, TEST_PASSWORD, TEST_SESSION_SECRET, make_account
from services import rate_limit
from services.auth import COOKIE_NAME, issue_session, valid_session
from logging_setup import JsonFormatter


@pytest.fixture
def client(test_db, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    rate_limit.limiter.reset()
    make_account(ADMIN_EMAIL, "admin")
    return TestClient(main.app)


def _sign_in(client, email=ADMIN_EMAIL, password=TEST_PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password},
                       headers={"X-Requested-With": "test"})


# ── Sessions ──────────────────────────────────────────────────────────────────

def test_protected_routes_need_a_session(client):
    assert client.get("/restaurants").status_code == 401
    assert client.get("/health").status_code == 200
    assert client.get("/health/ready").status_code == 200
    assert client.get("/auth/session").json()["authenticated"] is False


def test_wrong_password_is_refused_with_a_generic_message(client):
    resp = _sign_in(client, password="wrong-password-value")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Incorrect email or password."
    assert "ro_session" not in resp.cookies


def test_unknown_email_gets_the_same_refusal(client):
    resp = _sign_in(client, email="nobody@example.test")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Incorrect email or password."


def test_correct_credentials_set_an_http_only_session_cookie(client):
    resp = _sign_in(client)
    assert resp.status_code == 200
    assert resp.json()["user"]["email"] == ADMIN_EMAIL
    assert "password_hash" not in resp.json()["user"]
    cookie_header = resp.headers["set-cookie"]
    assert "ro_session=" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "SameSite=lax" in cookie_header
    assert client.get("/restaurants").status_code == 200
    assert client.get("/auth/session").json()["user"]["role"] == "admin"


def test_logout_ends_the_session(client):
    _sign_in(client)
    client.post("/auth/logout", headers={"X-Requested-With": "test"})
    client.cookies.clear()
    assert client.get("/restaurants").status_code == 401


def test_forged_and_expired_sessions_are_rejected(test_db, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    account = make_account("session.check@example.test", "viewer")
    token, _ = issue_session(account["id"])
    assert valid_session(token)
    assert not valid_session(token.replace(token[-1], "0" if token[-1] != "0" else "1"))
    assert not valid_session("9999999999.deadbeef")
    assert not valid_session("not-a-session")
    assert not valid_session(None)
    assert not valid_session("1.00")


def test_a_copied_cookie_stops_working_after_logout(client):
    _sign_in(client)
    token = client.cookies.get(COOKIE_NAME)
    assert token
    assert client.get("/restaurants").status_code == 200
    client.post("/auth/logout", headers={"X-Requested-With": "test"})
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, token)
    assert client.get("/restaurants").status_code == 401


# ── CSRF ──────────────────────────────────────────────────────────────────────

def test_state_changing_requests_need_the_csrf_header(client):
    _sign_in(client)
    assert client.post("/restaurants/discover", json={"city": "Lahore", "limit": 1}).status_code == 403
    ok = client.post("/restaurants/discover", json={"city": "Lahore", "limit": 1},
                     headers={"X-Requested-With": "app"})
    assert ok.status_code == 200


def test_unsubscribe_post_from_mail_clients_is_not_blocked_by_csrf(client):
    resp = client.post("/unsubscribe?r=1&t=forged")
    assert resp.status_code == 400


def test_login_itself_needs_the_csrf_header(client):
    resp = client.post("/auth/login", json={"email": ADMIN_EMAIL, "password": TEST_PASSWORD})
    assert resp.status_code == 403


# ── Rate limits ───────────────────────────────────────────────────────────────

def test_login_is_rate_limited_when_enabled(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    rate_limit.limiter.reset()
    statuses = [_sign_in(client, password="wrong-password-value").status_code for _ in range(11)]
    assert statuses[:10] == [401] * 10
    assert statuses[10] == 429


def test_rate_limits_are_off_in_development(client):
    rate_limit.limiter.reset()
    statuses = [_sign_in(client, password="wrong-password-value").status_code for _ in range(12)]
    assert 429 not in statuses


def test_login_throttle_cannot_be_reset_by_changing_forwarded_for(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    monkeypatch.setenv("TRUST_PROXY_HEADERS", "false")
    rate_limit.limiter.reset()
    statuses = [
        client.post("/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong-password-value"},
                    headers={"X-Requested-With": "t", "X-Forwarded-For": f"10.8.8.{i}"}).status_code
        for i in range(11)
    ]
    assert statuses[10] == 429


# ── Headers, request IDs, errors ──────────────────────────────────────────────

def test_security_headers_are_set_on_every_response(client):
    resp = client.get("/health")
    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]
    assert "Strict-Transport-Security" not in resp.headers


def test_request_id_is_echoed_or_replaced(client):
    assert client.get("/health", headers={"X-Request-ID": "trace-abc-123456"}).headers["X-Request-ID"] == "trace-abc-123456"
    replaced = client.get("/health", headers={"X-Request-ID": "bad id\n<script>"}).headers["X-Request-ID"]
    assert "<" not in replaced and len(replaced) >= 8


def test_auth_responses_are_not_cached(client):
    assert client.get("/auth/session").headers["Cache-Control"] == "no-store"


def test_readiness_reports_a_database_failure(client, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("models.database.fetch_one", broken)
    assert client.get("/health/ready").status_code == 503


def test_unexpected_errors_return_a_safe_json_body(client, monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("secret internal detail")

    _sign_in(client)
    monkeypatch.setattr("main.list_restaurants", broken)
    safe_client = TestClient(main.app, raise_server_exceptions=False)
    safe_client.cookies.update(client.cookies)
    resp = safe_client.get("/restaurants")
    assert resp.status_code == 500
    assert resp.json()["detail"] == "Internal server error."
    assert "secret internal detail" not in resp.text
    assert resp.json()["request_id"]


# ── Logging hygiene ───────────────────────────────────────────────────────────

def test_access_logs_never_contain_query_strings_or_tokens(client, caplog):
    caplog.set_level(logging.INFO, logger="app.http")
    client.get("/unsubscribe?r=7&t=super-secret-token-value")
    records = [r for r in caplog.records if r.name == "app.http"]
    assert records
    serialized = json.dumps([{"msg": r.getMessage(), **{k: getattr(r, k, None) for k in ("path", "status")}}
                             for r in records])
    assert "super-secret-token-value" not in serialized
    assert "?" not in records[-1].path


def test_json_log_lines_are_valid_json(caplog):
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    record.request_id = "abc12345"
    parsed = json.loads(JsonFormatter().format(record))
    assert parsed["message"] == "hello world"
    assert parsed["request_id"] == "abc12345"


# ── Production configuration ──────────────────────────────────────────────────

def test_production_configuration_lists_every_missing_secret(monkeypatch):
    for name in ("SESSION_SECRET", "UNSUBSCRIBE_SECRET", "DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173")
    problems = " ".join(production_problems())
    assert "SESSION_SECRET" in problems
    assert "UNSUBSCRIBE_SECRET" in problems
    assert "PostgreSQL" in problems
    assert "localhost" in problems


def test_production_configuration_accepts_a_complete_setup(monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.setenv("UNSUBSCRIBE_SECRET", "unsubscribe-secret-0123")
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pass@db.example/app")
    monkeypatch.setenv("CORS_ORIGINS", "https://ro-frontend.onrender.com")
    monkeypatch.setenv("MOCK_EMAIL_MODE", "true")
    assert production_problems() == []
