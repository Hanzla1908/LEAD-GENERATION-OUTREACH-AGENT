import { useEffect, useState } from 'react'
import * as api from '../services/api'
import { Icon } from './ui'
import { AuthShell, PasswordField, keepFocus } from './AuthShared'

export const REGISTERED_MESSAGE = 'Account created successfully. Please sign in.'
export const SIGN_UP_PASSWORD_LENGTH = 8
const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

// Mirrors the backend rule (services/passwords.py: registration_password_problem). Every field is checked here too.
export function validateSignUp({ name, email, password, confirm }) {
  const errors = {}
  if (name.trim().length < 2) errors.name = 'Enter your full name (at least 2 characters).'
  if (!EMAIL_PATTERN.test(email.trim())) errors.email = 'Enter a valid email address.'
  if (password.length !== SIGN_UP_PASSWORD_LENGTH) {
    errors.password = `Password must be exactly ${SIGN_UP_PASSWORD_LENGTH} characters.`
  } else if (!/^[A-Za-z0-9]+$/.test(password)) {
    errors.password = 'Use letters and numbers only (A to Z and 0 to 9).'
  }
  if (confirm !== password) errors.confirm = 'The passwords do not match.'
  return errors
}

export default function SignUpScreen({ onRegistered }) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [touched, setTouched] = useState({})
  const [attempted, setAttempted] = useState(false)
  const [serverEmailError, setServerEmailError] = useState('')
  const [serverError, setServerError] = useState('')
  const [busy, setBusy] = useState(false)
  const [needsSetup, setNeedsSetup] = useState(false)

  useEffect(() => {
    api.getSetupStatus()
      .then((status) => setNeedsSetup(Boolean(status.needs_setup)))
      .catch(() => setNeedsSetup(false))
  }, [])

  const errors = validateSignUp({ name, email, password, confirm })
  // A field's message appears once the field has been left, or after the first submit attempt.
  // A duplicate email reported by the server takes the place of the client message for that field.
  function shown(field) {
    if (!(attempted || touched[field])) return undefined
    if (field === 'email' && serverEmailError) return serverEmailError
    return errors[field]
  }
  // Leaving an empty field does not show an error. That error would appear while the person is moving to another
  // link or button, and the layout shift would swallow the click. Empty fields are checked on submit instead.
  const touch = (field, value) => () => {
    if (!value) return
    setTouched((current) => ({ ...current, [field]: true }))
  }

  async function submit(event) {
    event.preventDefault()
    setAttempted(true)
    setServerEmailError('')
    setServerError('')
    if (Object.keys(errors).length > 0 || busy) return
    setBusy(true)
    try {
      const result = await api.register(name.trim(), email.trim(), password)
      setPassword('')
      setConfirm('')
      onRegistered(result.message || REGISTERED_MESSAGE)
    } catch (err) {
      if (err.status === 409) {
        setServerEmailError(err.message)
      } else {
        setServerError(err.message || 'The account could not be created. Try again.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell
      footer={<p className="auth-switch">Already have an account? <a href="#signin" onMouseDown={keepFocus}>Sign In</a></p>}
    >
      <form className="auth-form" onSubmit={submit} noValidate aria-labelledby="signup-title">
        <div>
          <h1 id="signup-title" className="auth-title">Create your account</h1>
          <p className="auth-subtitle">Your account gets its own workspace, and you manage it as its admin.</p>
        </div>

        {needsSetup && (
          <div className="notice notice-info" role="note">
            <Icon name="alert" size={16} />
            <div>
              No account exists yet. <a href="#signin">Go to sign in</a> to create the first admin account.
            </div>
          </div>
        )}

        <div className="field">
          <label htmlFor="signup-name">Full name</label>
          <input
            id="signup-name"
            className="input"
            autoComplete="name"
            autoFocus
            maxLength={120}
            required
            value={name}
            aria-invalid={shown('name') ? true : undefined}
            aria-describedby={shown('name') ? 'signup-name-error' : undefined}
            onChange={(event) => setName(event.target.value)}
            onBlur={touch('name', name)}
          />
          {shown('name') && <span className="field-error" id="signup-name-error" role="alert">{shown('name')}</span>}
        </div>

        <div className="field">
          <label htmlFor="signup-email">Email</label>
          <input
            id="signup-email"
            className="input"
            type="email"
            autoComplete="email"
            maxLength={254}
            required
            value={email}
            aria-invalid={shown('email') ? true : undefined}
            aria-describedby={shown('email') ? 'signup-email-error' : undefined}
            onChange={(event) => { setEmail(event.target.value); setServerEmailError('') }}
            onBlur={touch('email', email)}
          />
          {shown('email') && <span className="field-error" id="signup-email-error" role="alert">{shown('email')}</span>}
        </div>

        <PasswordField
          id="signup-password"
          label="Password"
          autoComplete="new-password"
          maxLength={SIGN_UP_PASSWORD_LENGTH}
          hint={`${SIGN_UP_PASSWORD_LENGTH} letters and numbers only.`}
          value={password}
          error={shown('password')}
          onChange={setPassword}
          onBlur={touch('password', password)}
        />

        <PasswordField
          id="signup-confirm"
          label="Confirm Password"
          autoComplete="new-password"
          maxLength={SIGN_UP_PASSWORD_LENGTH}
          value={confirm}
          error={shown('confirm')}
          onChange={setConfirm}
          onBlur={touch('confirm', confirm)}
        />

        {serverError && (
          <div className="notice notice-bad" role="alert">
            <Icon name="alert" size={16} />
            <div>{serverError}</div>
          </div>
        )}

        <button type="submit" className="btn btn-primary btn-block" disabled={busy}>
          {busy ? 'Creating account…' : 'Create Account'}
        </button>
      </form>
    </AuthShell>
  )
}
