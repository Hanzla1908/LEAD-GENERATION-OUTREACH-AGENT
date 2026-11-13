import { useEffect, useId, useRef, useState } from 'react'
import COUNTRIES from '../lib/countries.json'

// A searchable list of every ISO 3166-1 country. The value is the two-letter code; the name is shown to the person.
export default function CountrySelect({ value, onChange, disabled, describedBy }) {
  const baseId = useId()
  const listId = `${baseId}-list`
  const wrapRef = useRef(null)
  const countries = COUNTRIES.countries
  const selected = countries.find((country) => country.code === value)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)

  const needle = query.trim().toLowerCase()
  const shown = needle
    ? countries.filter((country) => country.name.toLowerCase().includes(needle) || country.code.toLowerCase() === needle)
    : countries
  const activeIndex = Math.min(active, Math.max(shown.length - 1, 0))

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

  function choose(country) {
    onChange(country.code)
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
        type="text"
        role="combobox"
        className="input"
        aria-label="Country"
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls={listId}
        aria-describedby={describedBy}
        aria-activedescendant={open && shown[activeIndex] ? `${baseId}-${activeIndex}` : undefined}
        autoComplete="off"
        placeholder="Search a country"
        value={open ? query : (selected?.name ?? '')}
        disabled={disabled}
        onFocus={() => { setOpen(true); setQuery(''); setActive(Math.max(shown.findIndex((c) => c.code === value), 0)) }}
        onChange={(event) => { setQuery(event.target.value); setOpen(true); setActive(0) }}
        onKeyDown={handleKeyDown}
      />
      {open && (
        <ul
          className="combobox-list"
          role="listbox"
          id={listId}
          aria-label="Countries"
          onMouseDown={(event) => event.preventDefault()}
        >
          {shown.length === 0 && <li className="combobox-empty">No country matches “{query.trim()}”.</li>}
          {shown.map((country, index) => (
            <li
              key={country.code}
              id={`${baseId}-${index}`}
              role="option"
              aria-selected={country.code === value}
              className={`combobox-option${index === activeIndex ? ' is-active' : ''}`}
              onMouseDown={(event) => { event.preventDefault(); choose(country) }}
              onMouseEnter={() => setActive(index)}
            >
              {country.name} <span className="small muted">{country.code}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
