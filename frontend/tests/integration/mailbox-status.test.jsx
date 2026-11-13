import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { renderAppAt, waitForWorkspace } from '../support/render'
import { leadsScenario } from '../support/scenarios'

describe('Reply monitoring setup on the Campaigns page', () => {
  it('shows a setup note, not an error, when the mailbox is not connected', async () => {
    renderAppAt('campaigns', { ...leadsScenario(), mailboxConfigured: false })
    await waitForWorkspace()
    expect(await screen.findByText('Reply monitoring is not connected yet.')).toBeInTheDocument()
    expect(screen.getByText(/MAILBOX_IMAP_HOST/)).toBeInTheDocument()
    expect(screen.queryByRole('alert', { name: /Mailbox monitoring is not configured/ })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Check mailbox now' })).toBeDisabled()
  })

  it('hides the setup note and enables the check once the mailbox is connected', async () => {
    renderAppAt('campaigns', { ...leadsScenario(), mailboxConfigured: true })
    await waitForWorkspace()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Check mailbox now' })).toBeEnabled())
    expect(screen.queryByText('Reply monitoring is not connected yet.')).not.toBeInTheDocument()
  })
})
