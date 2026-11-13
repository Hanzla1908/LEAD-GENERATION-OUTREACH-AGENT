"""The workspace a request or background job works in.

Every query on restaurants, drafts and campaigns reads current_workspace(). It fails closed: when no
workspace is set, the query raises instead of reading across workspaces. The gateway sets the workspace from
the signed-in person's session before the route runs. Background workers capture it when they start.

Deliberately not scoped (system-wide maintenance and provider callbacks identified by their own keys):
- suppression_list: an address that opted out is never emailed, by any workspace.
- purge_expired_google_content: clears expired Google listing data everywhere (a data-retention duty).
- the provider webhook, which finds a campaign recipient by provider message id, then works inside that
  recipient's workspace.
"""
from contextlib import contextmanager
from contextvars import ContextVar

_workspace: ContextVar[int | None] = ContextVar("active_workspace_id", default=None)


class NoWorkspace(RuntimeError):
    """A workspace-scoped query ran with no workspace set. This is a programming error, never a user error."""


def current_workspace() -> int:
    value = _workspace.get()
    if value is None:
        raise NoWorkspace("No workspace is active for this operation.")
    return value


def current_workspace_or_none() -> int | None:
    return _workspace.get()


@contextmanager
def workspace_scope(workspace_id: int | None):
    """Run a block inside one workspace, then restore the previous one."""
    token = _workspace.set(workspace_id)
    try:
        yield workspace_id
    finally:
        _workspace.reset(token)
