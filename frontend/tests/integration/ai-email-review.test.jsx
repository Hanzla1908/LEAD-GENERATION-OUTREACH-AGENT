import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import { currentFakeApi, renderAppAt, waitForWorkspace } from '../support/render'
import { draftsScenario } from '../support/scenarios'

const LAHORE = 'Lahore Karahi House'
const JOHAR = 'Johar Town Pizza'

function listItem(name) {
  return screen.getByRole('button', { name: new RegExp(name) })
}

describe('Reviewing AI-written emails', () => {
  it('marks a changed draft as Edited once the change is saved', async () => {
    const { user, backend } = renderAppAt('drafts', draftsScenario())
    await waitForWorkspace()
    await user.type(screen.getByLabelText('Body'), ' Thank you.')
    await user.click(screen.getByRole('button', { name: 'Save changes' }))

    await waitFor(() => expect(backend.state.drafts.find((d) => d.id === 2001).edited_at).toBeTruthy())
    expect(await within(listItem(LAHORE)).findByText('Edited')).toBeInTheDocument()
  })

  it('keeps unsaved edits when moving to another draft and back', async () => {
    const { user } = renderAppAt('drafts', draftsScenario())
    await waitForWorkspace()
    await user.type(screen.getByLabelText('Subject'), ' (draft note)')
    await user.click(listItem(JOHAR))
    await user.click(listItem(LAHORE))
    expect(screen.getByLabelText('Subject').value).toContain('(draft note)')
    expect(within(listItem(LAHORE)).getByText('Unsaved changes')).toBeInTheDocument()
  })

  it('regenerates with the reviewer instructions', async () => {
    const { user, backend } = renderAppAt('drafts', draftsScenario())
    await waitForWorkspace()
    await user.type(screen.getByLabelText('Instructions for a new draft (optional)'), 'Make it shorter')
    await user.click(screen.getByRole('button', { name: 'Regenerate' }))
    const dialog = await screen.findByRole('dialog', { name: 'Regenerate this draft?' })
    await user.click(within(dialog).getByRole('button', { name: 'Regenerate' }))

    await waitFor(() => expect(backend.state.lastRegenerateInstructions).toBe('Make it shorter'))
    expect(backend.state.drafts.find((d) => d.id === 2001).status).toBe('rejected')
  })

  it('approves selected drafts in bulk after one confirmation', async () => {
    const { user, backend } = renderAppAt('drafts', draftsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('checkbox', { name: /Select the draft for Lahore Karahi House/ }))
    await user.click(screen.getByRole('button', { name: 'Approve selected (1)' }))
    const dialog = await screen.findByRole('dialog', { name: 'Approve 1 draft?' })
    await user.click(within(dialog).getByRole('button', { name: 'Approve 1' }))

    await waitFor(() => expect(backend.state.drafts.find((d) => d.id === 2001).status).toBe('approved'))
  })

  it('skips selected drafts that cannot be approved yet, and says so', async () => {
    const { user, backend } = renderAppAt('drafts', draftsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('checkbox', { name: /Select the draft for Lahore Karahi House/ }))
    await user.click(screen.getByRole('checkbox', { name: /Select the draft for Johar Town Pizza/ }))
    expect(screen.getByRole('button', { name: 'Approve selected (1)' })).toBeInTheDocument()
    expect(screen.getByText(/1 cannot be approved yet and will be skipped/)).toBeInTheDocument()
    expect(backend.state.drafts.find((d) => d.id === 2002).status).toBe('draft')
  })

  it('shows a sent draft as Sent and lists it under the Sent filter', async () => {
    const seed = draftsScenario()
    seed.drafts[0] = { ...seed.drafts[0], status: 'approved', sent: true }
    const { user } = renderAppAt('drafts', seed)
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: /^Sent/ }))
    expect(within(listItem(LAHORE)).getByText('Sent')).toBeInTheDocument()
    expect(currentFakeApi().state.drafts.find((d) => d.id === 2001).sent).toBe(true)
  })
})
