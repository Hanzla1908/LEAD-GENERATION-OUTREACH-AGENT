import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import {
  DRAFT_LABEL,
  LEAD_LABEL,
  cityFromAddress,
  dayKey,
  parseTimestamp,
  safeHref,
  shortUrl,
  timeAgo,
} from '../../src/lib/format'

describe('timeAgo', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-11-04T12:00:00Z'))
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('shows just now for less than a minute', () => {
    expect(timeAgo('2026-11-04T11:59:40Z')).toBe('just now')
  })

  it('shows minutes, hours and days', () => {
    expect(timeAgo('2026-11-04T11:50:00Z')).toBe('10m ago')
    expect(timeAgo('2026-11-04T09:00:00Z')).toBe('3h ago')
    expect(timeAgo('2026-11-02T12:00:00Z')).toBe('2d ago')
  })

  it('reads backend timestamps without a timezone as UTC', () => {
    expect(timeAgo('2026-11-04 09:00:00')).toBe('3h ago')
  })

  it('shows a dash for a missing or invalid value', () => {
    expect(timeAgo(null)).toBe('—')
    expect(timeAgo('not a date')).toBe('—')
  })
})

describe('parseTimestamp and dayKey', () => {
  it('returns null for empty or invalid input', () => {
    expect(parseTimestamp('')).toBeNull()
    expect(parseTimestamp('nope')).toBeNull()
  })

  it('returns the UTC calendar day', () => {
    expect(dayKey('2026-11-01 09:00:00')).toBe('2026-11-01')
    expect(dayKey(null)).toBeNull()
  })
})

describe('cityFromAddress', () => {
  it('takes the city from a full Pakistani address', () => {
    expect(cityFromAddress('Liberty Market, Gulberg, Lahore, Pakistan')).toBe('Lahore')
  })

  it('shows a dash when the address is too short to tell', () => {
    expect(cityFromAddress('Lahore, Pakistan')).toBe('—')
    expect(cityFromAddress(null)).toBe('—')
  })
})

describe('safeHref', () => {
  it('allows http and https links', () => {
    expect(safeHref('https://lahorekarahi.pk/menu')).toBe('https://lahorekarahi.pk/menu')
    expect(safeHref('http://example.test/')).toBe('http://example.test/')
  })

  it('blocks script and other non-web schemes', () => {
    expect(safeHref('javascript:alert(1)')).toBeNull()
    expect(safeHref('data:text/html,hi')).toBeNull()
  })

  it('returns null for text that is not a URL', () => {
    expect(safeHref('lahore karahi')).toBeNull()
  })
})

describe('shortUrl', () => {
  it('drops www and a trailing slash', () => {
    expect(shortUrl('https://www.lahorekarahi.pk/')).toBe('lahorekarahi.pk')
  })

  it('keeps the path', () => {
    expect(shortUrl('https://gulbergbiryani.pk/menu')).toBe('gulbergbiryani.pk/menu')
  })

  it('returns the input when it is not a URL', () => {
    expect(shortUrl('not a url')).toBe('not a url')
  })
})

describe('display labels', () => {
  it('names every lead status, including the not-yet-qualified one', () => {
    expect(LEAD_LABEL).toEqual({
      qualified: 'Qualified',
      needs_review: 'Needs review',
      disqualified: 'Disqualified',
      new: 'Not qualified',
    })
  })

  it('names every draft status', () => {
    expect(DRAFT_LABEL).toEqual({ draft: 'Awaiting approval', edited: 'Edited', approved: 'Approved', rejected: 'Rejected', sent: 'Sent' })
  })
})
