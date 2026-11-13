"""Individual accounts, roles, sessions, bootstrap and migration for Phase 21."""
import base64
import hashlib
import os
import secrets
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import text

import main
from models.database import execute, fetch_all, fetch_one, get_engine, init_db
from services import audit, users
from services.auth import COOKIE_NAME, issue_session, valid_session
from services.passwords import hash_password, verify_password
from tests.account_helpers import ADMIN_EMAIL, TEST_PASSWORD, TEST_SESSION_SECRET, login_client, make_account

BACKEND = Path(__file__).resolve().parent.parent
NEW_PASSWORD = "a-new-long-passphrase-42"


@pytest.fixture
def accounts(test_db, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    from services import rate_limit
    rate_limit.limiter.reset()
    admin = make_account(ADMIN_EMAIL, "admin")
    return {"admin": admin}


def _client_as(email, password=TEST_PASSWORD):
    return login_client(main.app, email=email, password=password)


def _role_clients(accounts):
    make_account("operator@example.test", "operator")
    make_account("viewer@example.test", "viewer")
    return {
        "admin": _client_as(ADMIN_EMAIL),
        "operator": _client_as("operator@example.test"),
        "viewer": _client_as("viewer@example.test"),
    }


# ── First-admin setup (public only while no account exists) ───────────────────

def _setup_client():
    client = TestClient(main.app)
    client.headers.update({"X-Requested-With": "t"})
    return client


def test_setup_creates_the_first_admin_and_signs_them_in(test_db, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    client = _setup_client()
    assert client.get("/auth/setup-status").json() == {"needs_setup": True}

    resp = client.post("/auth/setup", json={"name": "First Owner", "email": "Owner@Example.test",
                                            "password": NEW_PASSWORD})
    assert resp.status_code == 201, resp.text
    assert resp.json()["user"]["role"] == "admin"
    assert "ro_session=" in resp.headers["set-cookie"]
    assert client.get("/auth/session").json()["user"]["email"] == "owner@example.test"
    assert client.get("/auth/setup-status").json() == {"needs_setup": False}

    row = fetch_one("SELECT password_hash, status FROM users WHERE email = 'owner@example.test'")
    assert row["password_hash"].startswith("$argon2") and NEW_PASSWORD not in row["password_hash"]
    assert row["status"] == "active"


def test_setup_is_refused_once_any_account_exists(accounts):
    client = _setup_client()
    assert client.get("/auth/setup-status").json() == {"needs_setup": False}
    resp = client.post("/auth/setup", json={"name": "Second Owner", "email": "second@example.test",
                                            "password": NEW_PASSWORD})
    assert resp.status_code == 409
    assert "Accounts already exist" in resp.json()["detail"]
    assert fetch_one("SELECT COUNT(*) AS n FROM users")["n"] == 1


def test_setup_refuses_a_weak_password_and_creates_nothing(test_db):
    client = _setup_client()
    resp = client.post("/auth/setup", json={"name": "Weak Owner", "email": "weak@example.test", "password": "short"})
    assert resp.status_code == 422
    assert fetch_one("SELECT COUNT(*) AS n FROM users")["n"] == 0


def test_setup_needs_the_csrf_header(test_db):
    resp = TestClient(main.app).post("/auth/setup", json={"name": "No Header", "email": "nh@example.test",
                                                          "password": NEW_PASSWORD})
    assert resp.status_code == 403
    assert fetch_one("SELECT COUNT(*) AS n FROM users")["n"] == 0


# ── Login, invalid credentials, tokens ────────────────────────────────────────

def test_each_user_signs_in_with_their_own_credentials(accounts):
    make_account("second@example.test", "operator", password="another-long-password-1")
    admin = _client_as(ADMIN_EMAIL)
    second = _client_as("second@example.test", password="another-long-password-1")
    assert admin.get("/auth/session").json()["user"]["email"] == ADMIN_EMAIL
    assert second.get("/auth/session").json()["user"]["email"] == "second@example.test"
    # One account's password does not open another's.
    resp = admin.post("/auth/login", json={"email": "second@example.test", "password": TEST_PASSWORD})
    assert resp.status_code == 401


def test_invalid_credentials_are_refused_without_saying_which_part_was_wrong(accounts):
    client = TestClient(main.app)
    client.headers.update({"X-Requested-With": "t"})
    wrong_password = client.post("/auth/login", json={"email": ADMIN_EMAIL, "password": "wrong-password-value"})
    unknown_email = client.post("/auth/login", json={"email": "nobody@example.test", "password": "wrong-password-value"})
    malformed = client.post("/auth/login", json={"email": "not-an-email", "password": "wrong-password-value"})
    for resp in (wrong_password, unknown_email, malformed):
        assert resp.status_code == 401
        assert resp.json()["detail"] == "Incorrect email or password."
    assert "ro_session" not in wrong_password.cookies


def test_email_is_case_insensitive_at_sign_in(accounts):
    client = _client_as(ADMIN_EMAIL.upper())
    assert client.get("/auth/session").json()["authenticated"] is True


def test_expired_session_token_is_refused(accounts, monkeypatch):
    from services import auth

    monkeypatch.setattr(auth, "SESSION_SECONDS", -10)
    token, _ = issue_session(accounts["admin"]["id"])
    assert valid_session(token) is False


def test_session_row_past_its_expiry_is_refused(accounts):
    client = _client_as(ADMIN_EMAIL)
    token = client.cookies.get(COOKIE_NAME)
    execute("UPDATE auth_sessions SET expires_at = 1")
    assert valid_session(token) is False
    assert client.get("/restaurants").status_code == 401


def test_tampered_session_token_is_refused(accounts):
    client = _client_as(ADMIN_EMAIL)
    token = client.cookies.get(COOKIE_NAME)
    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
    assert valid_session(tampered) is False


# ── Inactive accounts ─────────────────────────────────────────────────────────

def test_deactivated_account_cannot_sign_in(accounts):
    viewer = make_account("left@example.test", "viewer", password="left-company-passphrase")
    users.update_user({"id": accounts["admin"]["id"]}, viewer["id"], status="inactive")
    client = TestClient(main.app)
    client.headers.update({"X-Requested-With": "t"})
    resp = client.post("/auth/login", json={"email": "left@example.test", "password": "left-company-passphrase"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Incorrect email or password."


def test_deactivation_ends_existing_sessions_immediately(accounts):
    viewer = make_account("leaving@example.test", "viewer", password="leaving-company-passphrase")
    viewer_client = _client_as("leaving@example.test", password="leaving-company-passphrase")
    assert viewer_client.get("/restaurants").status_code == 200
    users.update_user({"id": accounts["admin"]["id"]}, viewer["id"], status="inactive")
    assert viewer_client.get("/restaurants").status_code == 401


def test_reactivated_account_can_sign_in_again(accounts):
    viewer = make_account("back@example.test", "viewer", password="returning-company-passphrase")
    admin = _client_as(ADMIN_EMAIL)
    admin.post("/users/%d/reset-password" % viewer["id"], json={"new_password": "returning-company-passphrase"},
               headers={"X-Requested-With": "t"})
    users.update_user({"id": accounts["admin"]["id"]}, viewer["id"], status="inactive")
    users.update_user({"id": accounts["admin"]["id"]}, viewer["id"], status="active")
    assert _client_as("back@example.test", password="returning-company-passphrase").get("/restaurants").status_code == 200


# ── Role permissions ──────────────────────────────────────────────────────────

def test_viewer_can_read_but_not_change_anything(accounts):
    clients = _role_clients(accounts)
    viewer = clients["viewer"]
    assert viewer.get("/restaurants").status_code == 200
    assert viewer.get("/outreach/drafts").status_code == 200
    assert viewer.get("/campaigns").status_code == 200
    assert viewer.post("/restaurants/discover", json={"city": "Lahore", "limit": 1}).status_code == 403
    assert viewer.post("/campaigns", json={"name": "Nope", "restaurant_ids": [1]}).status_code == 403
    assert viewer.post("/suppression", json={"email": "a@example.test", "reason": "x"}).status_code == 403
    assert viewer.post("/email/sync").status_code == 403
    assert viewer.put("/outreach/drafts/1", json={"subject": "s", "body": "b"}).status_code == 403
    assert viewer.post("/outreach/drafts/1/approve").status_code == 403


def test_viewer_cannot_see_user_management_or_the_audit_log(accounts):
    viewer = _role_clients(accounts)["viewer"]
    assert viewer.get("/users").status_code == 403
    assert viewer.get("/audit-log").status_code == 403
    assert viewer.post("/users", json={"name": "New Person", "email": "new@example.test",
                                       "password": NEW_PASSWORD, "role": "viewer"}).status_code == 403


def test_operator_can_work_but_cannot_manage_users(accounts):
    operator = _role_clients(accounts)["operator"]
    assert operator.post("/restaurants/discover", json={"city": "Lahore", "limit": 2}).status_code == 200
    assert operator.get("/users").status_code == 403
    assert operator.post("/users", json={"name": "New Person", "email": "new@example.test",
                                         "password": NEW_PASSWORD, "role": "viewer"}).status_code == 403
    assert operator.get("/audit-log").status_code == 403


def test_admin_can_manage_users_and_read_the_audit_log(accounts):
    admin = _role_clients(accounts)["admin"]
    assert admin.get("/users").status_code == 200
    created = admin.post("/users", json={"name": "Sara Khan", "email": "sara@example.test",
                                         "password": NEW_PASSWORD, "role": "operator"})
    assert created.status_code == 201
    assert "password_hash" not in created.json()
    assert admin.get("/audit-log").status_code == 200


def test_every_protected_route_declares_a_permission():
    """Guard: a route added without require(...) fails this test, so no endpoint can be left open."""
    public = {("GET", "/health"), ("GET", "/health/ready"), ("POST", "/auth/login"), ("POST", "/auth/logout"),
              ("GET", "/auth/session"), ("GET", "/auth/setup-status"), ("POST", "/auth/setup"),
              ("POST", "/auth/register"), ("POST", "/invitations/preview"), ("POST", "/invitations/accept"),
              ("GET", "/unsubscribe"), ("POST", "/unsubscribe"), ("POST", "/webhooks/email-events")}
    missing = []
    for route in main.app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            if (method, route.path) in public:
                continue
            if not _has_permission(route.dependant):
                missing.append(f"{method} {route.path}")
    assert missing == []


def _has_permission(dependant) -> bool:
    for dep in dependant.dependencies:
        if getattr(dep.call, "__name__", "").startswith("require_"):
            return True
        if _has_permission(dep):
            return True
    return False


# ── Unauthorized API access ───────────────────────────────────────────────────

def test_requests_without_a_session_are_refused_everywhere(accounts):
    client = TestClient(main.app)
    client.headers.update({"X-Requested-With": "t"})
    for method, path in [("GET", "/restaurants"), ("GET", "/users"), ("GET", "/audit-log"),
                         ("GET", "/campaigns"), ("POST", "/campaigns"), ("POST", "/auth/password")]:
        resp = client.request(method, path, json={} if method != "GET" else None)
        assert resp.status_code == 401, (method, path)


def test_a_forged_cookie_is_refused(accounts):
    client = TestClient(main.app)
    client.cookies.set(COOKIE_NAME, "1.2.3")
    assert client.get("/users").status_code == 401


def test_state_changing_requests_need_the_csrf_header_even_when_signed_in(accounts):
    admin = _client_as(ADMIN_EMAIL)
    resp = admin.post("/users", json={"name": "No Header", "email": "nh@example.test",
                                      "password": NEW_PASSWORD, "role": "viewer"},
                      headers={"X-Requested-With": ""})
    assert resp.status_code == 403


# ── Admin account rules ───────────────────────────────────────────────────────

def test_email_addresses_are_unique_whatever_their_case(accounts):
    admin = _client_as(ADMIN_EMAIL)
    resp = admin.post("/users", json={"name": "Copy Cat", "email": ADMIN_EMAIL.upper(),
                                      "password": NEW_PASSWORD, "role": "viewer"})
    assert resp.status_code == 422
    assert "already exists" in resp.json()["detail"]


def test_weak_passwords_are_refused(accounts):
    admin = _client_as(ADMIN_EMAIL)
    resp = admin.post("/users", json={"name": "Weak Pass", "email": "weak@example.test",
                                      "password": "short", "role": "viewer"})
    assert resp.status_code == 422
    assert "at least 12 characters" in resp.json()["detail"]


def test_an_admin_can_demote_another_admin_but_not_themselves(accounts):
    admin = _client_as(ADMIN_EMAIL)
    other = make_account("second.admin@example.test", "admin", password="second-admin-passphrase")
    # Two active admins exist, so one may step down.
    assert admin.put(f"/users/{other['id']}", json={"role": "viewer"}).status_code == 200
    # Removing your own admin role is refused, so the workspace cannot lock itself out.
    assert admin.put(f"/users/{accounts['admin']['id']}", json={"role": "viewer"}).status_code == 422
    assert admin.get("/auth/session").json()["user"]["role"] == "admin"


def test_the_last_active_admin_is_never_removed(accounts):
    """Direct check of the guard in services/users.py, independent of the API's self-protection rule."""
    solo = make_account("solo.admin@example.test", "admin", password="solo-admin-passphrase")
    # Demote the original admin directly, so the solo admin is the only active admin left.
    execute("UPDATE users SET role = 'viewer' WHERE id = :id", {"id": accounts["admin"]["id"]})
    # The actor is someone else, so the self-protection rule does not apply and only the guard is tested.
    with pytest.raises(ValueError, match="At least one active admin"):
        users.update_user({"id": 0}, solo["id"], role="viewer")
    assert users.get_user(solo["id"])["role"] == "admin"


def test_an_admin_cannot_deactivate_themselves(accounts):
    make_account("backup.admin@example.test", "admin", password="backup-admin-passphrase")
    admin = _client_as(ADMIN_EMAIL)
    resp = admin.put(f"/users/{accounts['admin']['id']}", json={"status": "inactive"})
    assert resp.status_code == 422


def test_resetting_a_password_ends_that_users_sessions(accounts):
    viewer = make_account("reset@example.test", "viewer", password="original-passphrase-1")
    viewer_client = _client_as("reset@example.test", password="original-passphrase-1")
    admin = _client_as(ADMIN_EMAIL)
    assert admin.post(f"/users/{viewer['id']}/reset-password", json={"new_password": NEW_PASSWORD}).status_code == 200
    assert viewer_client.get("/restaurants").status_code == 401
    assert _client_as("reset@example.test", password=NEW_PASSWORD).get("/restaurants").status_code == 200


def test_changing_your_own_password(accounts):
    make_account("changer@example.test", "operator", password="current-passphrase-1")
    first = _client_as("changer@example.test", password="current-passphrase-1")
    second = _client_as("changer@example.test", password="current-passphrase-1")

    wrong = first.post("/auth/password", json={"current_password": "not-the-password", "new_password": NEW_PASSWORD})
    assert wrong.status_code == 400

    done = first.post("/auth/password", json={"current_password": "current-passphrase-1", "new_password": NEW_PASSWORD})
    assert done.status_code == 200
    assert first.get("/restaurants").status_code == 200       # the current session is kept
    assert second.get("/restaurants").status_code == 401       # other sessions end
    refused = TestClient(main.app)
    refused.headers.update({"X-Requested-With": "t"})
    assert refused.post("/auth/login", json={"email": "changer@example.test",
                                             "password": "current-passphrase-1"}).status_code == 401


# ── Password storage ──────────────────────────────────────────────────────────

def test_passwords_are_stored_as_argon2_hashes_never_in_plain_text(accounts):
    row = fetch_one("SELECT password_hash FROM users WHERE email = :email", {"email": ADMIN_EMAIL})
    assert row["password_hash"].startswith("$argon2")
    assert TEST_PASSWORD not in row["password_hash"]
    assert verify_password(TEST_PASSWORD, row["password_hash"])
    assert not verify_password(TEST_PASSWORD + " ", row["password_hash"])


def test_two_hashes_of_the_same_password_differ():
    assert hash_password(TEST_PASSWORD) != hash_password(TEST_PASSWORD)


def _legacy_scrypt(password: str) -> str:
    """The format the shared-admin code wrote (scrypt$N$r$p$salt$digest)."""
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)
    b64 = lambda data: base64.b64encode(data).decode("ascii")
    return f"scrypt$16384$8$1${b64(salt)}${b64(digest)}"


def test_a_legacy_scrypt_hash_still_signs_in_and_is_upgraded_to_argon2(accounts):
    legacy = _legacy_scrypt(NEW_PASSWORD)
    make_account("legacy@example.test", "admin", password=NEW_PASSWORD)
    execute("UPDATE users SET password_hash = :hash WHERE email = 'legacy@example.test'", {"hash": legacy})
    assert _client_as("legacy@example.test", password=NEW_PASSWORD).get("/auth/session").json()["authenticated"]
    upgraded = fetch_one("SELECT password_hash FROM users WHERE email = 'legacy@example.test'")
    assert upgraded["password_hash"].startswith("$argon2")


def test_a_malformed_hash_never_grants_access(accounts):
    assert verify_password(TEST_PASSWORD, "scrypt$not-a-number$8$1$AAAA$BBBB") is False
    assert verify_password(TEST_PASSWORD, "") is False
    assert verify_password(TEST_PASSWORD, "plaintext-password") is False


# ── Activity attribution ──────────────────────────────────────────────────────

def test_campaign_actions_are_recorded_against_the_signed_in_user(accounts, monkeypatch):
    # Keep draft writing offline: the campaign only needs its recipients recorded.
    from services import campaigns as campaign_service
    monkeypatch.setattr(campaign_service, "_start_drafting", lambda campaign_id: None, raising=False)
    operator = make_account("ops@example.test", "operator", password="ops-passphrase-2026")
    execute("INSERT INTO restaurants (place_id, name, source, website, contact_email, contact_email_status, "
            "contact_email_classification, lead_status, lead_score) VALUES ('attrib-1', 'Attribution Cafe', "
            "'google_places', 'https://attrib.pk', 'hello@attrib.pk', 'domain_valid', 'business', 'qualified', 80)")
    restaurant = fetch_one("SELECT id FROM restaurants WHERE place_id = 'attrib-1'")

    client = _client_as("ops@example.test", password="ops-passphrase-2026")
    created = client.post("/campaigns", json={"name": "Attribution check", "restaurant_ids": [restaurant["id"]]})
    assert created.status_code == 201, created.text

    campaign = fetch_one("SELECT created_by_user_id FROM campaigns WHERE name = 'Attribution check'")
    assert campaign["created_by_user_id"] == operator["id"]
    entry = fetch_one("SELECT actor_user_id FROM audit_log WHERE action = 'campaign.created' ORDER BY id DESC LIMIT 1")
    assert entry["actor_user_id"] == operator["id"]


def test_audit_entries_name_the_actor_and_never_hold_secrets(accounts):
    admin = _client_as(ADMIN_EMAIL)
    admin.post("/users", json={"name": "Audit Person", "email": "audit@example.test",
                               "password": NEW_PASSWORD, "role": "viewer"})
    entries = admin.get("/audit-log").json()
    created = [e for e in entries if e["action"] == "user.created"]
    assert created and created[0]["actor_email"] == ADMIN_EMAIL
    blob = repr(entries)
    assert NEW_PASSWORD not in blob and TEST_PASSWORD not in blob
    assert "password_hash" not in blob


def test_rows_from_before_accounts_keep_no_actor(accounts):
    execute("INSERT INTO campaigns (name, status) VALUES ('Written by the old shared admin', 'review')")
    row = fetch_one("SELECT created_by_user_id FROM campaigns WHERE name = 'Written by the old shared admin'")
    assert row["created_by_user_id"] is None


# ── Bootstrap ─────────────────────────────────────────────────────────────────

def _run_bootstrap(monkeypatch, argv, inputs, passwords=None):
    sys.path.insert(0, str(BACKEND / "scripts"))
    import importlib
    import create_admin

    importlib.reload(create_admin)
    answers = iter(inputs)
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    passwords = iter(passwords or [])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(passwords))
    monkeypatch.setattr(sys, "argv", ["create_admin.py", *argv])
    try:
        create_admin.main()
        return 0, None
    except SystemExit as exc:
        return exc.code, exc
    finally:
        sys.path.remove(str(BACKEND / "scripts"))


def test_bootstrap_creates_the_first_admin_from_a_hidden_prompt(test_db, monkeypatch):
    code, _ = _run_bootstrap(monkeypatch, [], ["Owner Person", "owner@example.test"],
                             [NEW_PASSWORD, NEW_PASSWORD])
    assert code == 0
    row = fetch_one("SELECT role, status, password_hash FROM users WHERE email = 'owner@example.test'")
    assert row["role"] == "admin" and row["status"] == "active"
    assert row["password_hash"].startswith("$argon2")


def test_bootstrap_refuses_when_an_active_admin_already_exists(accounts, monkeypatch):
    code, exc = _run_bootstrap(monkeypatch, [], [], [])
    assert code and "already exists" in str(code)


def test_bootstrap_refuses_mismatched_passwords(test_db, monkeypatch):
    code, _ = _run_bootstrap(monkeypatch, [], ["Owner Person", "owner2@example.test"],
                             [NEW_PASSWORD, "something-else-entirely"])
    assert code and "do not match" in str(code)
    assert fetch_one("SELECT id FROM users WHERE email = 'owner2@example.test'") is None


def test_bootstrap_can_reuse_the_previous_shared_admin_hash(test_db, monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", _legacy_scrypt(NEW_PASSWORD))
    code, _ = _run_bootstrap(monkeypatch, ["--from-legacy-hash"], ["Old Admin", "old.admin@example.test"], [])
    assert code == 0
    row = fetch_one("SELECT password_hash FROM users WHERE email = 'old.admin@example.test'")
    assert row["password_hash"].startswith("scrypt$")
    client = _client_as("old.admin@example.test", password=NEW_PASSWORD)
    assert client.get("/auth/session").json()["authenticated"] is True


# ── Migration 0008: data is kept, and the rollback works ──────────────────────

def _alembic(url: str, action: str, target: str, monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    getattr(command, action)(config, target)


def test_upgrade_keeps_existing_data_and_downgrade_restores_the_previous_schema(tmp_path, monkeypatch):
    url = str(tmp_path / "migrate.db")
    _alembic(url, "upgrade", "0007_relational_integrity", monkeypatch)
    monkeypatch.setenv("DATABASE_URL", url)
    execute("INSERT INTO restaurants (place_id, name, source) VALUES ('keep-1', 'Kept Cafe', 'google_places')")
    restaurant = fetch_one("SELECT id FROM restaurants WHERE place_id = 'keep-1'")
    execute("INSERT INTO campaigns (name, status) VALUES ('Before accounts', 'review')")
    execute("INSERT INTO auth_sessions (id, expires_at) VALUES ('legacy-session', 9999999999)")
    before = {
        "restaurants": fetch_one("SELECT COUNT(*) AS n FROM restaurants")["n"],
        "campaigns": fetch_one("SELECT COUNT(*) AS n FROM campaigns")["n"],
    }

    _alembic(url, "upgrade", "head", monkeypatch)
    assert fetch_one("SELECT name FROM restaurants WHERE id = :id", {"id": restaurant["id"]})["name"] == "Kept Cafe"
    assert fetch_one("SELECT COUNT(*) AS n FROM restaurants")["n"] == before["restaurants"]
    assert fetch_one("SELECT COUNT(*) AS n FROM campaigns")["n"] == before["campaigns"]
    campaign = fetch_one("SELECT created_by_user_id FROM campaigns WHERE name = 'Before accounts'")
    assert campaign["created_by_user_id"] is None
    legacy_session = fetch_one("SELECT user_id FROM auth_sessions WHERE id = 'legacy-session'")
    assert legacy_session["user_id"] is None  # old shared-admin sessions are no longer valid
    assert fetch_one("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'users'") is not None

    _alembic(url, "downgrade", "0007_relational_integrity", monkeypatch)
    assert fetch_one("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'users'") is None
    assert fetch_one("SELECT COUNT(*) AS n FROM restaurants")["n"] == before["restaurants"]
    assert fetch_one("SELECT COUNT(*) AS n FROM campaigns")["n"] == before["campaigns"]

    _alembic(url, "upgrade", "head", monkeypatch)
    assert fetch_one("SELECT COUNT(*) AS n FROM users")["n"] == 0
