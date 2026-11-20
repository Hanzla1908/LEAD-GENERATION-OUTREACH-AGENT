import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import { renderAppAt, waitForWorkspace } from '../support/render'
import { leadsScenario } from '../support/scenarios'

function leadNames() {
  return screen.queryAllByRole('checkbox', { name: /for email campaign$/ })
    .map((box) => box.getAttribute('aria-label').replace(/^Select /, '').replace(/ for email campaign$/, ''))
}

async function openDiscover(user) {
  await user.click(screen.getByRole('button', { name: 'Discover businesses' }))
  return screen.findByRole('dialog', { name: 'Discover businesses' })
}

describe('Discover businesses: country, city and business type', () => {
  it('searches a city from the list with a restaurant type and sends both to the API', async () => {
    const { user, backend } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)

    await user.type(within(dialog).getByRole('combobox', { name: 'City' }), 'Kar')
    await user.click(await screen.findByRole('option', { name: /^Karachi/ }))
    await user.selectOptions(within(dialog).getByLabelText('Business type'), 'biryani')
    await user.click(within(dialog).getByRole('button', { name: 'Search Google Places' }))

    await waitFor(() => {
      expect(backend.state.lastDiscover).toMatchObject({ city: 'Karachi', category: 'biryani', limit: 10, country_code: 'PK' })
    })
    expect(backend.state.lastDiscover.city_id).toEqual(expect.any(Number))
    expect(await screen.findByText('Found 3 businesses in Karachi.')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Discover businesses' })).not.toBeInTheDocument())
  })

  it('shows demo results as [DEMO] records that cannot be emailed', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    expect(screen.getByText(/Demo mode\./)).toBeInTheDocument()

    const dialog = await openDiscover(user)
    await user.type(within(dialog).getByRole('combobox', { name: 'City' }), 'Lahore{Enter}')
    await user.click(within(dialog).getByRole('button', { name: 'Search Google Places' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Discover businesses' })).not.toBeInTheDocument())

    // The three demo records sort after the first page, so narrow the list to them.
    await user.type(screen.getByRole('searchbox', { name: 'Search leads' }), 'DEMO')
    const demoBox = await screen.findByRole('checkbox', { name: 'Select [DEMO] Lahore sample business 1 for email campaign' })
    expect(demoBox).toBeDisabled()
    expect(demoBox.getAttribute('title')).toContain('Demo or sample record, not a real restaurant')
  })

  it('searches any city typed by hand, in a country chosen from the list', async () => {
    const { user, backend } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)

    await user.type(within(dialog).getByRole('combobox', { name: 'Country' }), 'United States{Enter}')
    await user.type(within(dialog).getByRole('combobox', { name: 'City' }), 'New York')
    await user.click(within(dialog).getByRole('button', { name: 'Search Google Places' }))

    await waitFor(() => {
      expect(backend.state.lastDiscover).toMatchObject({ city: 'New York', country_code: 'US' })
    })
  })

  it('refuses to search without a city and does not call the API', async () => {
    const { user, backend } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)

    await user.click(within(dialog).getByRole('button', { name: 'Search Google Places' }))
    expect(await within(dialog).findByText('Enter a city name.')).toBeInTheDocument()
    expect(backend.state.lastDiscover).toBeNull()
  })

  it('rejects a result count outside 1 to 60', async () => {
    const { user, backend } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)

    await user.type(within(dialog).getByRole('combobox', { name: 'City' }), 'Lahore')
    const limit = within(dialog).getByRole('spinbutton', { name: /Results \(1.60\)/ })
    await user.clear(limit)
    await user.type(limit, '0')
    await user.click(within(dialog).getByRole('button', { name: 'Search Google Places' }))

    expect(await within(dialog).findByText('Choose between 1 and 60 results.')).toBeInTheDocument()
    expect(backend.state.lastDiscover).toBeNull()
  })

  it('says so when a live search finds nothing in the chosen city', async () => {
    const { user } = renderAppAt('leads', {
      ...leadsScenario(),
      discoveryMode: { demo_mode: false, live_key_configured: true },
    })
    await waitForWorkspace()
    const dialog = await openDiscover(user)

    await user.type(within(dialog).getByRole('combobox', { name: 'Country' }), 'United States{Enter}')
    await user.type(within(dialog).getByRole('combobox', { name: 'City' }), 'Gujrat')
    await user.click(within(dialog).getByRole('button', { name: 'Search Google Places' }))

    expect(await within(dialog).findByText(/No businesses were found in Gujrat for this type/)).toBeInTheDocument()
  })
})

describe('Lead list filters', () => {
  it('searches by name, address and email', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const search = screen.getByRole('searchbox', { name: 'Search leads' })

    await user.type(search, 'Biryani')
    expect(leadNames()).toEqual(['Gulberg Biryani Point'])

    await user.clear(search)
    await user.type(search, 'hello@gulbergbiryani.pk')
    expect(leadNames()).toEqual(['Gulberg Biryani Point'])
  })

  it('filters by lead status', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    await user.selectOptions(screen.getByLabelText('Filter by lead status'), 'new')
    expect(leadNames()).toEqual(['Chai Corner'])
    await user.selectOptions(screen.getByLabelText('Filter by lead status'), 'disqualified')
    expect(leadNames()).toEqual(['Roadside Dhaba'])
  })

  it('filters by website presence', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    await user.selectOptions(screen.getByLabelText('Filter by website'), 'none')
    expect(leadNames()).toEqual([
      '[DEMO] Sample Cafe',
      'Invalid Mail Bistro',
      'Opted Out Grill',
      'Disposable Eats',
      'Chai Corner',
      'Roadside Dhaba',
    ])
  })

  it('filters by email status, including personal and disposable addresses', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const email = screen.getByLabelText('Filter by email')

    await user.selectOptions(email, 'review')
    expect(leadNames()).toEqual(['Johar Town Pizza'])

    await user.selectOptions(email, 'invalid')
    expect(leadNames()).toEqual(['Invalid Mail Bistro', 'Disposable Eats'])

    await user.selectOptions(email, 'none')
    expect(leadNames()).toEqual(['No Email Diner', 'Roadside Dhaba'])
  })

  it('shows a message and a way out when nothing matches', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    await user.type(screen.getByRole('searchbox', { name: 'Search leads' }), 'zzz-no-match')
    expect(await screen.findByRole('heading', { name: 'No leads match these filters' })).toBeInTheDocument()

    await user.click(screen.getAllByRole('button', { name: 'Clear filters' })[0])
    expect(leadNames()).toHaveLength(10)
  })

  it('pages through the list, ten restaurants at a time', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    expect(screen.getByText(/Showing 1.10 of 11/)).toBeInTheDocument()
    expect(screen.getByText('Page 1 of 2')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByText(/Showing 11.11 of 11/)).toBeInTheDocument()
    expect(leadNames()).toEqual(['Roadside Dhaba'])
  })
})
