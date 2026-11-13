import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import { renderAppAt, waitForWorkspace } from '../support/render'
import { leadsScenario } from '../support/scenarios'

const KARAHI = 'Lahore Karahi House'
const BIRYANI = 'Gulberg Biryani Point'

function isListed(name) {
  return screen.queryByRole('checkbox', { name: `Select ${name} for email campaign` }) !== null
}

describe('Deleting a lead', () => {
  it('shows a trash button with the Delete Lead tooltip on each lead', async () => {
    renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const button = screen.getByRole('button', { name: `Delete ${KARAHI}` })
    expect(button).toHaveAttribute('title', 'Delete Lead')
  })

  it('asks for confirmation with the business name, then removes the lead at once', async () => {
    const { user, backend } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: `Delete ${KARAHI}` }))

    const dialog = await screen.findByRole('dialog', { name: `Delete ${KARAHI}?` })
    expect(within(dialog).getByText(/Its drafts, campaign records and email history are kept/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Delete lead' }))

    expect(await screen.findByText(`${KARAHI} deleted. You can restore it from Deleted leads.`)).toBeInTheDocument()
    await waitFor(() => expect(isListed(KARAHI)).toBe(false))
    expect(backend.state.restaurants.find((r) => r.name === KARAHI).deleted_at).toBeTruthy()
  })

  it('cancelling the confirmation keeps the lead', async () => {
    const { user, backend } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: `Delete ${KARAHI}` }))
    const dialog = await screen.findByRole('dialog', { name: `Delete ${KARAHI}?` })
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(isListed(KARAHI)).toBe(true)
    expect(backend.state.restaurants.find((r) => r.name === KARAHI).deleted_at).toBeFalsy()
  })

  it('deletes the selected leads in one step after one confirmation', async () => {
    const { user, backend } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('checkbox', { name: `Select ${KARAHI} for email campaign` }))
    await user.click(screen.getByRole('checkbox', { name: `Select ${BIRYANI} for email campaign` }))
    await user.click(screen.getByRole('button', { name: 'Delete selected (2)' }))

    const dialog = await screen.findByRole('dialog', { name: 'Delete 2 leads?' })
    await user.click(within(dialog).getByRole('button', { name: 'Delete leads' }))

    expect(await screen.findByText('Deleted 2 leads.')).toBeInTheDocument()
    await waitFor(() => {
      expect(isListed(KARAHI)).toBe(false)
      expect(isListed(BIRYANI)).toBe(false)
    })
    expect(backend.state.restaurants.filter((r) => r.deleted_at).map((r) => r.name)).toEqual(
      expect.arrayContaining([KARAHI, BIRYANI]))
  })

  it('restores a deleted lead from the Deleted leads view, and it returns to the table', async () => {
    const { user, backend } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: `Delete ${KARAHI}` }))
    await user.click(within(await screen.findByRole('dialog', { name: `Delete ${KARAHI}?` }))
      .getByRole('button', { name: 'Delete lead' }))
    await waitFor(() => expect(isListed(KARAHI)).toBe(false))

    await user.click(screen.getByRole('button', { name: 'Deleted leads' }))
    const view = await screen.findByRole('dialog', { name: 'Deleted leads' })
    expect(await within(view).findByText(KARAHI)).toBeInTheDocument()
    await user.click(within(view).getByRole('button', { name: 'Restore' }))

    expect(await screen.findByText(`${KARAHI} restored.`)).toBeInTheDocument()
    await waitFor(() => expect(isListed(KARAHI)).toBe(true))
    expect(backend.state.restaurants.find((r) => r.name === KARAHI).deleted_at).toBeFalsy()
  })

  it('a deleted lead is no longer offered for an email campaign', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: `Delete ${KARAHI}` }))
    await user.click(within(await screen.findByRole('dialog', { name: `Delete ${KARAHI}?` }))
      .getByRole('button', { name: 'Delete lead' }))
    await waitFor(() => expect(isListed(KARAHI)).toBe(false))
    expect(screen.queryByText(KARAHI)).not.toBeInTheDocument()
  })
})
