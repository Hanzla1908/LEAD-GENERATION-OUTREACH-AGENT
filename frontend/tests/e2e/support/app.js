import { expect } from '@playwright/test'

/** Opens the app at a hash route and waits until the workspace has loaded. */
export async function openApp(page, route = 'overview') {
  await page.goto(`/#${route}`)
  await expect(page.getByRole('navigation', { name: 'Main navigation' })).toBeVisible()
  await expect(page.locator('.skeleton')).toHaveCount(0)
}
