import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import { renderAppAt, waitForWorkspace } from '../support/render'
import { leadsScenario } from '../support/scenarios'

const johar = (backend) => backend.state.restaurants.find((r) => r.name === 'Johar Town Pizza')

describe('Marking a lead that needs review as qualified', () => {
  it('shows the action only on leads that need review', async () => {
    renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    expect(screen.getByRole('button', { name: 'Mark Johar Town Pizza as qualified after review' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Mark Lahore Karahi House as qualified after review' })).not.toBeInTheDocument()
  })

  it('asks for confirmation, then records the decision and keeps the score', async () => {
    const { user, backend } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: 'Mark Johar Town Pizza as qualified after review' }))
    const dialog = await screen.findByRole('dialog', { name: 'Mark Johar Town Pizza as qualified?' })
    expect(within(dialog).getByText(/Only do this after you have checked the business yourself/)).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: 'Mark qualified' }))

    await waitFor(() => expect(johar(backend).lead_status).toBe('qualified'))
    expect(johar(backend).lead_score).toBe(40)
    expect(johar(backend).lead_reason).toBe('Qualified by manual review')
    expect(await screen.findByText('Johar Town Pizza marked as qualified after review.')).toBeInTheDocument()
  })

  it('cancelling the confirmation changes nothing', async () => {
    const { user, backend } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: 'Mark Johar Town Pizza as qualified after review' }))
    const dialog = await screen.findByRole('dialog', { name: 'Mark Johar Town Pizza as qualified?' })
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(johar(backend).lead_status).toBe('needs_review')
  })
})
