import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import { currentFakeApi, renderAppAt, waitForWorkspace } from '../support/render'
import { leadsScenario } from '../support/scenarios'

const STAMP = '2026-11-01T09:00:00Z'
const account = (overrides) => ({
  id: 1,
  name: 'Test Admin',
  email: 'admin@example.test',
  password: 'test-password',
  role: 'admin',
  status: 'active',
  created_at: STAMP,
  last_login_at: null,
  password_changed_at: STAMP,
  ...overrides,
})

const ADMIN = account({})
const OPERATOR = account({ id: 3, name: 'Omar Operator', email: 'operator@example.test', password: 'operator-passphrase-1', role: 'operator' })
const VIEWER = account({ id: 2, name: 'Vera Viewer', email: 'viewer@example.test', password: 'viewer-passphrase-1', role: 'viewer' })
const INACTIVE = account({ id: 4, name: 'Ian Inactive', email: 'inactive@example.test', password: 'inactive-passphrase-1', role: 'viewer', status: 'inactive' })

const signedInAs = (who) => ({ ...leadsScenario(), accounts: [ADMIN, OPERATOR, VIEWER, INACTIVE], sessionUserId: who.id, authenticated: true })

describe('First admin setup on the sign-in page', () => {
  it('offers to create the first admin when no account exists, and creates it', async () => {
    const { user, backend } = renderAppAt('signin', { ...leadsScenario(), accounts: [], authenticated: false })
    await screen.findByRole('heading', { name: 'Sign in' })
    await user.click(await screen.findByRole('button', { name: 'Create the first admin account' }))

    expect(await screen.findByRole('heading', { name: 'Create the first admin account' })).toBeInTheDocument()
    await user.type(screen.getByLabelText('Full name'), 'Hanzla Arif')
    await user.type(screen.getByLabelText('Email'), 'hanzla@example.test')
    await user.type(screen.getByLabelText('Password'), 'first-admin-passphrase')
    await user.type(screen.getByLabelText('Repeat password'), 'first-admin-passphrase')
    await user.click(screen.getByRole('button', { name: 'Create admin account' }))

    await waitForWorkspace()
    expect(backend.state.accounts).toHaveLength(1)
    expect(backend.state.accounts[0]).toMatchObject({ email: 'hanzla@example.test', role: 'admin' })
    await user.click(screen.getByRole('button', { name: 'Account menu' }))
    expect(screen.getByText('Hanzla Arif')).toBeInTheDocument()
  })

  it('refuses a setup whose password and repeat differ', async () => {
    const { user, backend } = renderAppAt('signin', { ...leadsScenario(), accounts: [], authenticated: false })
    await screen.findByRole('heading', { name: 'Sign in' })
    await user.click(await screen.findByRole('button', { name: 'Create the first admin account' }))
    await user.type(screen.getByLabelText('Full name'), 'Hanzla Arif')
    await user.type(screen.getByLabelText('Email'), 'hanzla@example.test')
    await user.type(screen.getByLabelText('Password'), 'first-admin-passphrase')
    await user.type(screen.getByLabelText('Repeat password'), 'something-different-here')
    await user.click(screen.getByRole('button', { name: 'Create admin account' }))

    expect(await screen.findByText('The password and its repeat do not match.')).toBeInTheDocument()
    expect(backend.state.accounts).toHaveLength(0)
  })

  it('does not offer setup once an account exists', async () => {
    renderAppAt('signin', { ...leadsScenario(), authenticated: false })
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('button', { name: 'Create the first admin account' })).not.toBeInTheDocument())
    expect(currentFakeApi().state.accounts.length).toBeGreaterThan(0)
  })
})

describe('Sign-in and sign-out', () => {
  it('shows the sign-in page with email and password fields when signed out', async () => {
    renderAppAt('signin', { ...leadsScenario(), accounts: [ADMIN], authenticated: false })
    expect(await screen.findByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Main navigation' })).not.toBeInTheDocument()
  })

  it('signs a viewer in and shows the name and role in the account menu', async () => {
    const { user } = renderAppAt('signin', { ...leadsScenario(), accounts: [ADMIN, VIEWER], authenticated: false })
    await screen.findByRole('heading', { name: 'Sign in' })
    await user.type(screen.getByLabelText('Email'), 'viewer@example.test')
    await user.type(screen.getByLabelText('Password'), 'viewer-passphrase-1')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: 'Account menu' }))
    expect(screen.getByText('Vera Viewer')).toBeInTheDocument()
    expect(screen.getByText('Viewer · viewer@example.test')).toBeInTheDocument()
  })

  it('refuses a deactivated account with the same message as a wrong password', async () => {
    const { user } = renderAppAt('signin', { ...leadsScenario(), accounts: [ADMIN, INACTIVE], authenticated: false })
    await screen.findByRole('heading', { name: 'Sign in' })
    await user.type(screen.getByLabelText('Email'), 'inactive@example.test')
    await user.type(screen.getByLabelText('Password'), 'inactive-passphrase-1')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect email or password.')
  })

  it('signs out from the account menu and returns to the sign-up page', async () => {
    const { user } = renderAppAt('overview', leadsScenario())
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: 'Account menu' }))
    await user.click(screen.getByRole('menuitem', { name: 'Sign out' }))
    expect(await screen.findByRole('heading', { name: 'Create your account' })).toBeInTheDocument()
    expect(currentFakeApi().state.authenticated).toBe(false)
  })
})

describe('Role-based access in the interface', () => {
  it('a viewer can read the leads, but the action buttons and checkboxes are disabled', async () => {
    const { user } = renderAppAt('leads', signedInAs(VIEWER))
    await waitForWorkspace()
    expect(screen.getByRole('button', { name: 'Discover businesses' })).toBeDisabled()
    expect(screen.getByRole('checkbox', { name: 'Select Lahore Karahi House for email campaign' })).toBeDisabled()
    await user.click(screen.getAllByRole('button', { name: /^More actions for/ })[0])
    expect(screen.getByRole('menuitem', { name: 'View history' })).toBeEnabled()
    await user.keyboard('{Escape}')

    await user.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByText(/Showing 11.11 of 11/)).toBeInTheDocument()
  })

  it('a viewer does not see the Users page in the navigation, and sees a notice if they open it', async () => {
    renderAppAt('users', signedInAs(VIEWER))
    await waitForWorkspace()
    expect(screen.queryByRole('link', { name: 'Users' })).not.toBeInTheDocument()
    expect(await screen.findByText('Only administrators can manage user accounts.')).toBeInTheDocument()
  })

  it('a viewer is refused by the server when an action is sent anyway', () => {
    renderAppAt('leads', signedInAs(VIEWER))
    const refused = currentFakeApi().handle({
      method: 'POST',
      path: '/campaigns',
      body: { name: 'Not allowed', restaurant_ids: [1] },
    })
    expect(refused.status).toBe(403)
    expect(refused.body.detail).toBe('Your account does not have permission for this action.')
  })

  it('an operator can work with leads but cannot open the Users page', async () => {
    renderAppAt('leads', signedInAs(OPERATOR))
    await waitForWorkspace()
    expect(screen.getByRole('button', { name: 'Discover businesses' })).toBeEnabled()
    expect(screen.queryByRole('link', { name: 'Users' })).not.toBeInTheDocument()
    const refused = currentFakeApi().handle({ method: 'GET', path: '/users' })
    expect(refused.status).toBe(403)
  })
})

describe('User management (admin)', () => {
  it('lists accounts with role and status, and marks the signed-in admin', async () => {
    renderAppAt('users', { ...leadsScenario(), accounts: [ADMIN, VIEWER] })
    await waitForWorkspace()
    expect(screen.getByRole('link', { name: 'Users' })).toBeInTheDocument()
    const own = screen.getByRole('row', { name: /Test Admin/ })
    expect(within(own).getByText('You')).toBeInTheDocument()
    expect(within(screen.getByRole('row', { name: /Vera Viewer/ })).getByText('Active')).toBeInTheDocument()
  })

  it('creates an account with a role, and it appears in the list', async () => {
    const { user } = renderAppAt('users', { ...leadsScenario(), accounts: [ADMIN] })
    await waitForWorkspace()
    await user.type(screen.getByLabelText('Full name'), 'Nadia New')
    await user.type(screen.getByLabelText('Email'), 'nadia@example.test')
    await user.type(screen.getByLabelText('Starting password'), 'nadia-starting-pass-1')
    await user.selectOptions(screen.getByLabelText('Role', { exact: true }), 'viewer')
    await user.click(screen.getByRole('button', { name: 'Create account' }))

    expect(await screen.findByText(/Account created\./)).toBeInTheDocument()
    expect(await screen.findByRole('row', { name: /Nadia New/ })).toBeInTheDocument()
  })

  it('refuses a short starting password before contacting the server', async () => {
    const { user, backend } = renderAppAt('users', { ...leadsScenario(), accounts: [ADMIN] })
    await waitForWorkspace()
    await user.type(screen.getByLabelText('Full name'), 'Short Pass')
    await user.type(screen.getByLabelText('Email'), 'short@example.test')
    await user.type(screen.getByLabelText('Starting password'), 'short')
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByText('Use at least 12 characters for the starting password.')).toBeInTheDocument()
    expect(backend.state.accounts).toHaveLength(1)
  })

  it('deactivates another account, which is then signed out and cannot sign in', async () => {
    const { user, backend } = renderAppAt('users', { ...leadsScenario(), accounts: [ADMIN, VIEWER] })
    await waitForWorkspace()
    await user.click(within(screen.getByRole('row', { name: /Vera Viewer/ })).getByRole('button', { name: 'Deactivate' }))
    expect(await screen.findByText('Vera Viewer was deactivated and signed out.')).toBeInTheDocument()
    expect(backend.state.accounts.find((a) => a.id === VIEWER.id).status).toBe('inactive')
  })

  it('cannot deactivate or demote the signed-in admin', async () => {
    renderAppAt('users', { ...leadsScenario(), accounts: [ADMIN, VIEWER] })
    await waitForWorkspace()
    const own = screen.getByRole('row', { name: /Test Admin/ })
    expect(within(own).getByRole('button', { name: 'Deactivate' })).toBeDisabled()
    expect(within(own).getByLabelText('Role for Test Admin')).toBeDisabled()
  })

  it('resets another user\'s password', async () => {
    const { user, backend } = renderAppAt('users', { ...leadsScenario(), accounts: [ADMIN, VIEWER] })
    await waitForWorkspace()
    await user.selectOptions(screen.getByLabelText('Account'), String(VIEWER.id))
    await user.type(screen.getByLabelText('New password'), 'vera-new-passphrase-2')
    await user.click(screen.getByRole('button', { name: 'Reset password' }))
    expect(await screen.findByText(/Password reset for Vera Viewer/)).toBeInTheDocument()
    expect(backend.state.accounts.find((a) => a.id === VIEWER.id).password).toBe('vera-new-passphrase-2')
  })

  it('shows the account changes in the recent activity list', async () => {
    const { user } = renderAppAt('users', { ...leadsScenario(), accounts: [ADMIN] })
    await waitForWorkspace()
    await user.type(screen.getByLabelText('Full name'), 'Audit Person')
    await user.type(screen.getByLabelText('Email'), 'audit@example.test')
    await user.type(screen.getByLabelText('Starting password'), 'audit-starting-pass-1')
    await user.click(screen.getByRole('button', { name: 'Create account' }))
    expect(await screen.findByText('user.created')).toBeInTheDocument()
  })
})

describe('Changing your own password', () => {
  it('rejects a repeat that does not match, then changes the password', async () => {
    const { user, backend } = renderAppAt('settings', leadsScenario())
    await waitForWorkspace()
    const form = screen.getByRole('form', { name: 'Change password' })
    await user.type(within(form).getByLabelText('Current password'), 'test-password')
    await user.type(within(form).getByLabelText('New password'), 'a-new-long-passphrase-42')
    await user.type(within(form).getByLabelText('Repeat new password'), 'a-different-passphrase-42')
    await user.click(within(form).getByRole('button', { name: 'Change password' }))
    expect(await within(form).findByText('The new password and its repeat do not match.')).toBeInTheDocument()

    await user.clear(within(form).getByLabelText('Repeat new password'))
    await user.type(within(form).getByLabelText('Repeat new password'), 'a-new-long-passphrase-42')
    await user.click(within(form).getByRole('button', { name: 'Change password' }))
    expect(await screen.findByText(/Password changed\. Your other sessions were signed out\./)).toBeInTheDocument()
    expect(backend.state.accounts[0].password).toBe('a-new-long-passphrase-42')
  })

  it('a viewer can change their own password too', async () => {
    const { user, backend } = renderAppAt('settings', signedInAs(VIEWER))
    await waitForWorkspace()
    const form = screen.getByRole('form', { name: 'Change password' })
    await user.type(within(form).getByLabelText('Current password'), 'viewer-passphrase-1')
    await user.type(within(form).getByLabelText('New password'), 'viewer-new-passphrase-2')
    await user.type(within(form).getByLabelText('Repeat new password'), 'viewer-new-passphrase-2')
    await user.click(within(form).getByRole('button', { name: 'Change password' }))
    await waitFor(() => expect(backend.state.accounts.find((a) => a.id === VIEWER.id).password).toBe('viewer-new-passphrase-2'))
  })
})
