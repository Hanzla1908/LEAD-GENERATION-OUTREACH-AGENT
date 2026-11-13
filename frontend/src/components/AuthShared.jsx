import { useState } from 'react'
import { BrandLockup, TAGLINE } from './Brand'

// Shared frame for the sign-up and sign-in screens. Wide screens show a navy brand panel beside the form;
// narrow screens show the brand above the form.
export function AuthShell({ children, footer }) {
  return (
    <main className="auth-split">
      <aside className="auth-aside" aria-label="About the product">
        <BrandLockup onDark />
        <div className="auth-aside-copy">
          <h2>Find businesses, qualify the leads, and reach out from one workspace.</h2>
          <ol className="auth-steps">
            <li><span className="step-no">1</span><span>Discover businesses across Pakistani cities and categories</span></li>
            <li><span className="step-no">2</span><span>Check each website and qualify the leads</span></li>
            <li><span className="step-no">3</span><span>Send reviewed outreach and track every reply</span></li>
          </ol>
        </div>
        <p className="auth-tagline">{TAGLINE}</p>
      </aside>
      <section className="auth-main">
        <div className="auth-stack">
          <div className="auth-mobile-brand">
            <BrandLockup showTagline markSize={36} />
          </div>
          <div className="card auth-card">
            {children}
          </div>
          {footer && <div className="auth-footer">{footer}</div>}
        </div>
      </section>
    </main>
  )
}

// Keeps focus where it is when a link or button is pressed with the mouse. Otherwise the field being left can
// show an error that moves the link before the click is completed.
export function keepFocus(event) {
  event.preventDefault()
}

// A password box with a show/hide toggle. The value is kept by the caller and never written to storage.
export function PasswordField({
  id, label, value, onChange, onBlur, autoComplete, maxLength, hint, error, required = true,
}) {
  const [visible, setVisible] = useState(false)
  const describedBy = [hint && !error ? `${id}-hint` : null, error ? `${id}-error` : null]
    .filter(Boolean)
    .join(' ') || undefined
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <div className="password-field">
        <input
          id={id}
          className="input"
          type={visible ? 'text' : 'password'}
          autoComplete={autoComplete}
          maxLength={maxLength}
          required={required}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onBlur={onBlur}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
        />
        <button
          type="button"
          className="password-toggle"
          aria-label={`${visible ? 'Hide' : 'Show'} ${label}`}
          aria-pressed={visible}
          onClick={() => setVisible((current) => !current)}
        >
          {visible ? 'Hide' : 'Show'}
        </button>
      </div>
      {hint && !error && <span className="field-hint" id={`${id}-hint`}>{hint}</span>}
      {error && <span className="field-error" id={`${id}-error`} role="alert">{error}</span>}
    </div>
  )
}
