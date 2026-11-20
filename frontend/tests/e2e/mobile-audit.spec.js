import { expect, test } from '@playwright/test'
import { installMockApi } from './support/mockApi.js'
import { openApp } from './support/app.js'
import { draftsScenario, seedApprovedCampaign } from '../support/scenarios.js'

// Regression check: every page, including a campaign detail page, must fit the screen at phone and tablet widths.
// Runs in the desktop project, which changes the viewport itself. A page that is wider than the screen fails here.
const WIDTHS = [360, 375, 390, 414, 768]

// Phone emulation (touch, mobile browser scaling) so the check matches a real phone, not a desktop window.
test.use({ isMobile: true, hasTouch: true })
const ROUTES = ['overview', 'leads', 'website', 'qualification', 'drafts', 'campaigns', 'settings', 'team', 'users', 'workspaces']

async function overflowOf(page) {
  return page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
}

for (const width of WIDTHS) {
  test(`every page fits a ${width}px screen without sideways page scrolling`, async ({ page }) => {
    test.setTimeout(180_000)
    await page.setViewportSize({ width, height: 812 })

    for (const route of ROUTES) {
      await installMockApi(page, draftsScenario())
      await openApp(page, route)
      expect(await overflowOf(page), `${route} at ${width}px`).toBeLessThanOrEqual(1)
      await page.unrouteAll({ behavior: 'ignoreErrors' })
    }

    const backend = await installMockApi(page, draftsScenario())
    const campaign = seedApprovedCampaign(backend, { name: 'Outreach 2026-11-16(ITz)', restaurantIds: [1] })
    await openApp(page, 'campaigns')
    expect(await overflowOf(page), `campaigns list with a campaign at ${width}px`).toBeLessThanOrEqual(1)
    await page.unrouteAll({ behavior: 'ignoreErrors' })

    const detail = await installMockApi(page, draftsScenario())
    const seeded = seedApprovedCampaign(detail, { name: 'Outreach 2026-11-16(ITz)', restaurantIds: [1] })
    await openApp(page, `campaigns/${seeded.id}`)
    expect(await overflowOf(page), `campaign detail at ${width}px`).toBeLessThanOrEqual(1)
    await page.unrouteAll({ behavior: 'ignoreErrors' })
  })
}
