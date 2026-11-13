import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import { renderAppAt, waitForWorkspace } from '../support/render'
import { leadsScenario } from '../support/scenarios'

function websiteRowNames() {
  return screen.getAllByRole('row').slice(1).map((row) => row.querySelector('.cell-title')?.textContent)
}

function leadCard(name) {
  return screen.getByRole('article', { name: `${name} lead` })
}

describe('Website analysis', () => {
  it('shows each restaurant with its website status and ordering signal', async () => {
    renderAppAt('website', leadsScenario())
    await waitForWorkspace()
    const row = screen.getByRole('row', { name: /Lahore Karahi House/ })
    expect(within(row).getByText('Live')).toBeInTheDocument()
    expect(within(row).getByText('No ordering')).toBeInTheDocument()
    expect(within(row).getByRole('button', { name: 'Recheck' })).toBeEnabled()
  })

  it('has nothing to check when every website has been checked', async () => {
    renderAppAt('website', leadsScenario())
    await waitForWorkspace()
    expect(screen.getByRole('button', { name: 'Check all unchecked (0)' })).toBeDisabled()
  })

  it('filters to restaurants with no online ordering', async () => {
    const { user } = renderAppAt('website', leadsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: /No online ordering/ }))
    expect(websiteRowNames()).toEqual([
      'Lahore Karahi House',
      'Gulberg Biryani Point',
      'Johar Town Pizza',
      'Same Address Cafe',
      'No Email Diner',
    ])
  })

  it('shows a restaurant without a website as having nothing to check', async () => {
    renderAppAt('website', leadsScenario())
    await waitForWorkspace()
    const row = screen.getByRole('row', { name: /Chai Corner/ })
    expect(within(row).getByRole('button', { name: 'Check' })).toBeDisabled()
  })

  it('rechecks a website and shows the new result', async () => {
    const { user } = renderAppAt('website', {
      ...leadsScenario(),
      checkResults: { 2: { website_status: 'not_found', ordering_status: 'unknown' } },
    })
    await waitForWorkspace()
    const row = screen.getByRole('row', { name: /Gulberg Biryani Point/ })
    await user.click(within(row).getByRole('button', { name: 'Recheck' }))
    await waitFor(() => expect(within(row).getByText('Not found')).toBeInTheDocument())
    expect(screen.getByText('Website checked.')).toBeInTheDocument()
  })
})

describe('Lead qualification', () => {
  it('shows the score, the reason and the signals behind it', async () => {
    renderAppAt('qualification', leadsScenario())
    await waitForWorkspace()
    const card = leadCard('Lahore Karahi House')
    expect(within(card).getByText('Score 90 of 90 possible')).toBeInTheDocument()
    expect(within(card).getByText('Score 90: live website, no online ordering, usable email, phone listed.')).toBeInTheDocument()
    expect(within(card).getByLabelText('Signals from stored data')).toHaveTextContent('Live website')
    expect(within(card).getByLabelText('Signals from stored data')).toHaveTextContent('No online ordering')
    expect(within(card).getByLabelText('Signals from stored data')).toHaveTextContent('Public email')
    expect(within(card).getByLabelText('Signals from stored data')).toHaveTextContent('Phone listed')
  })

  it('filters by review status', async () => {
    const { user } = renderAppAt('qualification', leadsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: /Needs review/ }))
    expect(screen.getAllByRole('article')).toHaveLength(1)
    expect(leadCard('Johar Town Pizza')).toBeInTheDocument()
  })

  it('requalifies a restaurant and shows the score the backend calculates', async () => {
    const { user } = renderAppAt('qualification', leadsScenario())
    await waitForWorkspace()
    const card = leadCard('Gulberg Biryani Point')
    expect(within(card).getByText('Score 65 of 90 possible')).toBeInTheDocument()

    await user.click(within(card).getByRole('button', { name: 'Requalify' }))
    await waitFor(() => expect(within(card).getByText('Score 80 of 90 possible')).toBeInTheDocument())
    expect(within(card).getByText('Qualified')).toBeInTheDocument()
  })

  it('scores every restaurant that is not yet qualified in one action', async () => {
    const { user } = renderAppAt('qualification', leadsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: 'Qualify all (1)' }))
    expect(await screen.findByText('Scored 1 business.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Qualify all (0)' })).toBeDisabled()
    expect(within(leadCard('Chai Corner')).getByText('Needs review')).toBeInTheDocument()
  })
})
