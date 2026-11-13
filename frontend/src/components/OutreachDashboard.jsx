import { useState, useEffect } from 'react'
import { getLeads, generateDraft, listDrafts, updateDraft, approveDraft, rejectDraft, regenerateDraft, optOut } from '../services/api'

const STATUS_COLORS = {
  qualified:    { bg: '#d1fae5', color: '#065f46' },
  needs_review: { bg: '#fef3c7', color: '#92400e' },
  disqualified: { bg: '#fee2e2', color: '#991b1b' },
}

const DRAFT_STATUS_COLORS = {
  draft:    { bg: '#dbeafe', color: '#1e40af' },
  approved: { bg: '#d1fae5', color: '#065f46' },
  rejected: { bg: '#fee2e2', color: '#991b1b' },
}

function Pill({ label, colors }) {
  return (
    <span style={{
      display: 'inline-block', padding: '2px 8px', borderRadius: 12,
      fontSize: 11, fontWeight: 600, background: colors.bg, color: colors.color,
    }}>{label}</span>
  )
}

function DraftPanel({ restaurant, draft, onDraftChange }) {
  const [subject, setSubject] = useState(draft.subject)
  const [body, setBody] = useState(draft.body)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => { setSubject(draft.subject); setBody(draft.body); setMsg('') }, [draft.id])

  async function handleSave() {
    setBusy(true); setMsg('')
    try {
      const updated = await updateDraft(draft.id, subject, body)
      onDraftChange(updated)
      setMsg('Saved.')
    } catch (e) { setMsg(e.message) }
    finally { setBusy(false) }
  }

  async function handleApprove() {
    setBusy(true); setMsg('')
    try {
      const updated = await approveDraft(draft.id)
      onDraftChange(updated)
      setMsg('Approved.')
    } catch (e) { setMsg(e.message) }
    finally { setBusy(false) }
  }

  async function handleReject() {
    setBusy(true); setMsg('')
    try {
      const updated = await rejectDraft(draft.id)
      onDraftChange(updated)
      setMsg('Rejected.')
    } catch (e) { setMsg(e.message) }
    finally { setBusy(false) }
  }

  async function handleRegenerate() {
    setBusy(true); setMsg('')
    try {
      const updated = await regenerateDraft(draft.id)
      onDraftChange(updated)
      setMsg('Regenerated.')
    } catch (e) { setMsg(e.message) }
    finally { setBusy(false) }
  }

  const isDraft = draft.status === 'draft'
  const btnBase = { padding: '5px 12px', borderRadius: 6, border: 'none', cursor: busy ? 'not-allowed' : 'pointer', fontSize: 12, fontWeight: 600 }

  return (
    <div style={{ padding: '12px 16px', background: '#f9fafb', border: '1px solid #e5e7eb', borderRadius: 8, marginTop: 8 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <Pill label={draft.status} colors={DRAFT_STATUS_COLORS[draft.status] || DRAFT_STATUS_COLORS.draft} />
        {draft.angle && <span style={{ fontSize: 11, color: '#6b7280' }}>angle: {draft.angle.replace('_', ' ')}</span>}
      </div>

      <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Subject</label>
      <input
        value={subject}
        onChange={(e) => setSubject(e.target.value)}
        disabled={!isDraft || busy}
        style={{ width: '100%', padding: '6px 8px', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 13, boxSizing: 'border-box', marginBottom: 8 }}
      />

      <label style={{ fontSize: 12, fontWeight: 600, display: 'block', marginBottom: 4 }}>Body</label>
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        disabled={!isDraft || busy}
        rows={6}
        style={{ width: '100%', padding: '6px 8px', border: '1px solid #d1d5db', borderRadius: 6, fontSize: 13, boxSizing: 'border-box', marginBottom: 8, resize: 'vertical' }}
      />

      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {isDraft && (
          <button onClick={handleSave} disabled={busy} style={{ ...btnBase, background: '#e5e7eb', color: '#111' }}>Save</button>
        )}
        {isDraft && (
          <button onClick={handleApprove} disabled={busy || !restaurant.contact_email} title={!restaurant.contact_email ? 'No contact email on file' : ''} style={{ ...btnBase, background: '#16a34a', color: '#fff', opacity: restaurant.contact_email ? 1 : 0.5 }}>Approve</button>
        )}
        <button onClick={handleRegenerate} disabled={busy} style={{ ...btnBase, background: '#6366f1', color: '#fff' }}>Regenerate</button>
        {isDraft && (
          <button onClick={handleReject} disabled={busy} style={{ ...btnBase, background: '#dc2626', color: '#fff' }}>Reject</button>
        )}
        {msg && <span style={{ fontSize: 12, color: '#6b7280', alignSelf: 'center' }}>{msg}</span>}
      </div>
    </div>
  )
}

export default function OutreachDashboard() {
  const [filter, setFilter] = useState('all')
  const [leads, setLeads] = useState([])
  const [drafts, setDrafts] = useState({})
  const [loading, setLoading] = useState(true)
  const [generatingIds, setGeneratingIds] = useState(new Set())
  const [expandedIds, setExpandedIds] = useState(new Set())
  const [optingOutIds, setOptingOutIds] = useState(new Set())
  const [error, setError] = useState('')

  useEffect(() => {
    async function load() {
      setLoading(true)
      setError('')
      try {
        const [leadsData, draftsData] = await Promise.all([
          getLeads(filter === 'all' ? null : filter),
          listDrafts(),
        ])
        setLeads(leadsData)
        const byRestaurant = {}
        for (const d of draftsData) {
          if (!byRestaurant[d.restaurant_id]) byRestaurant[d.restaurant_id] = []
          byRestaurant[d.restaurant_id].push(d)
        }
        setDrafts(byRestaurant)
      } catch (e) {
        setError(e.message)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [filter])

  function getActiveDraft(restaurantId) {
    const list = drafts[restaurantId] || []
    return list.find((d) => d.status === 'draft') || list[0] || null
  }

  function handleDraftChange(restaurantId, updated) {
    setDrafts((prev) => {
      const list = (prev[restaurantId] || []).map((d) => d.id === updated.id ? updated : d)
      if (!list.find((d) => d.id === updated.id)) list.unshift(updated)
      return { ...prev, [restaurantId]: list }
    })
  }

  async function handleGenerate(restaurant) {
    setGeneratingIds((prev) => new Set([...prev, restaurant.id]))
    try {
      const draft = await generateDraft(restaurant.id)
      setDrafts((prev) => ({ ...prev, [restaurant.id]: [draft, ...(prev[restaurant.id] || [])] }))
      setExpandedIds((prev) => new Set([...prev, restaurant.id]))
    } catch (e) {
      alert(e.message)
    } finally {
      setGeneratingIds((prev) => { const s = new Set(prev); s.delete(restaurant.id); return s })
    }
  }

  async function handleOptOut(restaurant) {
    if (!window.confirm(`Mark "${restaurant.name}" as opted out? This prevents generating or approving drafts for them.`)) return
    setOptingOutIds((prev) => new Set([...prev, restaurant.id]))
    try {
      const updated = await optOut(restaurant.id)
      setLeads((prev) => prev.map((r) => r.id === updated.id ? updated : r))
    } catch (e) {
      alert(e.message)
    } finally {
      setOptingOutIds((prev) => { const s = new Set(prev); s.delete(restaurant.id); return s })
    }
  }

  function toggleExpand(id) {
    setExpandedIds((prev) => {
      const s = new Set(prev); s.has(id) ? s.delete(id) : s.add(id); return s
    })
  }

  const FILTERS = [
    { label: 'All Leads', value: 'all' },
    { label: 'Qualified', value: 'qualified' },
    { label: 'Needs Review', value: 'needs_review' },
  ]

  return (
    <div>
      <h2 style={{ fontSize: 20, fontWeight: 700, marginBottom: 4 }}>Outreach Dashboard</h2>
      <p style={{ color: '#6b7280', fontSize: 13, marginBottom: 16 }}>
        Generate, review, and approve personalised cold emails for qualified leads.
      </p>

      {/* Filter bar */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 18 }}>
        {FILTERS.map((f) => (
          <button
            key={f.value}
            onClick={() => setFilter(f.value)}
            style={{
              padding: '6px 14px', borderRadius: 20, border: '1px solid', fontSize: 13, cursor: 'pointer',
              background: filter === f.value ? '#6366f1' : '#fff',
              color: filter === f.value ? '#fff' : '#374151',
              borderColor: filter === f.value ? '#6366f1' : '#d1d5db',
              fontWeight: filter === f.value ? 600 : 400,
            }}
          >{f.label}</button>
        ))}
      </div>

      {error && <p style={{ color: '#dc2626', marginBottom: 12 }}>{error}</p>}

      {loading ? (
        <p style={{ color: '#6b7280' }}>Loading leads…</p>
      ) : leads.length === 0 ? (
        <div style={{ padding: 32, textAlign: 'center', color: '#9ca3af', background: '#f9fafb', borderRadius: 8 }}>
          No leads found. Discover and qualify restaurants on the Discovery tab first.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {leads.map((r) => {
            const activeDraft = getActiveDraft(r.id)
            const hasDraft = !!activeDraft
            const isGenerating = generatingIds.has(r.id)
            const isExpanded = expandedIds.has(r.id)
            const isOptingOut = optingOutIds.has(r.id)
            const statusColors = STATUS_COLORS[r.lead_status] || { bg: '#f3f4f6', color: '#374151' }

            return (
              <div key={r.id} style={{ background: '#fff', borderRadius: 10, padding: '16px 20px', boxShadow: '0 1px 4px rgba(0,0,0,0.07)', border: '1px solid #e5e7eb' }}>
                {/* Row header */}
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
                  <div style={{ flex: 1, minWidth: 200 }}>
                    <div style={{ fontWeight: 600, fontSize: 15 }}>{r.name}</div>
                    <div style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>{r.address || '—'}</div>
                  </div>

                  {/* Status pills */}
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                    <Pill label={r.lead_status} colors={statusColors} />
                    {r.lead_score != null && (
                      <span style={{ fontSize: 11, color: '#6b7280' }}>Score: {r.lead_score}</span>
                    )}
                    {r.website_status && r.website_status !== 'unknown' && (
                      <span style={{ fontSize: 11, background: '#f3f4f6', color: '#374151', padding: '2px 6px', borderRadius: 10 }}>
                        Site: {r.website_status}
                      </span>
                    )}
                    {r.ordering_status && r.ordering_status !== 'unknown' && (
                      <span style={{ fontSize: 11, background: '#f3f4f6', color: '#374151', padding: '2px 6px', borderRadius: 10 }}>
                        Orders: {r.ordering_status}
                      </span>
                    )}
                  </div>

                  {/* Email */}
                  <div style={{ fontSize: 12, color: r.contact_email ? '#374151' : '#9ca3af', minWidth: 160 }}>
                    {r.contact_email || 'No email found'}
                  </div>

                  {/* Action buttons */}
                  <div style={{ display: 'flex', gap: 6 }}>
                    {r.opted_out ? (
                      <span style={{ fontSize: 12, color: '#9ca3af', padding: '5px 0' }}>Opted out</span>
                    ) : hasDraft ? (
                      <button
                        onClick={() => toggleExpand(r.id)}
                        style={{ padding: '5px 12px', borderRadius: 6, border: '1px solid #6366f1', background: '#fff', color: '#6366f1', cursor: 'pointer', fontSize: 12, fontWeight: 600 }}
                      >
                        {isExpanded ? 'Hide Draft' : 'View Draft'}
                      </button>
                    ) : (
                      <button
                        onClick={() => handleGenerate(r)}
                        disabled={isGenerating || !r.contact_email}
                        title={!r.contact_email ? 'No contact email — discover contact first' : ''}
                        style={{
                          padding: '5px 12px', borderRadius: 6, border: 'none',
                          background: r.contact_email ? '#6366f1' : '#e5e7eb',
                          color: r.contact_email ? '#fff' : '#9ca3af',
                          cursor: (isGenerating || !r.contact_email) ? 'not-allowed' : 'pointer',
                          fontSize: 12, fontWeight: 600,
                        }}
                      >
                        {isGenerating ? 'Generating…' : 'Generate Draft'}
                      </button>
                    )}

                    {!r.opted_out && (
                      <button
                        onClick={() => handleOptOut(r)}
                        disabled={isOptingOut}
                        style={{ padding: '5px 10px', borderRadius: 6, border: '1px solid #e5e7eb', background: '#fff', color: '#9ca3af', cursor: 'pointer', fontSize: 11 }}
                      >
                        Opt Out
                      </button>
                    )}
                  </div>
                </div>

                {/* Lead reason */}
                {r.lead_reason && (
                  <div style={{ fontSize: 12, color: '#6b7280', marginTop: 8, paddingLeft: 2 }}>{r.lead_reason}</div>
                )}

                {/* Draft panel */}
                {isExpanded && activeDraft && (
                  <DraftPanel
                    restaurant={r}
                    draft={activeDraft}
                    onDraftChange={(updated) => handleDraftChange(r.id, updated)}
                  />
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
