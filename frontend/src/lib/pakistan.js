export const COUNTRY = 'Pakistan'
export const OTHER_CITY = '__other__'

export const CITIES = [
  'Lahore', 'Karachi', 'Islamabad', 'Rawalpindi', 'Faisalabad', 'Multan',
  'Peshawar', 'Quetta', 'Sialkot', 'Gujranwala', 'Hyderabad', 'Bahawalpur',
  'Sargodha', 'Abbottabad', 'Sukkur', 'Mardan', 'Rahim Yar Khan',
  'Sheikhupura', 'Jhelum',
]

export const CUISINES = [
  { value: 'all', label: 'All businesses' },
  { value: 'desi', label: 'Desi / Pakistani' },
  { value: 'fast_food', label: 'Fast Food' },
  { value: 'burgers', label: 'Burgers & Sandwiches' },
  { value: 'pizza', label: 'Pizza' },
  { value: 'bbq', label: 'BBQ & Grills' },
  { value: 'biryani', label: 'Biryani & Pulao' },
  { value: 'karahi', label: 'Karahi & Handi' },
  { value: 'chinese', label: 'Chinese' },
  { value: 'continental', label: 'Continental' },
  { value: 'italian', label: 'Italian' },
  { value: 'cafe', label: 'Café & Coffee' },
  { value: 'tea', label: 'Tea & Chai' },
  { value: 'bakery', label: 'Bakery & Desserts' },
  { value: 'ice_cream', label: 'Ice Cream & Sweets' },
  { value: 'breakfast', label: 'Breakfast / Nashta' },
  { value: 'street_food', label: 'Street Food & Chaat' },
  { value: 'seafood', label: 'Seafood' },
  { value: 'healthy', label: 'Healthy Food' },
  { value: 'other', label: 'Other Cuisine' },
]

export const CITY_NAME_PATTERN = /^[A-Za-z][A-Za-z .'-]*$/

export function normalizeCityName(name) {
  return name.trim().replace(/\s+/g, ' ')
}

export function validateCityChoice(choice, otherName) {
  if (!choice) return 'Choose a city from the list.'
  if (choice !== OTHER_CITY) return ''
  const name = normalizeCityName(otherName)
  if (!name) return 'Enter the name of the Pakistani city.'
  if (name.length < 2) return 'City name needs at least 2 characters.'
  if (name.length > 60) return 'City name must be 60 characters or fewer.'
  if (!CITY_NAME_PATTERN.test(name)) return 'Use letters, spaces, hyphens, apostrophes or periods only.'
  return ''
}

export function cityDisplayName(choice, otherName) {
  return choice === OTHER_CITY ? normalizeCityName(otherName) : choice
}

export function cuisineLabel(value) {
  return CUISINES.find((c) => c.value === value)?.label ?? 'All businesses'
}
