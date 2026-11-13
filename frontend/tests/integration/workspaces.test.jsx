import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import { currentFakeApi, installFakeApi, renderAppAt, waitForWorkspace } from '../support/render'
import { leadsScenario } from '../support/scenarios'

const STAMP = '2026-11-01T09:00:00Z'
const ADMIN = {
  id: 1, name: 'Test Admin', email: 'admin@example.test', password: 'test-password', role: 'admin',
  status: 'active', created_at: STAMP, last_login_at: null, password_changed_at: STAMP,
}
const VIEWER = {
  id: 2, name: 'Vera Viewer', email: 'viewer@example.test', password: 'viewer-passphrase-1', role: 'viewer',
  status: 'active', created_at: STAMP, last_login_at: null, password_changed_at: STAMP,
}
const DEFAULT_WORKSPACE = { id: 1, name: 'Default workspace', status: 'active', created_at: STAMP, memberships: {} }
// In Bravo the admin is only a viewer, so switching there removes the admin tools.
const BRAVO = { id: 2, name: 'Team Bravo', status: 'active', created_at: STAMP, memberships: { 1: 'viewer' } }

function seed(overrides = {}) {
  return {
    ...leadsScenario(),
    accounts: [ADMIN, VIEWER],
    workspaces: [DEFAULT_WORKSPACE, BRAVO],
    sessionWorkspaceId: 1,
    ...overrides,
  }
}

describe('Workspace switcher', () => {
  it('switches to another workspace, and the role there replaces the old one', async () => {
    const { user, backend } = renderAppAt('overview', seed())
    await waitForWorkspace()
    const switcher = screen.getByRole('combobox', { name: 'Workspace' })
    expect(switcher).toHaveValue('1')
    expect(screen.getByRole('link', { name: 'Team' })).toBeInTheDocument()

    await user.selectOptions(switcher, '2')
    await waitFor(() => expect(backend.state.sessionWorkspaceId).toBe(2))
    await waitForWorkspace()
    expect(screen.queryByRole('link', { name: 'Team' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Account menu' }))
    expect(screen.getByText('Viewer · admin@example.test')).toBeInTheDocument()
  })
})

describe('Team page', () => {
  it('changes a member role and removes a member', async () => {
    const { user, backend } = renderAppAt('team', seed())
    await waitForWorkspace()
    const vera = screen.getByRole('row', { name: /Vera Viewer/ })
    await user.selectOptions(within(vera).getByLabelText('Role for Vera Viewer'), 'operator')
    expect(await screen.findByText('Vera Viewer is now Operator.')).toBeInTheDocument()
    expect(backend.state.workspaces[0].memberships[VIEWER.id]).toBe('operator')

    await user.click(within(screen.getByRole('row', { name: /Vera Viewer/ })).getByRole('button', { name: 'Remove' }))
    expect(await screen.findByText('Vera Viewer was removed from this workspace.')).toBeInTheDocument()
    expect(backend.state.workspaces[0].memberships[VIEWER.id]).toBe(null)
  })

  it('cannot remove or re-role yourself', async () => {
    renderAppAt('team', seed())
    await waitForWorkspace()
    const own = screen.getByRole('row', { name: /Test Admin/ })
    expect(within(own).getByRole('button', { name: 'Remove' })).toBeDisabled()
    expect(within(own).getByLabelText('Role for Test Admin')).toBeDisabled()
  })

  it('creates an invitation that shows its link once, and revokes it', async () => {
    const { user } = renderAppAt('team', seed())
    await waitForWorkspace()
    await user.type(screen.getByLabelText('Email'), 'new.person@example.test')
    await user.selectOptions(screen.getByLabelText('Role in this workspace'), 'operator')
    await user.click(screen.getByRole('button', { name: 'Create invitation' }))

    expect(await screen.findByText(/#invite=fake-invite-token-/)).toBeInTheDocument()
    const invitations = screen.getByRole('region', { name: 'Invitations' })
    expect(await within(invitations).findByText('new.person@example.test')).toBeInTheDocument()
    expect(within(invitations).getByText('Pending')).toBeInTheDocument()

    await user.click(within(invitations).getByRole('button', { name: 'Revoke' }))
    expect(await within(invitations).findByText('Revoked')).toBeInTheDocument()
  })

  it('tells a viewer that only admins can manage the team', async () => {
    renderAppAt('team', seed({ sessionUserId: VIEWER.id }))
    await waitForWorkspace()
    expect(screen.queryByRole('link', { name: 'Team' })).not.toBeInTheDocument()
    expect(await screen.findByText('Only workspace admins can manage the team.')).toBeInTheDocument()
  })
})

describe('Accepting an invitation', () => {
  it('a new person creates an account and joins the workspace with the invited role', async () => {
    installFakeApi(seed({ accounts: [ADMIN] }))
    currentFakeApi().state.workspaces[1].memberships[ADMIN.id] = 'admin' // only to issue the invitation below
    // The admin creates the invitation while signed in, then the person opens the link signed out.
    const invite = currentFakeApi().handle({
      method: 'POST', path: '/workspaces/2/invitations', body: { email: 'newbie@example.test', role: 'operator' },
    }).body
    currentFakeApi().state.authenticated = false
    const token = invite.link.split('#invite=')[1]

    const { user, backend } = renderAppAt(`invite=${token}`)
    expect(await screen.findByRole('heading', { name: 'Join Team Bravo' })).toBeInTheDocument()
    await user.type(screen.getByLabelText('Full name'), 'Newbie Person')
    await user.type(screen.getByLabelText('Choose a password'), 'newbie-passphrase-1')
    await user.type(screen.getByLabelText('Repeat password'), 'newbie-passphrase-1')
    await user.click(screen.getByRole('button', { name: 'Create account and join' }))

    await waitForWorkspace()
    expect(backend.state.accounts.some((a) => a.email === 'newbie@example.test')).toBe(true)
    expect(window.location.hash).toBe('#overview')
    await user.click(screen.getByRole('button', { name: 'Account menu' }))
    expect(screen.getByText('Operator · newbie@example.test')).toBeInTheDocument()
  })

  it('an existing account signs in to accept, and joins that workspace', async () => {
    installFakeApi(seed())
    currentFakeApi().state.workspaces[1].memberships[ADMIN.id] = 'admin' // only to issue the invitation below
    const invite = currentFakeApi().handle({
      method: 'POST', path: '/workspaces/2/invitations', body: { email: VIEWER.email, role: 'operator' },
    }).body
    currentFakeApi().state.authenticated = false
    const token = invite.link.split('#invite=')[1]

    const { user, backend } = renderAppAt(`invite=${token}`)
    expect(await screen.findByRole('button', { name: 'Sign in and accept' })).toBeInTheDocument()
    await user.type(screen.getByLabelText('Password'), VIEWER.password)
    await user.click(screen.getByRole('button', { name: 'Sign in and accept' }))

    await waitForWorkspace()
    expect(backend.state.workspaces[1].memberships[VIEWER.id]).toBe('operator')
  })
})

describe('Workspaces page (platform administrators)', () => {
  it('lists every workspace and creates a new one', async () => {
    const { user, backend } = renderAppAt('workspaces', seed())
    await waitForWorkspace()
    const list = screen.getByRole('region', { name: 'All workspaces' })
    expect(await within(list).findByRole('row', { name: /Team Bravo/ })).toBeInTheDocument()

    await user.type(screen.getByLabelText('Workspace name'), 'Team Charlie')
    await user.click(screen.getByRole('button', { name: 'Create workspace' }))
    expect(await screen.findByText('Workspace "Team Charlie" created. You are its first admin.')).toBeInTheDocument()
    expect(backend.state.workspaces.some((w) => w.name === 'Team Charlie')).toBe(true)
  })
})
