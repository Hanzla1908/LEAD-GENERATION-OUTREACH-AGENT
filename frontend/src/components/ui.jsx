import {
  AlertTriangle, ArrowRight, Ban, Bell, Building2, Eye, EyeOff, Globe, LayoutDashboard, Mail, Megaphone, Menu, Plus,
  AtSign, BadgeCheck, Check, History, MoreHorizontal, PenLine, RefreshCw, Search, Settings, ShieldCheck, Store, Target, Trash2, Undo2, Users, X,
} from 'lucide-react'
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { DRAFT_LABEL, EMAIL_CLASS_LABEL, EMAIL_LABEL, LEAD_LABEL, ORDERING_LABEL, WEBSITE_LABEL } from '../lib/format'

// Icons come from Lucide (lucide-react). The names below are the ones the screens use, so call sites stay the same.
const ICONS = {
  overview: LayoutDashboard,
  leads: Store,
  workspace: Building2,
  web: Globe,
  target: Target,
  mail: Mail,
  megaphone: Megaphone,
  settings: Settings,
  users: Users,
  search: Search,
  bell: Bell,
  menu: Menu,
  x: X,
  arrow: ArrowRight,
  alert: AlertTriangle,
  plus: Plus,
  refresh: RefreshCw,
  ban: Ban,
  eye: Eye,
  eyeOff: EyeOff,
  atSign: AtSign,
  badgeCheck: BadgeCheck,
  trash: Trash2,
  undo: Undo2,
  shield: ShieldCheck,
  check: Check,
  history: History,
  pen: PenLine,
  more: MoreHorizontal,
}

export function Icon({ name, size = 18 }) {
  const Glyph = ICONS[name]
  if (!Glyph) return null
  return <Glyph size={size} strokeWidth={1.8} className="icon" aria-hidden="true" focusable="false" />
}

// Who is signed in. Viewers can read everything but cannot change data, so their action buttons are disabled.
// The server enforces the same rule on every request; this only keeps the screen honest.
const AccessContext = createContext({ role: null, canOperate: true })

// role is the signed-in person's role in the workspace they are working in (admin, operator or viewer).
export function AccessProvider({ role = null, children }) {
  const value = useMemo(() => ({
    role,
    canOperate: role === 'admin' || role === 'operator',
  }), [role])
  return <AccessContext.Provider value={value}>{children}</AccessContext.Provider>
}

export function useAccess() {
  return useContext(AccessContext)
}

export const READ_ONLY_HINT = 'Viewer accounts can read this page but cannot change data.'

// readOnlyOk marks buttons that only navigate, page, filter or cancel. Viewers keep them.
export function Button({ variant = 'secondary', size = 'md', icon, className = '', children, readOnlyOk = false, disabled, title, ...props }) {
  const iconSize = size === 'sm' ? 14 : 16
  const { canOperate } = useAccess()
  const blocked = !canOperate && !readOnlyOk
  return (
    <button
      type="button"
      className={`btn btn-${variant}${size === 'sm' ? ' btn-sm' : ''}${className ? ` ${className}` : ''}`}
      disabled={disabled || blocked}
      title={blocked ? READ_ONLY_HINT : title}
      {...props}
    >
      {icon && <Icon name={icon} size={iconSize} />}
      {children}
    </button>
  )
}

// A three-dot menu for secondary actions. The list is drawn outside the table, so a scrolling table never clips it.
// Items: { key, label, icon, onSelect, disabled, danger }.
export function ActionMenu({ label, items }) {
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState(null)
  const buttonRef = useRef(null)
  const menuRef = useRef(null)

  function toggle() {
    if (open) { setOpen(false); return }
    const rect = buttonRef.current.getBoundingClientRect()
    setPosition({ top: rect.bottom + 6, right: Math.max(8, window.innerWidth - rect.right) })
    setOpen(true)
  }

  useEffect(() => {
    if (!open) return undefined
    const close = () => setOpen(false)
    function onDown(event) {
      if (menuRef.current?.contains(event.target) || buttonRef.current?.contains(event.target)) return
      setOpen(false)
    }
    function onKey(event) {
      if (event.key === 'Escape') { setOpen(false); buttonRef.current?.focus() }
    }
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    window.addEventListener('resize', close)
    window.addEventListener('scroll', close, true)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('resize', close)
      window.removeEventListener('scroll', close, true)
    }
  }, [open])

  useEffect(() => {
    if (open) menuRef.current?.querySelector('[role="menuitem"]:not(:disabled)')?.focus()
  }, [open])

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        className="btn btn-ghost btn-icon"
        aria-label={label}
        title={label}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={toggle}
      >
        <Icon name="more" size={16} />
      </button>
      {open && position && createPortal(
        <div ref={menuRef} className="menu action-menu" role="menu" style={{ top: position.top, right: position.right }}>
          {items.map((item) => (
            <button
              key={item.key}
              type="button"
              role="menuitem"
              className={`menu-item${item.danger ? ' is-danger' : ''}`}
              disabled={item.disabled}
              onClick={() => { setOpen(false); item.onSelect() }}
            >
              <Icon name={item.icon} size={16} />
              <span>{item.label}</span>
            </button>
          ))}
        </div>,
        document.body,
      )}
    </>
  )
}

export function Badge({ tone = 'neutral', title, children }) {
  return <span className={`badge badge-${tone}`} title={title}>{children}</span>
}

export function WebsiteBadge({ restaurant }) {
  if (!restaurant.website) return <Badge tone="neutral">No website</Badge>
  if (!restaurant.website_checked_at) return <Badge tone="neutral">Not checked</Badge>
  const tone = { present: 'ok', not_found: 'bad' }[restaurant.website_status] ?? 'warn'
  return <Badge tone={tone} title={restaurant.website_error || undefined}>{WEBSITE_LABEL[restaurant.website_status] ?? 'Unknown'}</Badge>
}

export function OrderingBadge({ restaurant }) {
  if (!restaurant.website) return <span className="muted">—</span>
  if (!restaurant.website_checked_at) return <Badge tone="neutral">Not checked</Badge>
  const tone = { present: 'ok', not_found: 'warn' }[restaurant.ordering_status] ?? 'neutral'
  return <Badge tone={tone}>{ORDERING_LABEL[restaurant.ordering_status] ?? 'Unknown'}</Badge>
}

export function LeadBadge({ status, score, reason }) {
  const key = status || 'new'
  const tone = { qualified: 'ok', needs_review: 'warn', disqualified: 'bad' }[key] ?? 'neutral'
  return (
    <span className="lead-badge">
      <Badge tone={tone} title={reason || undefined}>{LEAD_LABEL[key] ?? LEAD_LABEL.new}</Badge>
      {score != null && <span className="score">{score}</span>}
    </span>
  )
}

export function EmailBadge({ status, classification, reviewed }) {
  const tone = { verified: 'ok', domain_valid: 'info', unverified: 'neutral', unknown: 'warn', invalid: 'bad' }[status] ?? 'neutral'
  const needsReview = classification === 'personal' && !reviewed
  return (
    <span className="lead-badge">
      <Badge tone={tone} title="Automatic checks confirm the domain accepts mail. They do not confirm the mailbox.">
        {EMAIL_LABEL[status] ?? 'Not checked'}
      </Badge>
      {classification && classification !== 'unknown' && (
        <Badge tone={classification === 'business' ? 'ok' : needsReview || classification === 'disposable' ? 'warn' : 'neutral'}>
          {needsReview ? 'Personal: review' : EMAIL_CLASS_LABEL[classification]}
        </Badge>
      )}
    </span>
  )
}

export function DraftBadge({ status }) {
  const tone = { draft: 'pending', edited: 'info', approved: 'ok', rejected: 'bad', sent: 'accent' }[status] ?? 'neutral'
  return <Badge tone={tone}>{DRAFT_LABEL[status] ?? status}</Badge>
}

export function Skeleton({ width = '100%', height = 14 }) {
  return <span className="skeleton" style={{ width, height }} aria-hidden="true" />
}

export function EmptyState({ icon = 'search', title, children, action }) {
  return (
    <div className="empty" role="status">
      <div className="empty-icon"><Icon name={icon} size={20} /></div>
      <h4>{title}</h4>
      {children && <p>{children}</p>}
      {action}
    </div>
  )
}

export function Modal({ open, title, description, onClose, size = 'md', footer, children }) {
  const dialogRef = useRef(null)
  const onCloseRef = useRef(onClose)
  onCloseRef.current = onClose

  useEffect(() => {
    if (!open) return undefined
    const previous = document.activeElement
    const first = dialogRef.current?.querySelector('.modal-body input, .modal-body select, .modal-body textarea, .modal-foot button, .modal-body button')
    ;(first ?? dialogRef.current)?.focus()
    function onKey(event) {
      if (event.key === 'Escape') onCloseRef.current()
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      previous?.focus?.()
    }
  }, [open])

  if (!open) return null
  return (
    <div
      className="modal-backdrop"
      onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}
    >
      <div className={`modal modal-${size}`} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={dialogRef}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button type="button" className="icon-btn" aria-label="Close dialog" onClick={onClose}>
            <Icon name="x" />
          </button>
        </div>
        {description && <p className="modal-desc">{description}</p>}
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  )
}

export function ConfirmDialog({ open, title, description, confirmLabel, tone = 'primary', busy = false, onConfirm, onCancel }) {
  return (
    <Modal
      open={open}
      title={title}
      description={description}
      onClose={onCancel}
      size="sm"
      footer={(
        <>
          <Button variant="secondary" onClick={onCancel} disabled={busy} readOnlyOk>Cancel</Button>
          <Button variant={tone} onClick={onConfirm} disabled={busy}>{busy ? 'Working…' : confirmLabel}</Button>
        </>
      )}
    />
  )
}

const ToastContext = createContext(() => {})

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const push = useCallback((message, tone = 'success') => {
    const id = `${Date.now()}-${Math.random()}`
    setToasts((prev) => [...prev, { id, message, tone }])
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4200)
  }, [])
  return (
    <ToastContext.Provider value={push}>
      {children}
      <div className="toast-stack" role="status" aria-live="polite">
        {toasts.map((t) => <div key={t.id} className={`toast toast-${t.tone}`}>{t.message}</div>)}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  return useContext(ToastContext)
}
