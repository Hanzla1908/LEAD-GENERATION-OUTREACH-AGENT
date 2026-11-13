import { describe, expect, it } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import { currentFakeApi, renderAppAt, waitForWorkspace } from '../support/render'
import { leadsScenario } from '../support/scenarios'

const STAMP = '2026-11-01T09:00:00Z'
const ADMIN = {
  id: 1, name: 'Test Admin', email: 'admin@example.test', password: 'test-password', role: 'admin',
  status: 'active', created_at: STAMP, last_login_at: null, password_changed_at: STAMP,
}
const DEFAULT_WORKSPACE = { id: 1, name: 'Default workspace', status: 'active', created_at: STAMP, memberships: { 1: 'admin' } }

function seed(overrides = {}) {
  return {
    ...leadsScenario(),
    accounts: [ADMIN],
    workspaces: [DEFAULT_WORKSPACE],
    sessionWorkspaceId: 1,
    authRequired: true,
    authenticated: false,
    ...overrides,
  }
}

const SIGN_UP_HEADING = 'Create your account'
const SIGN_IN_HEADING = 'Sign in'
const SUCCESS = 'Account created successfully. Please sign in.'

async function fillSignUp(user, { name = 'Nadia Khan', email = 'nadia@example.test', password = 'Abc12345', confirm = password } = {}) {
  await user.type(screen.getByLabelText('Full name'), name)
  await user.type(screen.getByLabelText('Email'), email)
  await user.type(screen.getByLabelText('Password'), password)
  await user.type(screen.getByLabelText('Confirm Password'), confirm)
}

describe('Landing page: Sign Up first', () => {
  it('shows the Create Account page to a first visitor, not the dashboard or the sign-in page', async () => {
    renderAppAt('', seed())
    expect(await screen.findByRole('heading', { name: SIGN_UP_HEADING })).toBeInTheDocument()
    expect(screen.getByLabelText('Full name')).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
    expect(screen.getByLabelText('Confirm Password')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create Account' })).toBeInTheDocument()
    expect(screen.getByText('Already have an account?')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Sign In' })).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: 'Main navigation' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: SIGN_IN_HEADING })).not.toBeInTheDocument()
  })

  it('keeps the password within 8 characters', async () => {
    renderAppAt('', seed())
    await screen.findByRole('heading', { name: SIGN_UP_HEADING })
    expect(screen.getByLabelText('Password')).toHaveAttribute('maxLength', '8')
    expect(screen.getByLabelText('Confirm Password')).toHaveAttribute('maxLength', '8')
  })
})

describe('Navigation between the authentication pages', () => {
  it('opens the sign-in page from the sign-up link, and back again', async () => {
    const { user } = renderAppAt('', seed())
    await screen.findByRole('heading', { name: SIGN_UP_HEADING })
    await user.click(screen.getByRole('link', { name: 'Sign In' }))
    expect(await screen.findByRole('heading', { name: SIGN_IN_HEADING })).toBeInTheDocument()

    await user.click(screen.getByRole('link', { name: 'Create Account' }))
    expect(await screen.findByRole('heading', { name: SIGN_UP_HEADING })).toBeInTheDocument()
  })

  it('opens the sign-in page directly from its own address', async () => {
    renderAppAt('signin', seed())
    expect(await screen.findByRole('heading', { name: SIGN_IN_HEADING })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Create Account' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Forgot Password?' })).toBeInTheDocument()
  })
})

describe('Registration', () => {
  it('creates the account, sends the person to sign-in with the success message, and does not sign them in', async () => {
    const { user, backend } = renderAppAt('', seed())
    await screen.findByRole('heading', { name: SIGN_UP_HEADING })
    await fillSignUp(user)
    await user.click(screen.getByRole('button', { name: 'Create Account' }))

    expect(await screen.findByRole('heading', { name: SIGN_IN_HEADING })).toBeInTheDocument()
    expect(screen.getByText(SUCCESS)).toBeInTheDocument()
    expect(backend.state.accounts.some((a) => a.email === 'nadia@example.test')).toBe(true)
    expect(backend.state.authenticated).toBe(false)
    expect(screen.queryByRole('navigation', { name: 'Main navigation' })).not.toBeInTheDocument()
  })

  it('refuses a duplicate email and shows the message beside the email field', async () => {
    const { user, backend } = renderAppAt('', seed())
    await screen.findByRole('heading', { name: SIGN_UP_HEADING })
    await fillSignUp(user, { email: 'ADMIN@example.test' })
    await user.click(screen.getByRole('button', { name: 'Create Account' }))

    expect(await screen.findByText('An account with this email already exists.')).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toHaveAttribute('aria-invalid', 'true')
    expect(backend.state.accounts).toHaveLength(1)
    expect(screen.getByRole('heading', { name: SIGN_UP_HEADING })).toBeInTheDocument()
  })

})

describe('Password and field validation on sign-up', () => {
  it('refuses a password that is not exactly 8 characters', async () => {
    const { user, backend } = renderAppAt('', seed())
    await screen.findByRole('heading', { name: SIGN_UP_HEADING })
    await fillSignUp(user, { password: 'Abc1234' })
    await user.click(screen.getByRole('button', { name: 'Create Account' }))
    expect(await screen.findByText('Password must be exactly 8 characters.')).toBeInTheDocument()
    expect(backend.state.accounts).toHaveLength(1)
  })

  it('refuses a password with a symbol or a space', async () => {
    const { user } = renderAppAt('', seed())
    await screen.findByRole('heading', { name: SIGN_UP_HEADING })
    await fillSignUp(user, { password: 'Abc1234!' })
    await user.click(screen.getByRole('button', { name: 'Create Account' }))
    expect(await screen.findByText('Use letters and numbers only (A to Z and 0 to 9).')).toBeInTheDocument()
  })

  it('refuses a confirmation that does not match', async () => {
    const { user, backend } = renderAppAt('', seed())
    await screen.findByRole('heading', { name: SIGN_UP_HEADING })
    await fillSignUp(user, { password: 'Abc12345', confirm: 'Abc12346' })
    await user.click(screen.getByRole('button', { name: 'Create Account' }))
    expect(await screen.findByText('The passwords do not match.')).toBeInTheDocument()
    expect(backend.state.accounts).toHaveLength(1)
  })

  it('refuses a name that is too short and an email that is not one', async () => {
    const { user, backend } = renderAppAt('', seed())
    await screen.findByRole('heading', { name: SIGN_UP_HEADING })
    await fillSignUp(user, { name: 'N', email: 'not-an-email' })
    await user.click(screen.getByRole('button', { name: 'Create Account' }))
    expect(await screen.findByText('Enter your full name (at least 2 characters).')).toBeInTheDocument()
    expect(screen.getByText('Enter a valid email address.')).toBeInTheDocument()
    expect(backend.state.accounts).toHaveLength(1)
  })

  it('toggles password visibility for each password field', async () => {
    const { user } = renderAppAt('', seed())
    await screen.findByRole('heading', { name: SIGN_UP_HEADING })
    const password = screen.getByLabelText('Password')
    expect(password).toHaveAttribute('type', 'password')
    await user.click(screen.getByRole('button', { name: 'Show Password' }))
    expect(password).toHaveAttribute('type', 'text')
    await user.click(screen.getByRole('button', { name: 'Hide Password' }))
    expect(password).toHaveAttribute('type', 'password')

    const confirm = screen.getByLabelText('Confirm Password')
    await user.click(screen.getByRole('button', { name: 'Show Confirm Password' }))
    expect(confirm).toHaveAttribute('type', 'text')
  })
})

describe('Sign-in after registration', () => {
  it('signs the new person in and opens the dashboard', async () => {
    const { user, backend } = renderAppAt('', seed())
    await screen.findByRole('heading', { name: SIGN_UP_HEADING })
    await fillSignUp(user)
    await user.click(screen.getByRole('button', { name: 'Create Account' }))
    await screen.findByRole('heading', { name: SIGN_IN_HEADING })

    await user.type(screen.getByLabelText('Email'), 'nadia@example.test')
    await user.type(screen.getByLabelText('Password'), 'Abc12345')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    await waitForWorkspace()
    expect(backend.state.authenticated).toBe(true)
    expect(window.location.hash).toBe('#overview')
    await user.click(screen.getByRole('button', { name: 'Account menu' }))
    expect(screen.getByText('Admin · nadia@example.test')).toBeInTheDocument()
    expect(screen.getByText('Nadia Khan workspace')).toBeInTheDocument()
  })

  it('shows a clear error for invalid credentials and does not sign in', async () => {
    const { user, backend } = renderAppAt('signin', seed())
    await screen.findByRole('heading', { name: SIGN_IN_HEADING })
    await user.type(screen.getByLabelText('Email'), 'admin@example.test')
    await user.type(screen.getByLabelText('Password'), 'wrong-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Incorrect email or password.')
    expect(backend.state.authenticated).toBe(false)
  })

  it('explains that password reset is not available yet from the Forgot Password link', async () => {
    const { user } = renderAppAt('signin', seed())
    await screen.findByRole('heading', { name: SIGN_IN_HEADING })
    await user.click(screen.getByRole('button', { name: 'Forgot Password?' }))
    expect(await screen.findByText(/Password reset is not available yet/)).toBeInTheDocument()
  })
})

describe('Dashboard access and logout', () => {
  it('sends a signed-in person who opens a sign-in or sign-up address to the dashboard', async () => {
    renderAppAt('signin', seed({ authenticated: true, sessionUserId: ADMIN.id }))
    await waitForWorkspace()
    expect(window.location.hash).toBe('#overview')
    expect(screen.queryByRole('heading', { name: SIGN_IN_HEADING })).not.toBeInTheDocument()
  })

  it('logs out to the Create Account page', async () => {
    const { user } = renderAppAt('overview', seed({ authenticated: true, sessionUserId: ADMIN.id }))
    await waitForWorkspace()
    await user.click(screen.getByRole('button', { name: 'Account menu' }))
    await user.click(screen.getByRole('menuitem', { name: 'Sign out' }))

    expect(await screen.findByRole('heading', { name: SIGN_UP_HEADING })).toBeInTheDocument()
    expect(window.location.hash).toBe('#signup')
    expect(currentFakeApi().state.authenticated).toBe(false)
  })

  it('keeps the dashboard closed to a signed-out visitor', async () => {
    renderAppAt('leads', seed())
    expect(await screen.findByRole('heading', { name: SIGN_UP_HEADING })).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('navigation', { name: 'Main navigation' })).not.toBeInTheDocument())
    expect(within(document.body).queryByText('Leads')).not.toBeInTheDocument()
  })
})

describe('Switching between sign up and sign in with the mouse', () => {
  it('one click on Sign In opens the sign-in page, even with the empty Full name field focused', async () => {
    const { user } = renderAppAt('', seed())
    await screen.findByRole('heading', { name: SIGN_UP_HEADING })
    expect(screen.getByLabelText('Full name')).toHaveFocus()

    await user.click(screen.getByRole('link', { name: 'Sign In' }))

    expect(await screen.findByRole('heading', { name: SIGN_IN_HEADING })).toBeInTheDocument()
    expect(screen.queryByText('Enter your full name (at least 2 characters).')).not.toBeInTheDocument()
  })

  it('an empty field is still reported when the form is submitted', async () => {
    const { user, backend } = renderAppAt('', seed())
    await screen.findByRole('heading', { name: SIGN_UP_HEADING })
    await user.click(screen.getByRole('button', { name: 'Create Account' }))
    expect(await screen.findByText('Enter your full name (at least 2 characters).')).toBeInTheDocument()
    expect(backend.state.accounts).toHaveLength(1)
  })
})
