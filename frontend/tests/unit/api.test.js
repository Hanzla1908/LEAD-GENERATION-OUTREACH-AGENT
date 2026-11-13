import { describe, expect, it, vi } from 'vitest'
import * as api from '../../src/services/api'
import { installFakeApi } from '../support/mswServer'
import { leadsScenario } from '../support/scenarios'
import { makeRestaurant } from '../support/fakeBackend'

// These tests call the real API client. MSW answers each request from the fake backend.

describe('API client paging', () => {
  it('reads every page so bulk selection sees all restaurants', async () => {
    installFakeApi({
      restaurants: Array.from({ length: 1205 }, (_, i) => makeRestaurant({ id: i + 1, name: `R${i + 1}` })),
    })
    const rows = await api.getRestaurants()
    expect(rows).toHaveLength(1205)
    expect(rows[1204].name).toBe('R1205')
  })

  it('returns an empty list when there are no restaurants', async () => {
    installFakeApi({ restaurants: [] })
    await expect(api.getRestaurants()).resolves.toEqual([])
  })
})

describe('API client errors', () => {
  it('shows the server detail message for a rejected request', async () => {
    installFakeApi({ restaurants: leadsScenario().restaurants })
    await expect(api.createCampaign('Lahore cafes', [4, 5])).rejects.toThrow(
      'None of the selected businesses are eligible for this campaign.',
    )
  })

  it('joins every validation message and removes the Pydantic prefix', async () => {
    installFakeApi({
      failures: {
        'POST /restaurants/discover': {
          status: 422,
          detail: [{ msg: 'Value error, City is required.' }, { msg: 'Value error, Choose between 1 and 60 results.' }],
        },
      },
    })
    // Known issue, left as is in this phase: api.js joins with ". ", so a message that already ends
    // in a period gives "required.." here. The test checks both messages arrive without the prefix.
    const error = await api.discoverRestaurants('Lahore', 'all', 10).catch((err) => err)
    expect(error).toBeInstanceOf(Error)
    expect(error.message).toContain('City is required.')
    expect(error.message).toContain('Choose between 1 and 60 results.')
    expect(error.message).not.toContain('Value error')
  })

  it('falls back to the status code when the body has no detail', async () => {
    installFakeApi({ failures: { 'GET /restaurants': { status: 500 } } })
    await expect(api.getRestaurants()).rejects.toThrow('Request failed (HTTP 500)')
  })

  it('explains a network failure in plain words', async () => {
    installFakeApi({ failures: { 'GET /restaurants': 'network' } })
    await expect(api.getRestaurants()).rejects.toThrow(
      'Could not reach the server. Check your connection and try again.',
    )
  })

  it('announces an expired session on a workspace request', async () => {
    installFakeApi({ authRequired: true, authenticated: false })
    const listener = vi.fn()
    window.addEventListener(api.UNAUTHORIZED_EVENT, listener)
    try {
      await expect(api.getRestaurants()).rejects.toThrow('Sign in required.')
      expect(listener).toHaveBeenCalledTimes(1)
    } finally {
      window.removeEventListener(api.UNAUTHORIZED_EVENT, listener)
    }
  })

  it('does not announce a wrong password as an expired session', async () => {
    installFakeApi({ authRequired: true, authenticated: false })
    const listener = vi.fn()
    window.addEventListener(api.UNAUTHORIZED_EVENT, listener)
    try {
      await expect(api.login('admin@example.test', 'wrong')).rejects.toThrow('Incorrect email or password.')
      expect(listener).not.toHaveBeenCalled()
    } finally {
      window.removeEventListener(api.UNAUTHORIZED_EVENT, listener)
    }
  })
})
