import { useMemo, useState } from 'react'
import { Button, ConfirmDialog, DraftBadge, EmptyState, Icon, Skeleton, useAccess } from '../components/ui'
import { ANGLE_LABEL, shortUrl, timeAgo } from '../lib/format'

const FILTERS = [
  { id: 'draft', label: 'Awaiting approval' },
  { id: 'edited', label: 'Edited' },
  { id: 'approved', label: 'Approved' },
  { id: 'rejected', label: 'Rejected' },
  { id: 'sent', label: 'Sent' },
  { id: 'all', label: 'All' },
]

export const CONFIRMS = {
  approve: {
    title: 'Approve this draft?',
    description: 'Approval records your decision. Emails are sent only from a campaign, after you confirm the send.',
    confirmLabel: 'Approve',
    tone: 'primary',
  },
  reject: {
    title: 'Reject this draft?',
    description: 'The draft is marked rejected. You can regenerate a new draft for this business afterwards.',
    confirmLabel: 'Reject',
    tone: 'danger',
  },
  regenerate: {
    title: 'Regenerate this draft?',
    description: 'This draft is rejected and a new one is written with Claude, using any instructions you added. Unsaved edits will be lost.',
    confirmLabel: 'Regenerate',
    tone: 'primary',
  },
}

// The status a person sees. A draft that was changed after it was written, and is still waiting, is Edited.
export function displayStatus(draft) {
  if (draft.sent) return 'sent'
  if (draft.status === 'draft' && draft.edited_at) return 'edited'
  return draft.status
}

function matchesFilter(draft, filterId) {
  if (filterId === 'all') return true
  if (filterId === 'draft') return draft.status === 'draft'
  return displayStatus(draft) === filterId
}

// Reasons a draft cannot be approved. The same rules the editor has always shown.
export function approvalBlockers(restaurant, dirty = false) {
  const blockers = []
  if (!restaurant) {
    blockers.push('business record not found')
  } else {
    if (restaurant.opted_out) blockers.push('business has opted out')
    if (!restaurant.contact_email) blockers.push('no contact email on file')
    else if (restaurant.contact_email_status === 'invalid') blockers.push('contact email is marked invalid')
    else if (restaurant.contact_email_classification === 'disposable') blockers.push('disposable email address')
    else if (restaurant.contact_email_classification === 'personal' && !restaurant.contact_email_reviewed_at) {
      blockers.push('personal email address awaiting manual review')
    } else if (restaurant.contact_email_status === 'unknown') blockers.push('email check failed; check again')
  }
  if (dirty) blockers.push('save your changes first')
  return blockers
}

export function DraftEditor({ draft, restaurant, busy, onSave, onAction, onDraftChange, initial }) {
  const [subject, setSubject] = useState(initial?.subject ?? draft.subject)
  const [body, setBody] = useState(initial?.body ?? draft.body)
  const [view, setView] = useState('edit')
  const [instructions, setInstructions] = useState('')
  const { canOperate } = useAccess()

  const editable = draft.status === 'draft'
  const dirty = subject !== draft.subject || body !== draft.body
  const blockers = approvalBlockers(restaurant, dirty)
  const approveBlocked = !editable || busy || blockers.length > 0

  function changeSubject(value) {
    setSubject(value)
    onDraftChange?.(value, body)
  }

  function changeBody(value) {
    setBody(value)
    onDraftChange?.(subject, value)
  }

  return (
    <>
      <div className="card-head">
        <div>
          <h3>{restaurant?.name ?? 'Unknown business'}</h3>
          <p>{restaurant?.address ?? 'No address on file'}</p>
        </div>
        <DraftBadge status={displayStatus(draft)} />
      </div>

      <div className="card-body stack">
        <dl className="draft-meta">
          <div>
            <dt>Contact email</dt>
            <dd>{restaurant?.contact_email || 'None on file'}</dd>
          </div>
          <div>
            <dt>Website</dt>
            <dd>{restaurant?.website ? shortUrl(restaurant.website) : 'None'}</dd>
          </div>
          <div>
            <dt>Pitch angle</dt>
            <dd>{ANGLE_LABEL[draft.angle] ?? 'General services'}</dd>
          </div>
          <div>
            <dt>Campaign</dt>
            <dd>{draft.campaign}</dd>
          </div>
        </dl>

        {editable && blockers.length > 0 && (
          <div className="notice notice-warn" role="status">
            <Icon name="alert" size={16} />
            <div>Approval is blocked: {blockers.join('; ')}.</div>
          </div>
        )}

        <div className="field">
          <label htmlFor="draft-subject">Subject</label>
          <input
            id="draft-subject"
            className="input"
            value={subject}
            maxLength={200}
            readOnly={!editable || !canOperate}
            onChange={(event) => changeSubject(event.target.value)}
          />
        </div>

        <div className="segmented" role="group" aria-label="Editor view">
          <button type="button" aria-pressed={view === 'edit'} onClick={() => setView('edit')}>Edit</button>
          <button type="button" aria-pressed={view === 'preview'} onClick={() => setView('preview')}>Preview</button>
        </div>

        {view === 'edit' ? (
          <div className="field">
            <label htmlFor="draft-body">Body</label>
            <textarea
              id="draft-body"
              className="textarea"
              rows={12}
              value={body}
              maxLength={3000}
              readOnly={!editable || !canOperate}
              onChange={(event) => changeBody(event.target.value)}
            />
            <span className="small muted">{body.length} / 3000 characters</span>
          </div>
        ) : (
          <div className="preview" aria-label="Email preview">
            <div className="preview-head">
              <div><strong>To:</strong> {restaurant?.contact_email || '—'}</div>
              <div><strong>Subject:</strong> {subject}</div>
            </div>
            <div className="preview-body">{body}</div>
          </div>
        )}

        {editable && (
          <div className="field">
            <label htmlFor="draft-instructions">Instructions for a new draft (optional)</label>
            <textarea
              id="draft-instructions"
              className="textarea"
              rows={2}
              value={instructions}
              maxLength={500}
              placeholder="For example: shorter, more formal, mention the free site survey"
              readOnly={!canOperate}
              onChange={(event) => setInstructions(event.target.value)}
            />
            <span className="small muted">Used only when you regenerate. Facts still come from the business record.</span>
          </div>
        )}
      </div>

      <div className="card-foot editor-actions">
        <span className="small muted">Approving records your decision. Emails are sent only from a campaign, after you confirm.</span>
        <div className="group">
          <Button variant="ghost" className="is-danger" onClick={() => onAction('reject')} disabled={!editable || busy}>
            Reject
          </Button>
          <Button variant="secondary" icon="refresh" onClick={() => onAction('regenerate', instructions)} disabled={!editable || busy}>
            Regenerate
          </Button>
          <Button variant="secondary" onClick={() => onSave(subject, body)} disabled={!editable || !dirty || busy}>
            Save changes
          </Button>
          <Button variant="primary" onClick={() => onAction('approve')} disabled={approveBlocked}>
            Approve
          </Button>
        </div>
      </div>
    </>
  )
}

export default function OutreachDrafts({ drafts, restaurants, loading, isBusy, onSave, onApprove, onReject, onRegenerate }) {
  const [filterId, setFilterId] = useState('draft')
  const [selectedId, setSelectedId] = useState(null)
  const [pending, setPending] = useState(null)
  // Unsaved edits, kept per draft, so moving between drafts does not lose them.
  const [unsaved, setUnsaved] = useState({})
  const [checkedIds, setCheckedIds] = useState(() => new Set())
  const [bulkOpen, setBulkOpen] = useState(false)

  const restaurantsById = useMemo(() => new Map(restaurants.map((r) => [r.id, r])), [restaurants])
  const visible = drafts.filter((d) => matchesFilter(d, filterId))
  const selected = visible.find((d) => d.id === selectedId) ?? visible[0] ?? null

  // Only drafts that are waiting, have no unsaved edits, and pass every approval rule can be approved in bulk.
  const bulkDrafts = drafts.filter((d) => checkedIds.has(d.id))
  const bulkReady = bulkDrafts.filter((d) => d.status === 'draft' && !unsaved[d.id]
    && approvalBlockers(restaurantsById.get(d.restaurant_id)).length === 0)
  const bulkSkipped = bulkDrafts.length - bulkReady.length

  const handlers = { approve: onApprove, reject: onReject, regenerate: onRegenerate }

  function toggleChecked(id) {
    setCheckedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  function setDraftUnsaved(draft, subject, body) {
    setUnsaved((prev) => {
      const next = { ...prev }
      if (subject === draft.subject && body === draft.body) delete next[draft.id]
      else next[draft.id] = { subject, body }
      return next
    })
  }

  function clearUnsaved(id) {
    setUnsaved((prev) => {
      const next = { ...prev }
      delete next[id]
      return next
    })
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Outreach drafts</h2>
          <p>Review each email, edit it if needed, and approve it. Emails are sent only from a campaign, after you confirm.</p>
        </div>
      </div>

      <div className="segmented" role="group" aria-label="Filter drafts by status">
        {FILTERS.map((f) => (
          <button key={f.id} type="button" aria-pressed={filterId === f.id} onClick={() => setFilterId(f.id)}>
            {f.label}
            <span className="count">{drafts.filter((d) => matchesFilter(d, f.id)).length}</span>
          </button>
        ))}
      </div>

      {checkedIds.size > 0 && (
        <div className="batch-bar" role="region" aria-label="Bulk approval">
          <span>{checkedIds.size} selected</span>
          <Button variant="primary" size="sm" icon="check" disabled={bulkReady.length === 0 || !!isBusy('bulk-approve')}
            onClick={() => setBulkOpen(true)}>
            Approve selected ({bulkReady.length})
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setCheckedIds(new Set())}>Clear selection</Button>
          {bulkSkipped > 0 && <span className="small muted">{bulkSkipped} cannot be approved yet and will be skipped.</span>}
        </div>
      )}

      {loading ? (
        <div className="split">
          <section className="card card-body stack"><Skeleton height={60} /><Skeleton height={60} /></section>
          <section className="card card-body"><Skeleton height={240} /></section>
        </div>
      ) : (
        <div className="split">
          <section className="card card-flush" aria-label="Draft list">
            {visible.length === 0 ? (
              <EmptyState icon="mail" title="No drafts here">
                Select leads on the Leads page and choose Email selected to write one email per business.
              </EmptyState>
            ) : (
              <div className="draft-list">
                {visible.map((d) => {
                  const r = restaurantsById.get(d.restaurant_id)
                  const canCheck = d.status === 'draft'
                  return (
                    <div key={d.id} className="draft-row">
                      {canCheck && (
                        <input
                          type="checkbox"
                          className="checkbox draft-check"
                          aria-label={`Select the draft for ${r?.name ?? `business ${d.restaurant_id}`} for bulk approval`}
                          checked={checkedIds.has(d.id)}
                          onChange={() => toggleChecked(d.id)}
                        />
                      )}
                      <button
                        type="button"
                        className="draft-item"
                        aria-pressed={selected?.id === d.id}
                        onClick={() => setSelectedId(d.id)}
                      >
                        <span className="draft-item-title">{r?.name ?? `Business #${d.restaurant_id}`}</span>
                        <span className="draft-item-sub">{unsaved[d.id]?.subject ?? d.subject}</span>
                        <span className="draft-item-foot">
                          <DraftBadge status={displayStatus(d)} />
                          {unsaved[d.id] && <span className="small muted">Unsaved changes</span>}
                          <span className="small muted">{timeAgo(d.updated_at)}</span>
                        </span>
                      </button>
                    </div>
                  )
                })}
              </div>
            )}
          </section>

          <section className="card" aria-label="Draft editor">
            {selected ? (
              <DraftEditor
                key={selected.id}
                draft={selected}
                restaurant={restaurantsById.get(selected.restaurant_id)}
                busy={isBusy(`draftact:${selected.id}`)}
                initial={unsaved[selected.id] ?? null}
                onDraftChange={(subject, body) => setDraftUnsaved(selected, subject, body)}
                onSave={async (subject, body) => {
                  const saved = await onSave(selected, subject, body)
                  if (saved) clearUnsaved(selected.id)
                }}
                onAction={(action, instructions) => setPending({ action, draft: selected, instructions })}
              />
            ) : (
              <EmptyState icon="mail" title="Select a draft">
                Choose a draft from the list to review and edit it.
              </EmptyState>
            )}
          </section>
        </div>
      )}

      <ConfirmDialog
        open={pending !== null}
        title={pending ? CONFIRMS[pending.action].title : ''}
        description={pending ? CONFIRMS[pending.action].description : ''}
        confirmLabel={pending ? CONFIRMS[pending.action].confirmLabel : ''}
        tone={pending ? CONFIRMS[pending.action].tone : 'primary'}
        busy={pending ? isBusy(`draftact:${pending.draft.id}`) : false}
        onCancel={() => setPending(null)}
        onConfirm={async () => {
          const { action, draft, instructions } = pending
          if (action === 'regenerate') {
            await onRegenerate(draft, instructions)
            clearUnsaved(draft.id)
          } else {
            await handlers[action](draft)
          }
          setPending(null)
        }}
      />

      <ConfirmDialog
        open={bulkOpen}
        title={`Approve ${bulkReady.length} draft${bulkReady.length === 1 ? '' : 's'}?`}
        description={`Each draft is approved on its own. Nothing is sent until you start sending from a campaign.${bulkSkipped > 0 ? ` ${bulkSkipped} selected draft${bulkSkipped === 1 ? ' is' : 's are'} skipped because ${bulkSkipped === 1 ? 'it has' : 'they have'} unsaved changes or a blocked approval.` : ''}`}
        confirmLabel={`Approve ${bulkReady.length}`}
        tone="primary"
        busy={isBusy('bulk-approve')}
        onCancel={() => setBulkOpen(false)}
        onConfirm={async () => {
          for (const draft of bulkReady) {
            await onApprove(draft)
          }
          setCheckedIds(new Set())
          setBulkOpen(false)
        }}
      />
    </>
  )
}
