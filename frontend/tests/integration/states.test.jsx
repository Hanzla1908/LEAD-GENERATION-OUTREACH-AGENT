import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import { http, HttpResponse, delay } from 'msw'
import { server } from '../support/mswServer'
import { renderAppAt, waitForWorkspace } from '../support/render'
import { leadsScenario } from '../support/scenarios'

const API = 'http://api.test'

describe('Loading states', () => {
  it('shows skeleton placeholders while restaurants are still loading', async () => {
    server.use(http.get(`${API}/restaurants`, async () => {
      await delay(400)
      return HttpResponse.json([])
    }))
    renderAppAt('overview', leadsScenario())
    await screen.findByRole('navigation', { name: 'Main navigation' })
    expect(document.querySelectorAll('.skeleton').length).toBeGreaterThan(0)
    await waitFor(() => expect(document.querySelectorAll('.skeleton')).toHaveLength(0), { timeout: 3000 })
    expect(await screen.findByText('No businesses yet')).toBeInTheDocument()
  })

  it('shows skeleton rows in the lead table while loading', async () => {
    server.use(http.get(`${API}/restaurants`, async () => {
      await delay(400)
      return HttpResponse.json(leadsScenario().restaurants)
    }))
    renderAppAt('leads', leadsScenario())
    await screen.findByRole('navigation', { name: 'Main navigation' })
    expect(document.querySelectorAll('.skeleton').length).toBeGreaterThan(0)
    expect(await screen.findByRole('checkbox', { name: 'Select Lahore Karahi House for email campaign' })).toBeInTheDocument()
  })

  it('shows a loading placeholder while a campaign loads', async () => {
    server.use(http.get(`${API}/campaigns/:id`, async () => {
      await delay(400)
      return HttpResponse.json({})
    }))
    renderAppAt('campaigns/1001', leadsScenario())
    await screen.findByRole('navigation', { name: 'Main navigation' })
    expect(document.querySelectorAll('.skeleton').length).toBeGreaterThan(0)
  })
})

describe('Error states', () => {
  it('explains that data could not load when the restaurant list fails', async () => {
    renderAppAt('leads', { ...leadsScenario(), failures: { 'GET /restaurants': { status: 500, detail: 'Database unavailable.' } } })
    await waitForWorkspace()
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load data from the API')
  })

  it('explains a network failure when the page cannot reach the API', async () => {
    renderAppAt('overview', { ...leadsScenario(), failures: { 'GET /restaurants': 'network' } })
    await waitForWorkspace()
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load data from the API')
  })

  it('shows the server message when a single website check fails', async () => {
    const { user } = renderAppAt('leads', {
      ...leadsScenario(),
      failures: { 'POST /restaurants/1/check': { status: 500, detail: 'The website did not respond in time.' } },
    })
    await waitForWorkspace()
    const row = screen.getByRole('row', { name: /Lahore Karahi House/ })
    await user.click(within(row).getByRole('button', { name: /^More actions for/ }))
    await user.click(screen.getByRole('menuitem', { name: 'Recheck site' }))
    expect(await screen.findByText('The website did not respond in time.')).toBeInTheDocument()
  })

  it('shows an error on a campaign that does not exist', async () => {
    renderAppAt('campaigns/9999', leadsScenario())
    await waitForWorkspace()
    expect(await screen.findByRole('alert')).toHaveTextContent('Campaign not found.')
  })

  it('reports a network failure on the campaign list without breaking the page', async () => {
    renderAppAt('campaigns', { ...leadsScenario(), failures: { 'GET /campaigns': 'network' } })
    await waitForWorkspace()
    expect(await screen.findByText('Could not reach the server. Check your connection and try again.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Campaigns' })).toBeInTheDocument()
  })
})

describe('Empty states', () => {
  it('invites a search when no restaurants exist yet', async () => {
    renderAppAt('leads', { restaurants: [] })
    await waitForWorkspace()
    expect(await screen.findByRole('heading', { name: 'No businesses yet' })).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Discover businesses' }).length).toBeGreaterThan(0)
  })

  it('explains the website page when there is nothing to check', async () => {
    renderAppAt('website', { restaurants: [] })
    await waitForWorkspace()
    expect(await screen.findByText('Discover businesses first, then run website checks.')).toBeInTheDocument()
  })

  it('explains the qualification page when there is nothing to score', async () => {
    renderAppAt('qualification', { restaurants: [] })
    await waitForWorkspace()
    expect(await screen.findByText('Discover businesses first, then score them here.')).toBeInTheDocument()
  })

  it('shows an empty drafts list with guidance', async () => {
    renderAppAt('drafts', leadsScenario())
    await waitForWorkspace()
    expect(await screen.findByRole('heading', { name: 'No drafts here' })).toBeInTheDocument()
  })

  it('shows an empty campaign list with guidance', async () => {
    renderAppAt('campaigns', leadsScenario())
    await waitForWorkspace()
    expect(await screen.findByRole('heading', { name: 'No campaigns yet' })).toBeInTheDocument()
  })

  it('shows no pending actions on an empty pipeline', async () => {
    renderAppAt('overview', { restaurants: [] })
    await waitForWorkspace()
    expect(await screen.findByText('Nothing needs attention right now.')).toBeInTheDocument()
  })
})
