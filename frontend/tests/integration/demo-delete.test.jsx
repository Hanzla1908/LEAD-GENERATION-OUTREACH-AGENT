import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import { currentFakeApi, renderAppAt, waitForWorkspace } from '../support/render'
import { leadsScenario } from '../support/scenarios'

describe('Deleting demo business records', () => {
  it('offers the delete action only when demo records exist, and shows how many', async () => {
    renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    expect(await screen.findByRole('button', { name: /Delete demo records \(\d+\)/ })).toBeInTheDocument()
    expect(currentFakeApi().state.restaurants.some((r) => r.source === 'demo')).toBe(true)
  })

  it('asks for confirmation, deletes the demo records, and keeps real businesses', async () => {
    const { user, backend } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const before = backend.state.restaurants.length
    const demoBefore = backend.state.restaurants.filter((r) => r.source === 'demo').length

    await user.click(await screen.findByRole('button', { name: /Delete demo records \(\d+\)/ }))
    const dialog = await screen.findByRole('dialog', { name: 'Delete demo records?' })
    expect(within(dialog).getByText(/Real businesses are never affected/)).toBeInTheDocument()
    expect(within(dialog).getByText(/cannot be undone/)).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: 'Delete demo records' }))

    await waitFor(() => {
      expect(backend.state.restaurants.some((r) => r.source === 'demo')).toBe(false)
    })
    expect(backend.state.restaurants.length).toBe(before - demoBefore)
    expect(backend.state.restaurants.some((r) => r.name === 'Lahore Karahi House')).toBe(true)
    expect(await screen.findByText(/Deleted \d+ demo records?\./)).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Delete demo records?' })).not.toBeInTheDocument())
  })

  it('cancelling the confirmation deletes nothing', async () => {
    const { user, backend } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const before = backend.state.restaurants.length

    await user.click(await screen.findByRole('button', { name: /Delete demo records \(\d+\)/ }))
    const dialog = await screen.findByRole('dialog', { name: 'Delete demo records?' })
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))

    expect(backend.state.restaurants.length).toBe(before)
  })
})
