import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import * as api from '../../src/services/api'
import CampaignSetupDialog from '../../src/components/CampaignSetupDialog'
import { installFakeApi, renderAppAt, waitForWorkspace, currentFakeApi } from '../support/render'
import { leadsScenario, seedApprovedCampaign } from '../support/scenarios'

async function openSetupFor(user, names) {
  for (const name of names) {
    await user.click(screen.getByRole('checkbox', { name: `Select ${name} for email campaign` }))
  }
  await user.click(screen.getByRole('button', { name: new RegExp(`^Email selected \\(${names.length}\\)`) }))
  return screen.findByRole('dialog', { name: 'Email selected businesses' })
}

describe('Campaign setup: recipient counts and eligibility', () => {
  it('counts selected, eligible and skipped recipients and says why one is skipped', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: 'Select all eligible (3)' }))
    await user.click(screen.getByRole('button', { name: 'Email selected (3)' }))

    const dialog = await screen.findByRole('dialog', { name: 'Email selected businesses' })
    expect(await within(dialog).findByText('Skipped and why')).toBeInTheDocument()
    expect(dialog.querySelector('.plan-summary').textContent).toBe('Selected3Eligible2Skipped1')
    expect(within(dialog).getByText(/Another restaurant in this selection uses the same address/)).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Generate 2 drafts' })).toBeEnabled()
  })

  it('needs a campaign name of at least two characters', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openSetupFor(user, ['Lahore Karahi House'])

    const name = within(dialog).getByLabelText('Campaign name')
    await user.clear(name)
    await user.type(name, 'A')
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('Campaign name needs at least 2 characters.')
    // An invalid name clears the eligibility plan, so the button shows zero and stays disabled.
    expect(within(dialog).getByRole('button', { name: 'Generate 0 drafts' })).toBeDisabled()
  })

  it('creates the campaign and opens its page', async () => {
    const { user, backend } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openSetupFor(user, ['Lahore Karahi House', 'Gulberg Biryani Point'])

    const name = within(dialog).getByLabelText('Campaign name')
    await user.clear(name)
    await user.type(name, 'Lahore cafes, May')
    await user.click(await within(dialog).findByRole('button', { name: 'Generate 2 drafts' }))

    expect(await screen.findByText('Campaign "Lahore cafes, May" created. Drafts are being written.')).toBeInTheDocument()
    await waitFor(() => expect(window.location.hash).toMatch(/^#campaigns\/\d+$/))
    const [campaign] = backend.state.campaigns
    expect(campaign.name).toBe('Lahore cafes, May')
    expect(campaign.recipients.filter((r) => r.status === 'draft')).toHaveLength(2)
  })

  it('blocks a restaurant that was already emailed in a campaign with the same name', async () => {
    const backend = installFakeApi({ ...leadsScenario(), sendBatch: 10 })
    const campaign = seedApprovedCampaign(backend, { name: 'Lahore cafes', restaurantIds: [1] })
    backend.handle({ method: 'POST', path: `/campaigns/${campaign.id}/send`, body: {} })
    backend.handle({ method: 'GET', path: `/campaigns/${campaign.id}` })
    expect(backend.state.campaigns[0].status).toBe('completed')

    const { user } = renderAppAt('leads')
    await waitForWorkspace()
    const dialog = await openSetupFor(user, ['Lahore Karahi House'])
    const name = within(dialog).getByLabelText('Campaign name')
    await user.clear(name)
    await user.type(name, 'Lahore cafes')

    expect(await within(dialog).findByText(/Already emailed in campaign "Lahore cafes"/)).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Generate 0 drafts' })).toBeDisabled()
  })

  it('blocks a restaurant already emailed by a campaign with a different name', async () => {
    const backend = installFakeApi({ ...leadsScenario(), sendBatch: 10 })
    const campaign = seedApprovedCampaign(backend, { name: 'Lahore cafes', restaurantIds: [1] })
    backend.handle({ method: 'POST', path: `/campaigns/${campaign.id}/send`, body: {} })
    backend.handle({ method: 'GET', path: `/campaigns/${campaign.id}` })

    const { user } = renderAppAt('leads')
    await waitForWorkspace()
    const dialog = await openSetupFor(user, ['Lahore Karahi House'])
    const name = within(dialog).getByLabelText('Campaign name')
    await user.clear(name)
    await user.type(name, 'Karachi cafes')

    expect(await within(dialog).findByText(/Already emailed in campaign "Lahore cafes"/)).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Generate 0 drafts' })).toBeDisabled()
  })

  it('warns and disables creation when nothing in the selection is eligible', () => {
    installFakeApi(leadsScenario())
    render(
      <CampaignSetupDialog open restaurantIds={[4, 5, 6]} onClose={vi.fn()} onCreate={vi.fn()} />,
    )
    return screen.findByText('None of the selected businesses can be emailed in this campaign.').then(() => {
      expect(screen.getByRole('button', { name: 'Generate 0 drafts' })).toBeDisabled()
    })
  })
})

describe('Demo, invalid, duplicate and opted-out restaurants never enter a campaign', () => {
  it('the preview marks each blocked restaurant with its reason', async () => {
    installFakeApi(leadsScenario())
    const plan = await api.previewCampaign('Lahore cafes', [3, 4, 5, 6, 8, 9, 10])
    expect(plan.eligible_count).toBe(0)
    const reasonsById = Object.fromEntries(plan.items.map((item) => [item.restaurant_id, item.reasons.join(' | ')]))
    expect(reasonsById[3]).toContain('Personal email address: needs manual review before outreach')
    expect(reasonsById[4]).toContain('Demo or sample record, not a real restaurant')
    expect(reasonsById[5]).toContain('Contact email is marked invalid')
    expect(reasonsById[6]).toContain('Business has opted out of outreach')
    expect(reasonsById[8]).toContain('No public email found')
    expect(reasonsById[9]).toContain('Disposable email address: not accepted for outreach')
    expect(reasonsById[10]).toContain('Not qualified (current status: new)')
  })

  it('the server refuses to create a campaign that has no eligible restaurant', async () => {
    installFakeApi(leadsScenario())
    await expect(api.createCampaign('Lahore cafes', [4, 5, 6])).rejects.toThrow(
      'None of the selected businesses are eligible for this campaign.',
    )
    expect(currentFakeApi().state.campaigns).toHaveLength(0)
  })

  it('the server skips a second restaurant that uses the same address inside one campaign', async () => {
    installFakeApi(leadsScenario())
    const plan = await api.previewCampaign('Lahore cafes', [1, 7])
    expect(plan.eligible_count).toBe(1)
    expect(plan.items.find((i) => i.restaurant_id === 7).reasons).toEqual([
      'Another restaurant in this selection uses the same address',
    ])
  })
})
