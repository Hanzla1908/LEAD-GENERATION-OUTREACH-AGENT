import { useEffect, useState } from 'react'
import { Button, Icon } from './ui'
import CityCombobox from './CityCombobox'
import CountrySelect from './CountrySelect'
import SearchSelect from './SearchSelect'
import COUNTRIES from '../lib/countries.json'
import { CUISINES, cuisineLabel } from '../lib/pakistan'
import { cleanCityName, validateCity } from '../lib/cities'
import * as api from '../services/api'

const MAX_RESULTS = 60
const DEFAULT_COUNTRY = 'PK'
const RESTAURANTS = 'restaurants_food'

function validateLimit(limit) {
  if (!Number.isInteger(limit) || limit < 1 || limit > MAX_RESULTS) return `Choose between 1 and ${MAX_RESULTS} results.`
  return ''
}

export function countryNameFor(code) {
  return COUNTRIES.countries.find((country) => country.code === code)?.name ?? code
}

// Restaurants keep their existing cuisine list and labels. Other industries use the subcategories their profile
// defines (industries.json, served by GET /industries).
function subcategoryOptions(industries, industry) {
  if (industry === RESTAURANTS) return CUISINES
  const profile = industries.find((item) => item.key === industry)
  return (profile?.subcategories ?? []).map((sub) => ({ value: sub.key, label: sub.name }))
}

export default function DiscoveryForm({ onSearch, loading, error, notice, industries = [] }) {
  const [countryCode, setCountryCode] = useState(DEFAULT_COUNTRY)
  // The states of the chosen country, from the city database. status is loading, ready or error.
  const [states, setStates] = useState({ status: 'loading', items: [] })
  const [statesAttempt, setStatesAttempt] = useState(0)
  // The state chosen from the list, by its code. '' means all states.
  const [stateCode, setStateCode] = useState('')
  const [cityText, setCityText] = useState('')
  // The city picked from the city database: { id, name, admin1_name, admin1_code, ... }. Null when the city is typed by hand.
  const [pickedCity, setPickedCity] = useState(null)
  const [cityListReady, setCityListReady] = useState(null)
  const [industry, setIndustry] = useState(RESTAURANTS)
  const [category, setCategory] = useState('all')
  const [limit, setLimit] = useState(10)
  const [submitted, setSubmitted] = useState(false)

  useEffect(() => {
    let current = true
    api.getGeoStatus()
      .then((status) => { if (current) setCityListReady(Boolean(status.loaded)) })
      .catch(() => { if (current) setCityListReady(null) })
    return () => { current = false }
  }, [])

  // The states come from the city database for the chosen country. A country with none gets no state field.
  useEffect(() => {
    let current = true
    setStates({ status: 'loading', items: [] })
    api.getStates(countryCode)
      .then((result) => { if (current) setStates({ status: 'ready', items: result.items ?? [] }) })
      .catch(() => { if (current) setStates({ status: 'error', items: [] }) })
    return () => { current = false }
  }, [countryCode, statesAttempt])

  const industryOptions = industries.length > 0
    ? industries.map((item) => ({ value: item.key, label: item.name }))
    : [{ value: RESTAURANTS, label: 'Food & Beverage' }]
  const typeOptions = subcategoryOptions(industries, industry)
  const typeName = typeOptions.find((option) => option.value === category)?.label ?? typeOptions[0]?.label ?? ''
  const countryLabel = countryNameFor(countryCode)
  const stateItems = states.items
  const stateChoices = stateItems.map((item) => ({ value: item.code, label: item.name }))
  // While the states load, or when they cannot be loaded, the field stays; a country with no states hides it.
  const hasStates = states.status !== 'ready' || stateItems.length > 0
  const activeState = hasStates ? stateCode : ''
  const stateLabel = stateItems.find((item) => item.code === activeState)?.name ?? ''
  const cityHint = activeState
    ? `Pick a city in ${stateLabel}, or leave it empty to search the whole state.`
    : `Pick a city from the list, or type any city in ${countryLabel}.`

  // A picked city already comes from the database, so the typed-name rules do not apply to it. With a state chosen,
  // the city may be left empty, and the whole state is searched.
  const cityEmptyAllowed = Boolean(activeState) && !cityText.trim()
  const cityError = pickedCity || cityEmptyAllowed ? '' : validateCity(cityText)
  const limitError = validateLimit(limit)
  const cityShown = submitted ? cityError : ''
  const limitShown = submitted ? limitError : ''
  const cleanCity = pickedCity ? pickedCity.name : cleanCityName(cityText)
  // The place named in the summary: the city with its state (or the city's own division when no state is chosen).
  const placeName = [cleanCity, activeState ? stateLabel : pickedCity?.admin1_name].filter(Boolean).join(', ')

  function handleSubmit(event) {
    event.preventDefault()
    setSubmitted(true)
    if (cityError || limitError) return
    onSearch(cleanCity || null, category, limit, industry, countryCode, pickedCity?.id ?? null, activeState || null, stateLabel)
  }

  // A city belongs to one country. Changing the country resets the state and the city, so neither is searched in the
  // wrong country.
  function handleCountryChange(code) {
    setCountryCode(code)
    setStateCode('')
    setCityText('')
    setPickedCity(null)
  }

  // Changing the state resets the city, which may not be in the new state. A choice that does not change is ignored.
  function handleStateChange(code) {
    if (code === stateCode) return
    setStateCode(code)
    setCityText('')
    setPickedCity(null)
  }

  // Typing after a pick means the user is entering a city by hand, so the picked id is dropped.
  function handleCityText(text) {
    setCityText(text)
    setPickedCity(null)
  }

  function handleCityPick(city) {
    setCityText(city.name)
    setPickedCity(city)
    // A picked city sets the state it is in, so the state field and the search agree.
    if (stateItems.some((item) => item.code === city.admin1_code)) setStateCode(city.admin1_code)
  }

  function handleIndustryChange(value) {
    setIndustry(value)
    // Each industry starts on its first subcategory, so a choice from another industry is never sent.
    const options = subcategoryOptions(industries, value)
    setCategory(options[0]?.value ?? 'all')
  }

  return (
    <form className="discover-form" onSubmit={handleSubmit} noValidate>
      <div className="field">
        <label className="field-label" htmlFor="discover-country">Country</label>
        <CountrySelect
          value={countryCode}
          onChange={handleCountryChange}
          disabled={loading}
          describedBy="discover-country-help"
        />
        <span className="field-hint" id="discover-country-help">Results come from Google Places for this country.</span>
      </div>

      {hasStates && (
        <div className="field">
          <label className="field-label" htmlFor="discover-state">State</label>
          <SearchSelect
            id="discover-state"
            items={stateChoices}
            value={activeState}
            onChange={handleStateChange}
            ariaLabel="State"
            listLabel="States"
            placeholder={states.status === 'loading' ? 'Loading states…' : 'Search a state or region'}
            clearLabel="All states"
            noMatchText={(query) => `No state matches “${query}”.`}
            disabled={loading || states.status !== 'ready'}
            describedBy="discover-state-help"
          />
          {states.status === 'error' ? (
            <>
              <span className="field-error" id="discover-state-help" role="alert">
                Could not load the states of {countryLabel}.
              </span>
              <Button type="button" variant="secondary" onClick={() => setStatesAttempt((n) => n + 1)} disabled={loading}>
                Try again
              </Button>
            </>
          ) : (
            <span className="field-hint" id="discover-state-help">
              {states.status === 'loading' ? 'Loading states…' : 'Limits the search and the city list to one state or region.'}
            </span>
          )}
        </div>
      )}

      <div className="field">
        <span className="field-label">City</span>
        <CityCombobox
          value={cityText}
          selectedId={pickedCity?.id ?? null}
          onChange={handleCityText}
          onSelect={handleCityPick}
          countryCode={countryCode}
          countryName={countryLabel}
          admin1={activeState}
          areaName={activeState ? stateLabel : null}
          cityListReady={cityListReady}
          disabled={loading}
          invalid={Boolean(cityShown)}
          describedBy="discover-city-help"
        />
        {cityShown
          ? <span className="field-error" id="discover-city-help" role="alert">{cityShown}</span>
          : <span className="field-hint" id="discover-city-help">{cityHint}</span>}
        {cityListReady && (
          <span className="field-hint city-credit">
            City data © <a href="https://www.geonames.org/" target="_blank" rel="noreferrer">GeoNames</a>, CC BY 4.0.
          </span>
        )}
      </div>

      <div className="field">
        <label className="field-label" htmlFor="discover-industry">Industry</label>
        <select
          id="discover-industry"
          className="select"
          value={industry}
          onChange={(event) => handleIndustryChange(event.target.value)}
          disabled={loading}
        >
          {industryOptions.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
        <span className="field-hint">Each industry has its own search terms, website checks and outreach.</span>
      </div>

      <div className="field">
        <label className="field-label" htmlFor="discover-cuisine">Business type</label>
        <select
          id="discover-cuisine"
          className="select"
          value={category}
          onChange={(event) => setCategory(event.target.value)}
          disabled={loading}
        >
          {typeOptions.map((option) => (
            <option key={option.value} value={option.value}>{option.label}</option>
          ))}
        </select>
        <span className="field-hint">Matches Google Places search terms.</span>
      </div>

      <div className="field">
        <label className="field-label" htmlFor="discover-limit">Results (1–{MAX_RESULTS})</label>
        <input
          id="discover-limit"
          type="number"
          className="input"
          min={1}
          max={MAX_RESULTS}
          value={Number.isNaN(limit) ? '' : limit}
          aria-invalid={Boolean(limitShown) || undefined}
          aria-describedby="discover-limit-help"
          onChange={(event) => setLimit(event.target.value === '' ? NaN : Number(event.target.value))}
          disabled={loading}
        />
        {limitShown
          ? <span className="field-error" id="discover-limit-help" role="alert">{limitShown}</span>
          : <span className="field-hint" id="discover-limit-help">Up to {MAX_RESULTS} per search. Google returns at most {MAX_RESULTS}.</span>}
      </div>

      {(cleanCity || activeState) && !cityError && (
        <div className="notice notice-info span-full">
          <Icon name="search" size={16} />
          <div>
            Searching <strong>{industry === RESTAURANTS ? cuisineLabel(category) : typeName}</strong> in{' '}
            <strong>{placeName}, {countryLabel}</strong>.
            Results match the search; Google Places does not confirm what each business offers.
          </div>
        </div>
      )}

      {error && !(submitted && (cityError || limitError)) && (
        <div className="notice notice-bad span-full" role="alert">
          <Icon name="alert" size={16} />
          <div>{error}</div>
        </div>
      )}

      {notice && !error && (
        <div className="notice notice-warn span-full" role="status">
          <Icon name="alert" size={16} />
          <div>{notice}</div>
        </div>
      )}

      <div className="form-actions span-full">
        <Button type="submit" variant="primary" disabled={loading}>
          {loading ? 'Searching Google Places…' : 'Search Google Places'}
        </Button>
      </div>
    </form>
  )
}
