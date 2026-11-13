import { useEffect, useMemo, useState } from 'react'
import { Badge, Button, EmptyState, Icon, Skeleton } from '../components/ui'
import { listCampaigns } from '../services/api'
import { timeAgo } from '../lib/format'
import ReplyInbox from '../components/ReplyInbox'

const STATUS_BADGE = {
  generating: ['info', 'Generating'],
  review: ['neutral', 'Ready for review'],
  sending: ['info', 'Sending'],
  paused: ['warn', 'Paused'],
  completed: ['ok', 'Completed'],
  cancelled: ['neutral', 'Cancelled'],
}

function groupLegacyDrafts(drafts) {
  const groups = new Map()
  for (const d of drafts) {
    const group = groups.get(d.campaign) ?? {
      name: d.campaign,
      total: 0,
      draft: 0,
      approved: 0,
      rejected: 0,
      restaurants: new Set(),
      last: d.updated_at,
    }
    group.total += 1
    group[d.status] = (group[d.status] ?? 0) + 1
    group.restaurants.add(d.restaurant_id)
    if (d.updated_at > group.last) group.last = d.updated_at
    groups.set(d.campaign, group)
  }
  return [...groups.values()].sort((a, b) => (b.last > a.last ? 1 : -1))
}

export default function Campaigns({ drafts, loading, onNavigate }) {
  const [campaigns, setCampaigns] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    listCampaigns().then(setCampaigns).catch((err) => setError(err.message))
  }, [])

  const legacy = useMemo(() => groupLegacyDrafts(drafts.filter((d) => d.campaign_id == null)), [drafts])

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Campaigns</h2>
          <p>Bulk outreach campaigns. Select businesses on the Leads page to start one.</p>
        </div>
        <div className="page-actions">
          <Button variant="primary" icon="leads" readOnlyOk onClick={() => onNavigate('leads')}>Choose businesses</Button>
        </div>
      </div>
      <ReplyInbox />

      <section className="card card-flush" aria-label="Campaigns">
        {error && <div className="notice notice-bad" role="alert"><Icon name="alert" size={16} /><div>{error}</div></div>}
        {!error && (campaigns === null || loading) ? (
          <div className="card-body stack">
            <Skeleton height={14} />
            <Skeleton height={14} />
          </div>
        ) : !error && campaigns.length === 0 ? (
          <EmptyState icon="megaphone" title="No campaigns yet">
            Select restaurants on the Leads page and choose Email selected to create one.
          </EmptyState>
        ) : !error ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Campaign</th>
                  <th scope="col">Status</th>
                  <th scope="col">Selected</th>
                  <th scope="col">Eligible</th>
                  <th scope="col">Approved</th>
                  <th scope="col">Sent</th>
                  <th scope="col">Failed</th>
                  <th scope="col">Created</th>
                  <th scope="col"><span className="sr-only">Open</span></th>
                </tr>
              </thead>
              <tbody>
                {campaigns.map((c) => {
                  const [tone, label] = STATUS_BADGE[c.status] ?? ['neutral', c.status]
                  return (
                    <tr key={c.id}>
                      <td><div className="cell-title">{c.name}</div></td>
                      <td><Badge tone={tone}>{label}</Badge></td>
                      <td>{c.counts.total_selected}</td>
                      <td>{c.counts.eligible}</td>
                      <td>{c.counts.approved}</td>
                      <td>{c.counts.sent}</td>
                      <td>{c.counts.failed}</td>
                      <td className="muted">{timeAgo(c.created_at)}</td>
                      <td>
                        <Button size="sm" variant="secondary" readOnlyOk onClick={() => onNavigate(`campaigns/${c.id}`)}>Review</Button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      {legacy.length > 0 && (
        <section className="card card-flush" aria-label="Earlier draft groups">
          <div className="card-head">
            <div>
              <h3>Earlier draft groups</h3>
              <p>Drafts created before campaign records existed, grouped by campaign name.</p>
            </div>
          </div>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Campaign</th>
                  <th scope="col">Businesses</th>
                  <th scope="col">Drafts</th>
                  <th scope="col">Awaiting approval</th>
                  <th scope="col">Approved</th>
                  <th scope="col">Rejected</th>
                  <th scope="col">Last activity</th>
                </tr>
              </thead>
              <tbody>
                {legacy.map((c) => (
                  <tr key={c.name}>
                    <td><div className="cell-title">{c.name}</div></td>
                    <td>{c.restaurants.size}</td>
                    <td>{c.total}</td>
                    <td>{c.draft}</td>
                    <td>{c.approved}</td>
                    <td>{c.rejected}</td>
                    <td className="muted">{timeAgo(c.last)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  )
}
