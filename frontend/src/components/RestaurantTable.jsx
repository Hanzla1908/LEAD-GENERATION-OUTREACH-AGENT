const th = {
  padding: '9px 12px',
  textAlign: 'left',
  fontSize: 11,
  fontWeight: 700,
  color: '#6b7280',
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
  borderBottom: '1px solid #e5e7eb',
  whiteSpace: 'nowrap',
}

const td = {
  padding: '9px 12px',
  fontSize: 12,
  borderBottom: '1px solid #f3f4f6',
  verticalAlign: 'middle',
}

const SITE_STYLE = {
  present:   { background: '#d1fae5', color: '#065f46' },
  not_found: { background: '#fee2e2', color: '#991b1b' },
  unknown:   { background: '#fef3c7', color: '#92400e' },
}

const LEAD_STYLE = {
  qualified:    { background: '#d1fae5', color: '#065f46' },
  needs_review: { background: '#fef3c7', color: '#92400e' },
  disqualified: { background: '#fee2e2', color: '#991b1b' },
  new:          { background: '#f3f4f6', color: '#6b7280' },
}

const EMAIL_STYLE = {
  unverified: { background: '#fef3c7', color: '#92400e' },
  verified:   { background: '#d1fae5', color: '#065f46' },
  invalid:    { background: '#fee2e2', color: '#991b1b' },
}

const pill = (style, label, title) => (
  <span
    title={title}
    style={{
      ...style,
      padding: '2px 7px',
      borderRadius: 10,
      fontSize: 11,
      fontWeight: 600,
      display: 'inline-block',
    }}
  >
    {label}
  </span>
)

function StatusPill({ value, checked }) {
  if (!checked || !value || value === 'unknown')
    return pill(SITE_STYLE.unknown, '?', 'Not checked')
  return pill(SITE_STYLE[value] ?? SITE_STYLE.unknown, value === 'present' ? '✓' : value === 'not_found' ? '✗' : '?', value)
}

function LeadPill({ status, score, reason }) {
  if (!status || status === 'new')
    return pill(LEAD_STYLE.new, 'new', 'Not qualified yet')
  const s = LEAD_STYLE[status] ?? LEAD_STYLE.needs_review
  const title = reason ? `Score: ${score ?? '—'} · ${reason}` : `Score: ${score ?? '—'}`
  return pill(s, `${status} (${score ?? '—'})`, title)
}

function EmailCell({ email, source, status }) {
  if (!email) return <span style={{ color: '#9ca3af' }}>—</span>
  const s = EMAIL_STYLE[status] ?? EMAIL_STYLE.unverified
  return (
    <div>
      <div style={{ fontWeight: 500, fontSize: 11 }}>{email}</div>
      <div style={{ marginTop: 2 }}>
        {pill(s, status || 'unverified', source || '')}
        {source && (
          <a
            href={source}
            target="_blank"
            rel="noopener noreferrer"
            style={{ marginLeft: 5, fontSize: 10, color: '#6b7280' }}
            title={source}
          >
            src ↗
          </a>
        )}
      </div>
    </div>
  )
}

function EvidenceBadge({ evidence }) {
  if (!evidence || evidence.length === 0) return <span style={{ color: '#9ca3af' }}>—</span>
  return (
    <span
      title={evidence.join('\n')}
      style={{ background: '#ede9fe', color: '#5b21b6', padding: '2px 7px', borderRadius: 10, fontSize: 11, fontWeight: 600, cursor: 'help' }}
    >
      {evidence.length}
    </span>
  )
}

function Btn({ label, onClick, disabled, color = '#374151', bg = '#f3f4f6', border = '#e5e7eb' }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      style={{
        padding: '3px 9px', fontSize: 11, fontWeight: 600,
        background: disabled ? '#e5e7eb' : bg,
        color: disabled ? '#9ca3af' : color,
        border: `1px solid ${disabled ? '#e5e7eb' : border}`,
        borderRadius: 6, cursor: disabled ? 'not-allowed' : 'pointer',
        whiteSpace: 'nowrap',
      }}
    >
      {label}
    </button>
  )
}

export default function RestaurantTable({
  restaurants, state, errorMsg,
  checkingIds, isBatchChecking,
  contactingIds, isBatchContacting,
  qualifyingIds, isBatchQualifying,
  onCheckOne, onCheckAll,
  onContactOne, onContactAll,
  onQualifyOne, onQualifyAll,
}) {
  const uncheckedWithSite = restaurants.filter(r => r.website && !r.website_checked_at).length
  const uncontactedWithSite = restaurants.filter(r => r.website && !r.contact_discovered_at).length
  const unqualified = restaurants.filter(r => r.lead_status === 'new' || !r.lead_status).length

  if (state === 'loading')
    return <div style={{ textAlign: 'center', padding: '40px 0', color: '#9ca3af' }}>Searching Google Places…</div>

  if (state === 'error')
    return (
      <div style={{ padding: '12px 16px', background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, color: '#b91c1c', fontSize: 13 }}>
        {errorMsg || 'An error occurred.'}
      </div>
    )

  if (restaurants.length === 0)
    return <div style={{ textAlign: 'center', padding: '40px 0', color: '#9ca3af' }}>No restaurants found. Try a different city or category.</div>

  const anyBusy = isBatchChecking || isBatchContacting || isBatchQualifying

  return (
    <div style={{ background: '#fff', borderRadius: 12, padding: '20px 24px', boxShadow: '0 1px 4px rgba(0,0,0,0.08)' }}>
      {/* Batch controls */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14, alignItems: 'center' }}>
        <span style={{ fontSize: 13, fontWeight: 600 }}>Results</span>
        <span style={{ background: '#dbeafe', color: '#1e40af', fontSize: 11, fontWeight: 700, padding: '2px 7px', borderRadius: 10 }}>
          {restaurants.length}
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <Btn
            label={isBatchChecking ? 'Checking…' : `Check Sites (${uncheckedWithSite})`}
            onClick={onCheckAll}
            disabled={anyBusy || uncheckedWithSite === 0}
            bg="#7c3aed" color="#fff" border="#7c3aed"
          />
          <Btn
            label={isBatchContacting ? 'Discovering…' : `Find Emails (${uncontactedWithSite})`}
            onClick={onContactAll}
            disabled={anyBusy || uncontactedWithSite === 0}
            bg="#0891b2" color="#fff" border="#0891b2"
          />
          <Btn
            label={isBatchQualifying ? 'Qualifying…' : `Qualify All (${unqualified})`}
            onClick={onQualifyAll}
            disabled={anyBusy || unqualified === 0}
            bg="#059669" color="#fff" border="#059669"
          />
        </div>
      </div>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 1000 }}>
          <thead>
            <tr>
              <th style={th}>Name</th>
              <th style={th}>Phone</th>
              <th style={th}>Website</th>
              <th style={{ ...th, textAlign: 'center' }}>Site</th>
              <th style={{ ...th, textAlign: 'center' }}>Order</th>
              <th style={{ ...th, textAlign: 'center' }}>Ev.</th>
              <th style={th}>Email / Source</th>
              <th style={th}>Lead</th>
              <th style={{ ...th, textAlign: 'center' }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {restaurants.map((r) => {
              const busy = anyBusy
              const isChecking    = checkingIds.has(r.id)
              const isContacting  = contactingIds.has(r.id)
              const isQualifying  = qualifyingIds.has(r.id)
              const rowBusy       = isChecking || isContacting || isQualifying

              return (
                <tr key={r.place_id}>
                  <td style={{ ...td, maxWidth: 180 }}>
                    <div style={{ fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.name}>
                      {r.name}
                    </div>
                    {r.address && (
                      <div style={{ fontSize: 10, color: '#9ca3af', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={r.address}>
                        {r.address}
                      </div>
                    )}
                  </td>
                  <td style={{ ...td, whiteSpace: 'nowrap' }}>
                    {r.phone || <span style={{ color: '#9ca3af' }}>—</span>}
                  </td>
                  <td style={{ ...td, maxWidth: 140 }}>
                    {r.website ? (
                      <a
                        href={r.website}
                        target="_blank"
                        rel="noopener noreferrer"
                        style={{ color: '#2563eb', textDecoration: 'none', fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block' }}
                        title={r.website}
                      >
                        {(() => { try { return new URL(r.website).hostname.replace(/^www\./, '') } catch { return r.website } })()}
                      </a>
                    ) : <span style={{ color: '#9ca3af' }}>—</span>}
                  </td>
                  <td style={{ ...td, textAlign: 'center' }}>
                    {isChecking ? '…' : <StatusPill value={r.website_status} checked={!!r.website_checked_at} />}
                  </td>
                  <td style={{ ...td, textAlign: 'center' }}>
                    {isChecking ? '…' : <StatusPill value={r.ordering_status} checked={!!r.website_checked_at} />}
                  </td>
                  <td style={{ ...td, textAlign: 'center' }}>
                    <EvidenceBadge evidence={r.ordering_evidence} />
                  </td>
                  <td style={{ ...td, maxWidth: 200 }}>
                    {isContacting ? '…' : (
                      <EmailCell
                        email={r.contact_email}
                        source={r.contact_email_source}
                        status={r.contact_email_status}
                      />
                    )}
                  </td>
                  <td style={{ ...td, maxWidth: 160 }}>
                    {isQualifying ? '…' : (
                      <LeadPill
                        status={r.lead_status}
                        score={r.lead_score}
                        reason={r.lead_reason}
                      />
                    )}
                  </td>
                  <td style={{ ...td, whiteSpace: 'nowrap' }}>
                    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                      <Btn
                        label={isChecking ? '…' : r.website_checked_at ? 'Re-check' : 'Check'}
                        onClick={() => onCheckOne(r.id)}
                        disabled={busy || rowBusy || !r.website}
                      />
                      <Btn
                        label={isContacting ? '…' : r.contact_discovered_at ? 'Re-find' : 'Find Email'}
                        onClick={() => onContactOne(r.id)}
                        disabled={busy || rowBusy || !r.website}
                        bg="#e0f2fe" color="#0369a1" border="#bae6fd"
                      />
                      <Btn
                        label={isQualifying ? '…' : r.lead_status !== 'new' ? 'Re-qualify' : 'Qualify'}
                        onClick={() => onQualifyOne(r.id)}
                        disabled={busy || rowBusy}
                        bg="#d1fae5" color="#065f46" border="#a7f3d0"
                      />
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div style={{ marginTop: 12, fontSize: 10, color: '#9ca3af', textAlign: 'right' }}>
        Powered by Google
      </div>
    </div>
  )
}
