"""Helpers for tests that need accounts and signed-in clients. No network, no email."""
from fastapi.testclient import TestClient

TEST_SESSION_SECRET = "session-secret-0123456789abcdefghij"
TEST_PASSWORD = "correct-horse-battery-staple"
ADMIN_EMAIL = "admin@example.test"


def make_account(email: str = ADMIN_EMAIL, role: str = "admin", password: str = TEST_PASSWORD,
                 name: str = "Test Person") -> dict:
    """Create an active account directly in the test database."""
    from services import users

    return users.create_user(None, name, email, password, role)


def signed_in_client(app) -> TestClient:
    """A client signed in as the default admin. Creates that admin in the current test database if needed."""
    from services import users

    if users.active_admin_count() == 0:
        make_account(ADMIN_EMAIL, "admin")
    return login_client(app)


def login_client(app, email: str = ADMIN_EMAIL, password: str = TEST_PASSWORD) -> TestClient:
    """A TestClient signed in as the given account. Sends the CSRF header on every request."""
    client = TestClient(app)
    client.headers.update({"X-Requested-With": "test"})
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return client
