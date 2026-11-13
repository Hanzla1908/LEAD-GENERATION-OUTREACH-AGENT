import { useEffect, useState } from 'react'
import { Badge, Icon } from '../components/ui'
import { ROLE_LABEL } from '../components/Layout'
import ChangePassword from '../components/ChangePassword'

const DENSITY_KEY = 'ro-density'

export function readDensity() {
  try {
    return localStorage.getItem(DENSITY_KEY) === 'compact' ? 'compact' : 'comfortable'
  } catch {
    return 'comfortable'
  }
}

export default function Settings({ apiStatus, restaurantCount, draftCount, discoveryMode, user }) {
  const [density, setDensity] = useState(readDensity)

  useEffect(() => {
    document.documentElement.dataset.density = density
    try {
      localStorage.setItem(DENSITY_KEY, density)
    } catch {
      return
    }
  }, [density])

  const apiBadge = {
    ok: <Badge tone="ok">Connected</Badge>,
    error: <Badge tone="bad">Unreachable</Badge>,
    checking: <Badge tone="neutral">Checking</Badge>,
  }[apiStatus] ?? <Badge tone="neutral">Checking</Badge>

  return (
    <>
      <div className="page-header">
        <div>
          <h2>Settings</h2>
          <p>Connection status and workspace preferences.</p>
        </div>
      </div>

      <section className="card" aria-labelledby="settings-account">
        <div className="card-head"><h3 id="settings-account">Your account</h3></div>
        <div className="settings-row">
          <div>
            <h4>{user?.name ?? 'Signed in'}</h4>
            <p>{user?.email} · {ROLE_LABEL[user?.role] ?? 'Signed in'}</p>
          </div>
        </div>
        <div className="settings-row">
          <div>
            <h4>Password</h4>
            <p>Change the password you use to sign in. Your other sessions are signed out.</p>
          </div>
        </div>
        <div className="card-body">
          <ChangePassword />
        </div>
      </section>

      <section className="card" aria-labelledby="settings-api">
        <div className="card-head"><h3 id="settings-api">Connection</h3></div>
        <div className="settings-row">
          <div>
            <h4>Backend API</h4>
            <p>The app calls <code>/api</code>, which Vite forwards to the FastAPI backend on port 8000.</p>
          </div>
          {apiBadge}
        </div>
        <div className="settings-row">
          <div>
            <h4>Discovery mode</h4>
            <p>
              {discoveryMode?.demo_mode
                ? 'Demo mode: business searches return sample records marked [DEMO]. They are never emailed.'
                : 'Live mode: business searches use Google Places (New). Results are cached for at most 30 days.'}
            </p>
          </div>
          {discoveryMode?.demo_mode ? (
            <Badge tone="warn">Demo mode</Badge>
          ) : discoveryMode?.live_key_configured ? (
            <Badge tone="ok">Live · Google Places</Badge>
          ) : (
            <Badge tone="bad">Live · key missing</Badge>
          )}
        </div>
        <div className="settings-row">
          <div>
            <h4>Provider keys</h4>
            <p>
              Google Places and Anthropic keys are read only by the backend from its <code>.env</code> file and are never
              sent to the browser. This page cannot see whether they are set. The backend logs
              {' '}<em>configured</em> or <em>MISSING</em> for each key when it starts.
            </p>
          </div>
          <Badge tone="neutral">Server-side only</Badge>
        </div>
      </section>

      <section className="card" aria-labelledby="settings-data">
        <div className="card-head"><h3 id="settings-data">Stored data</h3></div>
        <div className="settings-row">
          <div>
            <h4>Businesses</h4>
            <p>Unique places saved from discovery searches.</p>
          </div>
          <strong>{restaurantCount}</strong>
        </div>
        <div className="settings-row">
          <div>
            <h4>Email drafts</h4>
            <p>All draft, approved and rejected drafts.</p>
          </div>
          <strong>{draftCount}</strong>
        </div>
      </section>

      <section className="card" aria-labelledby="settings-prefs">
        <div className="card-head"><h3 id="settings-prefs">Preferences</h3></div>
        <div className="settings-row">
          <div>
            <h4>Table density</h4>
            <p>Compact rows fit more leads on screen. Saved in this browser only.</p>
          </div>
          <div className="segmented" role="group" aria-label="Table density">
            <button type="button" aria-pressed={density === 'comfortable'} onClick={() => setDensity('comfortable')}>Comfortable</button>
            <button type="button" aria-pressed={density === 'compact'} onClick={() => setDensity('compact')}>Compact</button>
          </div>
        </div>
      </section>

      <div className="notice notice-warn" role="note">
        <Icon name="alert" size={16} />
        <div>Sending email is not implemented. Approving a draft only records the decision.</div>
      </div>
    </>
  )
}
