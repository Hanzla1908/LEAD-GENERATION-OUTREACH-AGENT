import { useEffect, useState } from 'react'
import * as api from '../services/api'
import { ActionMenu, Badge, Button, ConfirmDialog, EmailBadge, EmptyState, Icon, LeadBadge, Modal, OrderingBadge, Skeleton, WebsiteBadge, useAccess } from '../components/ui'
import DiscoveryForm from '../components/DiscoveryForm'
import CampaignSetupDialog from '../components/CampaignSetupDialog'
import { cityFromAddress, timeAgo } from '../lib/format'
import ConversationHistory from '../components/ConversationHistory'

const PAGE_SIZE = 10

const STATUS_OPTIONS = [
  { value: 'all', label: 'All lead statuses' },
  { value: 'qualified', label: 'Qualified' },
  { value: 'needs_review', label: 'Needs review' },
  { value: 'disqualified', label: 'Disqualified' },
  { value: 'new', label: 'Not qualified' },
]
const SITE_OPTIONS = [
  { value: 'all', label: 'Any website' },
  { value: 'has', label: 'Has website' },
  { value: 'none', label: 'No website' },
]
const EMAIL_OPTIONS = [
  { value: 'all', label: 'Any email status' },
  { value: 'has', label: 'Email found' },
  { value: 'none', label: 'No email' },
  { value: 'review', label: 'Personal: needs review' },
  { value: 'invalid', label: 'Invalid or disposable' },
  { value: 'verified', label: 'Approved by a person' },
  { value: 'unchecked', label: 'Not checked yet' },
  { value: 'unknown', label: 'Check failed' },
]

// Deleting is reversible: the lead can be restored, and its drafts, campaign records and email history stay.
const DELETE_DESCRIPTION = 'This removes the business from your leads, searches and outreach. Its drafts, campaign records and email history are kept, and you can restore it from Deleted leads.'

function LeadRow({ r, info, selected, hasPendingDraft, isBusy, actions, onToggle }) {
  const { canOperate } = useAccess()
  const checking = isBusy(`check:${r.id}`)
  const contacting = isBusy(`contact:${r.id}`)
  const qualifying = isBusy(`qualify:${r.id}`)
  const drafting = isBusy(`gen:${r.id}`)
  const optingOut = isBusy(`optout:${r.id}`)
  const verifying = isBusy(`verify:${r.id}`)
  const reviewing = isBusy(`review:${r.id}`)
  const manualBusy = isBusy(`manual:${r.id}`)
  const needsEmailReview = Boolean(r.contact_email) && (
    (r.contact_email_classification === 'personal' && !r.contact_email_reviewed_at) || r.contact_email_status === 'unknown'
  )
  const rowBusy = checking || contacting || qualifying || drafting || optingOut || verifying || reviewing
  const batchBusy = isBusy('batch:check') || isBusy('batch:contact') || isBusy('batch:qualify')
  const disabled = rowBusy || batchBusy
  const qualified = r.lead_status && r.lead_status !== 'new'
  const known = info !== undefined
  const eligible = known && info.eligible
  const reasonText = known ? info.reasons.join('; ') : 'Checking eligibility…'

  const qualifyLabel = qualifying ? 'Scoring…' : qualified ? 'Requalify' : 'Qualify'
  const writeBlocked = !canOperate
  const menuItems = [
    {
      key: 'check',
      label: checking ? 'Checking site…' : r.website_checked_at ? 'Recheck site' : 'Check site',
      icon: 'web',
      disabled: disabled || writeBlocked || !r.website,
      onSelect: () => actions.check(r.id),
    },
    {
      key: 'contact',
      label: contacting ? 'Finding email…' : r.contact_discovered_at ? 'Find email again' : 'Find email',
      icon: 'atSign',
      disabled: disabled || writeBlocked || !r.website,
      onSelect: () => actions.contact(r.id),
    },
    ...(r.contact_email ? [{
      key: 'verify',
      label: verifying ? 'Checking email…' : 'Check email',
      icon: 'shield',
      disabled: disabled || writeBlocked,
      onSelect: () => actions.verifyEmail(r.id),
    }] : []),
    { key: 'history', label: 'View history', icon: 'history', disabled: false, onSelect: () => actions.history(r) },
    ...(!r.opted_out ? [{
      key: 'optout',
      label: 'Opt out',
      icon: 'ban',
      danger: true,
      disabled: disabled || writeBlocked,
      onSelect: () => actions.requestOptOut(r),
    }] : []),
  ]

  return (
    <tr className={selected ? 'is-selected' : undefined}>
      <td className="select-cell">
        <input
          type="checkbox"
          className="checkbox"
          aria-label={`Select ${r.name} for email campaign`}
          checked={selected}
          disabled={!eligible || disabled || !canOperate}
          title={eligible ? undefined : reasonText}
          onChange={() => onToggle(r.id)}
        />
      </td>
      <td>
        <div className="cell-title" title={r.name}>{r.name}</div>
        <div className="cell-sub" title={r.address || undefined}>{r.address || 'No address'}</div>
        <div className="small muted">{[r.city || cityFromAddress(r.address), r.country_name].filter(Boolean).join(', ') || '—'}</div>
      </td>
      <td>
        <div className="cell-stack">
          <WebsiteBadge restaurant={r} />
          <OrderingBadge restaurant={r} />
        </div>
      </td>
      <td>
        {r.contact_email ? (
          <>
            <div className="cell-title" title={r.contact_email}>{r.contact_email}</div>
            <EmailBadge
              status={r.contact_email_status}
              classification={r.contact_email_classification}
              reviewed={Boolean(r.contact_email_reviewed_at)}
            />
            {r.contact_email_reasons?.[0] && (
              <div className="small muted reason-text" title={r.contact_email_reasons.join('\n')}>{r.contact_email_reasons[0]}</div>
            )}
          </>
        ) : <span className="muted">No email</span>}
      </td>
      <td>
        <div className="cell-stack">
          <LeadBadge status={r.lead_status} score={r.lead_score} reason={r.lead_reason} />
          {!known ? (
            <Badge tone="neutral">Checking</Badge>
          ) : eligible ? (
            <Badge tone="ok">Eligible</Badge>
          ) : (
            <>
              <Badge tone="warn">Not eligible</Badge>
              <div className="small muted reason-text" title={info.reasons.join('\n')}>{info.reasons[0]}</div>
            </>
          )}
        </div>
      </td>
      <td>
        <div className="action-bar">
          {needsEmailReview && (
            <>
              <Button
                size="sm"
                variant="secondary"
                icon="check"
                className="btn-icon"
                aria-label={reviewing ? 'Saving email review…' : `Approve email for ${r.name}`}
                title="Approve email"
                onClick={() => actions.approveEmail(r)}
                disabled={disabled}
              />
              <Button
                size="sm"
                variant="ghost"
                icon="x"
                className="btn-icon is-danger"
                aria-label={`Reject email for ${r.name}`}
                title="Reject email"
                onClick={() => actions.rejectEmail(r)}
                disabled={disabled}
              />
            </>
          )}
          <Button
            size="sm"
            variant="secondary"
            icon="target"
            className="btn-icon"
            aria-label={`${qualifyLabel} ${r.name}`}
            title={qualifyLabel}
            onClick={() => actions.qualify(r.id)}
            disabled={disabled || writeBlocked}
          />
          {r.lead_status === 'needs_review' && !r.opted_out && (
            <Button
              size="sm"
              variant="secondary"
              icon="badgeCheck"
              className="btn-icon"
              aria-label={`Mark ${r.name} as qualified after review`}
              title="Mark as qualified after review"
              onClick={() => actions.markQualifiedByHand(r)}
              disabled={disabled || writeBlocked || manualBusy}
            />
          )}
          {r.opted_out ? (
            <Badge tone="neutral">Opted out</Badge>
          ) : hasPendingDraft ? (
            <Badge tone="info">Draft pending</Badge>
          ) : (
            <Button
              size="sm"
              variant="secondary"
              icon="pen"
              className="btn-icon"
              aria-label={`${drafting ? 'Drafting email' : 'Draft email'} for ${r.name}`}
              title={r.contact_email ? (drafting ? 'Drafting email…' : 'Draft email') : 'Find an email first'}
              onClick={() => actions.draft(r)}
              disabled={disabled || writeBlocked || !r.contact_email}
            />
          )}
          <Button
            size="sm"
            variant="ghost"
            icon="trash"
            className="btn-icon is-danger"
            aria-label={`Delete ${r.name}`}
            title="Delete Lead"
            onClick={() => actions.deleteLead(r)}
            disabled={disabled || writeBlocked}
          />
          <ActionMenu label={`More actions for ${r.name}`} items={menuItems} />
        </div>
      </td>
    </tr>
  )
}

export default function Leads({
  restaurants, drafts, loading, query, onQueryChange, isBusy,
  onDiscover, discoverError, onDiscoverReset,
  onCheckOne, onContactOne, onQualifyOne,
  onCheckMany, onContactMany, onQualifyMany, onGenerateDraft, onOptOut, onDeleteDemo, onMarkQualifiedByHand, onDeleteLead, onDeleteLeads, onRestoreLead, onVerifyEmail, onReviewEmail,
  eligibility, selectedIds, onToggleSelect, onSelectMany, onDeselectMany, onClearSelection, onCreateCampaign,
  discoveryMode,
}) {
  const { canOperate } = useAccess()
  const [status, setStatus] = useState('all')
  const [site, setSite] = useState('all')
  const [email, setEmail] = useState('all')
  const [page, setPage] = useState(1)
  const [discoverOpen, setDiscoverOpen] = useState(false)
  const [discoverNotice, setDiscoverNotice] = useState('')
  // Industry profiles for the search form. If they cannot be loaded, the form offers restaurants only.
  const [industries, setIndustries] = useState([])
  useEffect(() => {
    let active = true
    api.getIndustries().then((list) => { if (active) setIndustries(list) }).catch(() => {})
    return () => { active = false }
  }, [])
  const [optOutTarget, setOptOutTarget] = useState(null)
  const [manualTarget, setManualTarget] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false)
  const [deletedOpen, setDeletedOpen] = useState(false)
  const [deletedLeads, setDeletedLeads] = useState(null)
  const [deletedLoading, setDeletedLoading] = useState(false)
  const [deletedError, setDeletedError] = useState('')
  const [deleteDemoOpen, setDeleteDemoOpen] = useState(false)
  const demoCount = restaurants.filter((r) => r.source === 'demo').length
  const [setupOpen, setSetupOpen] = useState(false)
  const [historyTarget, setHistoryTarget] = useState(null)

  async function loadDeletedLeads() {
    setDeletedLoading(true)
    setDeletedError('')
    try {
      setDeletedLeads(await api.listDeletedLeads())
    } catch (err) {
      setDeletedError(err.message || 'The deleted leads could not be loaded.')
    } finally {
      setDeletedLoading(false)
    }
  }

  function openDeleted() {
    setDeletedOpen(true)
    loadDeletedLeads()
  }

  async function restoreFromList(restaurant) {
    const restored = await onRestoreLead(restaurant)
    if (restored) setDeletedLeads((prev) => (prev ?? []).filter((r) => r.id !== restaurant.id))
  }

  function openDiscover() {
    onDiscoverReset()
    setDiscoverNotice('')
    setDiscoverOpen(true)
  }

  useEffect(() => { setPage(1) }, [status, site, email, query])

  const eligibleOf = (id) => eligibility?.[String(id)]?.eligible === true
  const pendingDraftIds = new Set(drafts.filter((d) => d.status === 'draft').map((d) => d.restaurant_id))

  const needle = query.trim().toLowerCase()
  const filtered = restaurants.filter((r) => {
    if (status !== 'all' && (r.lead_status || 'new') !== status) return false
    if (site === 'has' && !r.website) return false
    if (site === 'none' && r.website) return false
    if (email === 'has' && !r.contact_email) return false
    if (email === 'none' && r.contact_email) return false
    if (email === 'review' && !(r.contact_email_classification === 'personal' && !r.contact_email_reviewed_at)) return false
    if (email === 'invalid' && !(r.contact_email_status === 'invalid' || r.contact_email_classification === 'disposable')) return false
    if (email === 'verified' && r.contact_email_status !== 'verified') return false
    if (email === 'unchecked' && (!r.contact_email || r.contact_email_checked_at)) return false
    if (email === 'unknown' && r.contact_email_status !== 'unknown') return false
    if (needle && ![r.name, r.address, r.contact_email].some((v) => v && v.toLowerCase().includes(needle))) return false
    return true
  })

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const current = Math.min(page, pageCount)
  const rows = filtered.slice((current - 1) * PAGE_SIZE, current * PAGE_SIZE)

  const filteredEligibleIds = filtered.filter((r) => eligibleOf(r.id)).map((r) => r.id)
  const pageEligibleIds = rows.filter((r) => eligibleOf(r.id)).map((r) => r.id)
  const pageAllSelected = pageEligibleIds.length > 0 && pageEligibleIds.every((id) => selectedIds.has(id))
  const selectedCount = selectedIds.size
  const eligibleSelectedIds = [...selectedIds].filter(eligibleOf)

  const uncheckedIds = restaurants.filter((r) => r.website && !r.website_checked_at).map((r) => r.id)
  const uncontactedIds = restaurants.filter((r) => r.website && !r.contact_discovered_at).map((r) => r.id)
  const unqualifiedIds = restaurants.filter((r) => !r.lead_status || r.lead_status === 'new').map((r) => r.id)
  const batchChecking = isBusy('batch:check')
  const batchContacting = isBusy('batch:contact')
  const batchQualifying = isBusy('batch:qualify')
  const anyBatch = batchChecking || batchContacting || batchQualifying

  const actions = {
    check: onCheckOne,
    contact: onContactOne,
    qualify: onQualifyOne,
    draft: onGenerateDraft,
    requestOptOut: setOptOutTarget,
    markQualifiedByHand: setManualTarget,
    deleteLead: setDeleteTarget,
    verifyEmail: onVerifyEmail,
    history: setHistoryTarget,
    approveEmail: (r) => onReviewEmail(r.id, 'approve'),
    rejectEmail: (r) => onReviewEmail(r.id, 'reject'),
  }

  const clearFilters = () => {
    setStatus('all')
    setSite('all')
    setEmail('all')
    onQueryChange('')
  }

  const hasFilters = status !== 'all' || site !== 'all' || email !== 'all' || needle !== ''
  const start = filtered.length === 0 ? 0 : (current - 1) * PAGE_SIZE + 1
  const end = Math.min(current * PAGE_SIZE, filtered.length)

  const showGoogleAttribution = restaurants.some((r) => r.source === 'google_places')

  return (
    <>
      {discoveryMode?.demo_mode && (
        <div className="notice notice-warn" role="status">
          <Icon name="alert" size={16} />
          <div>
            <strong>Demo mode.</strong> Searches return sample records marked [DEMO]. They cannot be emailed.
            Set DEMO_MODE=false and add GOOGLE_PLACES_API_KEY on the server to search Google Places.
          </div>
        </div>
      )}
      {discoveryMode && !discoveryMode.demo_mode && !discoveryMode.live_key_configured && (
        <div className="notice notice-bad" role="alert">
          <Icon name="alert" size={16} />
          <div>Live mode is on, but GOOGLE_PLACES_API_KEY is missing on the server. Searches will fail until it is added.</div>
        </div>
      )}
      <div className="page-header">
        <div>
          <h2>Business leads</h2>
          <p>Discovered businesses with website, ordering, email and qualification data.</p>
        </div>
        <div className="page-actions">
          {demoCount > 0 && (
            <Button variant="secondary" icon="x" onClick={() => setDeleteDemoOpen(true)} disabled={!canOperate}>
              Delete demo records ({demoCount})
            </Button>
          )}
          <Button variant="secondary" icon="undo" onClick={openDeleted}>Deleted leads</Button>
          <Button variant="primary" icon="plus" onClick={openDiscover}>Discover businesses</Button>
        </div>
      </div>

      <section className="card card-flush" aria-label="Lead list">
        <div className="card-body">
          <div className="toolbar">
            <input
              type="search"
              className="input search"
              aria-label="Search leads"
              placeholder="Search name, address or email"
              value={query}
              onChange={(event) => onQueryChange(event.target.value)}
            />
            <select className="select" aria-label="Filter by lead status" value={status} onChange={(e) => setStatus(e.target.value)}>
              {STATUS_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <select className="select" aria-label="Filter by website" value={site} onChange={(e) => setSite(e.target.value)}>
              {SITE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <select className="select" aria-label="Filter by email" value={email} onChange={(e) => setEmail(e.target.value)}>
              {EMAIL_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            {hasFilters && <Button variant="ghost" size="sm" readOnlyOk onClick={clearFilters}>Clear filters</Button>}
          </div>
        </div>

        <div className="selection-bar" role="region" aria-label="Email selection">
          <div className="selection-count">
            <strong>{selectedCount}</strong> selected
            {selectedCount > 0 && <span className="muted"> · {eligibleSelectedIds.length} eligible</span>}
          </div>
          <div className="selection-actions">
            <Button
              size="sm"
              variant="secondary"
              disabled={filteredEligibleIds.length === 0}
              onClick={() => onSelectMany(filteredEligibleIds)}
            >
              Select all eligible ({filteredEligibleIds.length})
            </Button>
            <Button size="sm" variant="ghost" disabled={selectedCount === 0} onClick={onClearSelection}>
              Clear selection
            </Button>
            <Button
              size="sm"
              variant="secondary"
              icon="trash"
              className="is-danger"
              disabled={selectedCount === 0 || !canOperate}
              onClick={() => setBulkDeleteOpen(true)}
            >
              Delete selected ({selectedCount})
            </Button>
            <Button
              variant="primary"
              icon="mail"
              disabled={eligibleSelectedIds.length === 0}
              onClick={() => setSetupOpen(true)}
            >
              Email selected ({eligibleSelectedIds.length})
            </Button>
          </div>
        </div>

        <div className="batch-bar" role="group" aria-label="Bulk actions">
          <span>Bulk</span>
          <Button
            size="sm"
            variant="secondary"
            icon="refresh"
            disabled={anyBatch || uncheckedIds.length === 0}
            onClick={() => onCheckMany(uncheckedIds)}
          >
            {batchChecking ? 'Checking sites…' : `Check sites (${uncheckedIds.length})`}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            icon="mail"
            disabled={anyBatch || uncontactedIds.length === 0}
            onClick={() => onContactMany(uncontactedIds)}
          >
            {batchContacting ? 'Finding emails…' : `Find emails (${uncontactedIds.length})`}
          </Button>
          <Button
            size="sm"
            variant="secondary"
            icon="target"
            disabled={anyBatch || unqualifiedIds.length === 0}
            onClick={() => onQualifyMany(unqualifiedIds)}
          >
            {batchQualifying ? 'Scoring…' : `Qualify all (${unqualifiedIds.length})`}
          </Button>
        </div>

        <div className="table-wrap">
          <table className="table leads-table">
            <caption className="sr-only">Business leads</caption>
            <thead>
              <tr>
                <th scope="col" className="select-cell">
                  <input
                    type="checkbox"
                    className="checkbox"
                    aria-label="Select all eligible businesses on this page"
                    checked={pageAllSelected}
                    disabled={pageEligibleIds.length === 0 || !canOperate}
                    onChange={() => (pageAllSelected ? onDeselectMany(pageEligibleIds) : onSelectMany(pageEligibleIds))}
                  />
                </th>
                <th scope="col" className="col-business">Business</th>
                <th scope="col" className="col-site">Site</th>
                <th scope="col" className="col-email">Email</th>
                <th scope="col" className="col-lead">Lead</th>
                <th scope="col" className="col-actions">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && Array.from({ length: 5 }, (_, i) => (
                <tr key={`sk-${i}`}>
                  {Array.from({ length: 6 }, (_, j) => (
                    <td key={j}><Skeleton width={j === 1 ? '80%' : '60%'} height={12} /></td>
                  ))}
                </tr>
              ))}
              {!loading && rows.map((r) => (
                <LeadRow
                  key={r.id}
                  r={r}
                  info={eligibility?.[String(r.id)]}
                  selected={selectedIds.has(r.id)}
                  hasPendingDraft={pendingDraftIds.has(r.id)}
                  isBusy={isBusy}
                  actions={actions}
                  onToggle={onToggleSelect}
                />
              ))}
              {!loading && rows.length === 0 && (
                <tr>
                  <td colSpan={6}>
                    {restaurants.length === 0 ? (
                      <EmptyState
                        icon="leads"
                        title="No businesses yet"
                        action={<Button variant="primary" icon="plus" onClick={openDiscover}>Discover businesses</Button>}
                      >
                        Search a city to pull restaurants from Google Places.
                      </EmptyState>
                    ) : (
                      <EmptyState
                        icon="search"
                        title="No leads match these filters"
                        action={<Button variant="secondary" readOnlyOk onClick={clearFilters}>Clear filters</Button>}
                      >
                        Try a different search term or status.
                      </EmptyState>
                    )}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {!loading && filtered.length > 0 && (
          <div className="pagination">
            <span>Showing {start}–{end} of {filtered.length}</span>
            <div className="pagination-controls">
              <Button size="sm" variant="secondary" readOnlyOk onClick={() => setPage(current - 1)} disabled={current <= 1}>Previous</Button>
              <span>Page {current} of {pageCount}</span>
              <Button size="sm" variant="secondary" readOnlyOk onClick={() => setPage(current + 1)} disabled={current >= pageCount}>Next</Button>
            </div>
          </div>
        )}
      </section>

      {showGoogleAttribution && <p className="attribution">Powered by Google</p>}

      <Modal
        open={discoverOpen}
        title="Discover businesses"
        description="Searches Google Places for businesses in Pakistan and saves new results. Places already saved are not duplicated."
        onClose={() => setDiscoverOpen(false)}
        size="md"
      >
        <DiscoveryForm
          loading={isBusy('discover')}
          error={discoverError}
          notice={discoverNotice}
          industries={industries}
          onSearch={async (city, category, limit, industry, countryCode, cityId) => {
            setDiscoverNotice('')
            const count = await onDiscover(city, category, limit, industry, countryCode, cityId)
            if (count === null) return
            if (count > 0) {
              setDiscoverOpen(false)
            } else {
              setDiscoverNotice(`No businesses were found in ${city} for this type. Try another business type or city.`)
            }
          }}
        />
      </Modal>

      <CampaignSetupDialog
        open={setupOpen}
        restaurantIds={[...selectedIds]}
        onClose={() => setSetupOpen(false)}
        onCreate={onCreateCampaign}
      />

      <ConversationHistory restaurant={historyTarget} onClose={() => setHistoryTarget(null)} />

      <ConfirmDialog
        open={deleteDemoOpen}
        title="Delete demo records?"
        description="Removes the sample [DEMO] businesses from this workspace. Real businesses are never affected. A sample that already has drafts, campaign recipients or email history is kept, because that history must stay intact. This cannot be undone."
        confirmLabel="Delete demo records"
        tone="danger"
        busy={isBusy('delete-demo')}
        onCancel={() => setDeleteDemoOpen(false)}
        onConfirm={async () => {
          await onDeleteDemo()
          setDeleteDemoOpen(false)
        }}
      />

      <ConfirmDialog
        open={deleteTarget !== null}
        title={`Delete ${deleteTarget?.name ?? 'this lead'}?`}
        description={DELETE_DESCRIPTION}
        confirmLabel="Delete lead"
        tone="danger"
        busy={deleteTarget ? isBusy(`delete:${deleteTarget.id}`) : false}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={async () => {
          const removed = await onDeleteLead(deleteTarget)
          if (removed) setDeleteTarget(null)
        }}
      />

      <ConfirmDialog
        open={bulkDeleteOpen}
        title={`Delete ${selectedCount} lead${selectedCount === 1 ? '' : 's'}?`}
        description={DELETE_DESCRIPTION}
        confirmLabel="Delete leads"
        tone="danger"
        busy={isBusy('delete-leads')}
        onCancel={() => setBulkDeleteOpen(false)}
        onConfirm={async () => {
          const removed = await onDeleteLeads([...selectedIds])
          if (removed) setBulkDeleteOpen(false)
        }}
      />

      <Modal
        open={deletedOpen}
        title="Deleted leads"
        description="Restore a lead to bring it back to your leads, searches and outreach."
        onClose={() => setDeletedOpen(false)}
        size="md"
      >
        {deletedLoading && <Skeleton height={60} />}
        {deletedError && <div className="notice notice-bad" role="alert">{deletedError}</div>}
        {!deletedLoading && deletedLeads && deletedLeads.length === 0 && (
          <p className="muted">No deleted leads. Deleted leads appear here and can be restored.</p>
        )}
        {!deletedLoading && deletedLeads && deletedLeads.length > 0 && (
          <ul className="action-list">
            {deletedLeads.map((r) => (
              <li key={r.id}>
                <div className="action-row">
                  <span>
                    <strong>{r.name}</strong>
                    <span className="small muted">
                      {' '}{[r.city, r.country_name].filter(Boolean).join(', ')} · deleted {timeAgo(r.deleted_at)}
                    </span>
                  </span>
                  <Button
                    size="sm"
                    variant="secondary"
                    icon="undo"
                    disabled={isBusy(`restore:${r.id}`)}
                    onClick={() => restoreFromList(r)}
                  >
                    Restore
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Modal>

      <ConfirmDialog
        open={manualTarget !== null}
        title={`Mark ${manualTarget?.name ?? 'this business'} as qualified?`}
        description="Only do this after you have checked the business yourself. It makes the business eligible for outreach, and the reason records that a person decided. The score stays the same."
        confirmLabel="Mark qualified"
        busy={manualTarget ? isBusy(`manual:${manualTarget.id}`) : false}
        onCancel={() => setManualTarget(null)}
        onConfirm={async () => {
          await onMarkQualifiedByHand(manualTarget)
          setManualTarget(null)
        }}
      />

      <ConfirmDialog
        open={optOutTarget !== null}
        title={`Opt out ${optOutTarget?.name ?? 'this business'}?`}
        description="Draft generation and approval will be blocked for this business, and its email address is added to the suppression list. The opt-out cannot be reversed from this interface."
        confirmLabel="Opt out"
        tone="danger"
        busy={optOutTarget ? isBusy(`optout:${optOutTarget.id}`) : false}
        onCancel={() => setOptOutTarget(null)}
        onConfirm={async () => {
          await onOptOut(optOutTarget)
          setOptOutTarget(null)
        }}
      />
    </>
  )
}
