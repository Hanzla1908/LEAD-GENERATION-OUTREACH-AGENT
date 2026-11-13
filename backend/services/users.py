"""User accounts: creation, sign-in, roles, activation, and password changes.

Rules enforced here (the routes add the role checks on top):
- Emails are stored in lower case and are unique.
- Passwords are Argon2 hashes. Plain text is never stored or logged.
- At least one active admin must always exist. An admin cannot demote or deactivate themselves.
- Deactivating an account, resetting its password, or changing its own password ends its other sessions.
- Sign-in refuses unknown emails, wrong passwords, and inactive accounts with the same message, so the
  response does not reveal which accounts exist.
"""
import re

from sqlalchemy.exc import IntegrityError

from models.database import execute, execute_returning_id, fetch_all, fetch_one
from services import audit
from services.auth import revoke_user_sessions
from services.passwords import (
    hash_password, needs_rehash, password_problem, registration_password_problem, verify_dummy, verify_password,
)
from services.access import ROLES

EMAIL_PATTERN = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
GENERIC_LOGIN_ERROR = "Incorrect email or password."
PUBLIC_FIELDS = "id, name, email, role, status, created_at, updated_at, last_login_at, password_changed_at"


def normalize_email(email: str) -> str:
    value = (email or "").strip().lower()
    if len(value) > 254 or not EMAIL_PATTERN.match(value):
        raise ValueError("Enter a valid email address.")
    return value


def _clean_name(name: str) -> str:
    value = " ".join((name or "").split())
    if len(value) < 2 or len(value) > 120:
        raise ValueError("Name must be between 2 and 120 characters.")
    return value


def _check_role(role: str) -> str:
    if role not in ROLES:
        raise ValueError("Role must be admin, operator or viewer.")
    return role


def get_user(user_id: int) -> dict | None:
    return fetch_one(f"SELECT {PUBLIC_FIELDS} FROM users WHERE id = :id", {"id": user_id})


def list_users() -> list[dict]:
    return fetch_all(f"SELECT {PUBLIC_FIELDS} FROM users ORDER BY id")


def active_admin_count() -> int:
    row = fetch_one("SELECT COUNT(*) AS n FROM users WHERE role = 'admin' AND status = 'active'")
    return int(row["n"]) if row else 0


def _email_taken(email: str) -> bool:
    return fetch_one("SELECT id FROM users WHERE email = :email", {"email": email}) is not None


def _insert(name: str, email: str, password_hash: str, role: str, actor_id: int | None) -> int:
    return execute_returning_id(
        "INSERT INTO users (name, email, password_hash, role, status, created_by_user_id, password_changed_at) "
        "VALUES (:name, :email, :password_hash, :role, 'active', :actor, CURRENT_TIMESTAMP) RETURNING id",
        {"name": name, "email": email, "password_hash": password_hash, "role": role, "actor": actor_id},
    )


def join_workspace(user_id: int, workspace_id: int, role: str, added_by: int | None) -> None:
    execute(
        "INSERT INTO workspace_members (workspace_id, user_id, role, added_by_user_id) "
        "VALUES (:ws, :user, :role, :by)",
        {"ws": workspace_id, "user": user_id, "role": role, "by": added_by},
    )


def _default_workspace() -> int:
    row = fetch_one("SELECT MIN(id) AS id FROM workspaces")
    return int(row["id"])


def create_user(actor_id: int | None, name: str, email: str, password: str, role: str,
                workspace_id: int | None = None, workspace_role: str | None = None) -> dict:
    """Create an account and its membership. Without a workspace, the account joins the default workspace."""
    clean_name, clean_email, clean_role = _clean_name(name), normalize_email(email), _check_role(role)
    problem = password_problem(password)
    if problem:
        raise ValueError(problem)
    if _email_taken(clean_email):
        raise ValueError("An account with this email already exists.")
    user_id = _insert(clean_name, clean_email, hash_password(password), clean_role, actor_id)
    target = workspace_id if workspace_id is not None else _default_workspace()
    join_workspace(user_id, target, _check_role(workspace_role or clean_role), actor_id)
    audit.record(actor_id, "user.created", "user", user_id, f"role={clean_role}", target)
    return get_user(user_id)


REGISTRATION_WORKSPACE_NAME_MAX = 120


def register_account(name: str, email: str, password: str) -> dict:
    """Public sign-up. The new person gets a separate workspace in which they are its admin.

    Nothing about an existing workspace or account changes, and the new account is not signed in: the caller
    sends the person to the sign-in page. The platform role is 'viewer', so the account is never an instance
    administrator. Refused while no account exists at all; the first admin is created by the setup form.
    """
    clean_name, clean_email = _clean_name(name), normalize_email(email)
    problem = registration_password_problem(password)
    if problem:
        raise ValueError(problem)
    if not accounts_exist():
        raise PermissionError("No account exists yet. Create the first admin account from the sign-in page.")
    if _email_taken(clean_email):
        raise PermissionError("An account with this email already exists.")
    try:
        user_id = _insert(clean_name, clean_email, hash_password(password), "viewer", None)
    except IntegrityError:
        # Two sign-ups with the same email at the same moment: the unique index lets only one through.
        raise PermissionError("An account with this email already exists.")
    label = f"{clean_name} workspace"[:REGISTRATION_WORKSPACE_NAME_MAX]
    workspace_id = execute_returning_id(
        "INSERT INTO workspaces (name, created_by_user_id) VALUES (:name, :actor) RETURNING id",
        {"name": label, "actor": user_id},
    )
    join_workspace(user_id, workspace_id, "admin", user_id)
    audit.record(user_id, "user.registered", "user", user_id, f"workspace={workspace_id}", workspace_id)
    return get_user(user_id)


def accounts_exist() -> bool:
    row = fetch_one("SELECT COUNT(*) AS n FROM users")
    return bool(row and int(row["n"]) > 0)


def create_first_admin(name: str, email: str, password: str) -> dict:
    """Public setup, allowed only while no account exists at all.

    The insert itself checks that the table is empty, so two requests sent at the same moment cannot
    both create an admin. Everyone else gets an account from an admin on the Users page.
    """
    clean_name, clean_email = _clean_name(name), normalize_email(email)
    problem = password_problem(password)
    if problem:
        raise ValueError(problem)
    inserted = execute(
        "INSERT INTO users (name, email, password_hash, role, status, created_by_user_id, password_changed_at) "
        "SELECT :name, :email, :password_hash, 'admin', 'active', NULL, CURRENT_TIMESTAMP "
        "WHERE NOT EXISTS (SELECT 1 FROM users)",
        {"name": clean_name, "email": clean_email, "password_hash": hash_password(password)},
    )
    if not inserted:
        raise PermissionError("Accounts already exist. Ask an administrator to create yours.")
    row = fetch_one("SELECT id FROM users WHERE email = :email", {"email": clean_email})
    join_workspace(row["id"], _default_workspace(), "admin", None)
    audit.record(None, "bootstrap.first_admin_created", "user", row["id"], "public setup, first account",
                 _default_workspace())
    return get_user(row["id"])


def create_user_with_hash(actor_id: int | None, name: str, email: str, password_hash: str, role: str) -> dict:
    """Used only by the bootstrap command when importing the previous shared-admin hash."""
    user_id = _insert(_clean_name(name), normalize_email(email), password_hash, _check_role(role), actor_id)
    target = _default_workspace()
    join_workspace(user_id, target, role, actor_id)
    audit.record(actor_id, "user.created", "user", user_id, f"role={role}; imported password hash", target)
    return get_user(user_id)


def update_user(actor: dict, user_id: int, name: str | None = None, role: str | None = None,
                status: str | None = None) -> dict:
    target = get_user(user_id)
    if target is None:
        raise LookupError("User not found.")
    if user_id == actor["id"] and ((role is not None and role != "admin") or status == "inactive"):
        raise ValueError("You cannot remove your own admin role or deactivate your own account.")

    new_name = _clean_name(name) if name is not None else target["name"]
    new_role = _check_role(role) if role is not None else target["role"]
    new_status = status if status is not None else target["status"]
    if new_status not in ("active", "inactive"):
        raise ValueError("Status must be active or inactive.")

    losing_admin = target["role"] == "admin" and target["status"] == "active" and (
        new_role != "admin" or new_status != "active")
    if losing_admin and active_admin_count() <= 1:
        raise ValueError("At least one active admin must remain.")

    execute(
        "UPDATE users SET name = :name, role = :role, status = :status, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = :id",
        {"name": new_name, "role": new_role, "status": new_status, "id": user_id},
    )
    if new_status == "inactive":
        revoke_user_sessions(user_id)
    audit.record(actor["id"], "user.updated", "user", user_id,
                 f"role={new_role}; status={new_status}")
    return get_user(user_id)


def reset_password(actor: dict, user_id: int, new_password: str) -> dict:
    target = get_user(user_id)
    if target is None:
        raise LookupError("User not found.")
    problem = password_problem(new_password)
    if problem:
        raise ValueError(problem)
    execute(
        "UPDATE users SET password_hash = :hash, password_changed_at = CURRENT_TIMESTAMP, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = :id",
        {"hash": hash_password(new_password), "id": user_id},
    )
    revoke_user_sessions(user_id)
    audit.record(actor["id"], "user.password_reset", "user", user_id)
    return get_user(user_id)


def change_own_password(user: dict, current_password: str, new_password: str, keep_session_id: str) -> None:
    row = fetch_one("SELECT password_hash FROM users WHERE id = :id", {"id": user["id"]})
    if row is None or not verify_password(current_password, row["password_hash"]):
        raise PermissionError("The current password is not correct.")
    problem = password_problem(new_password)
    if problem:
        raise ValueError(problem)
    if current_password == new_password:
        raise ValueError("Choose a new password that differs from the current one.")
    execute(
        "UPDATE users SET password_hash = :hash, password_changed_at = CURRENT_TIMESTAMP, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = :id",
        {"hash": hash_password(new_password), "id": user["id"]},
    )
    revoke_user_sessions(user["id"], keep_session_id=keep_session_id)
    audit.record(user["id"], "auth.password_changed", "user", user["id"])


def authenticate(email: str, password: str) -> dict | None:
    """The public account for a correct email and password of an active user. None otherwise."""
    try:
        clean_email = normalize_email(email)
    except ValueError:
        verify_dummy(password)
        return None
    row = fetch_one("SELECT * FROM users WHERE email = :email", {"email": clean_email})
    if row is None:
        verify_dummy(password)
        return None
    matches = verify_password(password, row["password_hash"])
    if not matches or row["status"] != "active":
        return None
    if needs_rehash(row["password_hash"]):
        execute("UPDATE users SET password_hash = :hash WHERE id = :id",
                {"hash": hash_password(password), "id": row["id"]})
    execute("UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE id = :id", {"id": row["id"]})
    return get_user(row["id"])
