import { useEffect, useRef, useState } from 'react'
import { Icon } from './ui'
import { BrandLockup, BrandMark } from './Brand'

export const NAV_ITEMS = [
  { id: 'overview', label: 'Overview', icon: 'overview' },
  { id: 'leads', label: 'Leads', icon: 'leads' },
  { id: 'website', label: 'Website Analysis', icon: 'web' },
  { id: 'qualification', label: 'Lead Qualification', icon: 'target' },
  { id: 'drafts', label: 'Outreach Drafts', icon: 'mail' },
  { id: 'campaigns', label: 'Campaigns', icon: 'megaphone' },
  { id: 'settings', label: 'Settings', icon: 'settings' },
  { id: 'team', label: 'Team', icon: 'users', workspaceAdminOnly: true },
  { id: 'users', label: 'Users', icon: 'users', platformAdminOnly: true },
  { id: 'workspaces', label: 'Workspaces', icon: 'workspace', platformAdminOnly: true },
]

export const ROLE_LABEL = { admin: 'Admin', operator: 'Operator', viewer: 'Viewer' }

// Workspace-level items depend on the role in the workspace being worked in. Platform items depend on the account.
export function visibleNavItems(workspaceRole, platformAdmin) {
  return NAV_ITEMS.filter((item) => {
    if (item.workspaceAdminOnly) return workspaceRole === 'admin'
    if (item.platformAdminOnly) return Boolean(platformAdmin)
    return true
  })
}

function initials(name) {
  const parts = (name || '').trim().split(/\s+/).filter(Boolean)
  return parts.slice(0, 2).map((part) => part[0].toUpperCase()).join('') || '?'
}

const API_STATUS = {
  ok: { dot: 'ok', text: 'API connected' },
  error: { dot: 'bad', text: 'API unreachable' },
  checking: { dot: '', text: 'Checking API…' },
}

export function Sidebar({ page, badges, apiStatus, onNavigate, onClose, workspaceRole, platformAdmin }) {
  const api = API_STATUS[apiStatus] ?? API_STATUS.checking
  return (
    <aside className="sidebar" aria-label="Primary">
      <div className="sidebar-head">
        <div className="brand">
          <BrandLockup onDark markSize={30} />
        </div>
        {/* Shown only in drawer mode (narrow screens): the same menu control closes the drawer from inside it. */}
        <button type="button" className="icon-btn sidebar-close" aria-label="Close menu" onClick={onClose}>
          <Icon name="menu" />
        </button>
      </div>
      <nav className="nav" aria-label="Main navigation">
        <div className="nav-label">Workspace</div>
        {visibleNavItems(workspaceRole, platformAdmin).map((item) => (
          <a
            key={item.id}
            href={`#${item.id}`}
            className="nav-link"
            aria-current={page === item.id ? 'page' : undefined}
            onClick={onNavigate}
          >
            <Icon name={item.icon} />
            <span>{item.label}</span>
            {badges[item.id] > 0 && (
              <span className="nav-count" aria-label={`${badges[item.id]} pending`}>{badges[item.id]}</span>
            )}
          </a>
        ))}
      </nav>
      <div className="sidebar-foot">
        <span className={`status-dot ${api.dot}`} aria-hidden="true" />
        <span>{api.text}</span>
      </div>
    </aside>
  )
}

export function TopBar({
  title, query, onQueryChange, onSearchSubmit, onToggleNav, navExpanded = false, notifications, onNavigate,
  onSignOut, user, workspaces = [], activeWorkspaceId, workspaceRole, onSwitchWorkspace,
}) {
  const [openMenu, setOpenMenu] = useState(null)
  const wrapRef = useRef(null)

  useEffect(() => {
    if (!openMenu) return undefined
    function onDown(event) {
      if (wrapRef.current && !wrapRef.current.contains(event.target)) setOpenMenu(null)
    }
    function onKey(event) {
      if (event.key === 'Escape') setOpenMenu(null)
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [openMenu])

  const toggle = (name) => setOpenMenu((current) => (current === name ? null : name))

  return (
    <header className="topbar" ref={wrapRef}>
      <button
        type="button"
        className="icon-btn topbar-menu"
        aria-label={navExpanded ? 'Hide navigation' : 'Show navigation'}
        aria-expanded={navExpanded}
        onClick={onToggleNav}
      >
        <Icon name="menu" />
      </button>
      <span className="topbar-brand"><BrandMark size={26} /></span>
      <div className="topbar-crumb">
        <span className="muted">Workspace / </span>
        <strong>{title}</strong>
      </div>
      <form
        className="topbar-search"
        role="search"
        onSubmit={(event) => { event.preventDefault(); onSearchSubmit() }}
      >
        <Icon name="search" size={16} />
        <input
          type="search"
          aria-label="Search businesses"
          placeholder="Search name, address or email"
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
        />
      </form>
      <div className="topbar-actions">
        {workspaces.length > 0 && (
          <label className="workspace-switch">
            <span className="sr-only">Workspace</span>
            <select
              className="select"
              aria-label="Workspace"
              value={activeWorkspaceId ?? ''}
              onChange={(event) => onSwitchWorkspace(Number(event.target.value))}
            >
              {workspaces.map((ws) => <option key={ws.id} value={ws.id}>{ws.name}</option>)}
            </select>
          </label>
        )}
        <button
          type="button"
          className="icon-btn"
          aria-label={notifications.length ? `Notifications, ${notifications.length} pending` : 'Notifications'}
          aria-expanded={openMenu === 'notifications'}
          onClick={() => toggle('notifications')}
        >
          <Icon name="bell" />
          {notifications.length > 0 && <span className="dot" aria-hidden="true" />}
        </button>
        {openMenu === 'notifications' && (
          <div className="menu" role="menu">
            {notifications.length === 0 && <div className="menu-empty">You're all caught up.</div>}
            {notifications.map((item) => (
              <button
                key={item.key}
                type="button"
                role="menuitem"
                className="menu-item"
                onClick={() => { setOpenMenu(null); onNavigate(item.page) }}
              >
                <Icon name="arrow" size={16} />
                <span>{item.text}</span>
              </button>
            ))}
          </div>
        )}
        <button
          type="button"
          className="avatar"
          aria-label="Account menu"
          aria-expanded={openMenu === 'profile'}
          onClick={() => toggle('profile')}
        >
          {initials(user?.name)}
        </button>
        {openMenu === 'profile' && (
          <div className="menu" role="menu">
            <div className="menu-head">
              <div className="menu-title">{user?.name ?? 'Signed in'}</div>
              <div className="menu-meta">{ROLE_LABEL[workspaceRole] ?? 'Signed in'} · {user?.email ?? ''}</div>
            </div>
            <button
              type="button"
              role="menuitem"
              className="menu-item"
              onClick={() => { setOpenMenu(null); onNavigate('settings') }}
            >
              <Icon name="settings" size={16} />
              <span>Settings</span>
            </button>
            {onSignOut && (
              <button
                type="button"
                role="menuitem"
                className="menu-item"
                onClick={() => { setOpenMenu(null); onSignOut() }}
              >
                <Icon name="x" size={16} />
                <span>Sign out</span>
              </button>
            )}
          </div>
        )}
      </div>
    </header>
  )
}
