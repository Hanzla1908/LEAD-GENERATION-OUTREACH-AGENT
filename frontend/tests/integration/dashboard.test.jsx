import { describe, expect, it } from 'vitest'
import { screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '../support/mswServer'
import { renderAppAt, waitForWorkspace } from '../support/render'
import { draftsScenario, leadsScenario } from '../support/scenarios'

const API = 'http://api.test'

function metricValue(label) {
  const tile = screen.getByRole('button', { name: new RegExp(label) })
  return tile.querySelector('.metric-value').textContent
}

function navLink(name) {
  return within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('link', { name })
}

describe('Dashboard rendering', () => {
  it('shows pipeline metrics computed from the saved restaurants', async () => {
    renderAppAt('overview', leadsScenario())
    await waitForWorkspace()
    expect(metricValue('Businesses discovered')).toBe('11')
    expect(metricValue('Qualified leads')).toBe('8')
    expect(metricValue('Missing websites')).toBe('6')
    expect(metricValue('Missing online ordering')).toBe('5')
    expect(metricValue('Drafts awaiting approval')).toBe('0')
  })

  it('lists the eight most recent restaurants', async () => {
    renderAppAt('overview', leadsScenario())
    await waitForWorkspace()
    const recent = screen.getByRole('region', { name: 'Recent businesses' })
    expect(within(recent).getByRole('cell', { name: 'Lahore Karahi House' })).toBeInTheDocument()
    expect(within(recent).queryByRole('cell', { name: 'Disposable Eats' })).not.toBeInTheDocument()
    expect(within(recent).getAllByRole('row')).toHaveLength(9)
  })

  it('shows the pending work and opens the page it belongs to', async () => {
    const { user } = renderAppAt('overview', draftsScenario())
    await waitForWorkspace()
    expect(metricValue('Drafts awaiting approval')).toBe('2')
    await user.click(screen.getByRole('button', { name: /2 drafts awaiting approval/ }))
    expect(await screen.findByRole('heading', { name: 'Outreach drafts' })).toBeInTheDocument()
  })

  it('opens a page from a metric tile', async () => {
    const { user } = renderAppAt('overview', leadsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: /Qualified leads/ }))
    expect(await screen.findByRole('heading', { name: 'Lead qualification' })).toBeInTheDocument()
    expect(window.location.hash).toBe('#qualification')
  })
})

describe('Navigation', () => {
  it('moves between pages from the sidebar and updates the page title', async () => {
    const { user } = renderAppAt('overview', leadsScenario())
    await waitForWorkspace()
    await user.click(navLink('Website Analysis'))
    expect(await screen.findByRole('heading', { name: 'Website analysis' })).toBeInTheDocument()
    expect(document.title).toBe('Website Analysis · LEAD GENERATION & OUTREACH AGENT')
    expect(navLink('Website Analysis')).toHaveAttribute('aria-current', 'page')
  })

  it('opens Settings from the account menu', async () => {
    const { user } = renderAppAt('overview', leadsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: 'Account menu' }))
    await user.click(screen.getByRole('menuitem', { name: 'Settings' }))
    expect(await screen.findByRole('heading', { name: 'Settings' })).toBeInTheDocument()
    expect(document.title).toBe('Settings · LEAD GENERATION & OUTREACH AGENT')
  })

  it('searches restaurants from the top bar and carries the query to the leads page', async () => {
    const { user } = renderAppAt('overview', leadsScenario())
    await waitForWorkspace()
    await user.type(screen.getByRole('searchbox', { name: 'Search businesses' }), 'Biryani{Enter}')
    expect(await screen.findByRole('heading', { name: 'Business leads' })).toBeInTheDocument()
    expect(screen.getByRole('searchbox', { name: 'Search leads' })).toHaveValue('Biryani')
    expect(screen.getByRole('checkbox', { name: 'Select Gulberg Biryani Point for email campaign' })).toBeInTheDocument()
  })
})

describe('Session and API status', () => {
  it('shows the API as connected when the health check passes', async () => {
    renderAppAt('overview', leadsScenario())
    await waitForWorkspace()
    expect(await screen.findByText('API connected')).toBeInTheDocument()
  })

  it('shows the API as unreachable when the health check fails', async () => {
    server.use(http.get(`${API}/health`, () => HttpResponse.error()))
    renderAppAt('overview', leadsScenario())
    await waitForWorkspace()
    expect(await screen.findByText('API unreachable')).toBeInTheDocument()
  })

  it('asks for the admin password when the session is signed out', async () => {
    const { user } = renderAppAt('signin', { ...leadsScenario(), authRequired: true, authenticated: false })
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()

    await user.type(screen.getByLabelText('Email'), 'admin@example.test')
    await user.type(screen.getByLabelText('Password'), 'wrong-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect email or password.')

    await user.clear(screen.getByLabelText('Password'))
    await user.type(screen.getByLabelText('Password'), 'test-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitForWorkspace()
    expect(screen.getByRole('heading', { name: 'Overview' })).toBeInTheDocument()
  })
})
