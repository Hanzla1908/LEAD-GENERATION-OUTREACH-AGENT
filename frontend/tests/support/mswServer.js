import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import { createFakeBackend } from './fakeBackend'

// The API origin comes from .env.test. Requests to any other origin are unhandled and fail the test.
const API_ORIGIN = (import.meta.env.VITE_API_ORIGIN || 'http://api.test').replace(/\/+$/, '')

let current = createFakeBackend()

/** Replaces the fake backend for the next test. Each test starts from a clean, isolated state. */
export function installFakeApi(seed = {}) {
  current = createFakeBackend(seed)
  return current
}

export function currentFakeApi() {
  return current
}

export const server = setupServer(
  http.all(`${API_ORIGIN}/*`, async ({ request }) => {
    const url = new URL(request.url)
    const text = await request.text()
    const body = text ? JSON.parse(text) : {}
    const result = current.handle({
      method: request.method,
      path: url.pathname,
      query: url.searchParams,
      body,
    })
    if (result.networkError) return HttpResponse.error()
    return HttpResponse.json(result.body, { status: result.status })
  }),
)
