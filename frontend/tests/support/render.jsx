import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect } from 'vitest'
import App from '../../src/App.jsx'
import { currentFakeApi, installFakeApi } from './mswServer'

/**
 * Renders the whole app at a route with a fresh fake backend. Call waitForWorkspace() before asserting.
 * route is a hash such as 'leads' or 'campaigns/3001'.
 */
export function renderAppAt(route = 'overview', seed) {
  if (seed) installFakeApi(seed)
  window.location.hash = route
  const user = userEvent.setup()
  const utils = render(<App />)
  return { user, backend: currentFakeApi(), ...utils }
}

/** Waits until the session check, the navigation and the first data load have finished. */
export async function waitForWorkspace() {
  await screen.findByRole('navigation', { name: 'Main navigation' })
  await waitFor(() => {
    expect(document.querySelector('.skeleton')).toBeNull()
  })
}

/** Reads the table rows of the lead list as plain text, one string per row. */
export function leadRowTexts() {
  return screen.getAllByRole('row').slice(1).map((row) => row.textContent)
}

export { currentFakeApi, installFakeApi }
