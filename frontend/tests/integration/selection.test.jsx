import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { renderAppAt, waitForWorkspace } from '../support/render'
import { leadsScenario } from '../support/scenarios'

const box = (name) => screen.getByRole('checkbox', { name: `Select ${name} for email campaign` })
const selectionRegion = () => screen.getByRole('region', { name: 'Email selection' })

describe('Email eligibility in the lead list', () => {
  it('lets only eligible restaurants be selected', async () => {
    renderAppAt('leads', leadsScenario())
    await waitForWorkspace()

    expect(box('Lahore Karahi House')).toBeEnabled()
    expect(box('Gulberg Biryani Point')).toBeEnabled()
    expect(box('Same Address Cafe')).toBeEnabled()
    expect(screen.getAllByText('Eligible')).toHaveLength(3)
  })

  it.each([
    ['Johar Town Pizza', 'Personal email address: needs manual review before outreach'],
    ['[DEMO] Sample Cafe', 'Demo or sample record, not a real restaurant'],
    ['Invalid Mail Bistro', 'Contact email is marked invalid'],
    ['Opted Out Grill', 'Business has opted out of outreach'],
    ['No Email Diner', 'No public email found'],
    ['Disposable Eats', 'Disposable email address: not accepted for outreach'],
    ['Chai Corner', 'Not qualified (current status: new)'],
  ])('blocks %s and gives the reason', async (name, reason) => {
    renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    expect(box(name)).toBeDisabled()
    expect(box(name).getAttribute('title')).toContain(reason)
  })
})

describe('Selecting restaurants', () => {
  it('selects and deselects one restaurant at a time', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()

    await user.click(box('Lahore Karahi House'))
    expect(box('Lahore Karahi House')).toBeChecked()
    expect(selectionRegion()).toHaveTextContent('1 selected')
    expect(screen.getByRole('button', { name: 'Email selected (1)' })).toBeEnabled()

    await user.click(box('Lahore Karahi House'))
    expect(box('Lahore Karahi House')).not.toBeChecked()
    expect(selectionRegion()).toHaveTextContent('0 selected')
    expect(screen.getByRole('button', { name: 'Email selected (0)' })).toBeDisabled()
  })

  it('Select all eligible chooses every eligible restaurant in the filtered list', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()

    await user.click(screen.getByRole('button', { name: 'Select all eligible (3)' }))
    expect(selectionRegion()).toHaveTextContent('3 selected · 3 eligible')
    expect(box('Lahore Karahi House')).toBeChecked()
    expect(box('Gulberg Biryani Point')).toBeChecked()
    expect(box('Same Address Cafe')).toBeChecked()
    expect(screen.getByRole('button', { name: 'Email selected (3)' })).toBeEnabled()
  })

  it('removes one restaurant from a Select all selection', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: 'Select all eligible (3)' }))

    await user.click(box('Gulberg Biryani Point'))
    expect(box('Gulberg Biryani Point')).not.toBeChecked()
    expect(selectionRegion()).toHaveTextContent('2 selected')
    expect(box('Lahore Karahi House')).toBeChecked()
  })

  it('Clear selection empties the selection', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: 'Select all eligible (3)' }))

    await user.click(screen.getByRole('button', { name: 'Clear selection' }))
    expect(selectionRegion()).toHaveTextContent('0 selected')
    expect(box('Lahore Karahi House')).not.toBeChecked()
    expect(screen.getByRole('button', { name: 'Clear selection' })).toBeDisabled()
  })

  it('the page header checkbox selects and then deselects every eligible restaurant on the page', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const header = screen.getByRole('checkbox', { name: 'Select all eligible businesses on this page' })

    await user.click(header)
    await waitFor(() => expect(selectionRegion()).toHaveTextContent('3 selected'))

    await user.click(header)
    await waitFor(() => expect(selectionRegion()).toHaveTextContent('0 selected'))
    expect(box('Lahore Karahi House')).not.toBeChecked()
  })

  it('keeps the selection when the list moves to another page', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: 'Select all eligible (3)' }))

    await user.click(screen.getByRole('button', { name: 'Next' }))
    expect(selectionRegion()).toHaveTextContent('3 selected')
  })

  it('has nothing to select when the filter leaves no eligible restaurant', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const email = screen.getByLabelText('Filter by email')
    await user.selectOptions(email, 'review')

    expect(screen.getByRole('button', { name: 'Select all eligible (0)' })).toBeDisabled()
    expect(screen.getByRole('checkbox', { name: 'Select all eligible businesses on this page' })).toBeDisabled()
  })
})
