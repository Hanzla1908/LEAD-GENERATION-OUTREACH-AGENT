import { useCallback, useEffect, useState } from 'react'
import { Badge, Button } from './ui'
import { getMailboxStatus, getReviewQueue, resolveConversation, syncMailbox } from '../services/api'

// Uncertain replies and unmatched messages wait here for a person. Nothing is ever answered automatically.
export default function ReplyInbox() {
  const [items, setItems] = useState(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  // null until known. false means the mailbox settings are missing: that is a setup step, not an error.
  const [configured, setConfigured] = useState(null)

  const load = useCallback(async () => {
    try {
      setItems(await getReviewQueue())
      setError('')
    } catch (err) {
      setError(err.message || 'Could not load the reply inbox.')
    }
  }, [])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    getMailboxStatus()
      .then((status) => setConfigured(Boolean(status.configured)))
      .catch(() => setConfigured(null))
  }, [])

  async function checkMailbox() {
    setBusy(true)
    setNotice('')
    try {
      const result = await syncMailbox()
      setNotice(`Read ${result.read} message(s): ${result.matched} linked repl${result.matched === 1 ? 'y' : 'ies'}, `
        + `${result.needs_review} to review, ${result.unmatched} unmatched, ${result.event} delivery event(s).`)
      await load()
    } catch (err) {
      setError(err.message || 'The mailbox could not be checked.')
    } finally {
      setBusy(false)
    }
  }

  async function decide(item, decision) {
    setBusy(true)
    try {
      await resolveConversation(item.id, decision)
      await load()
    } catch (err) {
      setError(err.message || 'That decision could not be saved.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card" aria-label="Reply inbox">
      <div className="card-body stack">
        <div className="card-head">
          <div>
            <h3>Replies to review</h3>
            <p>Uncertain matches and messages nothing matched. Replies are never answered automatically.</p>
          </div>
          <Button variant="secondary" size="sm" icon="refresh" disabled={busy || configured === false} onClick={checkMailbox}>
            {busy ? 'Checking…' : 'Check mailbox now'}
          </Button>
        </div>
        {configured === false && (
          <div className="notice notice-info" role="note">
            <div>
              <strong>Reply monitoring is not connected yet.</strong> Replies will appear here once a mailbox is connected.
              To connect it, add <code>MAILBOX_IMAP_HOST</code>, <code>MAILBOX_USERNAME</code> and <code>MAILBOX_PASSWORD</code>
              {' '}to the project&apos;s <code>.env</code> file, then restart the backend.
            </div>
          </div>
        )}
        {notice && <p className="small muted" role="status">{notice}</p>}
        {error && <div className="notice notice-bad" role="alert">{error}</div>}
        {items && items.length === 0 && <p className="muted">Nothing is waiting for review.</p>}
        {items?.map((item) => (
          <div key={item.id} className="review-item">
            <div>
              <strong>{item.subject || '(no subject)'}</strong>
              <span className="muted small"> · {item.from_address || 'unknown sender'} · {item.received_at}</span>
              {item.match_status === 'unmatched' ? <Badge tone="neutral">Unmatched</Badge> : <Badge tone="warn">Uncertain</Badge>}
            </div>
            <div className="small muted">{item.match_reason}</div>
            <p className="reply-text">{item.body_text || '(no text content)'}</p>
            <div className="cell-actions">
              {item.match_status === 'needs_review' && item.recipient_id && (
                <Button size="sm" variant="primary" disabled={busy} onClick={() => decide(item, 'confirm')}>Confirm reply</Button>
              )}
              <Button size="sm" variant="ghost" disabled={busy} onClick={() => decide(item, 'dismiss')}>Dismiss</Button>
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
