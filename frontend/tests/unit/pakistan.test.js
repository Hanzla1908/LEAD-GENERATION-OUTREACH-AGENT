import { describe, expect, it } from 'vitest'
import {
  CITIES,
  CUISINES,
  OTHER_CITY,
  cityDisplayName,
  cuisineLabel,
  normalizeCityName,
  validateCityChoice,
} from '../../src/lib/pakistan'

describe('Pakistani city list', () => {
  it('offers the 19 cities the discovery form lists', () => {
    expect(CITIES).toHaveLength(19)
    expect(CITIES).toContain('Lahore')
    expect(CITIES).toContain('Rahim Yar Khan')
  })

  it('validates a listed city without a message', () => {
    expect(validateCityChoice('Lahore', '')).toBe('')
  })

  it('requires a choice before a search', () => {
    expect(validateCityChoice('', '')).toBe('Choose a city from the list.')
  })
})

describe('Other Pakistani city input', () => {
  it('asks for a name when Other is chosen and the name is blank', () => {
    expect(validateCityChoice(OTHER_CITY, '   ')).toBe('Enter the name of the Pakistani city.')
  })

  it('rejects a one-letter name', () => {
    expect(validateCityChoice(OTHER_CITY, ' G ')).toBe('City name needs at least 2 characters.')
  })

  it('rejects a name longer than 60 characters', () => {
    expect(validateCityChoice(OTHER_CITY, 'A'.repeat(61))).toBe('City name must be 60 characters or fewer.')
  })

  it('rejects digits and symbols', () => {
    expect(validateCityChoice(OTHER_CITY, 'Gujrat2')).toBe('Use letters, spaces, hyphens, apostrophes or periods only.')
  })

  it('accepts names with spaces, hyphens, apostrophes and periods', () => {
    expect(validateCityChoice(OTHER_CITY, 'Dera Ghazi Khan')).toBe('')
    expect(validateCityChoice(OTHER_CITY, "Mir's-Town.")).toBe('')
  })

  it('collapses repeated spaces in the display name', () => {
    expect(normalizeCityName('  Rahim   Yar  Khan ')).toBe('Rahim Yar Khan')
    expect(cityDisplayName(OTHER_CITY, '  Gujrat  ')).toBe('Gujrat')
  })

  it('returns the listed city name unchanged for a list choice', () => {
    expect(cityDisplayName('Karachi', 'ignored')).toBe('Karachi')
  })
})

describe('Business type (cuisine) list', () => {
  it('offers 20 options, starting with All Restaurants', () => {
    expect(CUISINES).toHaveLength(20)
    expect(CUISINES[0]).toEqual({ value: 'all', label: 'All businesses' })
  })

  it('returns the label for a known value', () => {
    expect(cuisineLabel('biryani')).toBe('Biryani & Pulao')
  })

  it('falls back to All Restaurants for an unknown value', () => {
    expect(cuisineLabel('not-a-cuisine')).toBe('All businesses')
  })
})
