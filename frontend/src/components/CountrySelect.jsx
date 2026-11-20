import COUNTRIES from '../lib/countries.json'
import SearchSelect from './SearchSelect'

// Every ISO 3166-1 country. The value is the two-letter code; the name is shown to the person.
const COUNTRY_ITEMS = COUNTRIES.countries.map((country) => ({ value: country.code, label: country.name, hint: country.code }))

export default function CountrySelect({ value, onChange, disabled, describedBy }) {
  return (
    <SearchSelect
      items={COUNTRY_ITEMS}
      value={value}
      onChange={onChange}
      ariaLabel="Country"
      listLabel="Countries"
      placeholder="Search a country"
      noMatchText={(query) => `No country matches “${query}”.`}
      disabled={disabled}
      describedBy={describedBy}
    />
  )
}
