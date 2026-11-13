// Brand used across the app. Change the name or tagline here and every screen follows.
export const PRODUCT_NAME = 'LEAD GENERATION & OUTREACH AGENT'
export const TAGLINE = 'AI-Powered Business Discovery, Lead Generation & Outreach.'

// The mark: a navy tile with a ring (a restaurant lead) and a teal dot (the outreach that reaches it).
export function BrandMark({ size = 32 }) {
  return (
    <svg
      className="brand-svg"
      width={size}
      height={size}
      viewBox="0 0 32 32"
      aria-hidden="true"
      focusable="false"
    >
      <rect className="bm-tile" x="0" y="0" width="32" height="32" rx="8" />
      <circle className="bm-ring" cx="14" cy="17" r="6.5" />
      <circle className="bm-dot" cx="23.5" cy="8.5" r="2.9" />
    </svg>
  )
}

// Mark plus wordmark. onDark switches the colours for the navy panels.
export function BrandLockup({ onDark = false, showTagline = false, markSize = 32 }) {
  return (
    <div className={`brand-lockup${onDark ? ' is-on-dark' : ''}`}>
      <BrandMark size={markSize} />
      <div className="brand-words">
        <div className="brand-name">{PRODUCT_NAME}</div>
        {showTagline && <div className="brand-sub">{TAGLINE}</div>}
      </div>
    </div>
  )
}
