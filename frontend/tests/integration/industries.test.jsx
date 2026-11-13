import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import { currentFakeApi, renderAppAt, waitForWorkspace } from '../support/render'
import { leadsScenario } from '../support/scenarios'

async function openDiscover(user) {
  await user.click(screen.getByRole('button', { name: 'Discover businesses' }))
  return screen.findByRole('dialog', { name: 'Discover businesses' })
}

describe('Discovery by industry', () => {
  it('offers the industries from the server, and restaurants stay the default', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)

    const industry = within(dialog).getByLabelText('Industry')
    expect(await within(industry).findByRole('option', { name: 'Real Estate & Property' })).toBeInTheDocument()
    expect(within(industry).getByRole('option', { name: 'Healthcare & Clinics' })).toBeInTheDocument()
    expect(industry).toHaveValue('restaurants_food')
    expect(within(dialog).getByLabelText('Business type')).toBeInTheDocument()
  })

  it('a real estate search sends its industry and subcategory and reports businesses', async () => {
    const { user, backend } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)

    await user.type(within(dialog).getByRole('combobox', { name: 'City' }), 'Karachi')
    await user.click(await screen.findByRole('option', { name: /^Karachi/ }))
    await user.selectOptions(within(dialog).getByLabelText('Industry'), 'real_estate')
    expect(within(dialog).getByLabelText('Business type')).toBeInTheDocument()
    await user.selectOptions(within(dialog).getByLabelText('Business type'), 'rentals')
    await user.click(within(dialog).getByRole('button', { name: 'Search Google Places' }))

    await waitFor(() => {
      expect(backend.state.lastDiscover).toMatchObject({
        city: 'Karachi', category: 'rentals', limit: 10, industry: 'real_estate', subcategory: 'rentals', country_code: 'PK',
      })
    })
    expect(await screen.findByText('Found 3 businesses in Karachi.')).toBeInTheDocument()
  })

  it('switching industry resets the business type to that industry’s first subcategory', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)

    await user.selectOptions(within(dialog).getByLabelText('Business type'), 'biryani')
    await user.selectOptions(within(dialog).getByLabelText('Industry'), 'healthcare')
    expect(within(dialog).getByLabelText('Business type')).toHaveValue('clinic')
    expect(within(dialog).getByRole('option', { name: 'Dental clinics' })).toBeInTheDocument()
  })

  it('a restaurant search sends its country with the original fields', async () => {
    const { user, backend } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)

    await user.type(within(dialog).getByRole('combobox', { name: 'City' }), 'Lahore{Enter}')
    await user.click(within(dialog).getByRole('button', { name: 'Search Google Places' }))
    await waitFor(() => {
      expect(currentFakeApi().state.lastDiscover).toEqual({ city: 'Lahore', category: 'all', limit: 10, country_code: 'PK' })
    })
    expect(backend.state.lastDiscover).not.toHaveProperty('industry')
  })
})
