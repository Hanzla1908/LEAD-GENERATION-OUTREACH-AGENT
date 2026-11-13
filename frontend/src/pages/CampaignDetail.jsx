import { useCallback, useEffect, useState } from 'react'
import { Badge, Button, ConfirmDialog, DraftBadge, EmptyState, Icon, Modal, Skeleton, useToast } from '../components/ui'
import { CONFIRMS, DraftEditor } from './OutreachDrafts'
import * as api from '../services/api'
import { timeAgo } from '../lib/format'
import { DeliveryBadge, DeliveryPanel } from '../components/DeliveryPanel'

const CAMPAIGN_STATUS = {
  generating: ['info', 'Generating drafts'],
  review: ['neutral', 'Ready for review'],
  sending: ['info', 'Sending'],
  paused: ['warn', 'Paused'],
  completed: ['ok', 'Completed'],
  cancelled: ['neutral', 'Cancelled'],
}

const SEND_STATUS = {
  queued: ['info', 'Queued'],
  sending: ['info', 'Sending'],
  sent: ['ok', 'Sent'],
  failed: ['bad', 'Failed'],
  interrupted: ['bad', 'Needs review'],
  skipped: ['neutral', 'Skipped'],
  cancelled: ['neutral', 'Cancelled'],
}

const LOG_EVENT = {
  approved: ['info', 'Approved'],
  send_started: ['info', 'Send started'],
  queued: ['info', 'Queued'],
  sending: ['info', 'Sending'],
  sent: ['ok', 'Sent'],
  failed: ['bad', 'Failed'],
  interrupted: ['bad', 'Needs review'],
  skipped: ['neutral', 'Skipped'],
  paused: ['warn', 'Paused'],
  cancelled: ['neutral', 'Cancelled'],
  completed: ['ok', 'Completed'],
}

const STAT_TILES = [
  { key: 'total_selected', label: 'Total selected' },
  { key: 'eligible', label: 'Eligible recipients' },
  { key: 'drafts_generated', label: 'Drafts generated' },
  { key: 'approved', label: 'Approved emails' },
  { key: 'sent', label: 'Successfully sent' },
  { key: 'failed', label: 'Failed emails' },
  { key: 'skipped', label: 'Skipped recipients' },
]

function recipientRestaurant(r) {
  return {
    name: r.restaurant_name ?? `Business #${r.restaurant_id}`,
    address: r.restaurant_address,
    website: r.restaurant_website,
    contact_email: r.recipient_email || r.restaurant_email,
    contact_email_status: r.restaurant_email_status,
    opted_out: r.restaurant_opted_out,
  }
}

function Progress({ detail }) {
  const c = detail.counts
  if (detail.status === 'generating') {
    const done = c.drafts_generated + c.drafts_failed
    const total = c.eligible
    return <ProgressBar label={`Writing drafts: ${done} of ${total} done${c.drafts_failed ? `, ${c.drafts_failed} failed` : ''}`} done={done} total={total} />
  }
  if (detail.status === 'sending' || detail.status === 'paused') {
    const done = c.sent + c.failed
    const total = done + c.queued
    return <ProgressBar label={`Sent ${c.sent}, failed ${c.failed}, waiting ${c.queued}`} done={done} total={total} />
  }
  return null
}

function ProgressBar({ label, done, total }) {
  const percent = total > 0 ? Math.round((done / total) * 100) : 0
  return (
    <div className="progress">
      <div className="progress-label">{label}</div>
      <div className="bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-label={label}>
        <span style={{ width: `${percent}%` }} />
      </div>
    </div>
  )
}

export default function CampaignDetail({ campaignId, onNavigate }) {
  const toast = useToast()
  const [detail, setDetail] = useState(null)
  const [logs, setLogs] = useState([])
  const [loadError, setLoadError] = useState('')
  const [config, setConfig] = useState(null)
  const [busy, setBusy] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [draftBusy, setDraftBusy] = useState(false)
  const [pendingDraftAction, setPendingDraftAction] = useState(null)
  const [sendOpen, setSendOpen] = useState(false)
  const [sendAcknowledged, setSendAcknowledged] = useState(false)
  const [cancelOpen, setCancelOpen] = useState(false)

  const refresh = useCallback(async () => {
    try {
      setDetail(await api.getCampaign(campaignId))
      setLoadError('')
    } catch (err) {
      setLoadError(err.message)
    }
    api.getCampaignLogs(campaignId).then(setLogs).catch(() => {})
  }, [campaignId])

  useEffect(() => {
    refresh()
    api.getCampaignConfig().then(setConfig).catch(() => setConfig(null))
  }, [refresh])

  useEffect(() => {
    if (!detail || !['generating', 'sending'].includes(detail.status)) return undefined
    const timer = setTimeout(refresh, 2000)
    return () => clearTimeout(timer)
  }, [detail, refresh])

  async function run(fn, message) {
    setBusy(true)
    try {
      const updated = await fn()
      if (updated && updated.recipients) setDetail(updated)
      else await refresh()
      if (message) toast(message)
      api.getCampaignConfig().then(setConfig).catch(() => {})
      return true
    } catch (err) {
      toast(err.message || 'The action failed.', 'error')
      return false
    } finally {
      setBusy(false)
    }
  }

  if (loadError) {
    return (
      <div className="notice notice-bad" role="alert">
        <Icon name="alert" size={16} />
        <div>{loadError}</div>
      </div>
    )
  }
  if (!detail) {
    return (
      <div className="stack">
        <Skeleton height={28} width="40%" />
        <Skeleton height={120} />
        <Skeleton height={240} />
      </div>
    )
  }

  const [statusTone, statusLabel] = CAMPAIGN_STATUS[detail.status] ?? ['neutral', detail.status]
  const c = detail.counts
  const readyToSend = detail.recipients.filter((r) => r.status === 'draft' && r.draft_status === 'approved')
  const canSend = ['review', 'paused', 'completed'].includes(detail.status) && readyToSend.length > 0
  const canRetry = c.retryable > 0 && !['sending', 'generating'].includes(detail.status)
  const canRetryDrafts = c.drafts_failed > 0 && ['review', 'completed'].includes(detail.status)
  const canCancel = ['generating', 'review', 'sending', 'paused'].includes(detail.status)
  const editing = detail.recipients.find((r) => r.id === editingId) ?? null
  const editingDraft = editing && editing.draft_id ? {
    id: editing.draft_id,
    subject: editing.subject,
    body: editing.body,
    status: editing.draft_status,
    angle: editing.angle,
    campaign: detail.name,
  } : null
  const pendingRecipient = pendingDraftAction
    ? detail.recipients.find((r) => r.id === pendingDraftAction.recipientId)
    : null

  async function handleDraftAction(action) {
    const draftId = pendingDraftAction.draftId
    setDraftBusy(true)
    try {
      if (action === 'approve') await api.approveDraft(draftId)
      if (action === 'reject') await api.rejectDraft(draftId)
      if (action === 'regenerate') await api.regenerateDraft(draftId)
      toast({ approve: 'Draft approved.', reject: 'Draft rejected.', regenerate: 'New draft generated.' }[action])
      setPendingDraftAction(null)
      await refresh()
    } catch (err) {
      toast(err.message, 'error')
    } finally {
      setDraftBusy(false)
    }
  }

  return (
    <>
      <div className="page-header">
        <div>
          <Button variant="ghost" size="sm" icon="arrow" className="back-link" onClick={() => onNavigate('campaigns')}>
            All campaigns
          </Button>
          <h2 className="campaign-title">{detail.name}</h2>
          <p>
            <Badge tone={statusTone}>{statusLabel}</Badge>
            {detail.status_note && <span className="muted small status-note"> {detail.status_note}</span>}
          </p>
        </div>
        <div className="page-actions">
          {detail.live_sending
            ? <Badge tone="warn">Live sending through SMTP</Badge>
            : <Badge tone="info">Mock provider · no email leaves this app</Badge>}
        </div>
      </div>

      <div className="stat-grid">
        {STAT_TILES.map((tile) => (
          <div className="stat" key={tile.key}>
            <span className="metric-label">{tile.label}</span>
            <span className="metric-value">{c[tile.key]}</span>
          </div>
        ))}
      </div>

      <DeliveryPanel delivery={detail.delivery} />

      <section className="card" aria-label="Campaign controls">
        <div className="card-body stack">
          <Progress detail={detail} />
          <div className="campaign-actions">
            <Button
              variant="primary"
              icon="mail"
              disabled={!canSend || busy}
              onClick={() => { setSendAcknowledged(false); setSendOpen(true) }}
            >
              Send Approved to Selected ({readyToSend.length})
            </Button>
            {detail.status === 'sending' && (
              <Button variant="secondary" disabled={busy} onClick={() => run(() => api.pauseCampaign(detail.id), 'Sending paused.')}>
                Pause
              </Button>
            )}
            {detail.status === 'paused' && (
              <Button variant="secondary" disabled={busy || readyToSend.length === 0 && c.queued === 0}
                onClick={() => run(() => api.resumeCampaign(detail.id), 'Sending resumed.')}>
                Resume
              </Button>
            )}
            {canRetryDrafts && (
              <Button variant="secondary" icon="refresh" disabled={busy}
                onClick={() => run(() => api.retryFailedDrafts(detail.id), 'Retrying failed drafts.')}>
                Retry {c.drafts_failed} failed draft{c.drafts_failed === 1 ? '' : 's'}
              </Button>
            )}
            {canRetry && (
              <Button variant="secondary" icon="refresh" disabled={busy}
                onClick={() => run(() => api.retryFailedSends(detail.id), 'Retrying failed emails.')}>
                Retry {c.retryable} failed email{c.retryable === 1 ? '' : 's'}
              </Button>
            )}
            {canCancel && (
              <Button variant="ghost" className="is-danger" icon="ban" disabled={busy} onClick={() => setCancelOpen(true)}>
                Cancel campaign
              </Button>
            )}
          </div>
          {config && !config.unsubscribe_ready && (
            <div className="notice notice-warn" role="alert">
              <Icon name="alert" size={16} />
              <div>Sending is blocked until UNSUBSCRIBE_SECRET and PUBLIC_BASE_URL are set in .env. Every email needs a working unsubscribe link.</div>
            </div>
          )}
          {config && (
            <p className="small muted">
              Limits: {config.per_minute} emails per minute, {config.daily_limit} per day. Sent today: {config.sent_today}.
            </p>
          )}
        </div>
      </section>

      <section className="card card-flush" aria-label="Recipients">
        <div className="card-head">
          <div>
            <h3>Recipients</h3>
            <p>Each business gets its own message. Skipped and failed rows explain why.</p>
          </div>
        </div>
        {detail.recipients.length === 0 ? (
          <EmptyState icon="mail" title="No recipients">This campaign has no selected businesses.</EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Business</th>
                  <th scope="col">Recipient email</th>
                  <th scope="col">Draft</th>
                  <th scope="col">Send status</th>
                  <th scope="col">Details</th>
                  <th scope="col">Updated</th>
                  <th scope="col"><span className="sr-only">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {detail.recipients.map((r) => {
                  const send = SEND_STATUS[r.status]
                  return (
                    <tr key={r.id}>
                      <td>
                        <div className="cell-title" title={r.restaurant_name}>{r.restaurant_name ?? `Business #${r.restaurant_id}`}</div>
                        <div className="cell-sub" title={r.restaurant_address}>{r.restaurant_address}</div>
                      </td>
                      <td>{r.recipient_email || <span className="muted">None</span>}</td>
                      <td>
                        {r.status === 'draft_failed' ? <Badge tone="bad">Failed to write</Badge>
                          : r.status === 'skipped' && !r.draft_id ? <Badge tone="neutral">—</Badge>
                          : r.draft_status ? <DraftBadge status={r.draft_status} />
                          : <Badge tone="info">Writing…</Badge>}
                      </td>
                      <td>
                        {send ? <Badge tone={send[0]}>{send[1]}</Badge> : <span className="muted small">Not sent</span>}
                        {r.status === 'sent' && <DeliveryBadge status={r.delivery_status} replied={Boolean(r.replied_at)} />}
                      </td>
                      <td className="small detail-cell">
                        {r.error_reason && <span className="error-text">{r.error_reason}</span>}
                        {r.skip_reason && <span className="muted">{r.skip_reason}</span>}
                        {r.status === 'sent' && r.provider_message_id && <span className="muted">Message {r.provider_message_id}</span>}
                      </td>
                      <td className="muted small">{timeAgo(r.updated_at)}</td>
                      <td>
                        {r.draft_id && r.status !== 'sent' && r.status !== 'skipped' && (
                          <Button size="sm" variant="secondary" readOnlyOk onClick={() => setEditingId(r.id)}>
                            {r.draft_status === 'draft' ? 'Review draft' : 'View draft'}
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

      <section className="card card-flush" aria-label="Sending log">
        <div className="card-head">
          <div>
            <h3>Sending log</h3>
            <p>Every approval, send attempt, and status change, oldest first.</p>
          </div>
        </div>
        {logs.length === 0 ? (
          <EmptyState icon="mail" title="No activity yet">Approved sends and their results will appear here.</EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Time (UTC)</th>
                  <th scope="col">Event</th>
                  <th scope="col">Recipient</th>
                  <th scope="col">Detail</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((entry) => {
                  const [tone, label] = LOG_EVENT[entry.event] ?? ['neutral', entry.event]
                  return (
                    <tr key={entry.id}>
                      <td className="muted small">{entry.created_at}</td>
                      <td><Badge tone={tone}>{label}</Badge></td>
                      <td>{entry.recipient_email || <span className="muted">—</span>}</td>
                      <td className="small detail-cell">{entry.detail}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <Modal
        open={Boolean(editingDraft)}
        title={editing ? `Draft for ${editing.restaurant_name ?? 'business'}` : 'Draft'}
        description="Edits apply to this business only. Approval records your decision; sending happens separately."
        onClose={() => setEditingId(null)}
        size="lg"
      >
        {editingDraft && (
          <DraftEditor
            key={editingDraft.id}
            draft={editingDraft}
            restaurant={recipientRestaurant(editing)}
            busy={draftBusy}
            onSave={async (subject, body) => {
              setDraftBusy(true)
              try {
                await api.updateDraft(editingDraft.id, subject, body)
                toast('Draft saved.')
                await refresh()
              } catch (err) {
                toast(err.message, 'error')
              } finally {
                setDraftBusy(false)
              }
            }}
            onAction={(action) => setPendingDraftAction({ action, draftId: editingDraft.id, recipientId: editing.id })}
          />
        )}
      </Modal>

      {pendingDraftAction && pendingRecipient && (
        <ConfirmDialog
          open
          title={CONFIRMS[pendingDraftAction.action].title}
          description={CONFIRMS[pendingDraftAction.action].description}
          confirmLabel={CONFIRMS[pendingDraftAction.action].confirmLabel}
          tone={CONFIRMS[pendingDraftAction.action].tone}
          busy={draftBusy}
          onCancel={() => setPendingDraftAction(null)}
          onConfirm={() => handleDraftAction(pendingDraftAction.action)}
        />
      )}

      <Modal
        open={sendOpen}
        title={`Send ${readyToSend.length} approved email${readyToSend.length === 1 ? '' : 's'}?`}
        description="Each business receives its own individual message. No email is copied or blind-copied to anyone else."
        onClose={() => setSendOpen(false)}
        size="lg"
        footer={(
          <>
            <Button variant="secondary" readOnlyOk onClick={() => setSendOpen(false)} disabled={busy}>Back</Button>
            <Button
              variant="primary"
              icon="mail"
              disabled={!sendAcknowledged || busy}
              onClick={async () => {
                const ok = await run(async () => {
                  await api.approveSending(detail.id, readyToSend.map((r) => r.draft_id))
                  return api.sendCampaign(detail.id)
                }, 'Send approved. Emails are being sent in the background.')
                if (ok) setSendOpen(false)
              }}
            >
              {busy ? 'Starting…' : `Send ${readyToSend.length} email${readyToSend.length === 1 ? '' : 's'}`}
            </Button>
          </>
        )}
      >
        <div className="stack">
          <div className="notice notice-info" role="note">
            <Icon name="alert" size={16} />
            <div>
              {detail.live_sending
                ? 'Live sending is enabled. These emails will be delivered through your SMTP provider.'
                : 'Mock provider: messages are recorded in the app only. Nothing is delivered to these addresses.'}
              {config && ` Limits: ${config.per_minute} per minute, ${config.daily_limit} per day.`}
            </div>
          </div>
          <ul className="plan-list send-list">
            {readyToSend.map((r) => (
              <li key={r.id}>
                <strong>{r.restaurant_name}</strong>
                <span className="muted"> · {r.recipient_email}</span>
                <div className="small muted">Subject: {r.subject}</div>
              </li>
            ))}
          </ul>
          <label className="ack">
            <input
              type="checkbox"
              className="checkbox"
              checked={sendAcknowledged}
              onChange={(event) => setSendAcknowledged(event.target.checked)}
            />
            <span>I have reviewed these recipients and drafts, and want to send them now.</span>
          </label>
        </div>
      </Modal>

      <ConfirmDialog
        open={cancelOpen}
        title="Cancel this campaign?"
        description="Queued emails will not be sent. Emails already delivered stay delivered, and drafts are kept for reference."
        confirmLabel="Cancel campaign"
        tone="danger"
        busy={busy}
        onCancel={() => setCancelOpen(false)}
        onConfirm={async () => {
          const ok = await run(() => api.cancelCampaign(detail.id), 'Campaign cancelled.')
          if (ok) setCancelOpen(false)
        }}
      />
    </>
  )
}
