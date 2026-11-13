"""Audit trail: who did what, when, and in which workspace.

Entries hold the action name, the record it touched, and a short detail. They never hold passwords,
tokens, or the text of drafts and replies. actor_user_id is NULL for actions with no signed-in account
(the bootstrap command, rows written before accounts existed). workspace_id is the workspace the action
belongs to; account-level actions (sign-in, password changes) have none.
"""
from models.database import execute, fetch_all
from services.tenancy import current_workspace_or_none

MAX_DETAIL = 500


def record(actor_id: int | None, action: str, target_type: str | None = None,
           target_id: int | str | None = None, detail: str | None = None,
           workspace_id: int | None = None) -> None:
    ws = workspace_id if workspace_id is not None else current_workspace_or_none()
    execute(
        "INSERT INTO audit_log (actor_user_id, action, target_type, target_id, detail, workspace_id) "
        "VALUES (:actor, :action, :target_type, :target_id, :detail, :ws)",
        {
            "actor": actor_id,
            "action": action[:64],
            "target_type": target_type[:40] if target_type else None,
            "target_id": str(target_id)[:64] if target_id is not None else None,
            "detail": detail[:MAX_DETAIL] if detail else None,
            "ws": ws,
        },
    )


def list_entries(workspace_id: int, limit: int = 100, offset: int = 0) -> list[dict]:
    return fetch_all(
        "SELECT a.id, a.created_at, a.action, a.target_type, a.target_id, a.detail, "
        "a.actor_user_id, u.name AS actor_name, u.email AS actor_email "
        "FROM audit_log a LEFT JOIN users u ON u.id = a.actor_user_id "
        "WHERE a.workspace_id = :ws ORDER BY a.id DESC LIMIT :limit OFFSET :offset",
        {"ws": workspace_id, "limit": limit, "offset": offset},
    )
