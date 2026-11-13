import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import { currentFakeApi, renderAppAt, waitForWorkspace } from '../support/render'
import { draftsScenario, leadsScenario } from '../support/scenarios'

const draftItem = (name) => screen.getByRole('button', { name: new RegExp(`^${name}`) })
const editorHeading = (name) => screen.getByRole('heading', { name, level: 3 })

describe('Outreach drafts list and editor', () => {
  it('lists drafts awaiting approval and opens the first one', async () => {
    renderAppAt('drafts', draftsScenario())
    await waitForWorkspace()
    expect(screen.getAllByRole('button', { pressed: true, name: /Lahore Karahi House|Johar Town Pizza/ })).toHaveLength(1)
    expect(editorHeading('Lahore Karahi House')).toBeInTheDocument()
    expect(screen.getByText('info@lahorekarahi.pk')).toBeInTheDocument()
    expect(screen.queryByText(/Approval is blocked/)).not.toBeInTheDocument()
  })

  it('switches between drafts from the list', async () => {
    const { user } = renderAppAt('drafts', draftsScenario())
    await waitForWorkspace()
    await user.click(draftItem('Johar Town Pizza'))
    expect(editorHeading('Johar Town Pizza')).toBeInTheDocument()
  })

  it('explains why approval is blocked for a personal email not yet reviewed', async () => {
    const { user } = renderAppAt('drafts', draftsScenario())
    await waitForWorkspace()
    await user.click(draftItem('Johar Town Pizza'))
    expect(screen.getByText(/Approval is blocked/)).toHaveTextContent(
      'Approval is blocked: personal email address awaiting manual review.',
    )
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled()
  })

  it('switches the editor between edit and preview views', async () => {
    const { user } = renderAppAt('drafts', draftsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: 'Preview' }))
    const preview = screen.getByLabelText('Email preview')
    // The "To:" and "Subject:" labels are in <strong> elements, so match the value text that follows them.
    expect(within(preview).getByText(/info@lahorekarahi\.pk/)).toBeInTheDocument()
    expect(within(preview).getByText(/Online ordering for Lahore Karahi House/)).toBeInTheDocument()
  })

  it('filters the list by status', async () => {
    const { user } = renderAppAt('drafts', draftsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: /Approved/ }))
    expect(screen.getByRole('heading', { name: 'No drafts here' })).toBeInTheDocument()
  })
})

describe('Editing and saving a draft', () => {
  it('enables Save only after a change, and blocks approval until the change is saved', async () => {
    const { user, backend } = renderAppAt('drafts', draftsScenario())
    await waitForWorkspace()
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeDisabled()

    const subject = screen.getByLabelText('Subject')
    await user.type(subject, ' (v2)')
    expect(screen.getByRole('button', { name: 'Save changes' })).toBeEnabled()
    expect(screen.getByText(/Approval is blocked/)).toHaveTextContent('save your changes first')
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Save changes' }))
    expect(await screen.findByText('Draft saved.')).toBeInTheDocument()
    expect(backend.state.drafts.find((d) => d.id === 2001).subject).toBe('Online ordering for Lahore Karahi House (v2)')
    await waitFor(() => expect(screen.getByRole('button', { name: 'Approve' })).toBeEnabled())
  })

  it('counts the characters in the body', async () => {
    renderAppAt('drafts', draftsScenario())
    await waitForWorkspace()
    expect(screen.getByText(/\/ 3000 characters/)).toBeInTheDocument()
  })
})

describe('Approving, rejecting and regenerating a draft', () => {
  it('approves a draft after confirmation and removes it from the awaiting list', async () => {
    const { user, backend } = renderAppAt('drafts', draftsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: 'Approve' }))

    const dialog = await screen.findByRole('dialog', { name: 'Approve this draft?' })
    expect(dialog).toHaveTextContent('Approval records your decision. Emails are sent only from a campaign, after you confirm the send.')
    await user.click(within(dialog).getByRole('button', { name: 'Approve' }))

    expect(await screen.findByText('Draft approved.')).toBeInTheDocument()
    expect(backend.state.drafts.find((d) => d.id === 2001).status).toBe('approved')
    await waitFor(() => expect(screen.queryByRole('button', { name: /^Lahore Karahi House/ })).not.toBeInTheDocument())
  })

  it('rejects a draft after confirmation', async () => {
    const { user, backend } = renderAppAt('drafts', draftsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: 'Reject' }))

    const dialog = await screen.findByRole('dialog', { name: 'Reject this draft?' })
    await user.click(within(dialog).getByRole('button', { name: 'Reject' }))

    expect(await screen.findByText('Draft rejected.')).toBeInTheDocument()
    expect(backend.state.drafts.find((d) => d.id === 2001).status).toBe('rejected')
  })

  it('does nothing when the reject confirmation is cancelled', async () => {
    const { user, backend } = renderAppAt('drafts', draftsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: 'Reject' }))
    const dialog = await screen.findByRole('dialog', { name: 'Reject this draft?' })
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(backend.state.drafts.find((d) => d.id === 2001).status).toBe('draft')
  })

  it('regenerates a draft after confirmation and keeps the old one as rejected', async () => {
    const { user, backend } = renderAppAt('drafts', draftsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: 'Regenerate' }))

    const dialog = await screen.findByRole('dialog', { name: 'Regenerate this draft?' })
    await user.click(within(dialog).getByRole('button', { name: 'Regenerate' }))

    expect(await screen.findByText('New draft generated.')).toBeInTheDocument()
    expect(backend.state.drafts.find((d) => d.id === 2001).status).toBe('rejected')
    expect(backend.state.drafts.filter((d) => d.restaurant_id === 1 && d.status === 'draft')).toHaveLength(1)
  })
})

describe('Drafting from the leads page', () => {
  it('writes a draft for an eligible restaurant with an email', async () => {
    const { user, backend } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const row = screen.getByRole('row', { name: /Lahore Karahi House/ })
    await user.click(within(row).getByRole('button', { name: /^Draft email for/ }))

    expect(await screen.findByText('Draft created for Lahore Karahi House.')).toBeInTheDocument()
    expect(backend.state.drafts.filter((d) => d.restaurant_id === 1)).toHaveLength(1)
    await waitFor(() => expect(within(row).getByText('Draft pending')).toBeInTheDocument())
  })

  it('does not offer a draft for an opted-out restaurant', async () => {
    renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const row = screen.getByRole('row', { name: /Opted Out Grill/ })
    expect(within(row).getByText('Opted out')).toBeInTheDocument()
    expect(within(row).queryByRole('button', { name: /^Draft email for/ })).not.toBeInTheDocument()
  })

  it('asks for an email before a draft can be written', async () => {
    renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const row = screen.getByRole('row', { name: /No Email Diner/ })
    expect(within(row).getByRole('button', { name: /^Draft email for/ })).toBeDisabled()
    expect(within(row).getByRole('button', { name: /^Draft email for/ })).toHaveAttribute('title', 'Find an email first')
  })

  it('is refused by the server for a demo record and the message is shown', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const row = screen.getByRole('row', { name: /\[DEMO\] Sample Cafe/ })
    await user.click(within(row).getByRole('button', { name: /^Draft email for/ }))
    // The refusal is shown in the toast. The same reason also appears in the row, so check the toast itself.
    await waitFor(() => {
      expect(document.querySelector('.toast-stack')).toHaveTextContent('Demo or sample record, not a real restaurant')
    })
    expect(currentFakeApi().state.drafts).toHaveLength(0)
  })
})

describe('Drafts list freshness', () => {
  it('shows drafts that a campaign wrote while the user was on another page', async () => {
    const { user, backend } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    // The campaign is created from the leads page; its drafts are written in the background.
    backend.handle({ method: 'POST', path: '/campaigns', body: { name: 'Lahore cafes', restaurant_ids: [1] } })

    await user.click(screen.getByRole('link', { name: /Outreach Drafts/ }))
    expect(await screen.findByRole('button', { name: /^Lahore Karahi House/ })).toBeInTheDocument()
  })
})
