import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import { installFakeApi, renderAppAt, waitForWorkspace } from '../support/render'
import { leadsScenario, seedApprovedCampaign } from '../support/scenarios'

// Sending advances one recipient per poll (every 2 seconds), so these tests wait longer than usual.
const SLOW = 25000

/** Seeds one campaign: restaurants 1 and 2 with approved drafts, restaurant 7 skipped as a duplicate. */
function seedCampaign(options = {}) {
  const backend = installFakeApi({ ...leadsScenario(), sendBatch: 1, ...options })
  const campaign = seedApprovedCampaign(backend, { name: 'Lahore cafes', restaurantIds: [1, 2, 7] })
  return { backend, campaign }
}

/** Reads a stat tile by its label, for example statValue('Successfully sent') returns '2'. */
function statValue(label, scope = document.body) {
  return within(scope).getByText(label, { selector: '.metric-label' })
    .parentElement.querySelector('.metric-value').textContent
}

async function confirmSend(user) {
  await user.click(screen.getByRole('button', { name: 'Send Approved to Selected (2)' }))
  const dialog = await screen.findByRole('dialog', { name: 'Send 2 approved emails?' })
  await user.click(within(dialog).getByRole('checkbox'))
  await user.click(within(dialog).getByRole('button', { name: 'Send 2 emails' }))
}

describe('Campaign page: recipients and tracking display', () => {
  it('shows the recipient counts and the mock-provider notice', async () => {
    const { campaign } = seedCampaign()
    renderAppAt(`campaigns/${campaign.id}`)
    await waitForWorkspace()

    expect(statValue('Total selected')).toBe('3')
    expect(statValue('Eligible recipients')).toBe('2')
    expect(statValue('Approved emails')).toBe('2')
    expect(statValue('Successfully sent')).toBe('0')
    expect(statValue('Skipped recipients')).toBe('1')
    expect(screen.getByText('Mock provider · no email leaves this app')).toBeInTheDocument()
  })

  it('shows the skipped duplicate with its reason and no draft action', async () => {
    const { campaign } = seedCampaign()
    renderAppAt(`campaigns/${campaign.id}`)
    await waitForWorkspace()
    const table = screen.getByRole('region', { name: 'Recipients' })
    const row = within(table).getByRole('row', { name: /Same Address Cafe/ })
    expect(within(row).getByText(/Another restaurant in this selection uses the same address/)).toBeInTheDocument()
    expect(within(row).queryByRole('button', { name: /draft/i })).not.toBeInTheDocument()
  })

  it('opens a draft for review from the recipient row', async () => {
    const { campaign } = seedCampaign()
    const { user } = renderAppAt(`campaigns/${campaign.id}`)
    await waitForWorkspace()
    const table = screen.getByRole('region', { name: 'Recipients' })
    // Approved drafts open with "View draft"; only drafts still awaiting approval say "Review draft".
    await user.click(within(table).getAllByRole('button', { name: 'View draft' })[0])
    expect(await screen.findByRole('dialog', { name: 'Draft for Lahore Karahi House' })).toBeInTheDocument()
  })

  it('reports a failed draft write with a retry action', async () => {
    const { campaign } = seedCampaign({ failDraftFor: [2] })
    renderAppAt(`campaigns/${campaign.id}`)
    await waitForWorkspace()
    expect(statValue('Drafts generated')).toBe('1')
    expect(screen.getByRole('button', { name: 'Retry 1 failed draft' })).toBeInTheDocument()
  })

  it('separates confirmed deliveries from sends that have no confirmation yet', async () => {
    const { campaign, backend } = seedCampaign()
    backend.state.campaigns[0].recipients
      .filter((r) => r.status === 'draft')
      .forEach((r) => { r.status = 'sent' })
    renderAppAt(`campaigns/${campaign.id}`)
    await waitForWorkspace()

    const delivery = screen.getByRole('region', { name: 'Delivery statistics' })
    expect(within(delivery).getByText('Out of 2 sent.')).toBeInTheDocument()
    expect(statValue('No confirmation yet', delivery)).toBe('2')
    expect(statValue('Delivered (confirmed)', delivery)).toBe('0')
    expect(within(delivery).getByText(/does not mean the email was delivered/)).toBeInTheDocument()
  })
})

describe('Sending a campaign', () => {
  it('needs an explicit acknowledgement before sending', async () => {
    const { campaign } = seedCampaign()
    const { user } = renderAppAt(`campaigns/${campaign.id}`)
    await waitForWorkspace()

    await user.click(screen.getByRole('button', { name: 'Send Approved to Selected (2)' }))
    const dialog = await screen.findByRole('dialog', { name: 'Send 2 approved emails?' })
    expect(within(dialog).getByText(/Each business receives its own individual message/)).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Send 2 emails' })).toBeDisabled()

    await user.click(within(dialog).getByRole('checkbox'))
    expect(within(dialog).getByRole('button', { name: 'Send 2 emails' })).toBeEnabled()

    await user.click(within(dialog).getByRole('button', { name: 'Back' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Send 2 approved emails?' })).not.toBeInTheDocument())
    expect(statValue('Successfully sent')).toBe('0')
  })

  it('sends each approved email, shows progress, and records every step in the log', async () => {
    const { campaign, backend } = seedCampaign()
    const { user } = renderAppAt(`campaigns/${campaign.id}`)
    await waitForWorkspace()

    await confirmSend(user)
    expect(await screen.findByText('Send approved. Emails are being sent in the background.')).toBeInTheDocument()
    await waitFor(() => expect(statValue('Successfully sent')).toBe('2'), { timeout: SLOW })
    expect(statValue('Failed emails')).toBe('0')
    expect(backend.state.config.sent_today).toBe(2)

    const delivery = screen.getByRole('region', { name: 'Delivery statistics' })
    expect(within(delivery).getByText('Out of 2 sent.')).toBeInTheDocument()

    const log = screen.getByRole('region', { name: 'Sending log' })
    expect(within(log).getByText('Approved')).toBeInTheDocument()
    expect(within(log).getAllByText('Sent')).toHaveLength(2)
  }, SLOW)

  it('shows a failed send with the provider reason and offers a retry', async () => {
    const { campaign, backend } = seedCampaign({ failSendTo: ['info@lahorekarahi.pk'] })
    const { user } = renderAppAt(`campaigns/${campaign.id}`)
    await waitForWorkspace()

    await confirmSend(user)
    await waitFor(() => {
      expect(statValue('Failed emails')).toBe('1')
      expect(statValue('Successfully sent')).toBe('1')
    }, { timeout: SLOW })
    const table = screen.getByRole('region', { name: 'Recipients' })
    expect(within(table).getByText('The mock provider rejected this address.')).toBeInTheDocument()
    expect(backend.state.logs.filter((l) => l.event === 'failed')).toHaveLength(1)

    await user.click(screen.getByRole('button', { name: 'Retry 1 failed email' }))
    expect(await screen.findByText('Retrying failed emails.')).toBeInTheDocument()
    // The retry reaches the provider again: a second failure is logged, and the campaign completes.
    await waitFor(() => {
      expect(backend.state.logs.filter((l) => l.event === 'failed')).toHaveLength(2)
      expect(backend.state.campaigns[0].status).toBe('completed')
    }, { timeout: SLOW })
  }, SLOW)

  it('cancels a campaign that has not been sent, after confirmation', async () => {
    const { campaign } = seedCampaign()
    const { user } = renderAppAt(`campaigns/${campaign.id}`)
    await waitForWorkspace()

    await user.click(screen.getByRole('button', { name: 'Cancel campaign' }))
    const dialog = await screen.findByRole('dialog', { name: 'Cancel this campaign?' })
    await user.click(within(dialog).getByRole('button', { name: 'Cancel campaign' }))

    expect(await screen.findByText('Campaign cancelled.')).toBeInTheDocument()
    expect(screen.getAllByText('Cancelled').length).toBeGreaterThan(0)
  })
})

describe('Campaign list and reply tracking', () => {
  it('lists campaigns with their status', async () => {
    seedCampaign()
    renderAppAt('campaigns')
    await waitForWorkspace()
    const list = await screen.findByRole('region', { name: 'Campaigns' })
    const row = within(list).getByRole('row', { name: /Lahore cafes/ })
    expect(within(row).getByText('Ready for review')).toBeInTheDocument()
  })

  it('says nothing is waiting when the reply inbox is empty', async () => {
    renderAppAt('campaigns', leadsScenario())
    await waitForWorkspace()
    expect(await screen.findByText('Nothing is waiting for review.')).toBeInTheDocument()
  })

  it('confirms an uncertain reply, and shows reply text as plain text', async () => {
    const { user } = renderAppAt('campaigns', {
      ...leadsScenario(),
      reviewQueue: [{
        id: 9001,
        subject: 'Re: Online ordering',
        from_address: 'owner@lahorekarahi.pk',
        received_at: '2026-11-02 10:00:00',
        body_text: '<b>Yes, send details.</b>',
        match_status: 'needs_review',
        match_reason: 'Could be a reply to two businesses.',
        recipient_id: 1,
      }],
    })
    await waitForWorkspace()
    const inbox = screen.getByRole('region', { name: 'Reply inbox' })
    expect(await within(inbox).findByText('Uncertain')).toBeInTheDocument()
    expect(within(inbox).getByText('<b>Yes, send details.</b>')).toBeInTheDocument()

    await user.click(within(inbox).getByRole('button', { name: 'Confirm reply' }))
    expect(await within(inbox).findByText('Nothing is waiting for review.')).toBeInTheDocument()
  })

  it('dismisses an unmatched message and offers no confirm action for it', async () => {
    const { user } = renderAppAt('campaigns', {
      ...leadsScenario(),
      reviewQueue: [{
        id: 9002,
        subject: 'Newsletter',
        from_address: 'news@example.test',
        received_at: '2026-11-02 11:00:00',
        body_text: 'Weekly update.',
        match_status: 'unmatched',
        match_reason: 'No campaign email matches this message.',
        recipient_id: null,
      }],
    })
    await waitForWorkspace()
    const inbox = screen.getByRole('region', { name: 'Reply inbox' })
    expect(await within(inbox).findByText('Unmatched')).toBeInTheDocument()
    expect(within(inbox).queryByRole('button', { name: 'Confirm reply' })).not.toBeInTheDocument()

    await user.click(within(inbox).getByRole('button', { name: 'Dismiss' }))
    expect(await within(inbox).findByText('Nothing is waiting for review.')).toBeInTheDocument()
  })

  it('shows the delivery history for a restaurant from the leads page', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const row = screen.getByRole('row', { name: /Lahore Karahi House/ })
    await user.click(within(row).getByRole('button', { name: /^More actions for/ }))
    await user.click(screen.getByRole('menuitem', { name: 'View history' }))
    const dialog = await screen.findByRole('dialog', { name: 'History: Lahore Karahi House' })
    expect(await within(dialog).findByText('No confirmed delivery events or replies for this business yet.')).toBeInTheDocument()
  })
})
