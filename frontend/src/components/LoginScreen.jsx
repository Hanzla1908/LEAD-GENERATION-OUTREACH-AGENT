import { useEffect, useState } from 'react'
import * as api from '../services/api'
import { Icon } from './ui'
import { AuthShell, PasswordField, keepFocus } from './AuthShared'
import { BrandMark } from './Brand'

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

const SETUP_PASSWORD_MIN = 12
export const RESET_UNAVAILABLE = 'Password reset is not available yet. Ask an administrator to reset your password.'

// The password is sent over the connection once and is never stored in the page or in browser storage.
// Public sign-up creates a separate workspace for each person. Existing accounts are unchanged.
export default function LoginScreen({ onSignedIn, notice }) {
  const [mode, setMode] = useState('signin')
  const [needsSetup, setNeedsSetup] = useState(false)

  useEffect(() => {
    api.getSetupStatus()
      .then((status) => setNeedsSetup(Boolean(status.needs_setup)))
      .catch(() => setNeedsSetup(false))
  }, [])

  if (mode === 'setup') {
    return (
      <main style={PAGE}>
        <FirstAdminForm onBack={() => setMode('signin')} onSignedIn={onSignedIn} />
      </main>
    )
  }

  return (
    <AuthShell
      footer={<p className="auth-switch">Don&apos;t have an account? <a href="#signup" onMouseDown={keepFocus}>Create Account</a></p>}
    >
      <SignInForm onSignedIn={onSignedIn} notice={notice}>
        {needsSetup && (
          <div className="notice notice-info" role="note">
            <div>
              No account exists yet.{' '}
              <button type="button" className="btn btn-primary btn-sm" onClick={() => setMode('setup')}>
                Create the first admin account
              </button>
            </div>
          </div>
        )}
      </SignInForm>
    </AuthShell>
  )
}

function SignInForm({ onSignedIn, notice, children }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [info, setInfo] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event) {
    event.preventDefault()
    if (!email.trim() || !password || busy) return
    setBusy(true)
    setError('')
    setInfo('')
    try {
      await api.login(email.trim(), password)
      setPassword('')
      onSignedIn()
    } catch (err) {
      setError(err.message || 'Sign-in failed. Check your email and password and try again.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="auth-form" onSubmit={submit} noValidate aria-labelledby="login-title">
      <div>
        <h1 id="login-title" className="auth-title">Sign in</h1>
        <p className="auth-subtitle">Enter the email and password for your account.</p>
      </div>
      {notice && (
        <div className="notice notice-ok" role="status">
          <Icon name="alert" size={16} />
          <div>{notice}</div>
        </div>
      )}
      <div className="field">
        <label htmlFor="login-email">Email</label>
        <input
          id="login-email"
          className="input"
          type="email"
          autoComplete="username"
          autoFocus
          maxLength={254}
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </div>
      <PasswordField
        id="login-password"
        label="Password"
        autoComplete="current-password"
        maxLength={200}
        value={password}
        onChange={setPassword}
      />
      <div className="auth-row">
        <button type="button" className="auth-link" onClick={() => { setError(''); setInfo(RESET_UNAVAILABLE) }}>
          Forgot Password?
        </button>
      </div>
      {info && (
        <div className="notice notice-info" role="note">
          <div>{info}</div>
        </div>
      )}
      {error && (
        <div className="notice notice-bad" role="alert">
          <Icon name="alert" size={16} />
          <div>{error}</div>
        </div>
      )}
      {children}
      <button type="submit" className="btn btn-primary btn-block" disabled={busy || !email.trim() || !password}>
        {busy ? 'Signing in…' : 'Sign in'}
      </button>
    </form>
  )
}

function FirstAdminForm({ onBack, onSignedIn }) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event) {
    event.preventDefault()
    setError('')
    if (password.length < SETUP_PASSWORD_MIN) {
      setError(`Use at least ${SETUP_PASSWORD_MIN} characters.`)
      return
    }
    if (password !== repeat) {
      setError('The password and its repeat do not match.')
      return
    }
    setBusy(true)
    try {
      await api.createFirstAdmin(name.trim(), email.trim(), password)
      setPassword('')
      setRepeat('')
      onSignedIn()
    } catch (err) {
      setError(err.message || 'The account could not be created.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card" onSubmit={submit} noValidate style={{ width: '100%', maxWidth: 380 }} aria-labelledby="setup-title">
      <div className="card-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div>
          <BrandMark size={34} />
          <h1 id="setup-title" style={{ fontSize: 20, marginTop: 12 }}>Create the first admin account</h1>
          <p className="muted" style={{ marginTop: 4 }}>
            This account manages everyone else&apos;s access. It is available only until the first account exists.
          </p>
        </div>
        <div className="field">
          <label htmlFor="setup-name">Full name</label>
          <input id="setup-name" className="input" maxLength={120} value={name}
            onChange={(event) => setName(event.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="setup-email">Email</label>
          <input id="setup-email" className="input" type="email" autoComplete="username" maxLength={254} value={email}
            onChange={(event) => setEmail(event.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="setup-password">Password</label>
          <input id="setup-password" className="input" type="password" autoComplete="new-password" maxLength={200}
            aria-describedby="setup-password-help" value={password} onChange={(event) => setPassword(event.target.value)} />
          <span className="field-hint" id="setup-password-help">At least {SETUP_PASSWORD_MIN} characters.</span>
        </div>
        <div className="field">
          <label htmlFor="setup-repeat">Repeat password</label>
          <input id="setup-repeat" className="input" type="password" autoComplete="new-password" maxLength={200} value={repeat}
            onChange={(event) => setRepeat(event.target.value)} />
        </div>
        {error && (
          <div className="notice notice-bad" role="alert">
            <Icon name="alert" size={16} />
            <div>{error}</div>
          </div>
        )}
        <div className="form-actions" style={{ justifyContent: 'space-between' }}>
          <button type="button" className="btn btn-secondary" onClick={onBack} disabled={busy}>Back to sign in</button>
          <button type="submit" className="btn btn-primary" disabled={busy || !name.trim() || !email.trim() || !password || !repeat}>
            {busy ? 'Creating…' : 'Create admin account'}
          </button>
        </div>
      </div>
    </form>
  )
}

export function SessionStatus({ children, onRetry }) {
  return (
    <main style={PAGE}>
      {children}
      {onRetry && (
        <button type="button" className="btn btn-secondary" onClick={onRetry}>Retry</button>
      )}
    </main>
  )
}
