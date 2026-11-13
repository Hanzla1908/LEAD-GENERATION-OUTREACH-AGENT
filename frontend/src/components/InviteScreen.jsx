import { useEffect, useRef, useState } from 'react'
import * as api from '../services/api'
import { Icon } from './ui'

const PAGE = {
  minHeight: '100vh',
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
  justifyContent: 'center',
  gap: 12,
  padding: 16,
  background: 'var(--surface-2)',
}

const ROLE_TEXT = { admin: 'Admin', operator: 'Operator', viewer: 'Viewer' }
const NAME_PASSWORD_MIN = 12

// Opens an invitation link. A new person creates their account here. A person who already has an account
// signs in, and the invitation is then accepted for that account.
export default function InviteScreen({ token, onAccepted }) {
  const acceptedRef = useRef(onAccepted)
  acceptedRef.current = onAccepted
  const [preview, setPreview] = useState(null)
  const [loadError, setLoadError] = useState('')
  const [needsSignIn, setNeedsSignIn] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')
  const [loginPassword, setLoginPassword] = useState('')

  useEffect(() => {
    let active = true
    api.previewInvitation(token)
      .then((info) => {
        if (!active) return
        setPreview(info)
        if (info.account_exists) {
          // A session for that account may already exist; accepting tells us whether a sign-in is needed.
          api.acceptInvitation(token)
            .then(() => active && acceptedRef.current())
            .catch(() => active && setNeedsSignIn(true))
        }
      })
      .catch((err) => active && setLoadError(err.message || 'This invitation link is not valid.'))
    return () => {
      active = false
    }
  }, [token])

  async function createAccount(event) {
    event.preventDefault()
    setError('')
    if (password.length < NAME_PASSWORD_MIN) {
      setError(`Use at least ${NAME_PASSWORD_MIN} characters.`)
      return
    }
    if (password !== repeat) {
      setError('The password and its repeat do not match.')
      return
    }
    setBusy(true)
    try {
      await api.acceptInvitation(token, name.trim(), password)
      onAccepted()
    } catch (err) {
      setError(err.message || 'The invitation could not be accepted.')
    } finally {
      setBusy(false)
    }
  }

  async function signInAndAccept(event) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      await api.login(preview.email, loginPassword)
      await api.acceptInvitation(token)
      onAccepted()
    } catch (err) {
      setError(err.message || 'The invitation could not be accepted.')
    } finally {
      setBusy(false)
    }
  }

  if (loadError) {
    return (
      <main style={PAGE}>
        <div className="card" style={{ width: '100%', maxWidth: 380 }}>
          <div className="card-body">
            <div className="notice notice-bad" role="alert">
              <Icon name="alert" size={16} />
              <div>{loadError}</div>
            </div>
          </div>
        </div>
      </main>
    )
  }

  if (!preview) {
    return <main style={PAGE}><p className="muted">Checking your invitation…</p></main>
  }

  const heading = (
    <div>
      <div className="brand-mark" aria-hidden="true">R</div>
      <h1 style={{ fontSize: 20, marginTop: 12 }}>Join {preview.workspace_name}</h1>
      <p className="muted" style={{ marginTop: 4 }}>
        You are invited as {ROLE_TEXT[preview.role] ?? preview.role} for {preview.email}.
      </p>
    </div>
  )

  if (preview.account_exists) {
    return (
      <main style={PAGE}>
        <form className="card" onSubmit={signInAndAccept} style={{ width: '100%', maxWidth: 380 }} aria-labelledby="invite-title">
          <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div id="invite-title">{heading}</div>
            <p className="small muted">Sign in with the account for {preview.email} to accept.</p>
            <div className="field">
              <label htmlFor="invite-login-password">Password</label>
              <input id="invite-login-password" className="input" type="password" autoComplete="current-password"
                value={loginPassword} onChange={(event) => setLoginPassword(event.target.value)} />
            </div>
            {needsSignIn && error && <div className="notice notice-bad" role="alert">{error}</div>}
            <div className="form-actions">
              <button type="submit" className="btn btn-primary" disabled={busy || !loginPassword}>
                {busy ? 'Working…' : 'Sign in and accept'}
              </button>
            </div>
          </div>
        </form>
      </main>
    )
  }

  return (
    <main style={PAGE}>
      <form className="card" onSubmit={createAccount} noValidate style={{ width: '100%', maxWidth: 380 }} aria-labelledby="invite-title">
        <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div id="invite-title">{heading}</div>
          <div className="field">
            <label htmlFor="invite-name">Full name</label>
            <input id="invite-name" className="input" maxLength={120} value={name} onChange={(event) => setName(event.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="invite-password">Choose a password</label>
            <input id="invite-password" className="input" type="password" autoComplete="new-password" maxLength={200}
              value={password} onChange={(event) => setPassword(event.target.value)} />
            <span className="field-hint">At least {NAME_PASSWORD_MIN} characters.</span>
          </div>
          <div className="field">
            <label htmlFor="invite-repeat">Repeat password</label>
            <input id="invite-repeat" className="input" type="password" autoComplete="new-password" maxLength={200}
              value={repeat} onChange={(event) => setRepeat(event.target.value)} />
          </div>
          {error && <div className="notice notice-bad" role="alert">{error}</div>}
          <div className="form-actions">
            <button type="submit" className="btn btn-primary" disabled={busy || !name.trim() || !password || !repeat}>
              {busy ? 'Creating…' : 'Create account and join'}
            </button>
          </div>
        </div>
      </form>
    </main>
  )
}
