import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import { renderAppAt, waitForWorkspace } from '../support/render'
import { leadsScenario } from '../support/scenarios'

async function openDiscover(user) {
  await user.click(screen.getByRole('button', { name: 'Discover businesses' }))
  return screen.findByRole('dialog', { name: 'Discover businesses' })
}

describe('Country selection', () => {
  it('defaults to Pakistan and lists every country alphabetically', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)

    const country = within(dialog).getByRole('combobox', { name: 'Country' })
    await user.click(country)
    const listbox = screen.getByRole('listbox', { name: 'Countries' })
    const options = within(listbox).getAllByRole('option')
    expect(options).toHaveLength(249)
    expect(options.find((option) => option.getAttribute('aria-selected') === 'true')).toHaveTextContent('Pakistan')
    const names = options.map((option) => option.textContent.replace(/\s*[A-Z]{2}$/, '').trim())
    expect(names[0]).toBe('Afghanistan')
    expect(names[names.length - 1]).toBe('Zimbabwe')
    expect(names).toEqual([...names].sort((a, b) => a.localeCompare(b)))
  })

  it('finds a country by typing part of its name', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)
    await user.type(within(dialog).getByRole('combobox', { name: 'Country' }), 'Ghana')
    const options = within(screen.getByRole('listbox', { name: 'Countries' })).getAllByRole('option')
    expect(options).toHaveLength(1)
    expect(options[0]).toHaveTextContent('Ghana')
  })

  it('changes the city suggestions when the country changes', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)
    const city = within(dialog).getByRole('combobox', { name: 'City' })

    await user.type(city, 'Lah')
    expect(await screen.findByRole('listbox', { name: /City suggestions in Pakistan/ })).toBeInTheDocument()
    expect(await screen.findByRole('option', { name: /^Lahore/ })).toBeInTheDocument()

    await user.type(within(dialog).getByRole('combobox', { name: 'Country' }), 'United States{Enter}')
    await user.type(city, 'Lah')
    await waitFor(() => expect(screen.queryByRole('option', { name: /^Lahore/ })).not.toBeInTheDocument())
    expect(await screen.findByText(/No city in United States matches “Lah”/)).toBeInTheDocument()
  })

  it('clears a typed city when the country changes, so the city is never searched in the wrong country', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)
    await user.type(within(dialog).getByRole('combobox', { name: 'City' }), 'Lahore')
    await user.type(within(dialog).getByRole('combobox', { name: 'Country' }), 'Australia{Enter}')
    expect(within(dialog).getByRole('combobox', { name: 'City' })).toHaveValue('')
  })

  it('offers only the cities of the chosen country, with their admin division', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)
    await user.type(within(dialog).getByRole('combobox', { name: 'Country' }), 'Canada{Enter}')
    await user.type(within(dialog).getByRole('combobox', { name: 'City' }), 'London')

    const options = await within(await screen.findByRole('listbox', { name: /City suggestions in Canada/ }))
      .findAllByRole('option')
    expect(options).toHaveLength(1)
    expect(options[0]).toHaveTextContent('London')
    expect(options[0]).toHaveTextContent('Ontario, Canada')
    expect(screen.queryByText(/England/)).not.toBeInTheDocument()
  })

  it('says so when no city of the country matches, and that the typed name will be searched', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)
    await user.type(within(dialog).getByRole('combobox', { name: 'City' }), 'Zzzville')
    expect(await screen.findByText(/No city in Pakistan matches “Zzzville”\. It will be searched exactly as typed\./))
      .toBeInTheDocument()
  })

  it('shows more cities one page at a time', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)
    await user.click(within(dialog).getByRole('combobox', { name: 'City' }))
    const list = await screen.findByRole('listbox', { name: /City suggestions in Pakistan/ })
    expect(within(list).getAllByRole('option')).toHaveLength(8)

    await user.click(screen.getByRole('button', { name: 'Show more cities' }))
    await waitFor(() => expect(within(list).getAllByRole('option')).toHaveLength(16))
  })

  it('shows the City data attribution with a link to GeoNames', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    await openDiscover(user)
    expect(await screen.findByRole('link', { name: 'GeoNames' })).toHaveAttribute('href', 'https://www.geonames.org/')
    expect(screen.getByText(/City data ©/)).toHaveTextContent('CC BY 4.0')
  })
})

describe('Picking a city', () => {
  it('picking a suggestion sends its database id, and the notice shows its admin division', async () => {
    const { user, backend } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)
    await user.type(within(dialog).getByRole('combobox', { name: 'Country' }), 'United States{Enter}')
    await user.type(within(dialog).getByRole('combobox', { name: 'City' }), 'New')
    await user.click(await screen.findByRole('option', { name: /^New York City/ }))
    expect(within(dialog).getByRole('combobox', { name: 'City' })).toHaveValue('New York City')
    expect(screen.getByText(/New York, United States/)).toBeInTheDocument()

    await user.click(within(dialog).getByRole('button', { name: 'Search Google Places' }))
    await waitFor(() => expect(backend.state.lastDiscover).toMatchObject({
      city: 'New York City', country_code: 'US', city_id: 5128581,
    }))
  })

  it('typing after a pick drops the picked id, so the text is searched as typed', async () => {
    const { user, backend } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)
    await user.type(within(dialog).getByRole('combobox', { name: 'Country' }), 'Australia{Enter}')
    await user.type(within(dialog).getByRole('combobox', { name: 'City' }), 'Syd')
    await user.click(await screen.findByRole('option', { name: /^Sydney/ }))
    await user.type(within(dialog).getByRole('combobox', { name: 'City' }), 'x')
    await user.click(within(dialog).getByRole('button', { name: 'Search Google Places' }))
    await waitFor(() => expect(backend.state.lastDiscover).toMatchObject({ city: 'Sydneyx', country_code: 'AU' }))
    expect(backend.state.lastDiscover.city_id).toBeUndefined()
  })

  it('a picked city is cleared when the country changes', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)
    await user.type(within(dialog).getByRole('combobox', { name: 'Country' }), 'United Arab Emirates{Enter}')
    await user.type(within(dialog).getByRole('combobox', { name: 'City' }), 'Dub')
    await user.click(await screen.findByRole('option', { name: /^Dubai/ }))
    await user.type(within(dialog).getByRole('combobox', { name: 'Country' }), 'Australia{Enter}')
    expect(within(dialog).getByRole('combobox', { name: 'City' })).toHaveValue('')
  })

  it('a typed city that is not in the database is searched exactly as typed', async () => {
    const { user, backend } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)
    await user.type(within(dialog).getByRole('combobox', { name: 'City' }), 'Zanzibar Town')
    await user.click(within(dialog).getByRole('button', { name: 'Search Google Places' }))
    await waitFor(() => expect(backend.state.lastDiscover).toMatchObject({ city: 'Zanzibar Town', country_code: 'PK' }))
    expect(backend.state.lastDiscover.city_id).toBeUndefined()
  })
})

// The five required searches, each run through the form: Country → City → Industry → Business type → Search.
const REQUIRED = [
  { label: 'Pakistan, Faisalabad, Restaurants', country: 'Pakistan', code: 'PK', city: 'Faisalabad',
    industry: null, type: null, request: { city: 'Faisalabad', country_code: 'PK', category: 'all' } },
  { label: 'United States, New York, Real Estate', country: 'United States', code: 'US', city: 'New York',
    industry: 'real_estate', type: 'agency', request: { city: 'New York', country_code: 'US', industry: 'real_estate', subcategory: 'agency' } },
  { label: 'United Kingdom, London, Education', country: 'United Kingdom', code: 'GB', city: 'London',
    industry: 'education', type: 'school', request: { city: 'London', country_code: 'GB', industry: 'education', subcategory: 'school' } },
  { label: 'UAE, Dubai, Healthcare', country: 'United Arab Emirates', code: 'AE', city: 'Dubai',
    industry: 'healthcare', type: 'clinic', request: { city: 'Dubai', country_code: 'AE', industry: 'healthcare', subcategory: 'clinic' } },
  { label: 'Australia, Sydney, Home Services', country: 'Australia', code: 'AU', city: 'Sydney',
    industry: 'home_services', type: 'construction', request: { city: 'Sydney', country_code: 'AU', industry: 'home_services', subcategory: 'construction' } },
]

describe('Required searches in Demo Mode', () => {
  for (const scenario of REQUIRED) {
    it(`sends ${scenario.label} with its country code and shows the country on the results`, async () => {
      const { user, backend } = renderAppAt('leads', leadsScenario())
      await waitForWorkspace()
      const dialog = await openDiscover(user)

      await user.type(within(dialog).getByRole('combobox', { name: 'Country' }), `${scenario.country}{Enter}`)
      await user.type(within(dialog).getByRole('combobox', { name: 'City' }), scenario.city)
      if (scenario.industry) {
        await user.selectOptions(within(dialog).getByLabelText('Industry'), scenario.industry)
        await user.selectOptions(within(dialog).getByLabelText('Business type'), scenario.type)
      }
      await user.click(within(dialog).getByRole('button', { name: 'Search Google Places' }))

      await waitFor(() => {
        expect(backend.state.lastDiscover).toMatchObject(scenario.request)
      })
      await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Discover businesses' })).not.toBeInTheDocument())
      expect(backend.state.restaurants.some((r) => r.city === scenario.city && r.country_code === scenario.code
        && r.country_name === scenario.country)).toBe(true)
    })
  }
})
