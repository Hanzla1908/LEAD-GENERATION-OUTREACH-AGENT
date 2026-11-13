"""Public sign-up: POST /auth/register.

A new person gets an account and a workspace of their own, as its admin. The account is not signed in, existing
workspaces and roles do not change, and the password is stored only as an Argon2 hash.
"""
import pytest
from fastapi.testclient import TestClient

import main
from models.database import fetch_all, fetch_one
from tests.account_helpers import TEST_SESSION_SECRET, login_client, make_account

ADMIN_EMAIL = "existing.admin@example.test"
ADMIN_PASSWORD = "existing-admin-passphrase-1"
GOOD = {"name": "Nadia Khan", "email": "nadia@example.test", "password": "Abc12345"}


@pytest.fixture
def client(test_db, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    make_account(ADMIN_EMAIL, "admin", password=ADMIN_PASSWORD, name="Existing Admin")
    c = TestClient(main.app)
    c.headers.update({"X-Requested-With": "test"})
    return c


def _register(client, **overrides):
    body = {**GOOD, **overrides}
    return client.post("/auth/register", json=body)


def test_a_valid_sign_up_creates_the_account_and_returns_the_success_message(client):
    resp = _register(client)
    assert resp.status_code == 201, resp.text
    assert resp.json() == {"registered": True, "email": GOOD["email"],
                           "message": "Account created successfully. Please sign in."}


def test_sign_up_does_not_sign_the_person_in(client):
    resp = _register(client)
    assert "ro_session=" not in resp.headers.get("set-cookie", "")
    assert client.get("/auth/session").json()["authenticated"] is False


def test_the_password_is_stored_only_as_an_argon2_hash(client):
    _register(client)
    row = fetch_one("SELECT password_hash FROM users WHERE email = :e", {"e": GOOD["email"]})
    assert row["password_hash"].startswith("$argon2")
    assert GOOD["password"] not in row["password_hash"]


def test_the_new_person_can_sign_in_after_sign_up(client):
    _register(client)
    signed_in = login_client(main.app, GOOD["email"], GOOD["password"])
    assert signed_in.get("/auth/session").json()["user"]["email"] == GOOD["email"]


def test_the_new_person_is_admin_only_of_their_own_workspace(client):
    _register(client)
    user_id = fetch_one("SELECT id FROM users WHERE email = :e", {"e": GOOD["email"]})["id"]
    memberships = fetch_all(
        "SELECT w.name, m.role FROM workspace_members m JOIN workspaces w ON w.id = m.workspace_id "
        "WHERE m.user_id = :u", {"u": user_id})
    assert memberships == [{"name": "Nadia Khan workspace", "role": "admin"}]
    platform_role = fetch_one("SELECT role FROM users WHERE id = :u", {"u": user_id})["role"]
    assert platform_role == "viewer"


def test_the_new_person_cannot_manage_accounts_on_the_instance(client):
    _register(client)
    signed_in = login_client(main.app, GOOD["email"], GOOD["password"])
    assert signed_in.get("/users").status_code == 403


def test_existing_workspaces_and_roles_are_not_changed(client):
    before = fetch_all("SELECT workspace_id, user_id, role FROM workspace_members ORDER BY workspace_id, user_id")
    _register(client)
    after = fetch_all("SELECT workspace_id, user_id, role FROM workspace_members ORDER BY workspace_id, user_id")
    assert all(row in after for row in before)
    new_user = fetch_one("SELECT id FROM users WHERE email = :e", {"e": GOOD["email"]})["id"]
    new_rows = [row for row in after if row not in before]
    assert {row["user_id"] for row in new_rows} == {new_user}
    assert {row["role"] for row in new_rows} == {"admin"}


def test_the_same_email_cannot_register_twice(client):
    assert _register(client).status_code == 201
    resp = _register(client)
    assert resp.status_code == 409
    assert resp.json()["detail"] == "An account with this email already exists."


def test_email_is_compared_without_regard_to_case(client):
    assert _register(client).status_code == 201
    assert _register(client, email="NADIA@Example.test").status_code == 409


def test_an_existing_account_email_is_refused(client):
    assert _register(client, email=ADMIN_EMAIL).status_code == 409


@pytest.mark.parametrize("password", ["Abc1234", "Abc123456", "Abc12345!", "Abc 1234", "Abcdéfg1"])
def test_passwords_outside_the_rule_are_refused(client, password):
    resp = _register(client, password=password)
    assert resp.status_code == 422, password


def test_a_password_of_eight_letters_and_numbers_is_accepted(client):
    assert _register(client, password="ABCDEFG8").status_code == 201


def test_the_password_rule_is_checked_before_the_duplicate_check(client):
    resp = _register(client, email=ADMIN_EMAIL, password="short")
    assert resp.status_code == 422


@pytest.mark.parametrize("name", ["", "A"])
def test_a_name_that_is_too_short_is_refused(client, name):
    assert _register(client, name=name).status_code == 422


@pytest.mark.parametrize("email", ["", "not-an-email", "a@b"])
def test_an_invalid_email_is_refused(client, email):
    assert _register(client, email=email).status_code == 422


def test_sign_up_is_refused_while_no_account_exists(test_db, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    c = TestClient(main.app)
    c.headers.update({"X-Requested-With": "test"})
    resp = c.post("/auth/register", json=GOOD)
    assert resp.status_code == 409
    assert "first admin" in resp.json()["detail"]


def test_sign_up_needs_the_csrf_header(test_db, monkeypatch):
    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    make_account(ADMIN_EMAIL, "admin", password=ADMIN_PASSWORD)
    resp = TestClient(main.app).post("/auth/register", json=GOOD)
    assert resp.status_code == 403


def test_sign_up_is_rate_limited_when_limiting_is_on(test_db, monkeypatch):
    from services import rate_limit

    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "true")
    rate_limit.limiter.reset()
    make_account(ADMIN_EMAIL, "admin", password=ADMIN_PASSWORD)
    c = TestClient(main.app)
    c.headers.update({"X-Requested-With": "test"})
    codes = [c.post("/auth/register", json={**GOOD, "email": f"user{i}@example.test"}).status_code
             for i in range(6)]
    assert codes[:5] == [201] * 5
    assert codes[5] == 429
