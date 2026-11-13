import { useEffect, useState } from 'react'
import { Button, Modal } from './ui'
import { previewCampaign } from '../services/api'

const NAME_MIN = 2

function defaultCampaignName() {
  return `Outreach ${new Date().toISOString().slice(0, 10)}`
}

function cleanName(value) {
  return value.trim().replace(/\s+/g, ' ')
}

export default function CampaignSetupDialog({ open, restaurantIds, onClose, onCreate }) {
  const [name, setName] = useState(defaultCampaignName)
  const [plan, setPlan] = useState(null)
  const [previewError, setPreviewError] = useState('')
  const [loadingPlan, setLoadingPlan] = useState(false)
  const [creating, setCreating] = useState(false)

  const idsKey = restaurantIds.join(',')
  const clean = cleanName(name)
  const nameError = clean.length < NAME_MIN ? `Campaign name needs at least ${NAME_MIN} characters.` : ''

  useEffect(() => {
    if (open) setName(defaultCampaignName())
  }, [open])

  useEffect(() => {
    if (!open || nameError) {
      setPlan(null)
      return undefined
    }
    let active = true
    const ids = idsKey.split(',').filter(Boolean).map(Number)
    setLoadingPlan(true)
    const timer = setTimeout(() => {
      previewCampaign(clean, ids)
        .then((result) => { if (active) { setPlan(result); setPreviewError('') } })
        .catch((err) => { if (active) { setPlan(null); setPreviewError(err.message) } })
        .finally(() => { if (active) setLoadingPlan(false) })
    }, 350)
    return () => {
      active = false
      clearTimeout(timer)
    }
  }, [open, clean, idsKey])

  const eligibleCount = plan?.eligible_count ?? 0
  const skipped = plan?.items.filter((i) => !i.eligible) ?? []

  async function handleCreate() {
    if (!plan || eligibleCount === 0) return
    setCreating(true)
    const ok = await onCreate(clean, restaurantIds)
    setCreating(false)
    if (ok) onClose()
  }

  return (
    <Modal
      open={open}
      title="Email selected businesses"
      description="Writes one personalized draft per eligible business. Nothing is sent until you review the drafts and confirm sending."
      onClose={onClose}
      size="lg"
      footer={(
        <>
          <Button variant="secondary" readOnlyOk onClick={onClose} disabled={creating}>Cancel</Button>
          <Button
            variant="primary"
            icon="mail"
            onClick={handleCreate}
            disabled={creating || loadingPlan || !plan || eligibleCount === 0 || Boolean(nameError)}
          >
            {creating ? 'Starting…' : `Generate ${eligibleCount} draft${eligibleCount === 1 ? '' : 's'}`}
          </Button>
        </>
      )}
    >
      <div className="stack">
        <div className="field">
          <label className="field-label" htmlFor="campaign-name">Campaign name</label>
          <input
            id="campaign-name"
            className="input"
            value={name}
            maxLength={80}
            placeholder="e.g. Lahore cafes, May"
            aria-invalid={Boolean(nameError) || undefined}
            aria-describedby="campaign-name-help"
            onChange={(event) => setName(event.target.value)}
          />
          {nameError
            ? <span className="field-error" id="campaign-name-help" role="alert">{nameError}</span>
            : <span className="field-hint" id="campaign-name-help">A business or address already emailed by any campaign in this workspace is skipped.</span>}
        </div>

        {previewError && <div className="notice notice-bad" role="alert">{previewError}</div>}

        {loadingPlan && !plan && <div className="muted small">Checking eligibility…</div>}

        {plan && (
          <>
            <div className="plan-summary" aria-live="polite">
              <div><span className="metric-label">Selected</span><strong>{plan.eligible_count + plan.skipped_count}</strong></div>
              <div><span className="metric-label">Eligible</span><strong>{plan.eligible_count}</strong></div>
              <div><span className="metric-label">Skipped</span><strong>{plan.skipped_count}</strong></div>
            </div>

            {skipped.length > 0 && (
              <div>
                <h4 className="plan-heading">Skipped and why</h4>
                <ul className="plan-list">
                  {skipped.map((item) => (
                    <li key={item.restaurant_id}>
                      <strong>{item.restaurant_name ?? `Business #${item.restaurant_id}`}</strong>
                      <span className="muted"> — {item.reasons.join('; ')}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {eligibleCount === 0 && (
              <div className="notice notice-warn" role="status">None of the selected businesses can be emailed in this campaign.</div>
            )}
          </>
        )}
      </div>
    </Modal>
  )
}
