import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import { renderAppAt, waitForWorkspace } from '../support/render'
import { leadsScenario } from '../support/scenarios'

// Country → state → city, searched in live mode (discovery is not in demo mode, so the search goes to the API with
// the country, state and city as chosen). The fake backend serves the same GeoNames ids and admin codes as the
// real database.
function liveScenario(extra = {}) {
  return { ...leadsScenario(), discoveryMode: { demo_mode: false, live_key_configured: true }, ...extra }
}

async function openDiscover(user) {
  await user.click(screen.getByRole('button', { name: 'Discover businesses' }))
  return screen.findByRole('dialog', { name: 'Discover businesses' })
}

async function chooseCountry(user, dialog, name) {
  await user.type(within(dialog).getByRole('combobox', { name: 'Country' }), `${name}{Enter}`)
}

// The state field appears only for countries with states, and it is disabled until those states have loaded.
async function chooseState(user, dialog, name) {
  const control = within(dialog).getByRole('combobox', { name: 'State' })
  await waitFor(() => expect(control).toBeEnabled())
  await user.type(control, `${name}{Enter}`)
}

async function chooseCity(user, dialog, typed, optionName) {
  await user.type(within(dialog).getByRole('combobox', { name: 'City' }), typed)
  await user.click(await screen.findByRole('option', { name: optionName }))
}

async function search(user, dialog) {
  await user.click(within(dialog).getByRole('button', { name: 'Search Google Places' }))
}

// The seven combinations the feature must cover, plus Pakistan's default country.
const COMBINATIONS = [
  { label: 'Pakistan → Punjab → Lahore', country: null, countryCode: 'PK', state: 'Punjab', stateCode: '04', typed: 'Lah', option: /^Lahore/, city: 'Lahore' },
  { label: 'Pakistan → Sindh → Karachi', country: null, countryCode: 'PK', state: 'Sindh', stateCode: '05', typed: 'Kar', option: /^Karachi/, city: 'Karachi' },
  { label: 'Pakistan → Khyber Pakhtunkhwa → Peshawar', country: null, countryCode: 'PK', state: 'Khyber Pakhtunkhwa', stateCode: '03', typed: 'Pesh', option: /^Peshawar/, city: 'Peshawar' },
  { label: 'USA → California → Los Angeles', country: 'United States', countryCode: 'US', state: 'California', stateCode: 'CA', typed: 'Los', option: /^Los Angeles/, city: 'Los Angeles' },
  { label: 'UK → England → London', country: 'United Kingdom', countryCode: 'GB', state: 'England', stateCode: 'ENG', typed: 'Lond', option: /^London/, city: 'London' },
  { label: 'UAE → Dubai → Dubai', country: 'United Arab Emirates', countryCode: 'AE', state: 'Dubai', stateCode: '03', typed: 'Dub', option: /^Dubai/, city: 'Dubai' },
  { label: 'Australia → New South Wales → Sydney', country: 'Australia', countryCode: 'AU', state: 'New South Wales', stateCode: '02', typed: 'Syd', option: /^Sydney/, city: 'Sydney' },
]

describe('Country → state → city', () => {
  describe.each(COMBINATIONS)('$label', (combination) => {
    it('searches the city in its state and country and sends all three to discovery', async () => {
      const { user, backend } = renderAppAt('leads', liveScenario())
      await waitForWorkspace()
      const dialog = await openDiscover(user)
      if (combination.country) await chooseCountry(user, dialog, combination.country)
      await chooseState(user, dialog, combination.state)
      await chooseCity(user, dialog, combination.typed, combination.option)
      await search(user, dialog)

      await waitFor(() => {
        expect(backend.state.lastDiscover).toMatchObject({
          country_code: combination.countryCode,
          state: combination.stateCode,
          city: combination.city,
        })
      })
      expect(backend.state.lastDiscover.city_id).toEqual(expect.any(Number))
    })
  })

  it('offers only the states of the chosen country', async () => {
    const { user } = renderAppAt('leads', liveScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)
    await chooseCountry(user, dialog, 'United States')
    const state = within(dialog).getByRole('combobox', { name: 'State' })
    await waitFor(() => expect(state).toBeEnabled())
    await user.click(state)
    const names = within(screen.getByRole('listbox', { name: 'States' })).getAllByRole('option').map((option) => option.textContent)
    expect(names).toEqual(['All states', 'California', 'New York', 'Virginia'])
  })

  it('hides the state field for a country with no first-level divisions and searches the city directly', async () => {
    const { user, backend } = renderAppAt('leads', liveScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)
    await chooseCountry(user, dialog, 'Singapore')
    await waitFor(() => expect(within(dialog).queryByRole('combobox', { name: 'State' })).not.toBeInTheDocument())

    await chooseCity(user, dialog, 'Sing', /^Singapore/)
    await search(user, dialog)
    await waitFor(() => expect(backend.state.lastDiscover).toMatchObject({ country_code: 'SG', city: 'Singapore' }))
    expect(backend.state.lastDiscover.state ?? null).toBeNull()
  })

  it('keeps two cities with the same name apart by their state', async () => {
    const { user, backend } = renderAppAt('leads', liveScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)
    await chooseCountry(user, dialog, 'United States')
    await chooseState(user, dialog, 'Virginia')
    await chooseCity(user, dialog, 'Rich', /^Richmond/)
    await search(user, dialog)
    await waitFor(() => {
      expect(backend.state.lastDiscover).toMatchObject({ country_code: 'US', state: 'VA', city: 'Richmond' })
    })
    expect(backend.state.lastDiscover.city_id).toBe(4781708)
  })

  it('sends the state and city for an industry other than restaurants', async () => {
    const { user, backend } = renderAppAt('leads', liveScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)
    await user.selectOptions(within(dialog).getByLabelText('Industry'), 'home_services')
    await chooseState(user, dialog, 'Punjab')
    await chooseCity(user, dialog, 'Lah', /^Lahore/)
    await search(user, dialog)
    await waitFor(() => {
      expect(backend.state.lastDiscover).toMatchObject({
        industry: 'home_services', country_code: 'PK', state: '04', city: 'Lahore',
      })
    })
  })

  it('clears the picked city when the state changes', async () => {
    const { user } = renderAppAt('leads', liveScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)
    await chooseState(user, dialog, 'Punjab')
    await chooseCity(user, dialog, 'Lah', /^Lahore/)
    const city = within(dialog).getByRole('combobox', { name: 'City' })
    expect(city).toHaveValue('Lahore')

    await chooseState(user, dialog, 'Sindh')
    expect(city).toHaveValue('')
  })

  it('clears the state and the city when the country changes', async () => {
    const { user } = renderAppAt('leads', liveScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)
    await chooseState(user, dialog, 'Punjab')
    await chooseCity(user, dialog, 'Lah', /^Lahore/)

    await chooseCountry(user, dialog, 'United States')
    expect(within(dialog).getByRole('combobox', { name: 'City' })).toHaveValue('')
    await waitFor(() => expect(within(dialog).getByRole('combobox', { name: 'State' })).toHaveValue('All states'))
  })

  it('still searches a city when the states cannot be loaded, and offers to try again', async () => {
    const { user, backend } = renderAppAt('leads', liveScenario({
      failures: { 'GET /geo/countries/PK/states': { status: 500 } },
    }))
    await waitForWorkspace()
    const dialog = await openDiscover(user)
    expect(await within(dialog).findByText('Could not load the states of Pakistan.')).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Try again' })).toBeInTheDocument()

    await chooseCity(user, dialog, 'Lah', /^Lahore/)
    await search(user, dialog)
    await waitFor(() => expect(backend.state.lastDiscover).toMatchObject({ country_code: 'PK', city: 'Lahore' }))
    expect(backend.state.lastDiscover.state ?? null).toBeNull()
  })
})
