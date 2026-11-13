"""Workspaces, team membership and invitations.

Roles inside a workspace: admin (manage the team and everything else), operator (work with restaurants,
drafts and campaigns), viewer (read only). Platform admins (users.role = admin) create workspaces; they
are not automatically members of them.

Rules
- Every membership change is audited.
- A workspace always keeps at least one admin, and nobody can remove or demote themselves.
- Removing a member ends their sessions that were working in that workspace.
- Invitations carry a random token. Only its SHA-256 hash is stored, the token is shown once, and it
  expires after INVITATION_DAYS. Accepting it once, or revoking it, makes it unusable.
- An invitation never grants platform-admin rights. An invited new account starts with the global role
  "viewer"; the invitation's role applies only inside its workspace.
"""
import hashlib
import secrets
from datetime import timedelta

from config import public_app_url
from models.database import execute, execute_returning_id, fetch_all, fetch_one, utc_now
from services import audit, users
from services.access import ROLES
from services.auth import remove_member_sessions
from services.membership import membership_role

INVITATION_DAYS = 7
WORKSPACE_NAME_MAX = 120


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def default_workspace_id() -> int:
    row = fetch_one("SELECT MIN(id) AS id FROM workspaces")
    if row is None or row["id"] is None:
        raise RuntimeError("No workspace exists. Run the database migrations.")
    return int(row["id"])


def my_workspaces(user_id: int) -> list[dict]:
    return fetch_all(
        "SELECT w.id, w.name, w.status, m.role FROM workspace_members m "
        "JOIN workspaces w ON w.id = m.workspace_id WHERE m.user_id = :user ORDER BY w.id",
        {"user": user_id},
    )


def all_workspaces() -> list[dict]:
    """Every workspace on the instance, for platform administrators. Names and member counts only."""
    return fetch_all(
        "SELECT w.id, w.name, w.status, w.created_at, "
        "(SELECT COUNT(*) FROM workspace_members m WHERE m.workspace_id = w.id) AS members "
        "FROM workspaces w ORDER BY w.id"
    )


def get_workspace(workspace_id: int) -> dict | None:
    return fetch_one("SELECT id, name, status, created_at FROM workspaces WHERE id = :id", {"id": workspace_id})


def _check_name(name: str) -> str:
    value = " ".join((name or "").split())
    if len(value) < 2 or len(value) > WORKSPACE_NAME_MAX:
        raise ValueError(f"Workspace name must be between 2 and {WORKSPACE_NAME_MAX} characters.")
    return value


def create_workspace(actor: dict, name: str) -> dict:
    clean = _check_name(name)
    workspace_id = execute_returning_id(
        "INSERT INTO workspaces (name, created_by_user_id) VALUES (:name, :actor) RETURNING id",
        {"name": clean, "actor": actor["id"]},
    )
    execute("INSERT INTO workspace_members (workspace_id, user_id, role, added_by_user_id) "
            "VALUES (:ws, :user, 'admin', :actor)", {"ws": workspace_id, "user": actor["id"], "actor": actor["id"]})
    audit.record(actor["id"], "workspace.created", "workspace", workspace_id, f"name={clean}", workspace_id)
    return get_workspace(workspace_id)


def rename_workspace(actor: dict, workspace_id: int, name: str) -> dict:
    clean = _check_name(name)
    execute("UPDATE workspaces SET name = :name WHERE id = :id", {"name": clean, "id": workspace_id})
    audit.record(actor["id"], "workspace.renamed", "workspace", workspace_id, f"name={clean}", workspace_id)
    return get_workspace(workspace_id)


def list_members(workspace_id: int) -> list[dict]:
    return fetch_all(
        "SELECT u.id, u.name, u.email, u.status AS account_status, m.role, m.created_at AS joined_at "
        "FROM workspace_members m JOIN users u ON u.id = m.user_id "
        "WHERE m.workspace_id = :ws ORDER BY u.id",
        {"ws": workspace_id},
    )


def _admin_count(workspace_id: int) -> int:
    row = fetch_one("SELECT COUNT(*) AS n FROM workspace_members m JOIN users u ON u.id = m.user_id "
                    "WHERE m.workspace_id = :ws AND m.role = 'admin' AND u.status = 'active'", {"ws": workspace_id})
    return int(row["n"]) if row else 0


def change_member_role(actor: dict, workspace_id: int, user_id: int, role: str) -> dict:
    if role not in ROLES:
        raise ValueError("Role must be admin, operator or viewer.")
    current = membership_role(user_id, workspace_id)
    if current is None:
        raise LookupError("That person is not a member of this workspace.")
    if user_id == actor["id"] and role != "admin":
        raise ValueError("You cannot remove your own admin role in this workspace.")
    if current == "admin" and role != "admin" and _admin_count(workspace_id) <= 1:
        raise ValueError("A workspace must keep at least one admin.")
    execute("UPDATE workspace_members SET role = :role WHERE workspace_id = :ws AND user_id = :user",
            {"role": role, "ws": workspace_id, "user": user_id})
    audit.record(actor["id"], "workspace.member_role_changed", "user", user_id, f"role={role}", workspace_id)
    return {"user_id": user_id, "role": role}


def remove_member(actor: dict, workspace_id: int, user_id: int) -> None:
    current = membership_role(user_id, workspace_id)
    if current is None:
        raise LookupError("That person is not a member of this workspace.")
    if user_id == actor["id"]:
        raise ValueError("You cannot remove yourself from this workspace.")
    if current == "admin" and _admin_count(workspace_id) <= 1:
        raise ValueError("A workspace must keep at least one admin.")
    execute("DELETE FROM workspace_members WHERE workspace_id = :ws AND user_id = :user",
            {"ws": workspace_id, "user": user_id})
    remove_member_sessions(user_id, workspace_id)
    audit.record(actor["id"], "workspace.member_removed", "user", user_id, None, workspace_id)


def create_invitation(actor: dict, workspace_id: int, email: str, role: str) -> dict:
    clean_email = users.normalize_email(email)
    if role not in ROLES:
        raise ValueError("Role must be admin, operator or viewer.")
    existing = fetch_one("SELECT id FROM users WHERE email = :email", {"email": clean_email})
    if existing and membership_role(existing["id"], workspace_id) is not None:
        raise ValueError("That person is already a member of this workspace.")
    token = secrets.token_urlsafe(32)
    expires = utc_now() + timedelta(days=INVITATION_DAYS)
    invitation_id = execute_returning_id(
        "INSERT INTO workspace_invitations (workspace_id, email, role, token_hash, created_by_user_id, expires_at) "
        "VALUES (:ws, :email, :role, :hash, :actor, :expires) RETURNING id",
        {"ws": workspace_id, "email": clean_email, "role": role, "hash": _hash_token(token),
         "actor": actor["id"], "expires": expires},
    )
    audit.record(actor["id"], "workspace.invitation_created", "invitation", invitation_id,
                 f"role={role}", workspace_id)
    return {
        "id": invitation_id,
        "email": clean_email,
        "role": role,
        "expires_at": expires.strftime("%Y-%m-%d %H:%M:%S"),
        "link": f"{public_app_url()}/#invite={token}",
    }


def invitation_status(row: dict) -> str:
    if row["revoked_at"]:
        return "revoked"
    if row["accepted_at"]:
        return "accepted"
    if str(row["expires_at"]) < utc_now().strftime("%Y-%m-%d %H:%M:%S"):
        return "expired"
    return "pending"


def list_invitations(workspace_id: int) -> list[dict]:
    rows = fetch_all(
        "SELECT id, email, role, created_at, expires_at, accepted_at, revoked_at FROM workspace_invitations "
        "WHERE workspace_id = :ws ORDER BY id DESC",
        {"ws": workspace_id},
    )
    return [{**{k: r[k] for k in ("id", "email", "role", "created_at", "expires_at", "accepted_at", "revoked_at")},
             "status": invitation_status(r)} for r in rows]


def revoke_invitation(actor: dict, workspace_id: int, invitation_id: int) -> None:
    row = fetch_one("SELECT id, accepted_at, revoked_at FROM workspace_invitations "
                    "WHERE id = :id AND workspace_id = :ws", {"id": invitation_id, "ws": workspace_id})
    if row is None:
        raise LookupError("Invitation not found.")
    if row["accepted_at"] or row["revoked_at"]:
        raise ValueError("This invitation is no longer open.")
    execute("UPDATE workspace_invitations SET revoked_at = CURRENT_TIMESTAMP WHERE id = :id", {"id": invitation_id})
    audit.record(actor["id"], "workspace.invitation_revoked", "invitation", invitation_id, None, workspace_id)


GENERIC_INVITE_ERROR = "This invitation link is not valid. Ask for a new invitation."


def accept_invitation(token: str, name: str | None, password: str | None, signed_in: dict | None) -> dict:
    """Accept an invitation. Returns {'user': ..., 'workspace_id': ...}.

    - If an account already exists for the invited email, the person must be signed in as that account.
    - Otherwise a new account is created with the name and password given.
    """
    row = fetch_one("SELECT * FROM workspace_invitations WHERE token_hash = :hash", {"hash": _hash_token(token or "")})
    if row is None or row["revoked_at"] or row["accepted_at"]:
        raise ValueError(GENERIC_INVITE_ERROR)
    if invitation_status(row) == "expired":
        raise ValueError("This invitation has expired. Ask for a new invitation.")

    created = False
    existing = fetch_one("SELECT id, email FROM users WHERE email = :email", {"email": row["email"]})
    if existing is not None:
        if signed_in is None or signed_in["email"] != row["email"]:
            raise PermissionError(f"Sign in as {row['email']} to accept this invitation.")
        user_id = existing["id"]
        if membership_role(user_id, row["workspace_id"]) is None:
            execute("INSERT INTO workspace_members (workspace_id, user_id, role, added_by_user_id) "
                    "VALUES (:ws, :user, :role, :by)",
                    {"ws": row["workspace_id"], "user": user_id, "role": row["role"], "by": row["created_by_user_id"]})
    else:
        account = users.create_user(None, name or "", row["email"], password or "", "viewer",
                                    workspace_id=row["workspace_id"], workspace_role=row["role"])
        user_id = account["id"]
        created = True

    execute("UPDATE workspace_invitations SET accepted_at = CURRENT_TIMESTAMP, accepted_user_id = :user "
            "WHERE id = :id", {"user": user_id, "id": row["id"]})
    audit.record(user_id, "workspace.invitation_accepted", "invitation", row["id"], f"role={row['role']}",
                 row["workspace_id"])
    return {"user": users.get_user(user_id), "workspace_id": row["workspace_id"], "created": created}


def preview_invitation(token: str) -> dict:
    """What an invitation is for, before anyone accepts it. Reads only; the token is never echoed back."""
    row = fetch_one("SELECT i.*, w.name AS workspace_name FROM workspace_invitations i "
                    "JOIN workspaces w ON w.id = i.workspace_id WHERE i.token_hash = :hash",
                    {"hash": _hash_token(token or "")})
    if row is None or row["revoked_at"] or row["accepted_at"]:
        raise ValueError(GENERIC_INVITE_ERROR)
    status = invitation_status(row)
    if status == "expired":
        raise ValueError("This invitation has expired. Ask for a new invitation.")
    account_exists = fetch_one("SELECT id FROM users WHERE email = :email", {"email": row["email"]}) is not None
    return {"workspace_name": row["workspace_name"], "email": row["email"], "role": row["role"],
            "expires_at": str(row["expires_at"]), "account_exists": account_exists}
