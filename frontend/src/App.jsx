import { useCallback, useEffect, useState } from 'react'
import * as api from './services/api'
import { AccessProvider, Icon, ToastProvider, useToast } from './components/ui'
import Users from './pages/Users'
import Team from './pages/Team'
import Workspaces from './pages/Workspaces'
import InviteScreen from './components/InviteScreen'

// The invitation token lives in the link's fragment, which the browser never sends to the server.
function readInviteToken() {
  const match = window.location.hash.match(/^#invite=([A-Za-z0-9_-]{10,200})$/)
  return match ? match[1] : null
}
import { NAV_ITEMS, Sidebar, TopBar } from './components/Layout'
import LoginScreen, { SessionStatus } from './components/LoginScreen'
import SignUpScreen from './components/SignUpScreen'
import { PRODUCT_NAME } from './components/Brand'

// The authentication screens are addressed by fragment: #signup (the default for anyone signed out) and #signin.
const AUTH_HASHES = new Set(['#signin', '#signup'])

function useHashValue() {
  const [hash, setHash] = useState(window.location.hash)
  useEffect(() => {
    const onChange = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return hash
}
import { pendingActions, summarize } from './lib/insights'
import { readDensity } from './pages/Settings'
import Overview from './pages/Overview'
import Leads from './pages/Leads'
import WebsiteAnalysis from './pages/WebsiteAnalysis'
import Qualification from './pages/Qualification'
import OutreachDrafts from './pages/OutreachDrafts'
import Campaigns from './pages/Campaigns'
import CampaignDetail from './pages/CampaignDetail'
import Settings from './pages/Settings'

const BATCH_LIMIT = 50

function readRoute() {
  const [id, param] = window.location.hash.replace('#', '').split('/')
  const page = NAV_ITEMS.some((item) => item.id === id) ? id : 'overview'
  return { page, param: page === 'campaigns' && param ? param : null }
}

function useRoute() {
  const [route, setRoute] = useState(readRoute)
  useEffect(() => {
    const onChange = () => setRoute(readRoute())
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}

function mergeRows(prev, updated) {
  const byId = new Map(updated.map((r) => [r.id, r]))
  return prev.map((r) => byId.get(r.id) ?? r)
}

function chunks(ids) {
  const out = []
  for (let i = 0; i < ids.length; i += BATCH_LIMIT) out.push(ids.slice(i, i + BATCH_LIMIT))
  return out
}

function Workspace({ user, workspace, workspaces, onSwitchWorkspace, onSignOut }) {
  const workspaceRole = workspace?.role ?? null
  const platformAdmin = user.role === 'admin'
  const toast = useToast()
  const { page: route, param } = useRoute()
  const [selectedIds, setSelectedIds] = useState(() => new Set())
  const [eligibility, setEligibility] = useState({})
  // Narrow screens: the sidebar is a drawer that opens and closes. Wide screens: the sidebar can be hidden to give
  // the page the full width. Both use the same menu button in the top bar.
  const [navOpen, setNavOpen] = useState(false)
  const [sidebarHidden, setSidebarHidden] = useState(false)
  const toggleNav = () => {
    if (window.matchMedia('(max-width: 960px)').matches) setNavOpen((open) => !open)
    else setSidebarHidden((hidden) => !hidden)
  }
  const [query, setQuery] = useState('')
  const [apiStatus, setApiStatus] = useState('checking')
  const [loadState, setLoadState] = useState('loading')
  const [restaurants, setRestaurants] = useState([])
  const [drafts, setDrafts] = useState([])
  const [busy, setBusy] = useState(() => new Set())
  const [discoverError, setDiscoverError] = useState('')
  const [discoveryMode, setDiscoveryMode] = useState(null)

  useEffect(() => {
    document.documentElement.dataset.density = readDensity()
    api.checkHealth().then(() => setApiStatus('ok')).catch(() => setApiStatus('error'))
    api.getDiscoveryMode().then(setDiscoveryMode).catch(() => {})
    Promise.all([api.getRestaurants(), api.listDrafts(), api.getEligibility().catch(() => ({}))])
      .then(([r, d, e]) => {
        setRestaurants(r)
        setDrafts(d)
        setEligibility(e)
        setLoadState('ready')
      })
      .catch(() => setLoadState('error'))
  }, [])

  useEffect(() => {
    const label = NAV_ITEMS.find((item) => item.id === route)?.label ?? 'Overview'
    document.title = `${label} · ${PRODUCT_NAME}`
    setNavOpen(false)
  }, [route])

  const isBusy = useCallback((key) => busy.has(key), [busy])

  const run = useCallback(async (key, fn) => {
    setBusy((prev) => new Set(prev).add(key))
    try {
      await fn()
      return true
    } catch (err) {
      toast(err.message || 'Something went wrong.', 'error')
      return false
    } finally {
      setBusy((prev) => {
        const next = new Set(prev)
        next.delete(key)
        return next
      })
    }
  }, [toast])

  const loadRestaurants = useCallback(async () => {
    setRestaurants(await api.getRestaurants())
  }, [])

  useEffect(() => {
    api.getEligibility()
      .then((rules) => {
        setEligibility(rules)
        setSelectedIds((prev) => new Set([...prev].filter((id) => rules[String(id)]?.eligible)))
      })
      .catch(() => {})
  }, [restaurants])

  const toggleSelect = (id) => setSelectedIds((prev) => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })

  const selectMany = (ids) => setSelectedIds((prev) => new Set([...prev, ...ids]))

  const deselectMany = (ids) => setSelectedIds((prev) => {
    const next = new Set(prev)
    ids.forEach((id) => next.delete(id))
    return next
  })

  const clearSelection = () => setSelectedIds(new Set())

  const createCampaign = async (name, ids) => {
    try {
      const detail = await api.createCampaign(name, ids)
      setSelectedIds(new Set())
      toast(`Campaign "${detail.name}" created. Drafts are being written.`)
      window.location.hash = `campaigns/${detail.id}`
      return true
    } catch (err) {
      toast(err.message || 'Could not create the campaign.', 'error')
      return false
    }
  }

  const loadDrafts = useCallback(async () => {
    setDrafts(await api.listDrafts())
  }, [])

  // Drafts can be written by a campaign after the list was first loaded, so refresh it each time
  // the Outreach Drafts page is opened.
  useEffect(() => {
    if (route === 'drafts') loadDrafts().catch((err) => toast(err.message || 'Could not load drafts.', 'error'))
  }, [route, loadDrafts, toast])

  // Restaurant searches are sent exactly as before. Other industries also send their industry and subcategory.
  const discover = async (city, category, limit, industry = null, countryCode = 'PK', cityId = null) => {
    setDiscoverError('')
    setBusy((prev) => new Set(prev).add('discover'))
    const other = industry && industry !== 'restaurants_food' ? industry : null
    try {
      const found = await api.discoverRestaurants(city, category, limit, other, other ? category : null, countryCode, cityId)
      await loadRestaurants()
      if (found.length > 0 && other) toast(`Found ${found.length} business${found.length === 1 ? '' : 'es'} in ${city}.`)
      else if (found.length > 0) toast(`Found ${found.length} business${found.length === 1 ? '' : 'es'} in ${city}.`)
      return found.length
    } catch (err) {
      setDiscoverError(err.message || 'The search failed. Try again.')
      return null
    } finally {
      setBusy((prev) => {
        const next = new Set(prev)
        next.delete('discover')
        return next
      })
    }
  }

  const checkOne = (id) => run(`check:${id}`, async () => {
    const updated = await api.checkRestaurantWebsite(id)
    setRestaurants((prev) => mergeRows(prev, [updated]))
    toast('Website checked.')
  })

  const contactOne = (id) => run(`contact:${id}`, async () => {
    const updated = await api.discoverContact(id)
    setRestaurants((prev) => mergeRows(prev, [updated]))
    toast('Email search complete.')
  })

  const qualifyOne = (id) => run(`qualify:${id}`, async () => {
    const updated = await api.qualifyLead(id)
    setRestaurants((prev) => mergeRows(prev, [updated]))
    toast('Lead scored.')
  })

  const checkMany = (ids) => {
    if (ids.length === 0) return Promise.resolve(false)
    return run('batch:check', async () => {
      for (const batch of chunks(ids)) {
        const updated = await api.checkRestaurantsBatch(batch)
        setRestaurants((prev) => mergeRows(prev, updated))
      }
      toast(`Checked ${ids.length} website${ids.length === 1 ? '' : 's'}.`)
    })
  }

  const contactMany = (ids) => {
    if (ids.length === 0) return Promise.resolve(false)
    return run('batch:contact', async () => {
      for (const batch of chunks(ids)) {
        const updated = await api.discoverContactsBatch(batch)
        setRestaurants((prev) => mergeRows(prev, updated))
      }
      toast(`Searched emails for ${ids.length} business${ids.length === 1 ? '' : 'es'}.`)
    })
  }

  const qualifyMany = (ids) => {
    if (ids.length === 0) return Promise.resolve(false)
    return run('batch:qualify', async () => {
      for (const batch of chunks(ids)) {
        const updated = await api.qualifyBatch(batch)
        setRestaurants((prev) => mergeRows(prev, updated))
      }
      toast(`Scored ${ids.length} business${ids.length === 1 ? '' : 'es'}.`)
    })
  }

  const generateDraft = (restaurant) => run(`gen:${restaurant.id}`, async () => {
    await api.generateDraft(restaurant.id)
    await loadDrafts()
    toast(`Draft created for ${restaurant.name}.`)
  })

  const deleteDemo = () => run('delete-demo', async () => {
    const result = await api.deleteDemoRecords()
    await loadRestaurants()
    const kept = result.kept.length
    const removed = result.deleted.length
    toast(
      kept > 0
        ? `Deleted ${removed} demo record${removed === 1 ? '' : 's'}. ${kept} kept because they have draft or campaign history.`
        : `Deleted ${removed} demo record${removed === 1 ? '' : 's'}.`,
    )
  })

  const markQualifiedByHand = (restaurant) => run(`manual:${restaurant.id}`, async () => {
    const updated = await api.markQualifiedByHand(restaurant.id)
    setRestaurants((prev) => mergeRows(prev, [updated]))
    toast(`${restaurant.name} marked as qualified after review.`)
  })

  // Lead deletion is a soft delete. The lead leaves the table at once and can be restored from Deleted leads.
  const deleteLead = (restaurant) => run(`delete:${restaurant.id}`, async () => {
    await api.deleteLead(restaurant.id)
    setRestaurants((prev) => prev.filter((r) => r.id !== restaurant.id))
    setSelectedIds((prev) => new Set([...prev].filter((id) => id !== restaurant.id)))
    toast(`${restaurant.name} deleted. You can restore it from Deleted leads.`)
  })

  const deleteLeads = (ids) => run('delete-leads', async () => {
    const result = await api.bulkDeleteLeads(ids)
    const gone = new Set(result.deleted)
    setRestaurants((prev) => prev.filter((r) => !gone.has(r.id)))
    setSelectedIds((prev) => new Set([...prev].filter((id) => !gone.has(id))))
    const count = result.deleted.length
    toast(`Deleted ${count} lead${count === 1 ? '' : 's'}.`)
  })

  const restoreLead = (restaurant) => run(`restore:${restaurant.id}`, async () => {
    await api.restoreLead(restaurant.id)
    // The lead left the list when it was deleted, so the list is read again to bring it back in server order.
    await loadRestaurants()
    toast(`${restaurant.name} restored.`)
  })

  const optOut = (restaurant) => run(`optout:${restaurant.id}`, async () => {
    const updated = await api.optOut(restaurant.id)
    setRestaurants((prev) => mergeRows(prev, [updated]))
    toast(`${restaurant.name} opted out.`)
  })

  const verifyEmailOf = (id) => run(`verify:${id}`, async () => {
    const updated = await api.verifyEmail(id)
    setRestaurants((prev) => mergeRows(prev, [updated]))
    toast('Email checked.')
  })

  const reviewEmailOf = (id, decision, note = '') => run(`review:${id}`, async () => {
    const updated = await api.reviewEmail(id, decision, note)
    setRestaurants((prev) => mergeRows(prev, [updated]))
    toast(decision === 'approve' ? 'Email approved for outreach.' : 'Email rejected. It will not be contacted.')
  })

  const changeDraft = (draft, change, message) => run(`draftact:${draft.id}`, async () => {
    await change()
    await loadDrafts()
    toast(message)
  })

  const saveDraft = (draft, subject, body) =>
    changeDraft(draft, () => api.updateDraft(draft.id, subject, body), 'Draft saved.')
  const approveDraft = (draft) =>
    changeDraft(draft, () => api.approveDraft(draft.id), 'Draft approved.')
  const rejectDraft = (draft) =>
    changeDraft(draft, () => api.rejectDraft(draft.id), 'Draft rejected.')
  const regenerateDraft = (draft, instructions = '') =>
    changeDraft(draft, () => api.regenerateDraft(draft.id, instructions), 'New draft generated.')

  const navigate = (id) => { window.location.hash = id }

  const summary = summarize(restaurants, drafts)
  const actions = pendingActions(summary)
  const loading = loadState === 'loading'
  const title = NAV_ITEMS.find((item) => item.id === route)?.label ?? 'Overview'

  const views = {
    overview: <Overview restaurants={restaurants} summary={summary} loading={loading} onNavigate={navigate} />,
    leads: (
      <Leads
        restaurants={restaurants}
        drafts={drafts}
        loading={loading}
        query={query}
        onQueryChange={setQuery}
        isBusy={isBusy}
        onDiscover={discover}
        discoverError={discoverError}
        onDiscoverReset={() => setDiscoverError('')}
        discoveryMode={discoveryMode}
        eligibility={eligibility}
        selectedIds={selectedIds}
        onToggleSelect={toggleSelect}
        onSelectMany={selectMany}
        onDeselectMany={deselectMany}
        onClearSelection={clearSelection}
        onCreateCampaign={createCampaign}
        onCheckOne={checkOne}
        onContactOne={contactOne}
        onQualifyOne={qualifyOne}
        onCheckMany={checkMany}
        onContactMany={contactMany}
        onQualifyMany={qualifyMany}
        onGenerateDraft={generateDraft}
        onOptOut={optOut}
        onMarkQualifiedByHand={markQualifiedByHand}
        onDeleteLead={deleteLead}
        onDeleteLeads={deleteLeads}
        onRestoreLead={restoreLead}
        onDeleteDemo={deleteDemo}
        onVerifyEmail={verifyEmailOf}
        onReviewEmail={reviewEmailOf}
      />
    ),
    website: (
      <WebsiteAnalysis
        restaurants={restaurants}
        loading={loading}
        isBusy={isBusy}
        onCheckOne={checkOne}
        onCheckMany={checkMany}
      />
    ),
    qualification: (
      <Qualification
        restaurants={restaurants}
        loading={loading}
        isBusy={isBusy}
        onQualifyOne={qualifyOne}
        onQualifyMany={qualifyMany}
      />
    ),
    drafts: (
      <OutreachDrafts
        drafts={drafts}
        restaurants={restaurants}
        loading={loading}
        isBusy={isBusy}
        onSave={saveDraft}
        onApprove={approveDraft}
        onReject={rejectDraft}
        onRegenerate={regenerateDraft}
      />
    ),
    campaigns: param ? (
      <CampaignDetail key={param} campaignId={param} onNavigate={navigate} />
    ) : (
      <Campaigns drafts={drafts} loading={loading} onNavigate={navigate} />
    ),
    settings: (
      <Settings
        apiStatus={apiStatus}
        restaurantCount={restaurants.length}
        draftCount={drafts.length}
        discoveryMode={discoveryMode}
        user={user}
      />
    ),
    team: workspaceRole === 'admin' ? (
      <Team workspaceId={workspace.id} currentUser={user} />
    ) : (
      <div className="notice notice-warn" role="alert">
        <Icon name="alert" size={16} />
        <div>Only workspace admins can manage the team.</div>
      </div>
    ),
    workspaces: platformAdmin ? (
      <Workspaces currentUser={user} activeWorkspaceId={workspace?.id ?? null} onSwitch={onSwitchWorkspace} />
    ) : (
      <div className="notice notice-warn" role="alert">
        <Icon name="alert" size={16} />
        <div>Only platform administrators can manage workspaces.</div>
      </div>
    ),
    users: user.role === 'admin' ? (
      <Users currentUser={user} />
    ) : (
      <div className="notice notice-warn" role="alert">
        <Icon name="alert" size={16} />
        <div>Only administrators can manage user accounts.</div>
      </div>
    ),
  }

  return (
    <div className={`app${navOpen ? ' nav-open' : ''}${sidebarHidden ? ' sidebar-hidden' : ''}`}>
      <a className="skip-link" href="#main">Skip to content</a>
      <Sidebar
        page={route}
        badges={{ drafts: summary.awaitingDrafts }}
        apiStatus={apiStatus}
        onNavigate={() => setNavOpen(false)}
        onClose={() => setNavOpen(false)}
        workspaceRole={workspaceRole}
        platformAdmin={platformAdmin}
      />
      <button
        type="button"
        className="nav-scrim"
        aria-label="Close navigation"
        tabIndex={-1}
        hidden={!navOpen}
        onClick={() => setNavOpen(false)}
      />
      <div className="main">
        <TopBar
          title={title}
          query={query}
          onQueryChange={setQuery}
          onSearchSubmit={() => navigate('leads')}
          onToggleNav={toggleNav}
          navExpanded={window.matchMedia('(max-width: 960px)').matches ? navOpen : !sidebarHidden}
          notifications={actions.map((a) => ({ key: a.key, text: `${a.count} ${a.label}`, page: a.page }))}
          onNavigate={navigate}
          onSignOut={onSignOut}
          user={user}
          workspaces={workspaces}
          activeWorkspaceId={workspace?.id ?? null}
          workspaceRole={workspaceRole}
          onSwitchWorkspace={onSwitchWorkspace}
        />
        <main id="main" className="page">
          {loadState === 'error' && (
            <div className="notice notice-bad" role="alert">
              <Icon name="alert" size={16} />
              <div>
                Could not load data from the API. Make sure the backend is running on port 8000, then refresh the page.
              </div>
            </div>
          )}
          {views[route]}
        </main>
      </div>
    </div>
  )
}

function Gate() {
  // Every page needs a signed-in account. The user comes from the server's session, not from browser storage.
  const [state, setState] = useState({ phase: 'checking', user: null, workspace: null, workspaces: [] })
  const hash = useHashValue()
  const [signInNotice, setSignInNotice] = useState('')

  const checkSession = useCallback(() => {
    setState({ phase: 'checking', user: null, workspace: null, workspaces: [] })
    api.getSession()
      .then((session) => {
        if (session.authenticated && session.user) {
          setState({
            phase: 'ready',
            user: session.user,
            workspace: session.workspace,
            workspaces: session.workspaces ?? [],
          })
        } else {
          setState({ phase: 'signed-out', user: null, workspace: null, workspaces: [] })
        }
      })
      .catch(() => setState({ phase: 'error', user: null, workspace: null, workspaces: [] }))
  }, [])

  // Switching workspace changes which data the session sees, so the session is read again and the workspace
  // view is rebuilt from scratch (its key changes).
  const switchWorkspace = useCallback((workspaceId) => {
    api.switchWorkspace(workspaceId)
      .then(() => checkSession())
      .catch(() => checkSession())
  }, [checkSession])

  useEffect(() => {
    checkSession()
  }, [checkSession])

  // A signed-in person is never shown the authentication screens: they go to the dashboard instead.
  useEffect(() => {
    if (state.phase === 'ready' && AUTH_HASHES.has(hash)) window.location.hash = 'overview'
  }, [state.phase, hash])

  useEffect(() => {
    const onUnauthorized = () => {
      // A session that expired while working goes to sign-in, because the person already has an account.
      setState((prev) => {
        if (prev.phase !== 'ready') return prev
        window.location.hash = 'signin'
        return { phase: 'signed-out', user: null }
      })
    }
    window.addEventListener(api.UNAUTHORIZED_EVENT, onUnauthorized)
    return () => window.removeEventListener(api.UNAUTHORIZED_EVENT, onUnauthorized)
  }, [])

  // Logging out returns to the Sign Up page.
  const signOut = useCallback(() => {
    api.logout()
      .catch(() => {})
      .finally(() => {
        setSignInNotice('')
        window.location.hash = 'signup'
        setState({ phase: 'signed-out', user: null })
      })
  }, [])

  if (state.phase === 'checking') return <SessionStatus>Checking session…</SessionStatus>
  if (state.phase === 'error') {
    return (
      <SessionStatus onRetry={checkSession}>
        <div className="notice notice-bad" role="alert" style={{ maxWidth: 380 }}>
          <Icon name="alert" size={16} />
          <div>Could not reach the server. Make sure the backend is running, then retry.</div>
        </div>
      </SessionStatus>
    )
  }
  // An invitation link opens the accept screen. It shows before sign-in, because accepting may create the account.
  const inviteToken = readInviteToken()
  if (inviteToken) {
    return (
      <InviteScreen
        token={inviteToken}
        onAccepted={() => {
          window.location.hash = 'overview'
          checkSession()
        }}
      />
    )
  }
  if (state.phase === 'signed-out') {
    if (hash === '#signin') return <LoginScreen onSignedIn={checkSession} notice={signInNotice} />
    return (
      <SignUpScreen
        onRegistered={(message) => {
          setSignInNotice(message)
          window.location.hash = 'signin'
        }}
      />
    )
  }
  return (
    <AccessProvider role={state.workspace?.role ?? null}>
      <Workspace
        key={state.workspace?.id ?? 'none'}
        user={state.user}
        workspace={state.workspace}
        workspaces={state.workspaces}
        onSwitchWorkspace={switchWorkspace}
        onSignOut={signOut}
      />
    </AccessProvider>
  )
}

export default function App() {
  return (
    <ToastProvider>
      <Gate />
    </ToastProvider>
  )
}
