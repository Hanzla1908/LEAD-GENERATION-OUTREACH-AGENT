import { expect, test } from '@playwright/test'
import { installMockApi } from './support/mockApi.js'
import { openApp } from './support/app.js'
import { draftsScenario, leadsScenario } from '../support/scenarios.js'

// Runs on the desktop, tablet (768 px) and mobile (375 px) projects from playwright.config.js.
const PAGES = ['overview', 'leads', 'website', 'qualification', 'drafts', 'campaigns', 'settings']

for (const route of PAGES) {
  test(`${route} page fits the screen width without sideways page scrolling`, async ({ page }) => {
    await installMockApi(page, draftsScenario())
    await openApp(page, route)
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
    expect(overflow, `page is ${overflow}px wider than the screen`).toBeLessThanOrEqual(1)
  })
}

test('navigation can be reached at every screen size', async ({ page }) => {
  await installMockApi(page, draftsScenario())
  await openApp(page, 'overview')

  const toggle = page.locator('.topbar-menu')
  if ((page.viewportSize()?.width ?? 1280) <= 960) {
    await toggle.click()
  }
  const leads = page.getByRole('navigation', { name: 'Main navigation' }).getByRole('link', { name: 'Leads' })
  await expect(leads).toBeVisible()
  await leads.click()
  await expect(page.getByRole('heading', { name: 'Business leads' })).toBeVisible()
})

test('the lead list and the primary action stay usable on this screen', async ({ page }) => {
  await installMockApi(page, draftsScenario())
  await openApp(page, 'leads')
  await expect(page.getByRole('button', { name: 'Discover businesses' })).toBeVisible()
  await expect(page.getByRole('searchbox', { name: 'Search leads' })).toBeVisible()
  await expect(page.getByRole('checkbox', { name: 'Select Lahore Karahi House for email campaign' })).toBeVisible()
})

test('the menu button opens and closes the drawer on narrow screens, and is removed on wide screens', async ({ page }) => {
  await installMockApi(page, draftsScenario())
  await openApp(page, 'overview')
  const toggle = page.locator('.topbar-menu')
  const narrow = (page.viewportSize()?.width ?? 1280) <= 960
  if (narrow) {
    await expect(toggle).toBeVisible()
    await toggle.click()
    await expect(page.locator('.app')).toHaveClass(/nav-open/)
    await expect(page.locator('.sidebar')).toBeInViewport()
    await toggle.click()
    await expect(page.locator('.app')).not.toHaveClass(/nav-open/)
  } else {
    await expect(toggle).toBeHidden()
    await expect(page.locator('.sidebar')).toBeVisible()
  }
})

test('one click on Sign In from the sign-up page reaches the sign-in page', async ({ page }) => {
  await installMockApi(page, { ...draftsScenario(), authRequired: true, authenticated: false })
  await page.goto('/#signup')
  await expect(page.getByRole('heading', { name: 'Create your account' })).toBeVisible()
  await expect(page.getByLabel('Full name')).toBeFocused()
  await page.getByRole('link', { name: 'Sign In' }).click()
  await expect(page.getByRole('heading', { name: 'Sign in', exact: true })).toBeVisible({ timeout: 3000 })
})

test('the sidebar has its own close button in drawer mode', async ({ page }) => {
  test.skip((page.viewportSize()?.width ?? 1280) > 960, 'the drawer only exists on narrow screens')
  await installMockApi(page, draftsScenario())
  await openApp(page, 'overview')
  await page.locator('.topbar-menu').click()
  await expect(page.locator('.app')).toHaveClass(/nav-open/)
  await page.getByRole('button', { name: 'Close menu' }).click()
  await expect(page.locator('.app')).not.toHaveClass(/nav-open/)
})

test('a lead row keeps its secondary actions in the three-dot menu, which runs and closes', async ({ page }) => {
  await installMockApi(page, { ...leadsScenario(), authRequired: true, authenticated: true, sessionUserId: 1 })
  await openApp(page, 'leads')
  const row = page.getByRole('row', { name: /Lahore Karahi House/ })
  await row.getByRole('button', { name: /^More actions for/ }).click()
  await expect(page.getByRole('menuitem', { name: 'View history' })).toBeVisible()
  await page.getByRole('menuitem', { name: 'View history' }).click()
  await expect(page.getByRole('dialog', { name: /History:/ })).toBeVisible()
  await page.keyboard.press('Escape')
  await page.getByRole('row', { name: /Lahore Karahi House/ }).getByRole('button', { name: /^More actions for/ }).click()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('menu')).toHaveCount(0)
})
