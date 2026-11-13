import { expect, test } from '@playwright/test'
import { installMockApi } from './support/mockApi.js'
import { openApp } from './support/app.js'
import { leadsScenario } from '../support/scenarios.js'
import { makeRestaurant } from '../support/fakeBackend.js'

/** The seeded leads, plus one restaurant that still needs a website check, an email and a score. */
function workflowScenario() {
  const seed = leadsScenario()
  seed.restaurants.push(makeRestaurant({
    id: 12,
    name: 'Fresh Find Kitchen',
    address: 'Model Town, Lahore, Pakistan',
    website: 'https://freshfind.pk',
    place_id: 'place-12',
  }))
  seed.checkResults = { 12: { website_status: 'present', ordering_status: 'not_found' } }
  seed.contactResults = { 12: 'hello@freshfind.pk' }
  return seed
}

test.describe('Restaurant to campaign', () => {
  test('discovers, checks, qualifies, selects, drafts, approves, sends and tracks a campaign', async ({ page }) => {
    test.setTimeout(120_000)
    const backend = await installMockApi(page, workflowScenario())
    await openApp(page, 'leads')
    await expect(page.getByText(/Demo mode\./)).toBeVisible()

    // 1. Discover. Demo mode returns sample records only, and they cannot be emailed.
    await page.getByRole('button', { name: 'Discover businesses' }).click()
    const discover = page.getByRole('dialog', { name: 'Discover businesses' })
    await discover.getByRole('combobox', { name: 'City' }).fill('Lahore')
    await discover.getByRole('option', { name: /^Lahore/ }).click()
    await discover.getByRole('button', { name: 'Search Google Places' }).click()
    await expect(discover).toBeHidden()
    await expect(page.getByText('Found 3 businesses in Lahore.')).toBeVisible()

    const search = page.getByRole('searchbox', { name: 'Search leads' })
    await search.fill('DEMO')
    await expect(page.getByRole('checkbox', { name: 'Select [DEMO] Lahore sample business 1 for email campaign' })).toBeDisabled()

    // 2. Check the website and find an email for a restaurant that has not been checked yet.
    await search.fill('Fresh Find')
    const row = page.getByRole('row', { name: /Fresh Find Kitchen/ })
    await row.getByRole('button', { name: /^More actions for/ }).click()
    await page.getByRole('menuitem', { name: 'Check site' }).click()
    await expect(row.getByText('Live', { exact: true })).toBeVisible()
    await row.getByRole('button', { name: /^More actions for/ }).click()
    await page.getByRole('menuitem', { name: 'Find email' }).click()
    await expect(row.getByText('hello@freshfind.pk')).toBeVisible()

    // 3. Qualify. The score is calculated from the stored website, ordering and email data.
    await row.getByRole('button', { name: /^Qualify / }).click()
    await expect(row.getByText('Qualified', { exact: true })).toBeVisible()

    // 4. Select three eligible restaurants and start a campaign.
    // Selection is kept across searches, so search for each restaurant before ticking it. Fresh Find is not on page 1.
    for (const name of ['Fresh Find Kitchen', 'Lahore Karahi House', 'Gulberg Biryani Point']) {
      await search.fill(name)
      await page.getByRole('checkbox', { name: `Select ${name} for email campaign` }).check()
    }
    await search.fill('')
    await page.getByRole('button', { name: 'Email selected (3)' }).click()
    const setup = page.getByRole('dialog', { name: 'Email selected businesses' })
    await setup.getByLabel('Campaign name').fill('Lahore cafes, E2E')
    await expect(setup.getByRole('button', { name: 'Generate 3 drafts' })).toBeEnabled()
    await setup.getByRole('button', { name: 'Generate 3 drafts' }).click()

    await expect(page.getByRole('heading', { name: 'Lahore cafes, E2E' })).toBeVisible()
    await expect(page.getByText('Mock provider · no email leaves this app')).toBeVisible()
    const campaignId = backend.state.campaigns[0].id

    // 5. Review and approve each draft on the Outreach Drafts page. Approval records a decision only.
    await page.getByRole('link', { name: 'Outreach Drafts' }).click()
    for (let i = 0; i < 3; i += 1) {
      await page.locator('.draft-item').first().click()
      await page.getByRole('button', { name: 'Approve', exact: true }).click()
      const confirm = page.getByRole('dialog', { name: 'Approve this draft?' })
      await confirm.getByRole('button', { name: 'Approve', exact: true }).click()
      await expect(confirm).toBeHidden()
    }
    await expect(page.getByRole('heading', { name: 'No drafts here' })).toBeVisible()
    await page.getByRole('link', { name: 'Campaigns' }).click()
    await page.getByRole('row', { name: /Lahore cafes, E2E/ }).getByRole('button', { name: 'Review' }).click()
    await expect(page.getByRole('heading', { name: 'Lahore cafes, E2E' })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Send Approved to Selected (3)' })).toBeEnabled()

    // 6. Send. Each restaurant gets its own message, and only after a person acknowledges the list.

    await page.getByRole('button', { name: 'Send Approved to Selected (3)' }).click()
    const send = page.getByRole('dialog', { name: 'Send 3 approved emails?' })
    await expect(send.getByText(/Nothing is delivered to these addresses/)).toBeVisible()
    await expect(send.getByRole('button', { name: 'Send 3 emails' })).toBeDisabled()
    await send.getByRole('checkbox').check()
    await send.getByRole('button', { name: 'Send 3 emails' }).click()

    // 7. Track. Sends are recorded, but no delivery is claimed until the provider confirms it.
    await expect(page.getByText('Completed', { exact: true }).first()).toBeVisible({ timeout: 30_000 })
    const delivery = page.getByRole('region', { name: 'Delivery statistics' })
    await expect(delivery).toContainText('Out of 3 sent.')
    await expect(delivery).toContainText('No confirmation yet')
    const log = page.getByRole('region', { name: 'Sending log' })
    await expect(log.getByText('Sent', { exact: true })).toHaveCount(3)

    // 8. The run used the mock provider only.
    expect(backend.state.config.live_sending).toBe(false)
    expect(backend.state.campaigns[0].id).toBe(campaignId)
    expect(backend.state.campaigns[0].recipients.filter((r) => r.status === 'sent')).toHaveLength(3)

    // 9. The campaign list shows the finished campaign.
    await page.getByRole('link', { name: 'Campaigns' }).click()
    await expect(page.getByRole('row', { name: /Lahore cafes, E2E/ })).toContainText('Completed')
  })

  test('restaurants that are blocked from outreach cannot be chosen for a campaign', async ({ page }) => {
    await installMockApi(page, leadsScenario())
    await openApp(page, 'leads')

    for (const name of [
      '[DEMO] Sample Cafe',
      'Invalid Mail Bistro',
      'Opted Out Grill',
      'Disposable Eats',
      'No Email Diner',
      'Johar Town Pizza',
    ]) {
      await expect(page.getByRole('checkbox', { name: `Select ${name} for email campaign` })).toBeDisabled()
    }
    await expect(page.getByRole('button', { name: 'Email selected (0)' })).toBeDisabled()
  })
})
