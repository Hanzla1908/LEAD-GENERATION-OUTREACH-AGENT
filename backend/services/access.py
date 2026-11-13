"""Roles and per-endpoint permission checks.

Two levels of role
- Workspace role (workspace_members.role): admin, operator or viewer, per workspace.
    read            any member (viewers included)
    operate         admin and operator: restaurants, leads, drafts, campaigns, mailbox actions
    workspace_admin admin: manage the team, invitations and the workspace's activity
- Platform role (users.role): admin only. Creates workspaces and manages accounts across the instance.
  It does not grant access to any workspace's data by itself.

Every protected endpoint declares one permission with Depends(require(...)). Data endpoints check the role
in the workspace the session works in. Team endpoints that name a workspace in the URL check the role in
that workspace, so a member of workspace A cannot act on workspace B by changing the URL.
tests/test_accounts.py and tests/test_workspaces.py fail if a protected route is added without a permission.
"""
from fastapi import HTTPException, Request

from services.auth import COOKIE_NAME, current_user
from services.membership import membership_role, resolve_active

ROLES = ("admin", "operator", "viewer")

WORKSPACE_PERMISSIONS = {
    "read": {"admin", "operator", "viewer"},
    "operate": {"admin", "operator"},
    "workspace_admin": {"admin"},
}
PLATFORM_PERMISSION = "platform_admin"
PERMISSIONS = set(WORKSPACE_PERMISSIONS) | {PLATFORM_PERMISSION}


def require_signed_in(request: Request) -> dict:
    """Any signed-in active account, with or without a workspace. Used for listing your own workspaces."""
    user = current_user(request.cookies.get(COOKIE_NAME))
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in required.")
    request.state.user = user
    return user


def require(permission: str, path_workspace: bool = False):
    """FastAPI dependency: the signed-in active account, with its workspace and role checked.

    path_workspace=True checks the workspace named by the {workspace_id} path parameter instead of the
    workspace the session works in.
    """
    if permission not in PERMISSIONS:
        raise ValueError(f"Unknown permission: {permission}")

    def dependency(request: Request) -> dict:
        user = current_user(request.cookies.get(COOKIE_NAME))
        if user is None:
            raise HTTPException(status_code=401, detail="Sign in required.")

        if permission == PLATFORM_PERMISSION:
            if user["role"] != "admin":
                raise HTTPException(status_code=403, detail="Only platform administrators can do this.")
            request.state.user = user
            return user

        if path_workspace:
            try:
                workspace_id = int(request.path_params["workspace_id"])
            except (KeyError, ValueError):
                raise HTTPException(status_code=404, detail="Workspace not found.")
            role = membership_role(user["id"], workspace_id)
        else:
            workspace_id, role = resolve_active(user)

        if role is None:
            raise HTTPException(status_code=403, detail="You are not a member of this workspace.")
        if role not in WORKSPACE_PERMISSIONS[permission]:
            raise HTTPException(status_code=403, detail="Your role in this workspace does not allow this action.")
        request.state.user = {**user, "workspace_id": workspace_id, "workspace_role": role}
        return request.state.user

    dependency.__name__ = f"require_{permission}"
    return dependency
