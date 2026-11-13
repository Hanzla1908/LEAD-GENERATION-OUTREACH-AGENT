// City names in any language and script: letters, spaces, and the punctuation found in place names.
// Digits and symbols are refused here and again on the server.
export const CITY_PATTERN = /^\p{L}[\p{L} .'’-]{1,59}$/u

export function cleanCityName(text) {
  return (text ?? '').trim().replace(/\s+/g, ' ')
}

// An empty string means the city is acceptable.
export function validateCity(text) {
  const name = cleanCityName(text)
  if (!name) return 'Enter a city name.'
  if (name.length < 2) return 'Enter a city name of at least 2 letters.'
  if (!CITY_PATTERN.test(name)) return 'Use letters, spaces, hyphens, apostrophes and periods only.'
  return ''
}
