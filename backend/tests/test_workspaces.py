"""Phase 22: workspaces, team membership, invitations, role permissions and workspace isolation."""
import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

import main
from models.database import execute, fetch_all, fetch_one, get_engine
from services.tenancy import workspace_scope
from tests.account_helpers import TEST_SESSION_SECRET, login_client, make_account

BACKEND = Path(__file__).resolve().parent.parent
PLATFORM_EMAIL = "platform@example.test"
PLATFORM_PASSWORD = "platform-passphrase-1"


@pytest.fixture
def world(test_db, monkeypatch):
    """A platform admin, two workspaces (Alpha and Bravo), and one member for each workspace."""
    from services import campaigns as campaign_service
    from services import rate_limit

    monkeypatch.setenv("SESSION_SECRET", TEST_SESSION_SECRET)
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.delenv("RATE_LIMIT_ENABLED", raising=False)
    rate_limit.limiter.reset()
    # Creating a campaign starts a background draft thread. These tests never need its output, and the thread
    # must not outlive the test database it reads from.
    monkeypatch.setattr(campaign_service, "_spawn", lambda target, *args: None)
    default_ws = int(fetch_one("SELECT MIN(id) AS id FROM workspaces")["id"])
    make_account(PLATFORM_EMAIL, "admin", password=PLATFORM_PASSWORD, name="Platform Owner")
    platform = login_client(main.app, PLATFORM_EMAIL, PLATFORM_PASSWORD)
    alpha = platform.post("/workspaces", json={"name": "Team Alpha"}).json()["id"]
    bravo = platform.post("/workspaces", json={"name": "Team Bravo"}).json()["id"]
    return {"default": default_ws, "platform": platform, "alpha": alpha, "bravo": bravo}


def _invite(admin_client, workspace_id, email, role):
    resp = admin_client.post(f"/workspaces/{workspace_id}/invitations", json={"email": email, "role": role})
    assert resp.status_code == 201, resp.text
    return resp.json()


def _accept(invitation, name, password, client=None):
    token = invitation["link"].split("#invite=", 1)[1]
    client = client or TestClient(main.app)
    client.headers.update({"X-Requested-With": "t"})
    resp = client.post("/invitations/accept", json={"token": token, "name": name, "password": password})
    return resp, client


def _member(world, workspace_key, email, role, name="Team Member", password="member-passphrase-1"):
    """Invite and accept a brand-new person into a workspace. Returns their signed-in client."""
    invitation = _invite(world["platform"], world[workspace_key], email, role)
    resp, client = _accept(invitation, name, password)
    assert resp.status_code == 200, resp.text
    return client


def _eligible_restaurant(workspace_id, name, email):
    """A qualified, emailable restaurant inside one workspace (written directly, as the discovery step would)."""
    with workspace_scope(workspace_id):
        execute(
            "INSERT INTO restaurants (place_id, name, address, source, website, contact_email, contact_email_status, "
            "contact_email_classification, lead_status, lead_score, workspace_id) VALUES "
            "(:place, :name, 'Main Road, Lahore, Pakistan', 'google_places', 'https://example.pk', :email, "
            "'domain_valid', 'business', 'qualified', 80, :ws)",
            {"place": f"place-{workspace_id}-{email}", "name": name, "email": email, "ws": workspace_id},
        )
    return fetch_one("SELECT id FROM restaurants WHERE name = :name AND workspace_id = :ws",
                     {"name": name, "ws": workspace_id})["id"]


# ── Invitations ───────────────────────────────────────────────────────────────

def test_the_invitation_token_is_returned_once_and_only_its_hash_is_stored(world):
    invitation = _invite(world["platform"], world["alpha"], "dana@example.test", "operator")
    token = invitation["link"].split("#invite=", 1)[1]
    assert len(token) >= 40
    rows = fetch_all("SELECT token_hash FROM workspace_invitations")
    assert rows[0]["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in repr(fetch_all("SELECT * FROM workspace_invitations"))
    assert "password" not in invitation and "password_hash" not in invitation


def test_accepting_creates_the_account_in_the_invited_workspace_with_the_invited_role(world):
    invitation = _invite(world["platform"], world["alpha"], "dana@example.test", "operator")
    resp, client = _accept(invitation, "Dana Ops", "dana-passphrase-1")
    assert resp.status_code == 200, resp.text
    session = client.get("/auth/session").json()
    assert session["user"]["email"] == "dana@example.test"
    assert session["workspace"] == {"id": world["alpha"], "role": "operator"}


def test_an_invited_person_is_not_a_platform_admin(world):
    dana = _member(world, "alpha", "dana@example.test", "admin")
    assert dana.get("/users").status_code == 403
    assert dana.post("/workspaces", json={"name": "Sneaky Team"}).status_code == 403


def test_an_expired_invitation_is_refused(world):
    invitation = _invite(world["platform"], world["alpha"], "late@example.test", "viewer")
    past = (datetime.now(timezone.utc) - timedelta(days=1)).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    execute("UPDATE workspace_invitations SET expires_at = :past WHERE id = :id", {"past": past, "id": invitation["id"]})
    resp, _ = _accept(invitation, "Late Person", "late-passphrase-1")
    assert resp.status_code == 422
    assert "expired" in resp.json()["detail"]


def test_an_accepted_invitation_cannot_be_used_again(world):
    invitation = _invite(world["platform"], world["alpha"], "once@example.test", "viewer")
    assert _accept(invitation, "Once Person", "once-passphrase-1")[0].status_code == 200
    resp, _ = _accept(invitation, "Again Person", "again-passphrase-1")
    assert resp.status_code == 404


def test_a_revoked_invitation_is_refused(world):
    invitation = _invite(world["platform"], world["alpha"], "revoked@example.test", "viewer")
    revoked = world["platform"].delete(f"/workspaces/{world['alpha']}/invitations/{invitation['id']}")
    assert revoked.status_code == 200
    assert _accept(invitation, "Revoked Person", "revoked-passphrase-1")[0].status_code == 404


def test_an_existing_account_must_sign_in_as_that_person_to_accept(world):
    make_account("carol@example.test", "viewer", password="carol-passphrase-1", name="Carol")
    invitation = _invite(world["platform"], world["alpha"], "carol@example.test", "viewer")

    anonymous, _ = _accept(invitation, None, None)
    assert anonymous.status_code == 403

    carol = login_client(main.app, "carol@example.test", "carol-passphrase-1")
    resp, _ = _accept(invitation, None, None, client=carol)
    assert resp.status_code == 200, resp.text
    session = carol.get("/auth/session").json()
    assert session["workspace"]["id"] == world["alpha"]
    assert len(session["workspaces"]) == 2  # her own workspace and Alpha


def test_inviting_an_existing_member_is_refused(world):
    _member(world, "alpha", "member@example.test", "viewer")
    resp = world["platform"].post(f"/workspaces/{world['alpha']}/invitations",
                                  json={"email": "member@example.test", "role": "viewer"})
    assert resp.status_code == 422
    assert "already a member" in resp.json()["detail"]


def test_the_preview_shows_the_invitation_without_accepting_it(world):
    invitation = _invite(world["platform"], world["alpha"], "preview@example.test", "operator")
    token = invitation["link"].split("#invite=", 1)[1]
    client = TestClient(main.app)
    client.headers.update({"X-Requested-With": "t"})
    preview = client.post("/invitations/preview", json={"token": token}).json()
    assert preview["workspace_name"] == "Team Alpha"
    assert preview["role"] == "operator"
    assert preview["account_exists"] is False
    assert "token" not in preview
    assert fetch_one("SELECT accepted_at FROM workspace_invitations WHERE id = :id",
                     {"id": invitation["id"]})["accepted_at"] is None
    assert client.post("/invitations/preview", json={"token": "not-a-real-token-value"}).status_code == 404


# ── Membership and role permissions ───────────────────────────────────────────

def test_a_workspace_admin_changes_a_member_role_and_the_permissions_follow(world):
    dana = _member(world, "alpha", "dana@example.test", "operator")
    assert dana.post("/restaurants/discover", json={"city": "Lahore", "limit": 1}).status_code == 200

    user_id = fetch_one("SELECT id FROM users WHERE email = 'dana@example.test'")["id"]
    changed = world["platform"].put(f"/workspaces/{world['alpha']}/members/{user_id}", json={"role": "viewer"})
    assert changed.status_code == 200
    assert dana.get("/restaurants").status_code == 200
    assert dana.post("/restaurants/discover", json={"city": "Lahore", "limit": 1}).status_code == 403


def test_an_operator_cannot_manage_the_team(world):
    dana = _member(world, "alpha", "dana@example.test", "operator")
    assert dana.get(f"/workspaces/{world['alpha']}/members").status_code == 200
    assert dana.post(f"/workspaces/{world['alpha']}/invitations",
                     json={"email": "x@example.test", "role": "viewer"}).status_code == 403
    assert dana.put(f"/workspaces/{world['alpha']}/members/1", json={"role": "viewer"}).status_code == 403
    assert dana.get("/audit-log").status_code == 403


def test_a_viewer_reads_but_cannot_change_anything(world):
    vera = _member(world, "alpha", "vera@example.test", "viewer")
    assert vera.get("/restaurants").status_code == 200
    assert vera.get("/campaigns").status_code == 200
    assert vera.post("/restaurants/discover", json={"city": "Lahore", "limit": 1}).status_code == 403
    assert vera.post("/campaigns", json={"name": "Nope", "restaurant_ids": [1]}).status_code == 403


def test_the_last_admin_cannot_remove_or_demote_themselves(world):
    platform = world["platform"]
    own_id = fetch_one("SELECT id FROM users WHERE email = :email", {"email": PLATFORM_EMAIL})["id"]
    assert platform.put(f"/workspaces/{world['alpha']}/members/{own_id}", json={"role": "viewer"}).status_code == 422
    assert platform.delete(f"/workspaces/{world['alpha']}/members/{own_id}").status_code == 422


def test_removing_a_member_ends_their_access_to_that_workspace(world):
    dana = _member(world, "alpha", "dana@example.test", "operator")
    assert dana.get("/restaurants").status_code == 200
    dana_id = fetch_one("SELECT id FROM users WHERE email = 'dana@example.test'")["id"]
    removed = world["platform"].delete(f"/workspaces/{world['alpha']}/members/{dana_id}")
    assert removed.status_code == 200
    # Her session was working in Alpha, so it ends. She is signed out, and cannot get back in without an invitation.
    assert dana.get("/restaurants").status_code == 401


def test_a_person_in_two_workspaces_switches_between_them(world):
    dana = _member(world, "alpha", "dana@example.test", "operator")
    _member_into = _invite(world["platform"], world["bravo"], "dana@example.test", "viewer")
    resp, _ = _accept(_member_into, None, None, client=dana)
    assert resp.status_code == 200, resp.text
    assert dana.post(f"/workspaces/{world['bravo']}/switch").json()["active_workspace_id"] == world["bravo"]
    assert dana.get("/auth/session").json()["workspace"] == {"id": world["bravo"], "role": "viewer"}
    assert dana.post(f"/workspaces/{world['alpha']}/switch").status_code == 200
    assert dana.post(f"/workspaces/{world['default']}/switch").status_code == 403


# ── Isolation ─────────────────────────────────────────────────────────────────

def test_restaurants_are_visible_only_inside_their_own_workspace(world):
    dana = _member(world, "alpha", "dana@example.test", "operator")
    bob = _member(world, "bravo", "bob@example.test", "admin")
    assert dana.post("/restaurants/discover", json={"city": "Lahore", "limit": 2}).status_code == 200
    assert len(dana.get("/restaurants").json()) == 2
    assert bob.get("/restaurants").json() == []


def test_another_workspace_record_is_missing_when_addressed_by_id(world):
    dana = _member(world, "alpha", "dana@example.test", "operator")
    bob = _member(world, "bravo", "bob@example.test", "admin")
    dana.post("/restaurants/discover", json={"city": "Lahore", "limit": 1})
    alpha_restaurant = dana.get("/restaurants").json()[0]["id"]
    assert bob.post(f"/restaurants/{alpha_restaurant}/check").status_code == 404
    assert bob.post(f"/restaurants/{alpha_restaurant}/opt-out").status_code == 404
    assert bob.post(f"/restaurants/{alpha_restaurant}/qualify").status_code == 404
    assert bob.get(f"/restaurants/{alpha_restaurant}/conversations").status_code == 404


def test_campaigns_and_drafts_are_isolated(world):
    dana = _member(world, "alpha", "dana@example.test", "operator")
    bob = _member(world, "bravo", "bob@example.test", "admin")
    restaurant = _eligible_restaurant(world["alpha"], "Alpha Karahi", "alpha.cafe@example.pk")
    created = dana.post("/campaigns", json={"name": "Alpha launch", "restaurant_ids": [restaurant]})
    assert created.status_code == 201, created.text
    campaign_id = created.json()["id"]
    assert dana.get(f"/campaigns/{campaign_id}").status_code == 200

    assert bob.get("/campaigns").json() == []
    assert bob.get(f"/campaigns/{campaign_id}").status_code == 404
    assert bob.get(f"/campaigns/{campaign_id}/logs").status_code == 404
    assert bob.post(f"/campaigns/{campaign_id}/cancel").status_code == 404
    assert bob.post(f"/campaigns/{campaign_id}/send").status_code == 404
    assert bob.post(f"/campaigns/{campaign_id}/approve-sending", json={"draft_ids": [1]}).status_code == 404


def test_duplicate_protection_is_per_workspace(world):
    dana = _member(world, "alpha", "dana@example.test", "operator")
    bob = _member(world, "bravo", "bob@example.test", "admin")
    alpha_restaurant = _eligible_restaurant(world["alpha"], "Alpha Karahi", "shared.name@example.pk")
    bravo_restaurant = _eligible_restaurant(world["bravo"], "Bravo Karahi", "bravo.cafe@example.pk")
    assert dana.post("/campaigns", json={"name": "Lahore cafes", "restaurant_ids": [alpha_restaurant]}).status_code == 201

    plan = bob.post("/campaigns/preview", json={"name": "Lahore cafes", "restaurant_ids": [bravo_restaurant]}).json()
    assert plan["eligible_count"] == 1
    assert plan["items"][0]["reasons"] == []


def test_a_campaign_in_another_workspace_does_not_block_an_address(world):
    """The workspace-wide contact block is scoped: another workspace's campaigns are never consulted."""
    dana = _member(world, "alpha", "dana@example.test", "operator")
    bob = _member(world, "bravo", "bob@example.test", "admin")
    alpha_restaurant = _eligible_restaurant(world["alpha"], "Alpha Shared", "shared.owner@example.pk")
    bravo_restaurant = _eligible_restaurant(world["bravo"], "Bravo Shared", "shared.owner@example.pk")
    assert dana.post("/campaigns", json={"name": "Alpha round", "restaurant_ids": [alpha_restaurant]}).status_code == 201

    plan = bob.post("/campaigns/preview", json={"name": "Bravo round", "restaurant_ids": [bravo_restaurant]}).json()
    assert plan["eligible_count"] == 1


def test_the_same_google_place_can_be_saved_once_in_each_workspace(world):
    dana = _member(world, "alpha", "dana@example.test", "operator")
    bob = _member(world, "bravo", "bob@example.test", "admin")
    assert dana.post("/restaurants/discover", json={"city": "Lahore", "limit": 2}).status_code == 200
    assert bob.post("/restaurants/discover", json={"city": "Lahore", "limit": 2}).status_code == 200
    assert len(dana.get("/restaurants").json()) == 2
    assert len(bob.get("/restaurants").json()) == 2
    assert {r["id"] for r in dana.get("/restaurants").json()}.isdisjoint(
        {r["id"] for r in bob.get("/restaurants").json()})


def test_activity_is_listed_only_for_the_workspace_it_happened_in(world):
    dana = _member(world, "alpha", "dana@example.test", "operator")
    bob = _member(world, "bravo", "bob@example.test", "admin")
    dana.post("/restaurants/discover", json={"city": "Karachi", "limit": 1})
    bob.post("/restaurants/discover", json={"city": "Quetta", "limit": 1})

    # The platform admin is an admin of Alpha, so switching there shows Alpha's activity (and not Bravo's).
    world["platform"].post(f"/workspaces/{world['alpha']}/switch")
    alpha_log = world["platform"].get("/audit-log").json()
    assert any(e["action"] == "lead.discovered" and "Karachi" in (e["detail"] or "") for e in alpha_log)
    assert not any("Quetta" in (e["detail"] or "") for e in alpha_log)
    assert dana.get("/audit-log").status_code == 403


# ── Workspace management ──────────────────────────────────────────────────────

def test_only_platform_admins_create_workspaces_and_the_creator_becomes_their_admin(world):
    dana = _member(world, "alpha", "dana@example.test", "admin")
    assert dana.post("/workspaces", json={"name": "Dana Team"}).status_code == 403
    created = world["platform"].post("/workspaces", json={"name": "New Team"})
    assert created.status_code == 201
    members = world["platform"].get(f"/workspaces/{created.json()['id']}/members").json()
    assert [m["role"] for m in members] == ["admin"]


def test_workspace_admins_can_rename_and_others_cannot(world):
    dana = _member(world, "alpha", "dana@example.test", "operator")
    assert dana.put(f"/workspaces/{world['alpha']}", json={"name": "Hijacked"}).status_code == 403
    assert world["platform"].put(f"/workspaces/{world['alpha']}", json={"name": "Team Alpha Renamed"}).status_code == 200
    assert fetch_one("SELECT name FROM workspaces WHERE id = :id", {"id": world["alpha"]})["name"] == "Team Alpha Renamed"


def test_requests_without_a_session_are_refused(world):
    client = TestClient(main.app)
    assert client.get("/workspaces").status_code == 401
    assert client.get(f"/workspaces/{world['alpha']}/members").status_code == 401


def test_a_non_member_cannot_act_on_a_workspace_by_its_id(world):
    bob = _member(world, "bravo", "bob@example.test", "admin")
    assert bob.get(f"/workspaces/{world['alpha']}/members").status_code == 403
    assert bob.put(f"/workspaces/{world['alpha']}", json={"name": "Nope"}).status_code == 403
    assert bob.get(f"/workspaces/{world['alpha']}/invitations").status_code == 403


# ── Migration 0009 ────────────────────────────────────────────────────────────

def _alembic(url, action, target, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    getattr(command, action)(config, target)


def test_existing_records_move_into_the_default_workspace_and_the_rollback_keeps_them(tmp_path, monkeypatch):
    url = str(tmp_path / "phase22.db")
    _alembic(url, "upgrade", "0008_user_accounts", monkeypatch)
    monkeypatch.setenv("DATABASE_URL", url)
    execute("INSERT INTO users (name, email, password_hash, role, status) "
            "VALUES ('Old Admin', 'old.admin@example.test', 'x', 'admin', 'active')")
    execute("INSERT INTO users (name, email, password_hash, role, status) "
            "VALUES ('Old Operator', 'old.op@example.test', 'x', 'operator', 'active')")
    execute("INSERT INTO restaurants (place_id, name, source, lead_status) "
            "VALUES ('legacy-place-1', 'Legacy Cafe', 'google_places', 'qualified')")
    execute("INSERT INTO campaigns (name, status) VALUES ('Legacy campaign', 'review')")
    restaurant_before = fetch_one("SELECT id, name FROM restaurants WHERE place_id = 'legacy-place-1'")

    _alembic(url, "upgrade", "head", monkeypatch)
    default_ws = fetch_one("SELECT id FROM workspaces ORDER BY id LIMIT 1")["id"]
    restaurant = fetch_one("SELECT name, workspace_id FROM restaurants WHERE id = :id", {"id": restaurant_before["id"]})
    assert restaurant["name"] == "Legacy Cafe"
    assert restaurant["workspace_id"] == default_ws
    assert fetch_one("SELECT workspace_id FROM campaigns WHERE name = 'Legacy campaign'")["workspace_id"] == default_ws
    roles = {r["email"]: r["role"] for r in fetch_all(
        "SELECT u.email, m.role FROM workspace_members m JOIN users u ON u.id = m.user_id WHERE m.workspace_id = :ws",
        {"ws": default_ws})}
    assert roles == {"old.admin@example.test": "admin", "old.op@example.test": "operator"}

    # The check constraints the restaurants table had before must still refuse bad values after the rebuild.
    with pytest.raises(IntegrityError):
        execute("INSERT INTO restaurants (place_id, name, source, lead_status, workspace_id) "
                "VALUES ('bad-status', 'Bad', 'google_places', 'not-a-status', :ws)", {"ws": default_ws})
    # The same place may now exist once in each workspace.
    execute("INSERT INTO workspaces (name) VALUES ('Second')")
    execute("INSERT INTO restaurants (place_id, name, source, workspace_id) "
            "VALUES ('legacy-place-1', 'Same Place Elsewhere', 'google_places', "
            "(SELECT MIN(id) FROM workspaces WHERE name = 'Second'))")

    # Rolling back would need the old one-place-per-instance rule, which this data breaks. The rollback refuses
    # and changes nothing.
    with pytest.raises(RuntimeError, match="more than one workspace"):
        _alembic(url, "downgrade", "0008_user_accounts", monkeypatch)
    assert fetch_one("SELECT COUNT(*) AS n FROM restaurants WHERE place_id = 'legacy-place-1'")["n"] == 2

    # Once that duplicate is removed on purpose, the rollback keeps every other row.
    execute("DELETE FROM restaurants WHERE name = 'Same Place Elsewhere'")
    _alembic(url, "downgrade", "0008_user_accounts", monkeypatch)
    assert fetch_one("SELECT COUNT(*) AS n FROM restaurants WHERE place_id = 'legacy-place-1'")["n"] == 1
    assert fetch_one("SELECT COUNT(*) AS n FROM campaigns WHERE name = 'Legacy campaign'")["n"] == 1
    _alembic(url, "upgrade", "head", monkeypatch)
