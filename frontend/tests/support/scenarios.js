import { makeRestaurant } from './fakeBackend'

// Shared, deterministic test data. Every value is invented. No real restaurant, person or address is used.
const STAMP = '2026-11-01T09:00:00Z'

/**
 * Eleven restaurants that cover every eligibility outcome the Leads page can show.
 * Eligible for a campaign: 1, 2 and 7. Everything else is blocked, with the reason in the backend wording.
 *   1  eligible, qualified, business email
 *   2  eligible, qualified, business email
 *   3  personal email not yet reviewed by a person, and not qualified
 *   4  demo record ([DEMO]), never emailable
 *   5  contact email marked invalid
 *   6  opted out of outreach
 *   7  eligible on its own, but shares an address with restaurant 1 (duplicate protection)
 *   8  no email found
 *   9  disposable email address
 *   10 not qualified yet
 *   11 disqualified, no website, no email (second page of the list)
 */
export function leadsScenario() {
  return {
    discoveryMode: { demo_mode: true, live_key_configured: false },
    restaurants: [
      makeRestaurant({
        id: 1,
        name: 'Lahore Karahi House',
        address: 'Liberty Market, Gulberg, Lahore, Pakistan',
        website: 'https://lahorekarahi.pk',
        phone: '+92 42 3500 1001',
        place_id: 'place-1',
        website_status: 'present',
        website_checked_at: STAMP,
        ordering_status: 'not_found',
        contact_email: 'info@lahorekarahi.pk',
        contact_email_status: 'domain_valid',
        contact_email_classification: 'business',
        contact_email_checked_at: STAMP,
        contact_discovered_at: STAMP,
        lead_status: 'qualified',
        lead_score: 90,
        lead_reason: 'Score 90: live website, no online ordering, usable email, phone listed.',
        lead_qualified_at: STAMP,
      }),
      makeRestaurant({
        id: 2,
        name: 'Gulberg Biryani Point',
        address: 'MM Alam Road, Gulberg, Lahore, Pakistan',
        website: 'https://gulbergbiryani.pk',
        place_id: 'place-2',
        website_status: 'present',
        website_checked_at: STAMP,
        ordering_status: 'not_found',
        contact_email: 'hello@gulbergbiryani.pk',
        contact_email_status: 'domain_valid',
        contact_email_classification: 'business',
        contact_discovered_at: STAMP,
        lead_status: 'qualified',
        lead_score: 65,
        lead_reason: 'Score 65: live website, no online ordering, usable email.',
        lead_qualified_at: STAMP,
      }),
      makeRestaurant({
        id: 3,
        name: 'Johar Town Pizza',
        address: 'Block C, Johar Town, Lahore, Pakistan',
        website: 'https://joharpizza.pk',
        place_id: 'place-3',
        website_status: 'present',
        website_checked_at: STAMP,
        ordering_status: 'not_found',
        contact_email: 'owner@gmail.com',
        contact_email_status: 'domain_valid',
        contact_email_classification: 'personal',
        contact_discovered_at: STAMP,
        lead_status: 'needs_review',
        lead_score: 40,
        lead_reason: 'Score 40: live website, no online ordering.',
        lead_qualified_at: STAMP,
      }),
      makeRestaurant({
        id: 4,
        name: '[DEMO] Sample Cafe',
        address: '1 Main Road, Lahore, Pakistan',
        city: 'Lahore',
        source: 'demo',
        place_id: 'demo-sample-cafe',
        contact_email: 'hello@samplecafe.pk',
        contact_email_status: 'domain_valid',
        contact_email_classification: 'business',
        lead_status: 'qualified',
        lead_score: 80,
        lead_reason: 'Sample record.',
        lead_qualified_at: STAMP,
      }),
      makeRestaurant({
        id: 5,
        name: 'Invalid Mail Bistro',
        address: 'DHA Phase 5, Lahore, Pakistan',
        place_id: 'place-5',
        contact_email: 'team@bistro.invalid',
        contact_email_status: 'invalid',
        contact_email_classification: 'business',
        contact_discovered_at: STAMP,
        lead_status: 'qualified',
        lead_score: 70,
        lead_reason: 'Score 70.',
        lead_qualified_at: STAMP,
      }),
      makeRestaurant({
        id: 6,
        name: 'Opted Out Grill',
        address: 'Model Town, Lahore, Pakistan',
        place_id: 'place-6',
        contact_email: 'order@optedoutgrill.pk',
        contact_email_status: 'domain_valid',
        contact_email_classification: 'business',
        opted_out: true,
        lead_status: 'qualified',
        lead_score: 75,
        lead_reason: 'Score 75.',
        lead_qualified_at: STAMP,
      }),
      makeRestaurant({
        id: 7,
        name: 'Same Address Cafe',
        address: 'Liberty Market, Gulberg, Lahore, Pakistan',
        website: 'https://sameaddresscafe.pk',
        place_id: 'place-7',
        website_status: 'present',
        website_checked_at: STAMP,
        ordering_status: 'not_found',
        contact_email: 'info@lahorekarahi.pk',
        contact_email_status: 'domain_valid',
        contact_email_classification: 'business',
        contact_discovered_at: STAMP,
        lead_status: 'qualified',
        lead_score: 70,
        lead_reason: 'Score 70.',
        lead_qualified_at: STAMP,
      }),
      makeRestaurant({
        id: 8,
        name: 'No Email Diner',
        address: 'Faisal Town, Lahore, Pakistan',
        website: 'https://noemaildiner.pk',
        place_id: 'place-8',
        website_status: 'present',
        website_checked_at: STAMP,
        ordering_status: 'not_found',
        contact_discovered_at: STAMP,
        lead_status: 'qualified',
        lead_score: 55,
        lead_reason: 'Score 55.',
        lead_qualified_at: STAMP,
      }),
      makeRestaurant({
        id: 9,
        name: 'Disposable Eats',
        address: 'Cantt, Lahore, Pakistan',
        place_id: 'place-9',
        contact_email: 'promo@mailinator.com',
        contact_email_status: 'unverified',
        contact_email_classification: 'disposable',
        contact_discovered_at: STAMP,
        lead_status: 'qualified',
        lead_score: 60,
        lead_reason: 'Score 60.',
        lead_qualified_at: STAMP,
      }),
      makeRestaurant({
        id: 10,
        name: 'Chai Corner',
        address: 'Garden Town, Lahore, Pakistan',
        place_id: 'place-10',
        contact_email: 'hello@chaicorner.pk',
        contact_email_status: 'domain_valid',
        contact_email_classification: 'business',
        contact_discovered_at: STAMP,
      }),
      makeRestaurant({
        id: 11,
        name: 'Roadside Dhaba',
        address: 'GT Road, Gujranwala, Pakistan',
        city: 'Gujranwala',
        place_id: 'place-11',
        lead_status: 'disqualified',
        lead_score: 5,
        lead_reason: 'Score 5: no signals.',
        lead_qualified_at: STAMP,
      }),
    ],
  }
}

/** Two drafts for restaurant 1 and 3, in the states the drafts page needs to show. */
export function draftsScenario() {
  return {
    ...leadsScenario(),
    drafts: [
      {
        id: 2001,
        restaurant_id: 1,
        campaign: 'Lahore cafes',
        campaign_id: null,
        subject: 'Online ordering for Lahore Karahi House',
        body: 'Hello Lahore Karahi House team,\n\nWould you like online ordering for your guests?',
        angle: 'ordering_gap',
        status: 'draft',
        created_at: STAMP,
        updated_at: STAMP,
      },
      {
        id: 2002,
        restaurant_id: 3,
        campaign: 'Lahore cafes',
        campaign_id: null,
        subject: 'Online ordering for Johar Town Pizza',
        body: 'Hello Johar Town Pizza team.',
        angle: 'ordering_gap',
        status: 'draft',
        created_at: STAMP,
        updated_at: STAMP,
      },
    ],
  }
}

/**
 * Creates a campaign through the same API the app uses, then approves its drafts.
 * Only the fake backend is touched.
 */
export function seedApprovedCampaign(backend, { name, restaurantIds }) {
  const created = backend.handle({
    method: 'POST',
    path: '/campaigns',
    body: { name, restaurant_ids: restaurantIds },
  })
  if (created.status !== 200) throw new Error(`Seed campaign failed: ${created.body.detail}`)
  const campaign = created.body
  campaign.recipients.forEach((rc) => {
    if (rc.draft_id) {
      backend.handle({ method: 'POST', path: `/outreach/drafts/${rc.draft_id}/approve`, body: {} })
    }
  })
  return campaign
}
