/**
 * In-memory fake of the backend API that the frontend calls.
 *
 * It mirrors the response shapes the pages read, and the eligibility rules in
 * backend/services/campaigns.py (outreach_reasons and preview). It does nothing else:
 * no database, no network, no Google Places, no Claude, no mailbox and no email.
 * Vitest reaches it through MSW (tests/support/mswServer.js). Playwright reaches it through
 * page.route (tests/e2e/support/mockApi.js). Both use this same file.
 */

const PLACEHOLDER_DOMAINS = new Set([
  'example.com', 'example.org', 'example.net', 'test.com', 'domain.com', 'email.com', 'localhost',
])
const EMAIL_PATTERN = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/
const DISPOSABLE_DOMAINS = new Set(['mailinator.com', 'tempmail.com', 'guerrillamail.com', '10minutemail.com'])
const PERSONAL_DOMAINS = new Set(['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com'])
const SENT_STATES = new Set(['queued', 'sending', 'sent', 'failed', 'interrupted'])

export function isValidBusinessEmail(email) {
  if (!email || !EMAIL_PATTERN.test(email)) return false
  return !PLACEHOLDER_DOMAINS.has(email.split('@')[1].toLowerCase())
}

/** Classification the real backend derives from the address domain. */
export function classifyEmail(email) {
  if (!email) return null
  const domain = email.split('@')[1]?.toLowerCase() ?? ''
  if (DISPOSABLE_DOMAINS.has(domain)) return 'disposable'
  if (PERSONAL_DOMAINS.has(domain)) return 'personal'
  return 'business'
}

/** Port of outreach_reasons() in backend/services/campaigns.py. An empty list means eligible. */
export function outreachReasons(r, suppressed = new Set()) {
  const reasons = []
  if (r.source !== 'google_places') reasons.push('Demo or sample record, not a real restaurant')
  if (r.listing_expired) reasons.push('Google listing expired; search again to refresh it before emailing')
  if (r.opted_out) reasons.push('Business has opted out of outreach')
  const email = r.contact_email
  if (!email) {
    reasons.push('No public email found')
  } else if (r.contact_email_status === 'invalid') {
    reasons.push('Contact email is marked invalid')
  } else if (!isValidBusinessEmail(email)) {
    reasons.push('Email is not a valid business address')
  } else if (suppressed.has(email.toLowerCase())) {
    reasons.push('Email is on the suppression list')
  }
  if (email && r.contact_email_classification === 'disposable') {
    reasons.push('Disposable email address: not accepted for outreach')
  }
  if (email && r.contact_email_classification === 'personal' && !r.contact_email_reviewed_at) {
    reasons.push('Personal email address: needs manual review before outreach')
  }
  if (r.lead_status !== 'qualified') {
    reasons.push(`Not qualified (current status: ${r.lead_status || 'new'})`)
  }
  return reasons
}

/** A restaurant record with every field the frontend reads. Pass overrides for the case under test. */
export function makeRestaurant(overrides = {}) {
  const stamp = new Date('2026-11-01T09:00:00Z').toISOString()
  return {
    id: 0,
    name: 'Business',
    address: 'Main Boulevard, Gulberg, Lahore, Pakistan',
    city: 'Lahore',
    phone: null,
    website: null,
    place_id: null,
    source: 'google_places',
    listing_expired: false,
    website_status: null,
    website_checked_at: null,
    website_error: null,
    ordering_status: null,
    ordering_evidence: [],
    contact_email: null,
    contact_email_status: null,
    contact_email_classification: null,
    contact_email_reasons: [],
    contact_email_checked_at: null,
    contact_email_reviewed_at: null,
    contact_discovered_at: null,
    lead_status: null,
    lead_score: null,
    lead_reason: null,
    lead_qualified_at: null,
    opted_out: false,
    created_at: stamp,
    updated_at: stamp,
    ...overrides,
  }
}

class ApiError extends Error {
  constructor(status, detail) {
    super(detail)
    this.status = status
    this.detail = detail
  }
}

const fail = (status, detail) => {
  throw new ApiError(status, detail)
}

const clone = (value) => JSON.parse(JSON.stringify(value))

/**
 * Creates one isolated backend. Each test creates its own, so no state leaks between tests.
 *
 * seed keys (all optional):
 *   restaurants, drafts, campaigns, suppressed (array of lowercase emails), reviewQueue,
 *   discoveryMode, config, password, authRequired, authenticated,
 *   discoverCatalog ({ [city]: restaurant[] }, used when demo_mode is false),
 *   checkResults ({ [id]: { website_status, ordering_status, ordering_evidence, website_error } }),
 *   contactResults ({ [id]: email | null }), emailCheckResults ({ [id]: status }),
 *   failSendTo (array of addresses the mock provider rejects),
 *   failDraftFor (array of restaurant ids whose draft writing fails),
 *   failures ({ 'METHOD /path': { status, detail } | 'network' }),
 *   sendBatch (recipients processed per poll while sending; default 1)
 */
export function createFakeBackend(seed = {}) {
  const state = {
    // One admin account signed in by default, so most tests start in a workspace. Seeds can add accounts
    // and change who is signed in.
    accounts: [{
      id: 1,
      name: 'Test Admin',
      email: 'admin@example.test',
      password: 'test-password',
      role: 'admin',
      status: 'active',
      created_at: '2026-11-01T09:00:00Z',
      last_login_at: null,
      password_changed_at: '2026-11-01T09:00:00Z',
    }],
    sessionUserId: 1,
    authenticated: true,
    audit: [],
    // Workspace 1 is the default workspace. An account with no explicit membership there keeps its global role.
    workspaces: [{ id: 1, name: 'Default workspace', status: 'active', created_at: '2026-11-01T09:00:00Z', memberships: {} }],
    sessionWorkspaceId: 1,
    invitations: [],
    discoveryMode: { demo_mode: true, live_key_configured: false },
    config: {
      per_minute: 5,
      daily_limit: 100,
      sent_today: 0,
      unsubscribe_ready: true,
      live_sending: false,
    },
    restaurants: [],
    drafts: [],
    campaigns: [],
    logs: [],
    suppressed: [],
    reviewQueue: [],
    discoverCatalog: {},
    checkResults: {},
    contactResults: {},
    emailCheckResults: {},
    failSendTo: [],
    failDraftFor: [],
    failures: {},
    sendBatch: 1,
    lastDiscover: null,
    sequence: 1000,
    ...clone(seed),
  }
  state.restaurants = state.restaurants.map((r) => makeRestaurant(r))
  state.suppressed = new Set(state.suppressed)
  state.config = { ...state.config }

  const nextId = () => {
    state.sequence += 1
    return state.sequence
  }
  const now = () => new Date().toISOString()
  const restaurantById = (id) => state.restaurants.find((r) => r.id === Number(id) && !r.deleted_at)
  const draftById = (id) => state.drafts.find((d) => d.id === Number(id))
  const campaignById = (id) => state.campaigns.find((c) => c.id === Number(id))
  const snapshot = (r) => clone(r)
  // Soft delete, as the server does it: the row stays, marked with deleted_at. Only this workspace's leads are touched.
  function deleteLeadFake(id) {
    const r = state.restaurants.find((x) => x.id === Number(id) && !x.deleted_at)
    if (!r) fail(404, 'Business not found.')
    r.deleted_at = now()
    return { deleted: [r.id] }
  }

  function bulkDeleteFake(body) {
    const wanted = [...new Set((body.ids ?? []).map(Number))]
    const deleted = []
    for (const id of wanted) {
      const r = state.restaurants.find((x) => x.id === id && !x.deleted_at)
      if (r) { r.deleted_at = now(); deleted.push(id) }
    }
    return { deleted, missing: wanted.filter((id) => !deleted.includes(id)) }
  }

  function restoreLeadFake(id) {
    const r = state.restaurants.find((x) => x.id === Number(id) && x.deleted_at)
    if (!r) fail(404, 'No deleted business with this id.')
    r.deleted_at = null
    return r
  }

  const requireRestaurant = (id) => {
    const r = restaurantById(id)
    if (!r) fail(404, 'Restaurant not found.')
    return r
  }
  const requireCampaign = (id) => {
    const c = campaignById(id)
    if (!c) fail(404, 'Campaign not found.')
    return c
  }
  const paginate = (rows, query) => {
    const limit = query.get('limit')
    if (limit === null) return rows
    const offset = Number(query.get('offset') ?? 0)
    return rows.slice(offset, offset + Number(limit))
  }
  const logEntry = (campaign, event, recipient, detail) => {
    state.logs.push({
      id: nextId(),
      campaign_id: campaign.id,
      created_at: now(),
      event,
      recipient_email: recipient?.recipient_email ?? null,
      detail,
    })
  }

  // Restaurant actions

  function checkWebsite(r) {
    if (!r.website) fail(422, 'This restaurant has no website to check.')
    const result = state.checkResults[r.id] ?? {}
    r.website_status = result.website_status ?? 'present'
    r.website_error = result.website_error ?? null
    r.ordering_status = r.website_status === 'present' ? (result.ordering_status ?? 'not_found') : 'unknown'
    r.ordering_evidence = result.ordering_evidence ?? (r.ordering_status === 'present' ? [`${r.website}/order`] : [])
    r.website_checked_at = now()
    r.updated_at = now()
    return r
  }

  function discoverContact(r) {
    if (!r.website) fail(422, 'This restaurant has no website to search for an email.')
    const found = state.contactResults[r.id]
    r.contact_discovered_at = now()
    if (found) {
      r.contact_email = found
      r.contact_email_status = 'unverified'
      r.contact_email_classification = classifyEmail(found)
      r.contact_email_reviewed_at = null
      r.contact_email_checked_at = null
    }
    r.updated_at = now()
    return r
  }

  function verifyEmail(r) {
    if (!r.contact_email) fail(422, 'No contact email to check.')
    r.contact_email_checked_at = now()
    r.contact_email_status = state.emailCheckResults[r.id]
      ?? (isValidBusinessEmail(r.contact_email) ? 'domain_valid' : 'invalid')
    r.updated_at = now()
    return r
  }

  function qualify(r) {
    let score = 0
    const signals = []
    if (r.website_status === 'present') {
      score += 30
      signals.push('live website')
    }
    if (r.website_status === 'not_found') {
      score -= 40
      signals.push('website not found')
    }
    if (r.website && r.ordering_status === 'not_found') {
      score += 25
      signals.push('no online ordering')
    }
    if (r.ordering_status === 'present') {
      score -= 20
      signals.push('online ordering found')
    }
    const usable = Boolean(r.contact_email)
      && isValidBusinessEmail(r.contact_email)
      && r.contact_email_status !== 'invalid'
      && r.contact_email_classification !== 'disposable'
    if (usable) {
      score += 25
      signals.push('usable email')
    }
    if (r.phone) {
      score += 10
      signals.push('phone listed')
    }
    r.lead_score = score
    r.lead_status = score >= 55 ? 'qualified' : score >= 20 ? 'needs_review' : 'disqualified'
    r.lead_reason = `Score ${score}: ${signals.join(', ') || 'no signals'}.`
    r.lead_qualified_at = now()
    r.updated_at = now()
    return r
  }

  function optOut(r) {
    r.opted_out = true
    if (r.contact_email) state.suppressed.add(r.contact_email.toLowerCase())
    r.updated_at = now()
    return r
  }

  // Mirrors the server: only a needs_review lead changes; the score is kept.
  function manualQualifyFake(r, body) {
    if (r.opted_out) fail(422, 'This business has opted out of outreach.')
    if (r.lead_status !== 'needs_review') fail(422, 'Only a lead that needs review can be marked qualified by hand.')
    const note = String(body.note ?? '').trim()
    r.lead_status = 'qualified'
    r.lead_reason = 'Qualified by manual review' + (note ? `: ${note}` : '')
    r.lead_qualified_at = now()
    return r
  }

  function reviewEmail(r, decision) {
    if (!r.contact_email) fail(422, 'No contact email to review.')
    if (decision !== 'approve' && decision !== 'reject') fail(422, 'Decision must be approve or reject.')
    r.contact_email_reviewed_at = now()
    if (decision === 'reject') r.contact_email_status = 'invalid'
    r.updated_at = now()
    return r
  }

  // Industry profiles as the backend serves them (GET /industries). Test data for the search form.
  const INDUSTRY_OPTIONS = [
    {
      key: 'restaurants_food', name: 'Food & Beverage', business_noun: 'restaurant', primary_feature: 'ordering',
      subcategories: [{ key: 'all', name: 'All businesses' }, { key: 'biryani', name: 'Biryani' }],
      features: [{ key: 'ordering', label: 'Online ordering' }], custom_fields: [],
    },
    {
      key: 'real_estate', name: 'Real Estate & Property', business_noun: 'real estate business', primary_feature: 'inquiry_form',
      subcategories: [
        { key: 'agency', name: 'Property agency' },
        { key: 'developer', name: 'Property developer' },
        { key: 'rentals', name: 'Rentals and property management' },
      ],
      features: [{ key: 'inquiry_form', label: 'Inquiry form' }], custom_fields: [],
    },
    {
      key: 'education', name: 'Education & Training', business_noun: 'education provider', primary_feature: 'admissions',
      subcategories: [{ key: 'school', name: 'Schools and academies' }, { key: 'training', name: 'Training and courses' }],
      features: [{ key: 'admissions', label: 'Admissions and applications' }], custom_fields: [],
    },
    {
      key: 'home_services', name: 'Home Services & Construction', business_noun: 'contractor', primary_feature: 'quote_request',
      subcategories: [{ key: 'construction', name: 'Construction contractors' }, { key: 'cleaning', name: 'Cleaning and maintenance' }],
      features: [{ key: 'quote_request', label: 'Quote request' }], custom_fields: [],
    },
    {
      key: 'healthcare', name: 'Healthcare & Clinics', business_noun: 'clinic', primary_feature: 'appointments',
      subcategories: [{ key: 'clinic', name: 'Clinics' }, { key: 'dental', name: 'Dental clinics' }],
      features: [{ key: 'appointments', label: 'Online appointments' }], custom_fields: [],
    },
  ]

  // Country names and the city database, as the backend serves it (GET /geo/countries/:cc/cities, GET /geo/status).
  // The database rows are a small sample: the five required countries plus enough Pakistani cities to page through.
  const COUNTRY_NAMES = { PK: 'Pakistan', US: 'United States', GB: 'United Kingdom', AE: 'United Arab Emirates', AU: 'Australia', CA: 'Canada' }
  const PAKISTAN_CITY_LIST = ['Abbottabad', 'Bahawalpur', 'Faisalabad', 'Gujranwala', 'Hyderabad', 'Islamabad', 'Jhelum', 'Karachi', 'Lahore', 'Mardan', 'Multan', 'Peshawar', 'Quetta', 'Rahim Yar Khan', 'Rawalpindi', 'Sargodha', 'Sheikhupura', 'Sialkot', 'Sukkur']
  const GEO_CITIES = [
    { id: 1172451, country: 'PK', name: 'Lahore', admin1: 'Punjab', population: 13004135, alt: [] },
    { id: 1179400, country: 'PK', name: 'Faisalabad', admin1: 'Punjab', population: 3800193, alt: ['Lyallpur'] },
    ...PAKISTAN_CITY_LIST
      .filter((name) => name !== 'Lahore' && name !== 'Faisalabad')
      .map((name, index) => ({ id: 900000 + index, country: 'PK', name, admin1: null, population: 500000 - index * 1000, alt: [] })),
    { id: 5128581, country: 'US', name: 'New York City', admin1: 'New York', population: 8804190, alt: ['NYC'] },
    { id: 2643743, country: 'GB', name: 'London', admin1: 'England', population: 8961989, alt: [] },
    { id: 6058560, country: 'CA', name: 'London', admin1: 'Ontario', population: 422324, alt: [] },
    { id: 292223, country: 'AE', name: 'Dubai', admin1: 'Dubai', population: 3790000, alt: [] },
    { id: 2147714, country: 'AU', name: 'Sydney', admin1: 'New South Wales', population: 5638830, alt: [] },
  ]

  const foldText = (text) => String(text).normalize('NFKD').replace(/[̀-ͯ]/g, '')
    .replace(/[-'’.]/g, ' ').replace(/\s+/g, ' ').trim().toLowerCase()

  // One country only. Main names rank above alternate-name matches, then the more populated city comes first.
  function citySearch(code, q, limit, offset) {
    const needle = foldText(q)
    const hits = GEO_CITIES.filter((c) => c.country === code).flatMap((c) => {
      if (foldText(c.name).startsWith(needle)) return [{ c, alias: null, byName: 1 }]
      const alias = c.alt.find((a) => foldText(a).startsWith(needle))
      return alias ? [{ c, alias, byName: 0 }] : []
    })
    hits.sort((a, b) => (b.byName - a.byName) || (b.c.population - a.c.population))
    const page = hits.slice(offset, offset + limit + 1)
    return {
      items: page.slice(0, limit).map(({ c, alias }) => ({
        id: c.id, name: c.name, admin1_name: c.admin1, country_code: code, population: c.population, matched_alias: alias,
      })),
      limit,
      offset,
      has_more: page.length > limit,
      source: 'geonames',
    }
  }

  function discover(body) {
    const countryCode = String(body.country_code ?? 'PK').toUpperCase()
    const picked = body.city_id != null ? GEO_CITIES.find((c) => c.id === Number(body.city_id)) : null
    if (body.city_id != null && (!picked || picked.country !== countryCode)) {
      fail(422, `That city is not in ${COUNTRY_NAMES[countryCode] ?? countryCode}. Pick it again from the list.`)
    }
    const city = picked ? picked.name : String(body.city ?? '').trim()
    const limit = Number(body.limit ?? 10)
    if (!city) fail(422, 'City is required.')
    if (!Number.isInteger(limit) || limit < 1 || limit > 60) fail(422, 'Choose between 1 and 60 results.')
    const countryName = COUNTRY_NAMES[countryCode] ?? countryCode
    const record = { city, category: body.category ?? 'all', limit, country_code: countryCode }
    if (picked) record.city_id = picked.id
    if (body.industry) record.industry = body.industry
    if (body.subcategory) record.subcategory = body.subcategory
    state.lastDiscover = record
    const otherIndustry = body.industry && body.industry !== 'restaurants_food'
    const noun = otherIndustry ? 'sample business' : 'sample business'
    const candidates = state.discoveryMode.demo_mode
      ? [1, 2, 3].map((i) => makeRestaurant({
        name: `[DEMO] ${city} ${noun} ${i}`,
        address: `${i} Main Road, ${city}, ${countryName}`,
        city,
        country_code: countryCode,
        country_name: countryName,
        source: 'demo',
        industry: body.industry ?? 'restaurants_food',
        subcategory: body.subcategory ?? null,
        place_id: `demo-${countryCode.toLowerCase()}-${body.industry ?? ''}-${city.toLowerCase().replace(/\s+/g, '-')}-${i}`,
      }))
      : (state.discoverCatalog[city] ?? []).map((r) => makeRestaurant(r))
    const fresh = candidates
      .filter((c) => !state.restaurants.some((r) => r.place_id && r.place_id === c.place_id))
      .slice(0, limit)
    fresh.forEach((c) => {
      c.id = nextId()
      state.restaurants.push(c)
    })
    return fresh.map(snapshot)
  }

  // Drafts

  function draftGateReasons(r) {
    const reasons = []
    if (r.source !== 'google_places') reasons.push('Demo or sample record, not a real restaurant')
    if (r.opted_out) reasons.push('Business has opted out of outreach')
    if (!r.contact_email) reasons.push('No public email found')
    else if (r.contact_email_status === 'invalid') reasons.push('Contact email is marked invalid')
    else if (r.contact_email_classification === 'disposable') reasons.push('Disposable email address: not accepted for outreach')
    return reasons
  }

  function approvalGateReasons(r) {
    const reasons = draftGateReasons(r)
    if (reasons.length) return reasons
    if (r.contact_email_status === 'unknown') reasons.push('Email check failed; check again')
    if (r.contact_email_classification === 'personal' && !r.contact_email_reviewed_at) {
      reasons.push('Personal email address: needs manual review before outreach')
    }
    return reasons
  }

  function writeDraft(r, campaignName, campaignId) {
    if (state.failDraftFor.includes(r.id)) fail(502, 'The draft could not be written. Try again.')
    const angle = r.ordering_status === 'not_found' ? 'ordering_gap' : 'general'
    const draft = {
      id: nextId(),
      restaurant_id: r.id,
      campaign: campaignName,
      campaign_id: campaignId ?? null,
      subject: `Online ordering for ${r.name}`,
      body: `Hello ${r.name} team,\n\nWe help Pakistani restaurants take orders online. Would you be open to a short call?`,
      angle,
      status: 'draft',
      created_at: now(),
      updated_at: now(),
    }
    state.drafts.push(draft)
    return draft
  }

  function generateDraft(body) {
    const r = requireRestaurant(body.restaurant_id)
    const reasons = draftGateReasons(r)
    if (reasons.length) fail(422, reasons.join('. '))
    return writeDraft(r, body.campaign ?? 'default', null)
  }

  function updateDraft(d, body) {
    if (d.status !== 'draft') fail(409, 'Only drafts awaiting approval can be edited.')
    if (!String(body.subject ?? '').trim()) fail(422, 'Subject is required.')
    if (String(body.body ?? '').length > 3000) fail(422, 'Body must be 3000 characters or fewer.')
    const changed = d.subject !== body.subject || d.body !== body.body
    d.subject = body.subject
    d.body = body.body
    d.updated_at = now()
    if (changed) d.edited_at = now()
    return d
  }

  function approveDraft(d) {
    if (d.status !== 'draft') fail(409, `Draft is already ${d.status}.`)
    const reasons = approvalGateReasons(requireRestaurant(d.restaurant_id))
    if (reasons.length) fail(422, reasons.join('; '))
    d.status = 'approved'
    d.updated_at = now()
    return d
  }

  function rejectDraft(d) {
    if (d.status !== 'draft') fail(409, `Draft is already ${d.status}.`)
    d.status = 'rejected'
    d.updated_at = now()
    return d
  }

  function regenerateDraft(d) {
    if (d.status !== 'draft' && d.status !== 'rejected') fail(409, 'This draft cannot be regenerated.')
    const r = requireRestaurant(d.restaurant_id)
    const fresh = writeDraft(r, d.campaign, d.campaign_id)
    if (d.status === 'draft') d.status = 'rejected'
    state.campaigns.forEach((c) => c.recipients.forEach((rc) => {
      if (rc.draft_id === d.id) rc.draft_id = fresh.id
    }))
    return fresh
  }

  // Campaigns

  function previewPlan(name, restaurantIds) {
    const alreadySent = new Set()
    const pendingDraft = new Set()
    const emailsSent = new Set()
    state.campaigns
      .filter((c) => c.name === name)
      .forEach((c) => c.recipients.forEach((rc) => {
        if (SENT_STATES.has(rc.status)) {
          alreadySent.add(rc.restaurant_id)
          if (rc.recipient_email) emailsSent.add(rc.recipient_email.toLowerCase())
        }
        if (rc.status === 'draft') pendingDraft.add(rc.restaurant_id)
      }))
    // Workspace-wide: any campaign in this workspace that already emails a restaurant or address blocks it.
    const elsewhereRestaurant = new Map()
    const elsewhereEmail = new Map()
    state.campaigns.forEach((c) => c.recipients.forEach((rc) => {
      if (!['queued', 'sending', 'sent', 'interrupted'].includes(rc.status)) return
      if (!elsewhereRestaurant.has(rc.restaurant_id)) elsewhereRestaurant.set(rc.restaurant_id, c.name)
      const addr = (rc.recipient_email ?? '').toLowerCase()
      if (addr && !elsewhereEmail.has(addr)) elsewhereEmail.set(addr, c.name)
    }))
    const seenEmails = new Set()
    const items = restaurantIds.map((rid) => {
      const r = restaurantById(rid)
      if (!r) {
        return { restaurant_id: rid, restaurant_name: null, email: null, eligible: false, reasons: ['Restaurant not found'] }
      }
      const reasons = outreachReasons(r, state.suppressed)
      if (alreadySent.has(r.id)) reasons.push(`Already emailed in campaign "${name}"`)
      else if (elsewhereRestaurant.has(r.id)) reasons.push(`Already emailed in campaign "${elsewhereRestaurant.get(r.id)}"`)
      if (pendingDraft.has(r.id)) reasons.push(`Already has a pending draft in campaign "${name}"`)
      const key = (r.contact_email ?? '').trim().toLowerCase()
      if (key && emailsSent.has(key)) reasons.push(`This address already received campaign "${name}"`)
      else if (key && elsewhereEmail.has(key)) reasons.push(`This address already received campaign "${elsewhereEmail.get(key)}"`)
      else if (key && seenEmails.has(key)) reasons.push('Another restaurant in this selection uses the same address')
      if (!reasons.length && key) seenEmails.add(key)
      return {
        restaurant_id: r.id,
        restaurant_name: r.name,
        email: r.contact_email,
        eligible: reasons.length === 0,
        reasons,
      }
    })
    const eligible = items.filter((i) => i.eligible).length
    return { eligible_count: eligible, skipped_count: items.length - eligible, items }
  }

  function createCampaign(body) {
    const name = String(body.name ?? '').trim()
    if (name.length < 2) fail(422, 'Campaign name needs at least 2 characters.')
    const plan = previewPlan(name, body.restaurant_ids ?? [])
    if (plan.eligible_count === 0) fail(422, 'None of the selected businesses are eligible for this campaign.')
    const campaign = {
      id: nextId(),
      name,
      status: 'review',
      status_note: null,
      created_at: now(),
      recipients: [],
    }
    state.campaigns.push(campaign)
    plan.items.forEach((item) => {
      const base = {
        id: nextId(),
        campaign_id: campaign.id,
        restaurant_id: item.restaurant_id,
        recipient_email: item.email ?? null,
        draft_id: null,
        skip_reason: null,
        error_reason: null,
        provider_message_id: null,
        delivery_status: null,
        replied_at: null,
        updated_at: now(),
      }
      if (!item.eligible) {
        campaign.recipients.push({ ...base, status: 'skipped', skip_reason: item.reasons.join('; ') })
        return
      }
      const r = requireRestaurant(item.restaurant_id)
      if (state.failDraftFor.includes(r.id)) {
        campaign.recipients.push({ ...base, status: 'draft_failed', error_reason: 'The draft could not be written. Try again.' })
        return
      }
      const draft = writeDraft(r, name, campaign.id)
      campaign.recipients.push({ ...base, status: 'draft', draft_id: draft.id })
    })
    logEntry(campaign, 'drafts_written', null, `${plan.eligible_count} drafts written, ${plan.skipped_count} skipped.`)
    return campaignDetail(campaign)
  }

  function recipientView(rc) {
    const r = restaurantById(rc.restaurant_id) ?? {}
    const draft = rc.draft_id ? draftById(rc.draft_id) : null
    return {
      id: rc.id,
      restaurant_id: rc.restaurant_id,
      status: rc.status,
      restaurant_name: r.name ?? null,
      restaurant_address: r.address ?? null,
      restaurant_website: r.website ?? null,
      restaurant_email: r.contact_email ?? null,
      restaurant_email_status: r.contact_email_status ?? null,
      restaurant_opted_out: Boolean(r.opted_out),
      recipient_email: rc.recipient_email,
      draft_id: rc.draft_id,
      draft_status: draft?.status ?? null,
      subject: draft?.subject ?? null,
      body: draft?.body ?? null,
      angle: draft?.angle ?? null,
      skip_reason: rc.skip_reason,
      error_reason: rc.error_reason,
      provider_message_id: rc.provider_message_id,
      delivery_status: rc.delivery_status,
      replied_at: rc.replied_at,
      updated_at: rc.updated_at,
    }
  }

  function campaignCounts(recipients) {
    const count = (fn) => recipients.filter(fn).length
    return {
      total_selected: recipients.length,
      eligible: count((r) => r.status !== 'skipped'),
      skipped: count((r) => r.status === 'skipped'),
      drafts_generated: count((r) => r.draft_id && r.status !== 'draft_failed'),
      drafts_failed: count((r) => r.status === 'draft_failed'),
      approved: count((r) => r.draft_status === 'approved'),
      queued: count((r) => r.status === 'queued'),
      sent: count((r) => r.status === 'sent'),
      failed: count((r) => r.status === 'failed'),
      retryable: count((r) => r.status === 'failed'),
      cancelled: count((r) => r.status === 'cancelled'),
    }
  }

  function campaignDetail(c) {
    const recipients = c.recipients.map(recipientView)
    const sent = recipients.filter((r) => r.status === 'sent')
    const delivery = {
      sent: sent.length,
      unconfirmed: sent.filter((r) => !r.delivery_status).length,
      delivered: sent.filter((r) => r.delivery_status === 'delivered').length,
      deferred: sent.filter((r) => r.delivery_status === 'deferred').length,
      bounced_soft: sent.filter((r) => r.delivery_status === 'bounced_soft').length,
      bounced_hard: sent.filter((r) => r.delivery_status === 'bounced_hard').length,
      rejected: sent.filter((r) => r.delivery_status === 'rejected').length,
      replied: sent.filter((r) => r.replied_at).length,
    }
    return {
      id: c.id,
      name: c.name,
      status: c.status,
      status_note: c.status_note,
      created_at: c.created_at,
      live_sending: state.config.live_sending,
      counts: campaignCounts(recipients),
      delivery,
      recipients,
    }
  }

  // The campaign list omits recipients, as the list endpoint does.
  function campaignSummary(c) {
    const { recipients: _omitted, ...summary } = campaignDetail(c)
    return summary
  }

  function approveSending(c, body) {
    const ids = (body.draft_ids ?? []).map(Number)
    for (const id of ids) {
      const d = draftById(id)
      if (!d || d.status !== 'approved') fail(422, `Draft ${id} is not approved.`)
    }
    return campaignDetail(c)
  }

  function startSending(c) {
    if (!['review', 'paused', 'completed'].includes(c.status)) fail(409, `Campaign is already ${c.status}.`)
    if (!state.config.unsubscribe_ready) {
      fail(422, 'Sending is blocked until UNSUBSCRIBE_SECRET and PUBLIC_BASE_URL are set in .env.')
    }
    let queued = 0
    c.recipients.forEach((rc) => {
      const draft = rc.draft_id ? draftById(rc.draft_id) : null
      if (rc.status === 'draft' && draft?.status === 'approved') {
        rc.status = 'queued'
        rc.updated_at = now()
        queued += 1
      }
    })
    if (queued === 0) fail(422, 'No approved drafts to send.')
    c.status = 'sending'
    c.status_note = null
    logEntry(c, 'approved', null, `${queued} approved drafts queued.`)
    logEntry(c, 'send_started', null, 'Sending started.')
    return campaignDetail(c)
  }

  /** Processes queued recipients. Runs on each detail read while the campaign is sending. */
  function advanceSending(c) {
    const queued = c.recipients.filter((rc) => rc.status === 'queued')
    queued.slice(0, state.sendBatch).forEach((rc) => {
      const r = restaurantById(rc.restaurant_id)
      rc.updated_at = now()
      if (state.failSendTo.includes(rc.recipient_email)) {
        rc.status = 'failed'
        rc.error_reason = 'The mock provider rejected this address.'
        logEntry(c, 'failed', rc, 'The mock provider rejected this address.')
        return
      }
      rc.status = 'sent'
      rc.provider_message_id = `mock-${rc.id}`
      state.config.sent_today += 1
      logEntry(c, 'sent', rc, `Recorded by the mock provider for ${r?.name ?? 'business'}.`)
    })
    if (c.recipients.every((rc) => rc.status !== 'queued') && c.status === 'sending') {
      c.status = 'completed'
      logEntry(c, 'completed', null, 'No queued recipients left.')
    }
  }

  // Accounts and roles. Mirrors services/access.py and the user routes in backend/main.py.

  const FORBIDDEN = 'Your account does not have permission for this action.'

  function publicAccount(account) {
    if (!account) return null
    const { password: _password, ...rest } = account
    return clone(rest)
  }

  function currentAccount() {
    return state.authenticated ? state.accounts.find((a) => a.id === state.sessionUserId) ?? null : null
  }

  const NOT_MEMBER = 'You are not a member of this workspace.'
  const DEFAULT_WORKSPACE = 1

  // The role an account has in a workspace. null means no membership (or a removed one).
  function roleIn(account, workspaceId) {
    if (!account) return null
    const workspace = state.workspaces.find((w) => w.id === workspaceId)
    if (!workspace) return null
    if (Object.prototype.hasOwnProperty.call(workspace.memberships, account.id)) return workspace.memberships[account.id]
    // Older scenarios have no membership rows: the default workspace then uses the account's own role. An account
    // created by public sign-up is a member only where a membership row says so.
    return workspaceId === DEFAULT_WORKSPACE && !account.self_registered ? account.role : null
  }

  // The workspace a session works in: the chosen one while the person is still a member, otherwise the first.
  function activeWorkspace(account) {
    if (!account) return null
    if (state.sessionWorkspaceId != null && roleIn(account, state.sessionWorkspaceId)) {
      return { id: state.sessionWorkspaceId, role: roleIn(account, state.sessionWorkspaceId) }
    }
    const first = state.workspaces.find((w) => roleIn(account, w.id))
    return first ? { id: first.id, role: roleIn(account, first.id) } : null
  }

  function myWorkspaces(account) {
    return state.workspaces
      .filter((w) => roleIn(account, w.id))
      .map((w) => ({ id: w.id, name: w.name, status: w.status, role: roleIn(account, w.id) }))
  }

  function permissionDenied(account, method, path) {
    const safe = method === 'GET' || method === 'HEAD' || method === 'OPTIONS'
    if (path === '/users' || path.startsWith('/users/')) {
      return account.role === 'admin' ? null : FORBIDDEN
    }
    if (path === '/admin/workspaces' || (path === '/workspaces' && method === 'POST')) {
      return account.role === 'admin' ? null : FORBIDDEN
    }
    const pathWorkspace = path.match(/^\/workspaces\/(\d+)/)
    if (pathWorkspace) {
      const role = roleIn(account, Number(pathWorkspace[1]))
      if (!role) return NOT_MEMBER
      if (path.endsWith('/switch')) return null
      if (safe && !path.endsWith('/invitations')) return null
      return role === 'admin' ? null : FORBIDDEN
    }
    const active = activeWorkspace(account)
    if (path === '/audit-log') return active?.role === 'admin' ? null : FORBIDDEN
    if (!active) return NOT_MEMBER
    if (safe) return null
    return active.role === 'viewer' ? FORBIDDEN : null
  }

  // Mirrors the server: only demo rows are deleted; a demo row with drafts is kept and reported.
  function deleteDemoFake(body) {
    const ids = Array.isArray(body.ids) ? body.ids.map(Number) : null
    const deleted = []
    const kept = []
    state.restaurants = state.restaurants.filter((r) => {
      if (r.source !== 'demo' || (ids && !ids.includes(r.id))) return true
      if (state.drafts.some((d) => d.restaurant_id === r.id)) {
        kept.push({ id: r.id, name: r.name, reason: 'Has drafts, campaign or email history, so it is kept.' })
        return true
      }
      deleted.push(r.id)
      return false
    })
    return { deleted, kept }
  }

  // Public sign-up, mirroring backend/services/users.py register_account and services/passwords.py.
  // The new account gets its own workspace as admin and is NOT signed in.
  function registerFake(body) {
    if (state.accounts.length === 0) {
      fail(409, 'No account exists yet. Create the first admin account from the sign-in page.')
    }
    const name = String(body.name ?? '').trim()
    if (name.length < 2 || name.length > 120) fail(422, 'Name must be between 2 and 120 characters.')
    const email = String(body.email ?? '').trim().toLowerCase()
    if (!/^[^@\s]+@[^@\s]+\.[a-z]{2,}$/.test(email)) fail(422, 'Enter a valid email address.')
    const password = String(body.password ?? '')
    if (password.length !== 8) fail(422, 'Use exactly 8 characters.')
    if (!/^[A-Za-z0-9]+$/.test(password)) fail(422, 'Use letters and numbers only (A to Z and 0 to 9).')
    if (state.accounts.some((a) => a.email === email)) fail(409, 'An account with this email already exists.')
    const id = nextId()
    state.accounts.push({
      id, name, email, password, role: 'viewer', status: 'active', self_registered: true,
      created_at: now(), last_login_at: null, password_changed_at: now(),
    })
    state.workspaces.push({ id: nextId(), name: `${name} workspace`, status: 'active', created_at: now(), memberships: { [id]: 'admin' } })
    return { registered: true, email, message: 'Account created successfully. Please sign in.' }
  }

  function createWorkspaceFake(body) {
    const name = String(body.name ?? '').trim()
    if (name.length < 2 || name.length > 120) fail(422, 'Workspace name must be between 2 and 120 characters.')
    const creator = currentAccount()
    const workspace = { id: nextId(), name, status: 'active', created_at: now(), memberships: { [creator.id]: 'admin' } }
    state.workspaces.push(workspace)
    recordAudit(creator.id, 'workspace.created', 'workspace', workspace.id, `name=${name}`)
    return { id: workspace.id, name, status: 'active', created_at: workspace.created_at }
  }

  function membersOf(workspaceId) {
    return state.accounts
      .filter((a) => roleIn(a, workspaceId))
      .map((a) => ({ id: a.id, name: a.name, email: a.email, account_status: a.status, role: roleIn(a, workspaceId), joined_at: a.created_at }))
  }

  function setRole(workspaceId, userId, role) {
    const workspace = state.workspaces.find((w) => w.id === workspaceId)
    workspace.memberships[userId] = role
  }

  function changeMemberRole(workspaceId, userId, body) {
    const target = state.accounts.find((a) => a.id === userId)
    if (!target || !roleIn(target, workspaceId)) fail(404, 'That person is not a member of this workspace.')
    if (!['admin', 'operator', 'viewer'].includes(body.role)) fail(422, 'Role must be admin, operator or viewer.')
    if (currentAccount().id === userId && body.role !== 'admin') {
      fail(422, 'You cannot remove your own admin role in this workspace.')
    }
    const admins = membersOf(workspaceId).filter((m) => m.role === 'admin').length
    if (roleIn(target, workspaceId) === 'admin' && body.role !== 'admin' && admins <= 1) {
      fail(422, 'A workspace must keep at least one admin.')
    }
    setRole(workspaceId, userId, body.role)
    recordAudit(currentAccount().id, 'workspace.member_role_changed', 'user', userId, `role=${body.role}`)
    return { user_id: userId, role: body.role }
  }

  function removeMember(workspaceId, userId) {
    const target = state.accounts.find((a) => a.id === userId)
    if (!target || !roleIn(target, workspaceId)) fail(404, 'That person is not a member of this workspace.')
    if (currentAccount().id === userId) fail(422, 'You cannot remove yourself from this workspace.')
    const admins = membersOf(workspaceId).filter((m) => m.role === 'admin').length
    if (roleIn(target, workspaceId) === 'admin' && admins <= 1) fail(422, 'A workspace must keep at least one admin.')
    setRole(workspaceId, userId, null)
    recordAudit(currentAccount().id, 'workspace.member_removed', 'user', userId)
    return { removed: true }
  }

  function createInvitationFake(workspaceId, body) {
    const email = String(body.email ?? '').trim().toLowerCase()
    if (!/^[^@\s]+@[^@\s]+\.[a-z]{2,}$/.test(email)) fail(422, 'Enter a valid email address.')
    if (!['admin', 'operator', 'viewer'].includes(body.role)) fail(422, 'Role must be admin, operator or viewer.')
    const existing = state.accounts.find((a) => a.email === email)
    if (existing && roleIn(existing, workspaceId)) fail(422, 'That person is already a member of this workspace.')
    const id = nextId()
    const token = `fake-invite-token-${id}-abcdefgh`
    const expires = '2026-11-12 09:00:00'
    state.invitations.push({ id, workspace_id: workspaceId, email, role: body.role, status: 'pending', token, expires_at: expires, created_at: now() })
    return {
      id, email, role: body.role, expires_at: expires,
      link: `http://localhost:5173/#invite=${token}`,
    }
  }

  function findOpenInvitation(token) {
    const invitation = state.invitations.find((i) => i.token === token)
    if (!invitation || invitation.status !== 'pending') return null
    return invitation
  }

  function previewInvitationFake(token) {
    const invitation = findOpenInvitation(token)
    if (!invitation) fail(404, 'This invitation link is not valid. Ask for a new invitation.')
    const workspace = state.workspaces.find((w) => w.id === invitation.workspace_id)
    return {
      workspace_name: workspace.name,
      email: invitation.email,
      role: invitation.role,
      expires_at: invitation.expires_at,
      account_exists: state.accounts.some((a) => a.email === invitation.email),
    }
  }

  function acceptInvitationFake(body) {
    const invitation = findOpenInvitation(String(body.token ?? ''))
    if (!invitation) fail(404, 'This invitation link is not valid. Ask for a new invitation.')
    const existing = state.accounts.find((a) => a.email === invitation.email)
    if (existing) {
      if (!state.authenticated || currentAccount().email !== invitation.email) {
        fail(403, `Sign in as ${invitation.email} to accept this invitation.`)
      }
      setRole(invitation.workspace_id, existing.id, invitation.role)
    } else {
      const name = String(body.name ?? '').trim()
      if (name.length < 2) fail(422, 'Name must be between 2 and 120 characters.')
      if (String(body.password ?? '').length < 12) fail(422, 'Use at least 12 characters.')
      const account = {
        id: nextId(), name, email: invitation.email, password: body.password, role: 'viewer', status: 'active',
        created_at: now(), last_login_at: now(), password_changed_at: now(),
      }
      state.accounts.push(account)
      state.authenticated = true
      state.sessionUserId = account.id
      setRole(invitation.workspace_id, account.id, invitation.role)
    }
    invitation.status = 'accepted'
    state.sessionWorkspaceId = invitation.workspace_id
    const signedIn = currentAccount()
    return {
      authenticated: true, auth_required: true, session_seconds: 43200,
      user: publicAccount(signedIn), workspace_id: invitation.workspace_id,
    }
  }

  function recordAudit(actorId, action, targetType, targetId, detail) {
    const actor = state.accounts.find((a) => a.id === actorId)
    state.audit.push({
      id: nextId(),
      created_at: now(),
      actor_user_id: actorId ?? null,
      actor_name: actor?.name ?? null,
      actor_email: actor?.email ?? null,
      action,
      target_type: targetType ?? null,
      target_id: targetId ?? null,
      detail: detail ?? null,
    })
  }

  function createAccount(body) {
    const email = String(body.email ?? '').trim().toLowerCase()
    if (!/^[^@\s]+@[^@\s]+\.[a-z]{2,}$/.test(email)) fail(422, 'Enter a valid email address.')
    if (state.accounts.some((a) => a.email === email)) fail(422, 'An account with this email already exists.')
    if (String(body.password ?? '').length < 12) fail(422, 'Use at least 12 characters.')
    if (!['admin', 'operator', 'viewer'].includes(body.role)) fail(422, 'Role must be admin, operator or viewer.')
    const account = {
      id: nextId(),
      name: String(body.name ?? '').trim(),
      email,
      password: body.password,
      role: body.role,
      status: 'active',
      created_at: now(),
      last_login_at: null,
      password_changed_at: now(),
    }
    state.accounts.push(account)
    recordAudit(currentAccount()?.id ?? null, 'user.created', 'user', account.id, `role=${account.role}`)
    return publicAccount(account)
  }

  function updateAccount(id, body) {
    const target = state.accounts.find((a) => a.id === id)
    if (!target) fail(404, 'User not found.')
    const actor = currentAccount()
    const nextRole = body.role ?? target.role
    const nextStatus = body.status ?? target.status
    if (actor.id === id && (nextRole !== 'admin' || nextStatus === 'inactive')) {
      fail(422, 'You cannot remove your own admin role or deactivate your own account.')
    }
    const activeAdmins = state.accounts.filter((a) => a.role === 'admin' && a.status === 'active').length
    const losingAdmin = target.role === 'admin' && target.status === 'active'
      && (nextRole !== 'admin' || nextStatus !== 'active')
    if (losingAdmin && activeAdmins <= 1) fail(422, 'At least one active admin must remain.')
    if (body.name !== undefined) target.name = String(body.name).trim()
    target.role = nextRole
    target.status = nextStatus
    recordAudit(actor.id, 'user.updated', 'user', id, `role=${nextRole}; status=${nextStatus}`)
    return publicAccount(target)
  }

  function resetAccountPassword(id, body) {
    const target = state.accounts.find((a) => a.id === id)
    if (!target) fail(404, 'User not found.')
    if (String(body.new_password ?? '').length < 12) fail(422, 'Use at least 12 characters.')
    target.password = body.new_password
    target.password_changed_at = now()
    recordAudit(currentAccount()?.id ?? null, 'user.password_reset', 'user', id)
    return publicAccount(target)
  }

  // Routes

  const ROUTES = [
    ['GET', /^\/health$/, () => ({ status: 'ok' })],
    ['GET', /^\/auth\/session$/, () => {
      const account = state.authenticated ? currentAccount() : null
      return {
        authenticated: state.authenticated,
        auth_required: true,
        session_seconds: 43200,
        user: publicAccount(account),
        workspace: account ? activeWorkspace(account) : null,
        workspaces: account ? myWorkspaces(account) : [],
      }
    }],
    ['GET', /^\/workspaces$/, () => myWorkspaces(currentAccount())],
    ['POST', /^\/workspaces$/, ({ body }) => createWorkspaceFake(body)],
    ['GET', /^\/admin\/workspaces$/, () => state.workspaces.map((w) => ({
      id: w.id, name: w.name, status: w.status, created_at: w.created_at,
      members: membersOf(w.id).length,
    }))],
    ['PUT', /^\/workspaces\/(\d+)$/, ({ params, body }) => {
      const workspace = state.workspaces.find((w) => w.id === Number(params[0]))
      if (!workspace) fail(404, 'Workspace not found.')
      workspace.name = String(body.name ?? '').trim()
      return { id: workspace.id, name: workspace.name, status: workspace.status, created_at: workspace.created_at }
    }],
    ['POST', /^\/workspaces\/(\d+)\/switch$/, ({ params }) => {
      const workspaceId = Number(params[0])
      state.sessionWorkspaceId = workspaceId
      return { active_workspace_id: workspaceId, role: roleIn(currentAccount(), workspaceId) }
    }],
    ['GET', /^\/workspaces\/(\d+)\/members$/, ({ params }) => membersOf(Number(params[0]))],
    ['PUT', /^\/workspaces\/(\d+)\/members\/(\d+)$/, ({ params, body }) =>
      changeMemberRole(Number(params[0]), Number(params[1]), body)],
    ['DELETE', /^\/workspaces\/(\d+)\/members\/(\d+)$/, ({ params }) =>
      removeMember(Number(params[0]), Number(params[1]))],
    ['GET', /^\/workspaces\/(\d+)\/invitations$/, ({ params }) => state.invitations
      .filter((i) => i.workspace_id === Number(params[0]))
      .map(({ token: _token, ...rest }) => rest)],
    ['POST', /^\/workspaces\/(\d+)\/invitations$/, ({ params, body }) =>
      createInvitationFake(Number(params[0]), body)],
    ['DELETE', /^\/workspaces\/(\d+)\/invitations\/(\d+)$/, ({ params }) => {
      const invitation = state.invitations.find((i) => i.id === Number(params[1]) && i.workspace_id === Number(params[0]))
      if (!invitation) fail(404, 'Invitation not found.')
      invitation.status = 'revoked'
      return { revoked: true }
    }],
    ['POST', /^\/invitations\/preview$/, ({ body }) => previewInvitationFake(String(body.token ?? ''))],
    ['POST', /^\/invitations\/accept$/, ({ body }) => acceptInvitationFake(body)],
    ['POST', /^\/auth\/login$/, ({ body }) => {
      const account = state.accounts.find((a) => a.email === String(body.email ?? '').trim().toLowerCase())
      const matches = account && account.password === body.password
      if (!matches || account.status !== 'active') fail(401, 'Incorrect email or password.')
      state.authenticated = true
      state.sessionUserId = account.id
      state.sessionWorkspaceId = activeWorkspace(account)?.id ?? null
      account.last_login_at = now()
      return { authenticated: true, auth_required: true, session_seconds: 43200, user: publicAccount(account) }
    }],
    ['POST', /^\/auth\/register$/, ({ body }) => registerFake(body)],
    ['GET', /^\/industries$/, () => clone(INDUSTRY_OPTIONS)],
    ['GET', /^\/geo\/countries\/([A-Za-z]{2})\/cities$/, ({ params, query }) => citySearch(
      params[0].toUpperCase(), query.get('q') ?? '', Number(query.get('limit') ?? 10), Number(query.get('offset') ?? 0))],
    ['GET', /^\/geo\/status$/, () => ({
      loaded: true, city_count: GEO_CITIES.length, source: 'GeoNames', source_url: 'https://www.geonames.org/',
      licence: 'CC BY 4.0', attribution: 'City data © GeoNames (https://www.geonames.org/), licensed under CC BY 4.0.',
      imported_at: null, alternate_name_count: 0,
    })],
    ['GET', /^\/auth\/setup-status$/, () => ({ needs_setup: state.accounts.length === 0 })],
    ['POST', /^\/auth\/setup$/, ({ body }) => {
      if (state.accounts.length > 0) fail(409, 'Accounts already exist. Ask an administrator to create yours.')
      const email = String(body.email ?? '').trim().toLowerCase()
      if (!/^[^@\s]+@[^@\s]+\.[a-z]{2,}$/.test(email)) fail(422, 'Enter a valid email address.')
      if (String(body.password ?? '').length < 12) fail(422, 'Use at least 12 characters.')
      const account = {
        id: nextId(),
        name: String(body.name ?? '').trim(),
        email,
        password: body.password,
        role: 'admin',
        status: 'active',
        created_at: now(),
        last_login_at: now(),
        password_changed_at: now(),
      }
      state.accounts.push(account)
      state.authenticated = true
      state.sessionUserId = account.id
      recordAudit(account.id, 'bootstrap.first_admin_created', 'user', account.id)
      return { authenticated: true, auth_required: true, session_seconds: 43200, user: publicAccount(account) }
    }],
    ['POST', /^\/auth\/logout$/, () => {
      state.authenticated = false
      return { authenticated: false, auth_required: true }
    }],
    ['POST', /^\/auth\/password$/, ({ body }) => {
      const account = currentAccount()
      if (!account) fail(401, 'Sign in required.')
      if (account.password !== body.current_password) fail(400, 'The current password is not correct.')
      if (String(body.new_password ?? '').length < 12) fail(422, 'Use at least 12 characters.')
      if (body.new_password === body.current_password) fail(422, 'Choose a new password that differs from the current one.')
      account.password = body.new_password
      account.password_changed_at = now()
      recordAudit(account.id, 'auth.password_changed', 'user', account.id)
      return { changed: true }
    }],
    ['GET', /^\/users$/, () => state.accounts.map(publicAccount)],
    ['POST', /^\/users$/, ({ body }) => createAccount(body)],
    ['PUT', /^\/users\/(\d+)$/, ({ params, body }) => updateAccount(Number(params[0]), body)],
    ['POST', /^\/users\/(\d+)\/reset-password$/, ({ params, body }) => resetAccountPassword(Number(params[0]), body)],
    ['GET', /^\/audit-log$/, () => state.audit.slice().reverse()],
    ['GET', /^\/discovery\/mode$/, () => state.discoveryMode],
    ['GET', /^\/restaurants\/deleted$/, () => state.restaurants.filter((r) => r.deleted_at).map(snapshot)],
    ['POST', /^\/restaurants\/bulk-delete$/, ({ body }) => bulkDeleteFake(body)],
    ['DELETE', /^\/restaurants\/(\d+)$/, ({ params }) => deleteLeadFake(params[0])],
    ['POST', /^\/restaurants\/(\d+)\/restore$/, ({ params }) => snapshot(restoreLeadFake(params[0]))],
    ['GET', /^\/restaurants$/, ({ query }) => paginate(state.restaurants.filter((r) => !r.deleted_at), query).map(snapshot)],
    ['GET', /^\/restaurants\/leads$/, ({ query }) => state.restaurants
      .filter((r) => !r.deleted_at)
      .filter((r) => !query.get('status') || (r.lead_status || 'new') === query.get('status'))
      .map(snapshot)],
    ['POST', /^\/restaurants\/discover$/, ({ body }) => discover(body)],
    ['POST', /^\/restaurants\/check-batch$/, ({ body }) => (body.ids ?? []).map((id) => snapshot(checkWebsite(requireRestaurant(id))))],
    ['POST', /^\/restaurants\/discover-contacts-batch$/, ({ body }) => (body.ids ?? []).map((id) => snapshot(discoverContact(requireRestaurant(id))))],
    ['POST', /^\/restaurants\/qualify-batch$/, ({ body }) => (body.ids ?? []).map((id) => snapshot(qualify(requireRestaurant(id))))],
    ['POST', /^\/restaurants\/(\d+)\/check$/, ({ params }) => snapshot(checkWebsite(requireRestaurant(params[0])))],
    ['POST', /^\/restaurants\/(\d+)\/discover-contact$/, ({ params }) => snapshot(discoverContact(requireRestaurant(params[0])))],
    ['POST', /^\/restaurants\/(\d+)\/qualify$/, ({ params }) => snapshot(qualify(requireRestaurant(params[0])))],
    ['POST', /^\/restaurants\/delete-demo$/, ({ body }) => deleteDemoFake(body)],
    ['POST', /^\/restaurants\/(\d+)\/manual-qualify$/, ({ params, body }) => snapshot(manualQualifyFake(requireRestaurant(params[0]), body))],
    ['POST', /^\/restaurants\/(\d+)\/opt-out$/, ({ params }) => snapshot(optOut(requireRestaurant(params[0])))],
    ['POST', /^\/restaurants\/(\d+)\/verify-email$/, ({ params }) => snapshot(verifyEmail(requireRestaurant(params[0])))],
    ['POST', /^\/restaurants\/(\d+)\/email-review$/, ({ params, body }) => snapshot(reviewEmail(requireRestaurant(params[0]), body.decision))],
    ['GET', /^\/restaurants\/(\d+)\/conversations$/, () => ({ events: [], replies: [] })],
    ['GET', /^\/outreach\/eligibility$/, () => Object.fromEntries(state.restaurants.map((r) => {
      const reasons = outreachReasons(r, state.suppressed)
      return [String(r.id), { eligible: reasons.length === 0, reasons }]
    }))],
    ['POST', /^\/outreach\/generate$/, ({ body }) => generateDraft(body)],
    ['GET', /^\/outreach\/drafts$/, ({ query }) => {
      const restaurantId = query.get('restaurant_id')
      const status = query.get('status')
      const rows = state.drafts.filter((d) => (restaurantId === null || d.restaurant_id === Number(restaurantId))
        && (status === null || d.status === status))
      return paginate(rows, query).map(clone)
    }],
    ['GET', /^\/outreach\/drafts\/(\d+)$/, ({ params }) => {
      const d = draftById(params[0])
      if (!d) fail(404, 'Draft not found.')
      return clone(d)
    }],
    ['PUT', /^\/outreach\/drafts\/(\d+)$/, ({ params, body }) => clone(updateDraft(draftById(params[0]) ?? fail(404, 'Draft not found.'), body))],
    ['POST', /^\/outreach\/drafts\/(\d+)\/approve$/, ({ params }) => clone(approveDraft(draftById(params[0]) ?? fail(404, 'Draft not found.')))],
    ['POST', /^\/outreach\/drafts\/(\d+)\/reject$/, ({ params }) => clone(rejectDraft(draftById(params[0]) ?? fail(404, 'Draft not found.')))],
    ['POST', /^\/outreach\/drafts\/(\d+)\/regenerate$/, ({ params, body }) => {
      state.lastRegenerateInstructions = String(body?.instructions ?? '')
      return clone(regenerateDraft(draftById(params[0]) ?? fail(404, 'Draft not found.')))
    }],
    ['POST', /^\/campaigns\/preview$/, ({ body }) => previewPlan(String(body.name ?? '').trim(), body.restaurant_ids ?? [])],
    ['POST', /^\/campaigns$/, ({ body }) => createCampaign(body)],
    ['GET', /^\/campaigns$/, () => state.campaigns.map(campaignSummary)],
    ['GET', /^\/campaigns\/config$/, () => ({ ...state.config })],
    ['GET', /^\/campaigns\/(\d+)$/, ({ params }) => {
      const c = requireCampaign(params[0])
      if (c.status === 'sending') advanceSending(c)
      return campaignDetail(c)
    }],
    ['GET', /^\/campaigns\/(\d+)\/logs$/, ({ params }) => state.logs.filter((l) => l.campaign_id === requireCampaign(params[0]).id)],
    ['POST', /^\/campaigns\/(\d+)\/approve-sending$/, ({ params, body }) => approveSending(requireCampaign(params[0]), body)],
    ['POST', /^\/campaigns\/(\d+)\/send$/, ({ params }) => startSending(requireCampaign(params[0]))],
    ['POST', /^\/campaigns\/(\d+)\/pause$/, ({ params }) => {
      const c = requireCampaign(params[0])
      if (c.status !== 'sending') fail(409, `Campaign is ${c.status}, not sending.`)
      c.status = 'paused'
      c.status_note = 'Paused. Queued emails will wait until you resume.'
      logEntry(c, 'paused', null, 'Paused by a person.')
      return campaignDetail(c)
    }],
    ['POST', /^\/campaigns\/(\d+)\/resume$/, ({ params }) => {
      const c = requireCampaign(params[0])
      if (c.status !== 'paused') fail(409, `Campaign is ${c.status}, not paused.`)
      c.status = 'sending'
      c.status_note = null
      return campaignDetail(c)
    }],
    ['POST', /^\/campaigns\/(\d+)\/cancel$/, ({ params }) => {
      const c = requireCampaign(params[0])
      if (!['generating', 'review', 'sending', 'paused'].includes(c.status)) fail(409, `Campaign is already ${c.status}.`)
      c.recipients.forEach((rc) => { if (rc.status === 'queued') rc.status = 'cancelled' })
      c.status = 'cancelled'
      logEntry(c, 'cancelled', null, 'Campaign cancelled by a person.')
      return campaignDetail(c)
    }],
    ['POST', /^\/campaigns\/(\d+)\/retry-failed$/, ({ params }) => {
      const c = requireCampaign(params[0])
      c.recipients.forEach((rc) => { if (rc.status === 'failed') { rc.status = 'queued'; rc.error_reason = null } })
      c.status = 'sending'
      return campaignDetail(c)
    }],
    ['POST', /^\/campaigns\/(\d+)\/retry-drafts$/, ({ params }) => {
      const c = requireCampaign(params[0])
      c.recipients.forEach((rc) => {
        if (rc.status !== 'draft_failed') return
        const r = requireRestaurant(rc.restaurant_id)
        state.failDraftFor = state.failDraftFor.filter((id) => id !== r.id)
        const draft = writeDraft(r, c.name, c.id)
        rc.draft_id = draft.id
        rc.status = 'draft'
        rc.error_reason = null
      })
      return campaignDetail(c)
    }],
    ['GET', /^\/email\/review-queue$/, () => state.reviewQueue.map(clone)],
    ['GET', /^\/email\/mailbox-status$/, () => ({ configured: Boolean(state.mailboxConfigured) })],
    ['POST', /^\/email\/conversations\/(\d+)\/resolve$/, ({ params, body }) => {
      const index = state.reviewQueue.findIndex((item) => item.id === Number(params[0]))
      if (index === -1) fail(404, 'Message not found.')
      if (body.decision !== 'confirm' && body.decision !== 'dismiss') fail(422, 'Decision must be confirm or dismiss.')
      state.reviewQueue.splice(index, 1)
      return { ok: true }
    }],
    ['POST', /^\/email\/sync$/, () => ({
      read: 0, event: 0, matched: 0, needs_review: state.reviewQueue.length, unmatched: 0,
    })],
  ]

  /**
   * Answers one request. Returns { status, body } or { networkError: true }.
   * Never throws for an API error: those become a status and a FastAPI-style { detail }.
   */
  function handle({ method, path, query = new URLSearchParams(), body = {} }) {
    const injected = state.failures[`${method} ${path}`]
    if (injected === 'network') return { networkError: true }
    if (injected) return { status: injected.status, body: { detail: injected.detail } }
    const publicPath = path.startsWith('/auth/') || path.startsWith('/invitations/') || path === '/health'
    if (!state.authenticated && !publicPath) {
      return { status: 401, body: { detail: 'Sign in required.' } }
    }
    const account = currentAccount()
    if (account && !publicPath) {
      const denied = permissionDenied(account, method, path)
      if (denied) return { status: 403, body: { detail: denied } }
    }
    for (const [routeMethod, pattern, run] of ROUTES) {
      if (routeMethod !== method) continue
      const match = path.match(pattern)
      if (!match) continue
      try {
        const result = run({ params: match.slice(1), query, body: body ?? {} })
        return { status: 200, body: result }
      } catch (err) {
        if (err instanceof ApiError) return { status: err.status, body: { detail: err.detail } }
        throw err
      }
    }
    return { status: 404, body: { detail: 'Not found' } }
  }

  return { state, handle, nextId }
}
