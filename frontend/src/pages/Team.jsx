import { useCallback, useEffect, useState } from 'react'
import { Badge, Button, EmptyState, Icon, Skeleton, useToast } from '../components/ui'
import { ROLE_LABEL } from '../components/Layout'
import * as api from '../services/api'
import { timeAgo } from '../lib/format'

const ROLES = ['admin', 'operator', 'viewer']
const ROLE_HELP = {
  admin: 'Manages the team, invitations and the activity log, and can do everything else.',
  operator: 'Works with businesses, drafts and campaigns. Cannot manage the team.',
  viewer: 'Reads everything in the workspace. Cannot change data.',
}
const STATUS_BADGE = {
  pending: ['info', 'Pending'],
  accepted: ['ok', 'Accepted'],
  revoked: ['neutral', 'Revoked'],
  expired: ['warn', 'Expired'],
}

export default function Team({ workspaceId, currentUser }) {
  const toast = useToast()
  const [members, setMembers] = useState(null)
  const [invitations, setInvitations] = useState([])
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState(null)
  const [email, setEmail] = useState('')
  const [role, setRole] = useState('operator')
  const [formError, setFormError] = useState('')
  const [createdLink, setCreatedLink] = useState(null)

  const load = useCallback(async () => {
    try {
      const [team, invites] = await Promise.all([api.listMembers(workspaceId), api.listInvitations(workspaceId)])
      setMembers(team)
      setInvitations(invites)
      setError('')
    } catch (err) {
      setError(err.message || 'Could not load the team.')
    }
  }, [workspaceId])

  useEffect(() => {
    load()
  }, [load])

  async function changeRole(member, nextRole) {
    setBusyId(member.id)
    try {
      await api.changeMemberRole(workspaceId, member.id, nextRole)
      toast(`${member.name} is now ${ROLE_LABEL[nextRole]}.`)
      await load()
    } catch (err) {
      toast(err.message || 'The role could not be changed.', 'error')
    } finally {
      setBusyId(null)
    }
  }

  async function remove(member) {
    setBusyId(member.id)
    try {
      await api.removeMember(workspaceId, member.id)
      toast(`${member.name} was removed from this workspace.`)
      await load()
    } catch (err) {
      toast(err.message || 'The member could not be removed.', 'error')
    } finally {
      setBusyId(null)
    }
  }

  async function invite(event) {
    event.preventDefault()
    setFormError('')
    setCreatedLink(null)
    try {
      const created = await api.createInvitation(workspaceId, email.trim(), role)
      setCreatedLink(created)
      setEmail('')
      await load()
    } catch (err) {
      setFormError(err.message || 'The invitation could not be created.')
    }
  }

  async function revoke(invitation) {
    try {
      await api.revokeInvitation(workspaceId, invitation.id)
      toast(`Invitation for ${invitation.email} was revoked.`)
      await load()
    } catch (err) {
      toast(err.message || 'The invitation could not be revoked.', 'error')
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
          <h2>Team</h2>
          <p>Invite people to this workspace, and set what each person can do here.</p>
        </div>
      </div>

      <section className="card card-flush" aria-label="Members">
        <div className="card-head">
          <div>
            <h3>Members</h3>
            <p>The last admin of a workspace cannot be removed or demoted. You cannot change your own role.</p>
          </div>
        </div>
        {members === null ? (
          <div className="card-body stack"><Skeleton height={14} /><Skeleton height={14} /></div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Email</th>
                  <th scope="col">Role here</th>
                  <th scope="col">Joined</th>
                  <th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {members.map((member) => {
                  const isSelf = member.id === currentUser.id
                  const busy = busyId === member.id
                  return (
                    <tr key={member.id}>
                      <td>
                        <div className="cell-title">{member.name}{isSelf && <> <Badge tone="info">You</Badge></>}</div>
                      </td>
                      <td>{member.email}</td>
                      <td>
                        <label className="sr-only" htmlFor={`member-role-${member.id}`}>Role for {member.name}</label>
                        <select
                          id={`member-role-${member.id}`}
                          className="select"
                          value={member.role}
                          disabled={busy || isSelf}
                          title={isSelf ? 'You cannot change your own role here.' : ROLE_HELP[member.role]}
                          onChange={(event) => changeRole(member, event.target.value)}
                        >
                          {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
                        </select>
                      </td>
                      <td className="muted small">{timeAgo(member.joined_at)}</td>
                      <td>
                        <Button size="sm" variant="ghost" className="is-danger" disabled={busy || isSelf}
                          title={isSelf ? 'You cannot remove yourself.' : undefined} onClick={() => remove(member)}>
                          Remove
                        </Button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <div className="grid-2">
        <section className="card" aria-labelledby="invite-form-title">
          <div className="card-head">
            <div>
              <h3 id="invite-form-title">Invite someone</h3>
              <p>The invitation link is shown once. Nothing is emailed by the app; send the link yourself.</p>
            </div>
          </div>
          <form className="card-body stack" onSubmit={invite} noValidate>
            <div className="field">
              <label htmlFor="invite-email">Email</label>
              <input id="invite-email" className="input" type="email" maxLength={254} value={email}
                onChange={(event) => setEmail(event.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="invite-role">Role in this workspace</label>
              <select id="invite-role" className="select" value={role} onChange={(event) => setRole(event.target.value)}>
                {ROLES.map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}: {ROLE_HELP[r]}</option>)}
              </select>
            </div>
            {formError && <div className="notice notice-bad" role="alert">{formError}</div>}
            {createdLink && (
              <div className="notice notice-info" role="status">
                <div>
                  Invitation for {createdLink.email} (expires {createdLink.expires_at} UTC). Copy this link now; it will not be shown again:
                  <code className="invite-link">{createdLink.link}</code>
                </div>
              </div>
            )}
            <div className="form-actions">
              <Button variant="primary" icon="plus" type="submit" disabled={!email.trim()}>Create invitation</Button>
            </div>
          </form>
        </section>

        <section className="card card-flush" aria-label="Invitations">
          <div className="card-head">
            <div>
              <h3>Invitations</h3>
              <p>Pending invitations can be revoked. Accepted, revoked and expired ones stay listed.</p>
            </div>
          </div>
          {invitations.length === 0 ? (
            <EmptyState icon="users" title="No invitations yet">Invite someone with the form.</EmptyState>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Email</th>
                    <th scope="col">Role</th>
                    <th scope="col">Status</th>
                    <th scope="col"><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {invitations.map((invitation) => {
                    const [tone, label] = STATUS_BADGE[invitation.status] ?? ['neutral', invitation.status]
                    return (
                      <tr key={invitation.id}>
                        <td>{invitation.email}</td>
                        <td>{ROLE_LABEL[invitation.role]}</td>
                        <td><Badge tone={tone}>{label}</Badge></td>
                        <td>
                          {invitation.status === 'pending' && (
                            <Button size="sm" variant="ghost" className="is-danger" onClick={() => revoke(invitation)}>
                              Revoke
                            </Button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </>
  )
}
