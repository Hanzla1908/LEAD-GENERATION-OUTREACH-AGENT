import { createFakeBackend } from '../../support/fakeBackend.js'

/**
 * Answers every /api request from the in-memory fake backend, and blocks every other external request.
 * Nothing reaches a real API, a database, Google Places, Claude, a mailbox or an email server.
 * Returns the backend so a test can read its state, for example to confirm no real provider was used.
 */
export async function installMockApi(page, seed = {}, { origin = 'http://127.0.0.1:4173' } = {}) {
  const backend = createFakeBackend(seed)

  await page.route((url) => url.origin !== origin, (route) => route.abort())

  await page.route(/\/api\//, async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const raw = request.postData()
    const result = backend.handle({
      method: request.method(),
      path: url.pathname.replace(/^\/api/, ''),
      query: url.searchParams,
      body: raw ? JSON.parse(raw) : {},
    })
    if (result.networkError) {
      await route.abort('failed')
      return
    }
    await route.fulfill({
      status: result.status,
      contentType: 'application/json',
      body: JSON.stringify(result.body),
    })
  })

  return backend
}
