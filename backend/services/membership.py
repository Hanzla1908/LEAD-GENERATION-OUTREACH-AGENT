"""Who belongs to which workspace, and in what role. Used by the access checks and the workspace service."""
from models.database import fetch_one


def membership_role(user_id: int, workspace_id: int) -> str | None:
    row = fetch_one("SELECT role FROM workspace_members WHERE user_id = :user AND workspace_id = :ws",
                    {"user": user_id, "ws": workspace_id})
    return row["role"] if row else None


def resolve_active(user: dict) -> tuple[int | None, str | None]:
    """The workspace a session works in, and the person's role there.

    The workspace chosen for the session is used while the person is still a member of it. Otherwise the
    first workspace they belong to is used. Someone with no membership gets (None, None).
    """
    chosen = user.get("session_workspace_id")
    if chosen is not None:
        role = membership_role(user["id"], chosen)
        if role is not None:
            return chosen, role
    row = fetch_one("SELECT workspace_id, role FROM workspace_members WHERE user_id = :user "
                    "ORDER BY workspace_id LIMIT 1", {"user": user["id"]})
    if row is None:
        return None, None
    return int(row["workspace_id"]), row["role"]
