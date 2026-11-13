import { useCallback, useEffect, useState } from 'react'
import { Badge, Button, EmptyState, Icon, Skeleton, useToast } from '../components/ui'
import * as api from '../services/api'
import { timeAgo } from '../lib/format'

// Platform administrators create workspaces. Creating one makes its creator the workspace's first admin.
export default function Workspaces({ currentUser, activeWorkspaceId, onSwitch }) {
  const toast = useToast()
  const [workspaces, setWorkspaces] = useState(null)
  const [error, setError] = useState('')
  const [name, setName] = useState('')
  const [formError, setFormError] = useState('')

  const load = useCallback(async () => {
    try {
      setWorkspaces(await api.listAllWorkspaces())
      setError('')
    } catch (err) {
      setError(err.message || 'Could not load workspaces.')
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function create(event) {
    event.preventDefault()
    setFormError('')
    try {
      const created = await api.createWorkspace(name.trim())
      toast(`Workspace "${created.name}" created. You are its first admin.`)
      setName('')
      await load()
    } catch (err) {
      setFormError(err.message || 'The workspace could not be created.')
    }
  }

  if (error) {
    return (
      <div className="notice notice-bad" role="alert">
        <Icon name="alert" size={16} />
        <div>{error}</div>
      </div>
    )
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Workspaces</h2>
          <p>Each workspace has its own businesses, leads, drafts and campaigns. People only see the workspaces they belong to.</p>
        </div>
      </div>

      <section className="card card-flush" aria-label="All workspaces">
        {workspaces === null ? (
          <div className="card-body stack"><Skeleton height={14} /><Skeleton height={14} /></div>
        ) : workspaces.length === 0 ? (
          <EmptyState icon="leads" title="No workspaces">Create the first workspace below.</EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Workspace</th>
                  <th scope="col">Members</th>
                  <th scope="col">Status</th>
                  <th scope="col">Created</th>
                  <th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {workspaces.map((ws) => (
                  <tr key={ws.id}>
                    <td>
                      <div className="cell-title">
                        {ws.name}
                        {ws.id === activeWorkspaceId && <> <Badge tone="info">Working here</Badge></>}
                      </div>
                    </td>
                    <td>{ws.members}</td>
                    <td><Badge tone={ws.status === 'active' ? 'ok' : 'neutral'}>{ws.status}</Badge></td>
                    <td className="muted small">{timeAgo(ws.created_at)}</td>
                    <td>
                      <Button size="sm" variant="secondary" disabled={ws.id === activeWorkspaceId}
                        title="Works only if you are a member of this workspace."
                        onClick={() => onSwitch(ws.id)}>
                        Switch to
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section className="card" aria-labelledby="create-workspace-title">
        <div className="card-head">
          <div>
            <h3 id="create-workspace-title">Create a workspace</h3>
            <p>Signed in as {currentUser.name}. You become the first admin of the new workspace.</p>
          </div>
        </div>
        <form className="card-body stack" onSubmit={create} noValidate>
          <div className="field">
            <label htmlFor="workspace-name">Workspace name</label>
            <input id="workspace-name" className="input" maxLength={120} value={name}
              onChange={(event) => setName(event.target.value)} />
          </div>
          {formError && <div className="notice notice-bad" role="alert">{formError}</div>}
          <div className="form-actions">
            <Button variant="primary" icon="plus" type="submit" disabled={name.trim().length < 2}>Create workspace</Button>
          </div>
        </form>
      </section>
    </>
  )
}
