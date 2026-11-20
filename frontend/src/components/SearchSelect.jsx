import { useEffect, useId, useRef, useState } from 'react'

// A searchable list of choices: countries, states, and anything else with a short fixed-or-loaded set of values.
// items are { value, label, hint? }. Typing narrows the list; Enter or a click picks the highlighted choice. clearLabel,
// when given, adds a first choice with the value '' (for example "All states"), shown when nothing is typed.
export default function SearchSelect({
  items, value, onChange, ariaLabel, listLabel, placeholder, noMatchText, clearLabel = null, id, disabled, describedBy,
}) {
  const baseId = useId()
  const listId = `${baseId}-list`
  const wrapRef = useRef(null)
  const selected = items.find((item) => item.value === value)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)

  const needle = query.trim().toLowerCase()
  const matches = needle
    ? items.filter((item) => item.label.toLowerCase().includes(needle) || (item.hint ?? '').toLowerCase() === needle)
    : items
  const shown = clearLabel && !needle ? [{ value: '', label: clearLabel }, ...matches] : matches
  const activeIndex = Math.min(active, Math.max(shown.length - 1, 0))
  const closedText = selected?.label ?? (value === '' && clearLabel ? clearLabel : '')

  useEffect(() => {
    if (!open) return undefined
    function onPointerDown(event) {
      if (!wrapRef.current?.contains(event.target)) {
        setOpen(false)
        setQuery('')
      }
    }
    document.addEventListener('mousedown', onPointerDown)
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [open])

  // Keep the highlighted choice on screen while the arrow keys move through a long list such as the countries.
  useEffect(() => {
    if (!open) return
    document.getElementById(`${baseId}-${activeIndex}`)?.scrollIntoView?.({ block: 'nearest' })
  }, [activeIndex, open, baseId])

  function choose(item) {
    onChange(item.value)
    setOpen(false)
    setQuery('')
  }

  function handleKeyDown(event) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setOpen(true)
      setActive(Math.min(activeIndex + 1, shown.length - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActive(Math.max(activeIndex - 1, 0))
    } else if (event.key === 'Enter' && open && shown[activeIndex]) {
      event.preventDefault()
      choose(shown[activeIndex])
    } else if (event.key === 'Escape' || event.key === 'Tab') {
      setOpen(false)
      setQuery('')
    }
  }

  return (
    <div className="combobox" ref={wrapRef}>
      <input
        id={id}
        type="text"
        role="combobox"
        className="input"
        aria-label={ariaLabel}
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls={listId}
        aria-describedby={describedBy}
        aria-activedescendant={open && shown[activeIndex] ? `${baseId}-${activeIndex}` : undefined}
        autoComplete="off"
        placeholder={placeholder}
        value={open ? query : closedText}
        disabled={disabled}
        onFocus={() => {
          setOpen(true)
          setQuery('')
          setActive(Math.max(shown.findIndex((item) => item.value === value), 0))
        }}
        onChange={(event) => { setQuery(event.target.value); setOpen(true); setActive(0) }}
        onKeyDown={handleKeyDown}
      />
      {open && (
        <ul
          className="combobox-list"
          role="listbox"
          id={listId}
          aria-label={listLabel}
          onMouseDown={(event) => event.preventDefault()}
        >
          {shown.length === 0 && <li className="combobox-empty">{noMatchText(query.trim())}</li>}
          {shown.map((item, index) => (
            <li
              key={item.value || '__clear__'}
              id={`${baseId}-${index}`}
              role="option"
              aria-selected={item.value === value}
              className={`combobox-option${index === activeIndex ? ' is-active' : ''}`}
              onMouseDown={(event) => { event.preventDefault(); choose(item) }}
              onMouseEnter={() => setActive(index)}
            >
              {item.label}{item.hint && <>{' '}<span className="small muted">{item.hint}</span></>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
