import { describe, expect, it } from 'vitest'
import { pendingActions, summarize } from '../../src/lib/insights'

describe('summarize', () => {
  it('counts the pipeline from restaurants and drafts', () => {
    const restaurants = [
      { website: 'https://a.pk', website_checked_at: null, website_status: null, ordering_status: null, contact_discovered_at: null, lead_status: null },
      { website: 'https://b.pk', website_checked_at: 'x', website_status: 'not_found', ordering_status: 'not_found', contact_discovered_at: 'x', lead_status: 'qualified' },
      { website: null, website_checked_at: null, website_status: null, ordering_status: null, contact_discovered_at: null, lead_status: 'new' },
    ]
    const drafts = [{ status: 'draft' }, { status: 'approved' }, { status: 'draft' }]
    expect(summarize(restaurants, drafts)).toEqual({
      total: 3,
      qualified: 1,
      missingWebsites: 2,
      missingOrdering: 1,
      uncheckedSites: 1,
      uncontactedSites: 1,
      unqualified: 2,
      awaitingDrafts: 2,
    })
  })
})

describe('pendingActions', () => {
  it('lists only the work that is waiting, in a fixed order', () => {
    const actions = pendingActions({
      awaitingDrafts: 2,
      uncheckedSites: 0,
      uncontactedSites: 4,
      unqualified: 1,
    })
    expect(actions.map((a) => a.key)).toEqual(['drafts', 'emails', 'qualify'])
    expect(actions[0]).toMatchObject({ count: 2, page: 'drafts' })
  })

  it('returns nothing when there is no pending work', () => {
    expect(pendingActions({ awaitingDrafts: 0, uncheckedSites: 0, uncontactedSites: 0, unqualified: 0 })).toEqual([])
  })
})
