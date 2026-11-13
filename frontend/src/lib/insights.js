export function summarize(restaurants, drafts) {
  return {
    total: restaurants.length,
    qualified: restaurants.filter((r) => r.lead_status === 'qualified').length,
    missingWebsites: restaurants.filter((r) => !r.website || r.website_status === 'not_found').length,
    missingOrdering: restaurants.filter((r) => r.website && r.ordering_status === 'not_found').length,
    uncheckedSites: restaurants.filter((r) => r.website && !r.website_checked_at).length,
    uncontactedSites: restaurants.filter((r) => r.website && !r.contact_discovered_at).length,
    unqualified: restaurants.filter((r) => !r.lead_status || r.lead_status === 'new').length,
    awaitingDrafts: drafts.filter((d) => d.status === 'draft').length,
  }
}

export function pendingActions(s) {
  return [
    { key: 'drafts', count: s.awaitingDrafts, label: 'drafts awaiting approval', page: 'drafts' },
    { key: 'sites', count: s.uncheckedSites, label: 'websites not checked yet', page: 'website' },
    { key: 'emails', count: s.uncontactedSites, label: 'websites without an email search', page: 'leads' },
    { key: 'qualify', count: s.unqualified, label: 'businesses not qualified', page: 'qualification' },
  ].filter((action) => action.count > 0)
}
