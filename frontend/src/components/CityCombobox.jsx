import { useEffect, useId, useRef, useState } from 'react'
import * as api from '../services/api'

// City field for discovery. Suggestions come from the city database for the chosen country only, one page at a time,
// after a short pause in typing. A typed name that is not in the list is still allowed: it is searched as typed.
// Picking a suggestion reports the city (with its database id and admin division) through onSelect.

const PAGE_SIZE = 8
const DEBOUNCE_MS = 250
const CACHE_MS = 10 * 60 * 1000
const CACHE_LIMIT = 200
const pageCache = new Map()

function cacheKey(code, query, offset) {
  return `${code}|${query.toLowerCase()}|${offset}`
}

function readCache(key) {
  const hit = pageCache.get(key)
  if (!hit) return null
  if (Date.now() - hit.at > CACHE_MS) {
    pageCache.delete(key)
    return null
  }
  return hit.page
}

function writeCache(key, page) {
  if (pageCache.size >= CACHE_LIMIT) pageCache.delete(pageCache.keys().next().value)
  pageCache.set(key, { at: Date.now(), page })
}

function placeLabel(item, countryName) {
  return item.admin1_name ? `${item.admin1_name}, ${countryName}` : countryName
}

export default function CityCombobox({
  value, selectedId = null, onChange, onSelect, countryCode, countryName, cityListReady = null,
  disabled, invalid, describedBy,
}) {
  const baseId = useId()
  const listId = `${baseId}-list`
  const wrapRef = useRef(null)
  const latestKey = useRef('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const [items, setItems] = useState([])
  const [hasMore, setHasMore] = useState(false)
  const [status, setStatus] = useState('idle')
  const [loadingMore, setLoadingMore] = useState(false)
  const query = value.trim()

  // A different country means none of the shown cities apply any more.
  useEffect(() => {
    setItems([])
    setHasMore(false)
    setActive(0)
  }, [countryCode])

  // Each query (after a short pause) asks the server for the first page. A reply for an older query is ignored.
  useEffect(() => {
    let current = true
    const key = cacheKey(countryCode, query, 0)
    latestKey.current = key
    // Results for the previous query are dropped at once, so Enter or a click can only pick a city that matches
    // what is typed now.
    setItems([])
    setHasMore(false)
    setActive(0)
    setStatus('loading')
    const timer = setTimeout(async () => {
      const cached = readCache(key)
      if (cached) {
        setItems(cached.items)
        setHasMore(cached.has_more)
        setStatus('ready')
        return
      }
      try {
        const page = await api.searchCities(countryCode, query, { limit: PAGE_SIZE, offset: 0 })
        if (!current) return
        writeCache(key, page)
        setItems(page.items)
        setHasMore(page.has_more)
        setActive(0)
        setStatus('ready')
      } catch {
        if (current) {
          setItems([])
          setHasMore(false)
          setStatus('error')
        }
      }
    }, DEBOUNCE_MS)
    return () => {
      current = false
      clearTimeout(timer)
    }
  }, [countryCode, query])

  useEffect(() => {
    if (!open) return undefined
    function onPointerDown(event) {
      if (!wrapRef.current?.contains(event.target)) setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [open])

  async function showMore() {
    if (loadingMore || !hasMore) return
    const key = latestKey.current
    const offset = items.length
    setLoadingMore(true)
    try {
      const page = await api.searchCities(countryCode, query, { limit: PAGE_SIZE, offset })
      if (latestKey.current !== key) return
      writeCache(cacheKey(countryCode, query, offset), page)
      setItems((prev) => [...prev, ...page.items])
      setHasMore(page.has_more)
    } catch {
      if (latestKey.current === key) setStatus('error')
    } finally {
      setLoadingMore(false)
    }
  }

  function choose(item) {
    onSelect(item)
    setOpen(false)
  }

  function handleKeyDown(event) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setOpen(true)
      setActive((index) => Math.min(index + 1, Math.max(items.length - 1, 0)))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive((index) => Math.max(index - 1, 0))
    } else if (event.key === 'Enter' && open && items[active]) {
      // Pick the highlighted suggestion. With no suggestion showing, Enter submits the typed name as it is.
      event.preventDefault()
      choose(items[active])
    } else if (event.key === 'Escape') {
      setOpen(false)
    }
  }

  let message = ''
  if (status === 'loading' && items.length === 0) message = 'Searching cities…'
  else if (status === 'error') message = 'Could not load city suggestions. You can still type a city.'
  else if (status === 'ready' && items.length === 0 && query) {
    message = `No city in ${countryName} matches “${query}”. It will be searched exactly as typed.`
  } else if (status === 'ready' && items.length === 0) {
    message = cityListReady === false
      ? 'The city list has not been imported yet. Type any city.'
      : `No cities listed for ${countryName} yet. Type any city.`
  }
  const showPanel = open && (items.length > 0 || message)

  return (
    <div className="combobox" ref={wrapRef}>
      <input
        type="text"
        role="combobox"
        className="input"
        aria-label="City"
        aria-autocomplete="list"
        aria-expanded={open && items.length > 0}
        aria-controls={items.length > 0 ? listId : undefined}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        aria-activedescendant={open && items[active] ? `${baseId}-${active}` : undefined}
        autoComplete="off"
        placeholder="Pick a city or type one"
        maxLength={60}
        value={value}
        disabled={disabled}
        onFocus={() => setOpen(true)}
        onChange={(event) => { onChange(event.target.value); setOpen(true) }}
        onKeyDown={handleKeyDown}
      />
      {showPanel && (
        <div className="combobox-list">
          {items.length > 0 && (
            <ul
              role="listbox"
              id={listId}
              aria-label={`City suggestions in ${countryName}`}
              onMouseDown={(event) => event.preventDefault()}
            >
              {items.map((item, index) => (
                <li
                  key={`${item.id ?? item.name}-${index}`}
                  id={`${baseId}-${index}`}
                  role="option"
                  aria-selected={item.id != null && item.id === selectedId}
                  className={`combobox-option${index === active ? ' is-active' : ''}`}
                  onMouseDown={(event) => { event.preventDefault(); choose(item) }}
                  onMouseEnter={() => setActive(index)}
                >
                  <span className="combobox-name">
                    {item.name}
                    {item.matched_alias && <span className="combobox-alias"> (also “{item.matched_alias}”)</span>}
                  </span>
                  <span className="combobox-meta">{placeLabel(item, countryName)}</span>
                </li>
              ))}
            </ul>
          )}
          {items.length > 0 && hasMore && (
            <button
              type="button"
              className="combobox-more"
              disabled={loadingMore}
              onMouseDown={(event) => event.preventDefault()}
              onClick={showMore}
            >
              {loadingMore ? 'Loading…' : 'Show more cities'}
            </button>
          )}
          {message && <p className="combobox-empty" role="status">{message}</p>}
        </div>
      )}
    </div>
  )
}
