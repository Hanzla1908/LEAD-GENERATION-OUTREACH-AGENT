import { Badge } from './ui'

export const DELIVERY_LABEL = {
  delivered: 'Delivered',
  deferred: 'Deferred (retrying)',
  bounced_soft: 'Soft bounce',
  bounced_hard: 'Bounced',
  rejected: 'Rejected by provider',
}

const DELIVERY_TONE = {
  delivered: 'ok',
  deferred: 'warn',
  bounced_soft: 'warn',
  bounced_hard: 'bad',
  rejected: 'bad',
}

// A recipient with no confirmed event is shown as "No confirmation yet". It is never shown as delivered.
export function DeliveryBadge({ status, replied }) {
  return (
    <span className="lead-badge">
      {status ? (
        <Badge tone={DELIVERY_TONE[status] ?? 'neutral'}>{DELIVERY_LABEL[status] ?? status}</Badge>
      ) : (
        <Badge tone="neutral" title="No delivery event has been confirmed yet. This is not the same as delivered.">
          No confirmation yet
        </Badge>
      )}
      {replied && <Badge tone="info">Replied</Badge>}
    </span>
  )
}

const TILES = [
  { key: 'delivered', label: 'Delivered (confirmed)' },
  { key: 'deferred', label: 'Deferred' },
  { key: 'bounced_soft', label: 'Soft bounces' },
  { key: 'bounced_hard', label: 'Hard bounces' },
  { key: 'rejected', label: 'Rejected' },
  { key: 'replied', label: 'Replied' },
  { key: 'unconfirmed', label: 'No confirmation yet' },
]

export function DeliveryPanel({ delivery }) {
  if (!delivery) return null
  return (
    <section className="card" aria-label="Delivery statistics">
      <div className="card-body stack">
        <h3>Delivery</h3>
        <p className="muted small">
          Counts come only from confirmed events: provider webhooks and bounce messages in the sending mailbox.
          &ldquo;No confirmation yet&rdquo; means no event has arrived. It does not mean the email was delivered.
        </p>
        <div className="stat-grid">
          {TILES.map((tile) => (
            <div className="stat" key={tile.key}>
              <span className="metric-label">{tile.label}</span>
              <span className="metric-value">{delivery[tile.key] ?? 0}</span>
            </div>
          ))}
        </div>
        <p className="small muted">Out of {delivery.sent} sent.</p>
      </div>
    </section>
  )
}
