import { useState } from 'react'
import { Button, useToast } from './ui'
import * as api from '../services/api'

const PASSWORD_MIN = 12

// Changing the password signs out every other session of this account. The current session stays signed in.
export default function ChangePassword() {
  const toast = useToast()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(event) {
    event.preventDefault()
    setError('')
    if (next.length < PASSWORD_MIN) {
      setError(`Use at least ${PASSWORD_MIN} characters.`)
      return
    }
    if (next !== confirm) {
      setError('The new password and its repeat do not match.')
      return
    }
    setBusy(true)
    try {
      await api.changePassword(current, next)
      toast('Password changed. Your other sessions were signed out.')
      setCurrent('')
      setNext('')
      setConfirm('')
    } catch (err) {
      setError(err.message || 'The password could not be changed.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate className="stack" aria-label="Change password">
      <div className="field">
        <label htmlFor="pw-current">Current password</label>
        <input id="pw-current" className="input" type="password" autoComplete="current-password" maxLength={200}
          value={current} onChange={(event) => setCurrent(event.target.value)} />
      </div>
      <div className="field">
        <label htmlFor="pw-new">New password</label>
        <input id="pw-new" className="input" type="password" autoComplete="new-password" maxLength={200}
          aria-describedby="pw-new-help" value={next} onChange={(event) => setNext(event.target.value)} />
        <span className="field-hint" id="pw-new-help">At least {PASSWORD_MIN} characters.</span>
      </div>
      <div className="field">
        <label htmlFor="pw-confirm">Repeat new password</label>
        <input id="pw-confirm" className="input" type="password" autoComplete="new-password" maxLength={200}
          value={confirm} onChange={(event) => setConfirm(event.target.value)} />
      </div>
      {error && <div className="notice notice-bad" role="alert">{error}</div>}
      <div className="form-actions">
        <Button variant="primary" type="submit" readOnlyOk disabled={busy || !current || !next || !confirm}>
          {busy ? 'Saving…' : 'Change password'}
        </Button>
      </div>
    </form>
  )
}
