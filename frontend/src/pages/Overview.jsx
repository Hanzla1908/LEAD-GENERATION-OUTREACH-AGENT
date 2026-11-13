import { Button, EmptyState, Icon, LeadBadge, Skeleton, WebsiteBadge } from '../components/ui'
import { pendingActions } from '../lib/insights'
import { cityFromAddress, dayKey, timeAgo } from '../lib/format'

function DiscoveryChart({ restaurants }) {
  const days = []
  for (let i = 13; i >= 0; i -= 1) {
    const date = new Date()
    date.setUTCDate(date.getUTCDate() - i)
    days.push(date.toISOString().slice(0, 10))
  }
  const counts = new Map(days.map((day) => [day, 0]))
  restaurants.forEach((r) => {
    const key = dayKey(r.created_at)
    if (counts.has(key)) counts.set(key, counts.get(key) + 1)
  })
  const values = days.map((day) => counts.get(day))
  const max = Math.max(1, ...values)
  const total = values.reduce((sum, v) => sum + v, 0)

  const width = 640
  const height = 200
  const padX = 12
  const padTop = 12
  const padBottom = 28
  const slot = (width - padX * 2) / days.length
  const plotHeight = height - padTop - padBottom

  return (
    <svg
      className="chart"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`Businesses discovered per day over the last 14 days, ${total} in total`}
    >
      <defs>
        <linearGradient id="chart-bar-gradient" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#6558d3" />
          <stop offset="100%" stopColor="#315be8" />
        </linearGradient>
      </defs>
      <line x1={padX} x2={width - padX} y1={height - padBottom} y2={height - padBottom} className="chart-base" />
      {days.map((day, i) => {
        const value = values[i]
        const barHeight = (value / max) * plotHeight
        const x = padX + i * slot + slot * 0.22
        return (
          <g key={day}>
            <rect
              x={x}
              y={height - padBottom - barHeight}
              width={slot * 0.56}
              height={barHeight}
              rx="3"
              className="chart-bar"
            >
              <title>{`${day}: ${value}`}</title>
            </rect>
            {i % 2 === 1 && (
              <text x={x + slot * 0.28} y={height - 8} textAnchor="middle" className="chart-label">
                {day.slice(5)}
              </text>
            )}
          </g>
        )
      })}
    </svg>
  )
}

export default function Overview({ restaurants, summary, loading, onNavigate }) {
  const actions = pendingActions(summary)
  const metrics = [
    { label: 'Businesses discovered', value: summary.total, hint: 'Saved in the local database', page: 'leads', icon: 'leads', tone: 'blue' },
    { label: 'Qualified leads', value: summary.qualified, hint: 'Scored as qualified', page: 'qualification', icon: 'target', tone: 'teal' },
    { label: 'Missing websites', value: summary.missingWebsites, hint: 'No website or site not found', page: 'website', icon: 'web', tone: 'amber' },
    { label: 'Missing online ordering', value: summary.missingOrdering, hint: 'Website without online ordering', page: 'website', icon: 'overview', tone: 'cyan' },
    { label: 'Drafts awaiting approval', value: summary.awaitingDrafts, hint: 'Review before any outreach', page: 'drafts', icon: 'mail', tone: 'indigo' },
  ]
  const recent = restaurants.slice(0, 8)

  return (
    <>
      <div className="hero-band">
        <div>
          <h2>Overview</h2>
          <p>Pipeline health for your business outreach.</p>
        </div>
      </div>

      <div className="metrics">
        {loading
          ? Array.from({ length: 5 }, (_, i) => (
            <div className="metric" key={i}>
              <Skeleton width="60%" height={12} />
              <Skeleton width="40%" height={26} />
            </div>
          ))
          : metrics.map((m) => (
            <button type="button" className="metric" key={m.label} onClick={() => onNavigate(m.page)}>
              <span className="metric-top">
                <span className="metric-label">{m.label}</span>
                <span className={`metric-icon tone-${m.tone}`} aria-hidden="true"><Icon name={m.icon} size={17} /></span>
              </span>
              <span className="metric-value">{m.value}</span>
              <span className="metric-hint">{m.hint}</span>
            </button>
          ))}
      </div>

      <div className="grid-2">
        <section className="card card-accent-blue" aria-labelledby="chart-title">
          <div className="card-head">
            <div>
              <h3 id="chart-title">Discovery activity</h3>
              <p>Businesses saved per day, last 14 days</p>
            </div>
          </div>
          <div className="card-body">
            {loading ? <Skeleton height={200} /> : <DiscoveryChart restaurants={restaurants} />}
          </div>
        </section>

        <section className="card card-accent-amber" aria-labelledby="actions-title">
          <div className="card-head">
            <div>
              <h3 id="actions-title">Next actions</h3>
              <p>Work waiting on you</p>
            </div>
          </div>
          <div className="card-body">
            {loading ? (
              <Skeleton height={80} />
            ) : actions.length === 0 ? (
              <div className="notice notice-info">Nothing needs attention right now.</div>
            ) : (
              <ul className="action-list">
                {actions.map((a) => (
                  <li key={a.key}>
                    <button type="button" className="action-row" onClick={() => onNavigate(a.page)}>
                      <span><strong>{a.count}</strong> {a.label}</span>
                      <Icon name="arrow" size={16} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </section>
      </div>

      <section className="card card-flush card-accent-teal" aria-labelledby="recent-title">
        <div className="card-head">
          <div>
            <h3 id="recent-title">Recent businesses</h3>
            <p>Latest 8 saved results</p>
          </div>
          <Button variant="ghost" size="sm" readOnlyOk onClick={() => onNavigate('leads')}>View all leads</Button>
        </div>
        {loading ? (
          <div className="card-body stack">
            <Skeleton height={14} />
            <Skeleton height={14} />
            <Skeleton height={14} />
          </div>
        ) : recent.length === 0 ? (
          <EmptyState
            icon="leads"
            title="No businesses yet"
            action={<Button variant="primary" icon="plus" readOnlyOk onClick={() => onNavigate('leads')}>Discover businesses</Button>}
          >
            Search a city on the Leads page to start building your list.
          </EmptyState>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Business</th>
                  <th scope="col">City</th>
                  <th scope="col">Website</th>
                  <th scope="col">Lead</th>
                  <th scope="col">Added</th>
                </tr>
              </thead>
              <tbody>
                {recent.map((r) => (
                  <tr key={r.id}>
                    <td>
                      <div className="cell-title" title={r.name}>{r.name}</div>
                    </td>
                    <td>{r.city || cityFromAddress(r.address)}</td>
                    <td><WebsiteBadge restaurant={r} /></td>
                    <td><LeadBadge status={r.lead_status} score={r.lead_score} reason={r.lead_reason} /></td>
                    <td className="muted">{timeAgo(r.created_at)}</td>
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
