import { useState } from 'react'
import { Button, EmptyState, OrderingBadge, Skeleton, WebsiteBadge } from '../components/ui'
import { safeHref, shortUrl } from '../lib/format'

const FILTERS = [
  { id: 'all', label: 'All', test: () => true },
  { id: 'unchecked', label: 'Not checked', test: (r) => !!r.website && !r.website_checked_at },
  { id: 'live', label: 'Live site', test: (r) => r.website_status === 'present' },
  { id: 'not_found', label: 'Not found', test: (r) => !!r.website_checked_at && r.website_status === 'not_found' },
  { id: 'no_ordering', label: 'No online ordering', test: (r) => !!r.website && r.ordering_status === 'not_found' },
  { id: 'ordering', label: 'Has ordering', test: (r) => r.ordering_status === 'present' },
]

function EvidenceList({ urls }) {
  if (!urls || urls.length === 0) return <span className="muted">None</span>
  return (
    <ul className="evidence">
      {urls.slice(0, 3).map((url) => {
        const href = safeHref(url)
        return (
          <li key={url}>
            {href
              ? <a className="link" href={href} target="_blank" rel="noopener noreferrer" title={url}>{shortUrl(href)}</a>
              : <span className="muted">{shortUrl(url)}</span>}
          </li>
        )
      })}
      {urls.length > 3 && <li className="muted">+{urls.length - 3} more</li>}
    </ul>
  )
}

export default function WebsiteAnalysis({ restaurants, loading, isBusy, onCheckOne, onCheckMany }) {
  const [filterId, setFilterId] = useState('all')
  const active = FILTERS.find((f) => f.id === filterId) ?? FILTERS[0]
  const rows = restaurants.filter(active.test)
  const uncheckedIds = restaurants.filter((r) => r.website && !r.website_checked_at).map((r) => r.id)
  const batchChecking = isBusy('batch:check')

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Website analysis</h2>
          <p>Website availability and online ordering signals, with the pages they were found on.</p>
        </div>
        <div className="page-actions">
          <Button
            variant="primary"
            icon="refresh"
            disabled={batchChecking || uncheckedIds.length === 0}
            onClick={() => onCheckMany(uncheckedIds)}
          >
            {batchChecking ? 'Checking…' : `Check all unchecked (${uncheckedIds.length})`}
          </Button>
        </div>
      </div>

      <div className="segmented" role="group" aria-label="Filter websites">
        {FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            aria-pressed={filterId === f.id}
            onClick={() => setFilterId(f.id)}
          >
            {f.label}
            <span className="count">{restaurants.filter(f.test).length}</span>
          </button>
        ))}
      </div>

      <section className="card card-flush" aria-label="Website results">
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th scope="col">Business</th>
                <th scope="col">Website</th>
                <th scope="col">Website status</th>
                <th scope="col">Ordering</th>
                <th scope="col">Evidence</th>
                <th scope="col">Action</th>
              </tr>
            </thead>
            <tbody>
              {loading && Array.from({ length: 4 }, (_, i) => (
                <tr key={i}>
                  {Array.from({ length: 6 }, (_, j) => (
                    <td key={j}><Skeleton width="70%" height={12} /></td>
                  ))}
                </tr>
              ))}
              {!loading && rows.map((r) => {
                const checking = isBusy(`check:${r.id}`)
                const needsRetry = r.website_checked_at && (r.website_error || r.website_status !== 'present')
                return (
                  <tr key={r.id}>
                    <td>
                      <div className="cell-title" title={r.name}>{r.name}</div>
                    </td>
                    <td>
                      {r.website ? (
                        <a className="link" href={safeHref(r.website) ?? undefined} target="_blank" rel="noopener noreferrer" title={r.website}>
                          {shortUrl(r.website)}
                        </a>
                      ) : <span className="muted">None</span>}
                    </td>
                    <td>
                      <WebsiteBadge restaurant={r} />
                      {r.website_error && <div className="small muted">{r.website_error}</div>}
                    </td>
                    <td><OrderingBadge restaurant={r} /></td>
                    <td><EvidenceList urls={r.ordering_evidence} /></td>
                    <td>
                      <Button
                        size="sm"
                        variant="secondary"
                        icon="refresh"
                        disabled={!r.website || checking || isBusy('batch:check')}
                        onClick={() => onCheckOne(r.id)}
                      >
                        {checking ? 'Checking…' : needsRetry ? 'Retry' : r.website_checked_at ? 'Recheck' : 'Check'}
                      </Button>
                    </td>
                  </tr>
                )
              })}
              {!loading && rows.length === 0 && (
                <tr>
                  <td colSpan={6}>
                    <EmptyState icon="web" title="Nothing in this view">
                      {restaurants.length === 0
                        ? 'Discover businesses first, then run website checks.'
                        : 'Choose another filter to see more businesses.'}
                    </EmptyState>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </>
  )
}
