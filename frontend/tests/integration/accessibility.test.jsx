import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import { currentFakeApi, renderAppAt, waitForWorkspace } from '../support/render'
import { draftsScenario, leadsScenario } from '../support/scenarios'

async function openDiscover(user) {
  await user.click(screen.getByRole('button', { name: 'Discover businesses' }))
  return screen.findByRole('dialog', { name: 'Discover businesses' })
}

describe('Landmarks and names', () => {
  it('offers a skip link to the main content and labels every landmark', async () => {
    renderAppAt('overview', leadsScenario())
    await waitForWorkspace()
    expect(screen.getByRole('link', { name: 'Skip to content' })).toHaveAttribute('href', '#main')
    expect(screen.getByRole('main')).toHaveAttribute('id', 'main')
    expect(screen.getByRole('complementary', { name: 'Primary' })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Main navigation' })).toBeInTheDocument()
  })

  it('marks the current page in the navigation', async () => {
    renderAppAt('campaigns', leadsScenario())
    await waitForWorkspace()
    const nav = screen.getByRole('navigation', { name: 'Main navigation' })
    expect(within(nav).getByRole('link', { name: 'Campaigns' })).toHaveAttribute('aria-current', 'page')
    expect(within(nav).getByRole('link', { name: 'Settings' })).not.toHaveAttribute('aria-current')
  })

  it('announces the number of pending items on the notifications button', async () => {
    renderAppAt('overview', draftsScenario())
    await waitForWorkspace()
    expect(screen.getByRole('button', { name: /Notifications, \d+ pending/ })).toBeInTheDocument()
  })

  it('labels every control on the lead page', async () => {
    renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    expect(screen.getByRole('searchbox', { name: 'Search leads' })).toBeInTheDocument()
    expect(screen.getByLabelText('Filter by lead status')).toBeInTheDocument()
    expect(screen.getByLabelText('Filter by website')).toBeInTheDocument()
    expect(screen.getByLabelText('Filter by email')).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Email selection' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Bulk actions' })).toBeInTheDocument()
  })

  it('labels the discovery form fields', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)
    expect(within(dialog).getByRole('combobox', { name: 'City' })).toBeInTheDocument()
    expect(within(dialog).getByLabelText('Business type')).toBeInTheDocument()
    expect(within(dialog).getByRole('spinbutton', { name: /Results \(1.60\)/ })).toBeInTheDocument()
  })
})

describe('Dialogs', () => {
  it('closes with Escape and returns focus to the button that opened it', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const trigger = screen.getByRole('button', { name: 'Discover businesses' })
    await user.click(trigger)
    const dialog = await screen.findByRole('dialog', { name: 'Discover businesses' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')

    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Discover businesses' })).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()
  })

  it('closes from its close button', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    await openDiscover(user)
    await user.click(screen.getByRole('button', { name: 'Close dialog' }))
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Discover businesses' })).not.toBeInTheDocument())
  })

  it('moves focus into the dialog when it opens', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)
    expect(dialog.contains(document.activeElement)).toBe(true)
  })
})

describe('Keyboard use', () => {
  it('chooses a city from the list with the arrow keys and Enter', async () => {
    const { user, backend } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)
    const combo = within(dialog).getByRole('combobox', { name: 'City' })

    await user.click(combo)
    await user.type(combo, 'Kar')
    expect(await screen.findByRole('listbox', { name: /City suggestions/ })).toBeInTheDocument()
    await user.keyboard('{ArrowDown}{Enter}')

    await user.click(within(dialog).getByRole('button', { name: 'Search Google Places' }))
    await waitFor(() => expect(backend.state.lastDiscover?.city).toBe('Karachi'))
  })

  it('explains that a typed city is not in the list', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const dialog = await openDiscover(user)
    await user.type(within(dialog).getByRole('combobox', { name: 'City' }), 'Zzz')
    expect(await within(dialog).findByText(/No city in Pakistan matches “Zzz”/)).toBeInTheDocument()
  })

  it('selects a restaurant with the Space key on its checkbox', async () => {
    const { user } = renderAppAt('leads', leadsScenario())
    await waitForWorkspace()
    const box = screen.getByRole('checkbox', { name: 'Select Lahore Karahi House for email campaign' })
    box.focus()
    await user.keyboard(' ')
    expect(box).toBeChecked()
    expect(screen.getByRole('region', { name: 'Email selection' })).toHaveTextContent('1 selected')
  })

  it('opens the account menu from the keyboard and closes it with Escape', async () => {
    const { user } = renderAppAt('overview', leadsScenario())
    await waitForWorkspace()
    const avatar = screen.getByRole('button', { name: 'Account menu' })
    avatar.focus()
    await user.keyboard('{Enter}')
    expect(await screen.findByText('Admin · admin@example.test')).toBeInTheDocument()
    expect(avatar).toHaveAttribute('aria-expanded', 'true')

    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByText('Admin · admin@example.test')).not.toBeInTheDocument())
  })

  it('offers Sign out only when the workspace requires a password', async () => {
    const { user } = renderAppAt('overview', { ...leadsScenario(), authRequired: true, authenticated: true })
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: 'Account menu' }))
    expect(screen.getByRole('menuitem', { name: 'Sign out' })).toBeInTheDocument()
  })

  it('signs out through the account menu', async () => {
    const { user } = renderAppAt('overview', { ...leadsScenario(), authRequired: true, authenticated: true })
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: 'Account menu' }))
    await user.click(screen.getByRole('menuitem', { name: 'Sign out' }))
    expect(await screen.findByRole('heading', { name: 'Create your account' })).toBeInTheDocument()
    expect(currentFakeApi().state.authenticated).toBe(false)
  })
})

describe('Settings toggles', () => {
  it('reports the chosen table density through aria-pressed', async () => {
    const { user } = renderAppAt('settings', leadsScenario())
    await waitForWorkspace()
    const density = screen.getByRole('group', { name: 'Table density' })
    expect(within(density).getByRole('button', { name: 'Comfortable' })).toHaveAttribute('aria-pressed', 'true')
    await user.click(within(density).getByRole('button', { name: 'Compact' }))
    expect(within(density).getByRole('button', { name: 'Compact' })).toHaveAttribute('aria-pressed', 'true')
  })
})
