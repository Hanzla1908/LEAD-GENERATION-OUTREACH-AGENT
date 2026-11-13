import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, beforeEach } from 'vitest'
import { installFakeApi, server } from '../support/mswServer'

beforeAll(() => {
  // Any request the fake backend does not answer fails the test instead of reaching the network.
  server.listen({ onUnhandledRequest: 'error' })
})

beforeEach(() => {
  installFakeApi()
  window.location.hash = ''
})

afterEach(() => {
  cleanup()
  server.resetHandlers()
})

afterAll(() => {
  server.close()
})

// jsdom does not implement these browser APIs. The app does not depend on them; the shims only stop
// components from throwing if they call them.
if (!window.matchMedia) {
  window.matchMedia = (query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener() {},
    removeListener() {},
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() { return false },
  })
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = function scrollIntoView() {}
}
