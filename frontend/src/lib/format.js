export const WEBSITE_LABEL = { present: 'Live', not_found: 'Not found', unknown: 'Unknown' }
export const ORDERING_LABEL = { present: 'Online ordering', not_found: 'No ordering', unknown: 'Unknown' }
export const LEAD_LABEL = { qualified: 'Qualified', needs_review: 'Needs review', disqualified: 'Disqualified', new: 'Not qualified' }
export const EMAIL_LABEL = {
  verified: 'Verified', domain_valid: 'Domain OK', unverified: 'Not checked', unknown: 'Check failed', invalid: 'Invalid',
}
export const EMAIL_CLASS_LABEL = { business: 'Business', personal: 'Personal', disposable: 'Disposable', unknown: 'Unclassified' }
export const DRAFT_LABEL = { draft: 'Awaiting approval', edited: 'Edited', approved: 'Approved', rejected: 'Rejected', sent: 'Sent' }
export const ANGLE_LABEL = {
  ordering_gap: 'Online ordering gap',
  website_gap: 'Website gap',
  ai_assistant: 'AI order assistant',
  general: 'General services',
}

export function parseTimestamp(value) {
  if (!value) return null
  const iso = value.includes('T') ? value : `${value.replace(' ', 'T')}Z`
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? null : date
}

export function timeAgo(value) {
  const date = parseTimestamp(value)
  if (!date) return '—'
  const minutes = Math.round((Date.now() - date.getTime()) / 60000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

export function dayKey(value) {
  const date = parseTimestamp(value)
  return date ? date.toISOString().slice(0, 10) : null
}

export function cityFromAddress(address) {
  if (!address) return '—'
  const parts = address.split(',').map((part) => part.trim()).filter(Boolean)
  return parts.length >= 3 ? parts[parts.length - 2] : '—'
}

export function safeHref(url) {
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : null
  } catch {
    return null
  }
}

export function shortUrl(url) {
  try {
    const parsed = new URL(url)
    const path = parsed.pathname === '/' ? '' : parsed.pathname
    return `${parsed.hostname.replace(/^www\./, '')}${path}`
  } catch {
    return url
  }
}
