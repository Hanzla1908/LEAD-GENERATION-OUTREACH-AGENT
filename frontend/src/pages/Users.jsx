import { useCallback, useEffect, useState } from 'react'
import { Badge, Button, EmptyState, Icon, Skeleton, useToast } from '../components/ui'
import { ROLE_LABEL } from '../components/Layout'
import * as api from '../services/api'
import { timeAgo } from '../lib/format'

const PASSWORD_MIN = 12
const ROLES = ['admin', 'operator', 'viewer']
const EMPTY_FORM = { name: '', email: '', password: '', role: 'operator' }

const ROLE_HELP = {
  admin: 'Everything, including managing accounts.',
  operator: 'Searches, leads, drafts and campaigns. Cannot manage accounts.',
  viewer: 'Read-only.',
}

export default function Users({ currentUser }) {
  const toast = useToast()
  const [users, setUsers] = useState(null)
  const [entries, setEntries] = useState([])
  const [error, setError] = useState('')
  const [busyId, setBusyId] = useState(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [formError, setFormError] = useState('')
  const [resetId, setResetId] = useState('')
  const [resetPassword, setResetPassword] = useState('')
  const [resetError, setResetError] = useState('')

  const load = useCallback(async () => {
    try {
      const [accounts, log] = await Promise.all([api.listUsers(), api.listAuditLog(50)])
      setUsers(accounts)
      setEntries(log)
      setError('')
    } catch (err) {
      setError(err.message || 'Could not load accounts.')
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  async function change(account, body, message) {
    setBusyId(account.id)
    try {
      await api.updateUser(account.id, body)
      toast(message)
      await load()
    } catch (err) {
      toast(err.message || 'The change could not be saved.', 'error')
    } finally {
      setBusyId(null)
    }
  }

  async function createAccount(event) {
    event.preventDefault()
    setFormError('')
    if (form.password.length < PASSWORD_MIN) {
      setFormError(`Use at least ${PASSWORD_MIN} characters for the starting password.`)
      return
    }
    try {
      await api.createUser({ ...form, email: form.email.trim() })
      toast('Account created. Share the starting password with the person through a secure channel.')
      setForm(EMPTY_FORM)
      await load()
    } catch (err) {
      setFormError(err.message || 'The account could not be created.')
    }
  }

  async function resetFor(event) {
    event.preventDefault()
    setResetError('')
    const account = users?.find((u) => String(u.id) === resetId)
    if (!account) {
      setResetError('Choose an account.')
      return
    }
    if (resetPassword.length < PASSWORD_MIN) {
      setResetError(`Use at least ${PASSWORD_MIN} characters.`)
      return
    }
    try {
      await api.resetUserPassword(account.id, resetPassword)
      toast(`Password reset for ${account.name}. Their other sessions were signed out.`)
      setResetPassword('')
      setResetId('')
      await load()
    } catch (err) {
      setResetError(err.message || 'The password could not be reset.')
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
          <h2>Users</h2>
          <p>Create accounts, assign roles, and turn access on or off. Only administrators can see this page.</p>
        </div>
      </div>

      <section className="card card-flush" aria-label="Accounts">
        {users === null ? (
          <div className="card-body stack">
            <Skeleton height={14} />
            <Skeleton height={14} />
          </div>
        ) : users.length === 0 ? (
          <EmptyState icon="users" title="No accounts">Create the first account below.</EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Email</th>
                  <th scope="col">Role</th>
                  <th scope="col">Status</th>
                  <th scope="col">Last sign-in</th>
                  <th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {users.map((account) => {
                  const isSelf = account.id === currentUser.id
                  const busy = busyId === account.id
                  return (
                    <tr key={account.id}>
                      <td>
                        <div className="cell-title">{account.name}{isSelf && <> <Badge tone="info">You</Badge></>}</div>
                      </td>
                      <td>{account.email}</td>
                      <td>
                        <label className="sr-only" htmlFor={`role-${account.id}`}>Role for {account.name}</label>
                        <select
                          id={`role-${account.id}`}
                          className="select"
                          value={account.role}
                          disabled={busy || isSelf}
                          title={isSelf ? 'You cannot change your own role.' : ROLE_HELP[account.role]}
                          onChange={(event) => change(account, { role: event.target.value },
                            `${account.name} is now ${ROLE_LABEL[event.target.value]}.`)}
                        >
                          {ROLES.map((role) => <option key={role} value={role}>{ROLE_LABEL[role]}</option>)}
                        </select>
                      </td>
                      <td>
                        {account.status === 'active' ? <Badge tone="ok">Active</Badge> : <Badge tone="neutral">Deactivated</Badge>}
                      </td>
                      <td className="muted small">{account.last_login_at ? timeAgo(account.last_login_at) : 'Never'}</td>
                      <td>
                        <Button
                          size="sm"
                          variant="secondary"
                          disabled={busy || isSelf}
                          title={isSelf ? 'You cannot deactivate your own account.' : undefined}
                          onClick={() => change(account,
                            { status: account.status === 'active' ? 'inactive' : 'active' },
                            account.status === 'active' ? `${account.name} was deactivated and signed out.`
                              : `${account.name} can sign in again.`)}
                        >
                          {account.status === 'active' ? 'Deactivate' : 'Activate'}
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
        <section className="card" aria-labelledby="create-account-title">
          <div className="card-head">
            <div>
              <h3 id="create-account-title">Create an account</h3>
              <p>There is no public sign-up. Set a starting password and give it to the person securely.</p>
            </div>
          </div>
          <form className="card-body stack" onSubmit={createAccount} noValidate>
            <div className="field">
              <label htmlFor="new-name">Full name</label>
              <input id="new-name" className="input" maxLength={120} value={form.name}
                onChange={(event) => setForm({ ...form, name: event.target.value })} />
            </div>
            <div className="field">
              <label htmlFor="new-email">Email</label>
              <input id="new-email" className="input" type="email" maxLength={254} value={form.email}
                onChange={(event) => setForm({ ...form, email: event.target.value })} />
            </div>
            <div className="field">
              <label htmlFor="new-password">Starting password</label>
              <input id="new-password" className="input" type="password" autoComplete="new-password" maxLength={200}
                aria-describedby="new-password-help" value={form.password}
                onChange={(event) => setForm({ ...form, password: event.target.value })} />
              <span className="field-hint" id="new-password-help">At least {PASSWORD_MIN} characters.</span>
            </div>
            <div className="field">
              <label htmlFor="new-role">Role</label>
              <select id="new-role" className="select" value={form.role}
                onChange={(event) => setForm({ ...form, role: event.target.value })}>
                {ROLES.map((role) => <option key={role} value={role}>{ROLE_LABEL[role]}: {ROLE_HELP[role]}</option>)}
              </select>
            </div>
            {formError && <div className="notice notice-bad" role="alert">{formError}</div>}
            <div className="form-actions">
              <Button variant="primary" icon="plus" type="submit">Create account</Button>
            </div>
          </form>
        </section>

        <section className="card" aria-labelledby="reset-title">
          <div className="card-head">
            <div>
              <h3 id="reset-title">Reset a password</h3>
              <p>Resetting a password signs that person out everywhere.</p>
            </div>
          </div>
          <form className="card-body stack" onSubmit={resetFor} noValidate>
            <div className="field">
              <label htmlFor="reset-account">Account</label>
              <select id="reset-account" className="select" value={resetId}
                onChange={(event) => setResetId(event.target.value)}>
                <option value="">Choose an account</option>
                {(users ?? []).map((account) => (
                  <option key={account.id} value={account.id}>{account.name} ({account.email})</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="reset-password">New password</label>
              <input id="reset-password" className="input" type="password" autoComplete="new-password" maxLength={200}
                value={resetPassword} onChange={(event) => setResetPassword(event.target.value)} />
            </div>
            {resetError && <div className="notice notice-bad" role="alert">{resetError}</div>}
            <div className="form-actions">
              <Button variant="secondary" type="submit">Reset password</Button>
            </div>
          </form>
        </section>
      </div>

      <section className="card card-flush" aria-labelledby="audit-title">
        <div className="card-head">
          <div>
            <h3 id="audit-title">Recent activity</h3>
            <p>Sign-ins, campaign actions, draft decisions and account changes, newest first. Message text and passwords are never recorded.</p>
          </div>
        </div>
        {entries.length === 0 ? (
          <EmptyState icon="search" title="No activity yet">Actions will appear here as people use the app.</EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">When (UTC)</th>
                  <th scope="col">Who</th>
                  <th scope="col">Action</th>
                  <th scope="col">Record</th>
                  <th scope="col">Detail</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <tr key={entry.id}>
                    <td className="muted small">{entry.created_at}</td>
                    <td>{entry.actor_name ?? (entry.actor_user_id ? `User #${entry.actor_user_id}` : 'System or signed out')}</td>
                    <td><code>{entry.action}</code></td>
                    <td className="small">{entry.target_type ? `${entry.target_type} ${entry.target_id ?? ''}`.trim() : '—'}</td>
                    <td className="small detail-cell">{entry.detail ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  )
}
