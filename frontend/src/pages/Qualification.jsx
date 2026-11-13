import { useState } from 'react'
import { Badge, Button, EmptyState, LeadBadge, Skeleton } from '../components/ui'
import { LEAD_LABEL, timeAgo } from '../lib/format'

const FILTERS = [
  { id: 'all', label: 'All', test: () => true },
  { id: 'qualified', label: 'Qualified', test: (r) => r.lead_status === 'qualified' },
  { id: 'needs_review', label: 'Needs review', test: (r) => r.lead_status === 'needs_review' },
  { id: 'disqualified', label: 'Disqualified', test: (r) => r.lead_status === 'disqualified' },
  { id: 'new', label: 'Not qualified', test: (r) => !r.lead_status || r.lead_status === 'new' },
]

const SCORE_MAX = 90

function signalsFor(r) {
  const signals = []
  if (r.website_status === 'present') signals.push('Live website')
  if (r.website_status === 'not_found') signals.push('Website not found')
  if (r.website && r.ordering_status === 'not_found') signals.push('No online ordering')
  if (r.ordering_status === 'present') signals.push('Online ordering found')
  if (r.contact_email) signals.push('Public email')
  if (r.phone) signals.push('Phone listed')
  return signals
}

export default function Qualification({ restaurants, loading, isBusy, onQualifyOne, onQualifyMany }) {
  const [filterId, setFilterId] = useState('all')
  const active = FILTERS.find((f) => f.id === filterId) ?? FILTERS[0]
  const rows = restaurants.filter(active.test)
  const unqualifiedIds = restaurants.filter((r) => !r.lead_status || r.lead_status === 'new').map((r) => r.id)
  const batchQualifying = isBusy('batch:qualify')

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Lead qualification</h2>
          <p>Deterministic scores from stored website, ordering and email data. The AI summary explains a score but never changes it.</p>
        </div>
        <div className="page-actions">
          <Button
            variant="primary"
            icon="target"
            disabled={batchQualifying || unqualifiedIds.length === 0}
            onClick={() => onQualifyMany(unqualifiedIds)}
          >
            {batchQualifying ? 'Scoring…' : `Qualify all (${unqualifiedIds.length})`}
          </Button>
        </div>
      </div>

      <div className="segmented" role="group" aria-label="Filter by review status">
        {FILTERS.map((f) => (
          <button key={f.id} type="button" aria-pressed={filterId === f.id} onClick={() => setFilterId(f.id)}>
            {f.label}
            <span className="count">{restaurants.filter(f.test).length}</span>
          </button>
        ))}
      </div>

      {loading ? (
        <div className="cards-grid">
          {Array.from({ length: 4 }, (_, i) => (
            <div className="card card-body lead-card" key={i}>
              <Skeleton width="50%" height={16} />
              <Skeleton width="30%" height={12} />
              <Skeleton height={40} />
            </div>
          ))}
        </div>
      ) : rows.length === 0 ? (
        <section className="card">
          <EmptyState icon="target" title="No businesses in this view">
            {restaurants.length === 0
              ? 'Discover businesses first, then score them here.'
              : 'Choose another status to see more businesses.'}
          </EmptyState>
        </section>
      ) : (
        <div className="cards-grid">
          {rows.map((r) => {
            const scoring = isBusy(`qualify:${r.id}`)
            const score = r.lead_score
            const width = score == null ? 0 : Math.max(0, Math.min(100, (score / SCORE_MAX) * 100))
            return (
              <article className="card card-body lead-card" key={r.id} aria-label={`${r.name} lead`}>
                <div className="lead-card-head">
                  <div>
                    <h3>{r.name}</h3>
                    <p>{r.address || 'No address on file'}</p>
                  </div>
                  <LeadBadge status={r.lead_status} score={r.lead_score} />
                </div>

                <div className="stack" style={{ gap: 12, marginTop: 14 }}>
                  <div>
                    <div className="small muted" style={{ marginBottom: 6 }}>
                      Score {score ?? '—'} of {SCORE_MAX} possible
                    </div>
                    <div className="bar" aria-hidden="true"><span style={{ width: `${width}%` }} /></div>
                  </div>

                  <p className="lead-reason">
                    {r.lead_reason || 'Not scored yet. Run qualification to generate a score and reason.'}
                  </p>

                  <div className="chips" aria-label="Signals from stored data">
                    {signalsFor(r).length === 0
                      ? <span className="small muted">No signals recorded yet</span>
                      : signalsFor(r).map((s) => <Badge key={s} tone="neutral">{s}</Badge>)}
                  </div>
                </div>

                <div className="lead-card-foot" style={{ marginTop: 16 }}>
                  <span className="small muted">
                    {r.lead_qualified_at ? `${LEAD_LABEL[r.lead_status] ?? 'Scored'} · ${timeAgo(r.lead_qualified_at)}` : 'Not reviewed'}
                  </span>
                  <Button
                    size="sm"
                    variant="secondary"
                    icon="target"
                    disabled={scoring || batchQualifying}
                    onClick={() => onQualifyOne(r.id)}
                  >
                    {scoring ? 'Scoring…' : r.lead_status && r.lead_status !== 'new' ? 'Requalify' : 'Qualify'}
                  </Button>
                </div>
              </article>
            )
          })}
        </div>
      )}
    </>
  )
}
