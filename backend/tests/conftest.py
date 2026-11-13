import os

import pytest


def use_database(tmp_path, monkeypatch) -> str:
    """Point the app at a clean database: a temp SQLite file, or TEST_POSTGRES_URL when set."""
    from models.database import get_engine, init_db
    from sqlalchemy import text

    postgres_url = os.getenv("TEST_POSTGRES_URL", "").strip()
    if postgres_url:
        monkeypatch.setenv("DATABASE_URL", postgres_url)
        with get_engine().begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
        init_db()
        return postgres_url

    db_file = str(tmp_path / "test.db")
    monkeypatch.setenv("DATABASE_URL", db_file)
    init_db()
    return db_file


@pytest.fixture()
def test_db(tmp_path, monkeypatch):
    """Provide an isolated database for each test, with the default workspace active.

    Model-level tests run outside a request, so the gateway does not set the workspace for them. The
    default workspace stands in for it. Isolation tests change it with workspace_scope(...).
    """
    url = use_database(tmp_path, monkeypatch)
    from models.database import fetch_one
    from services.tenancy import _workspace

    default = fetch_one("SELECT MIN(id) AS id FROM workspaces")["id"]
    _workspace.set(int(default))
    return url


@pytest.fixture
def account_client(test_db, monkeypatch):
    """An app client signed in as an active admin, in an isolated database."""
    import main
    from tests.account_helpers import ADMIN_EMAIL, TEST_SESSION_SECRET, login_client, make_account

    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    make_account(ADMIN_EMAIL, "admin")
    return login_client(main.app)


@pytest.fixture(autouse=True)
def offline_dns(monkeypatch):
    """Tests never touch the network. Every mail domain answers 'MX found' unless a test replaces this."""
    from services import email_validator

    email_validator.clear_cache()
    monkeypatch.setattr(email_validator, "_query_dns", lambda domain: ("mx", "mocked MX record"))
    yield
    email_validator.clear_cache()
