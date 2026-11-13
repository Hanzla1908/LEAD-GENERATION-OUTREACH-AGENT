// Set VITE_API_ORIGIN at build time to the backend's public URL (for example https://ro-backend.onrender.com).
// Leave it empty in development: requests then go to /api and Vite proxies them to localhost:8000.
const API_ORIGIN = (import.meta.env.VITE_API_ORIGIN || '').trim().replace(/\/+$/, '')
const BASE_URL = API_ORIGIN || '/api'

// Fired when the server answers 401 to a workspace request, so the app can show the sign-in screen.
export const UNAUTHORIZED_EVENT = 'ro:unauthorized'

async function _errorFrom(res) {
  const err = await res.json().catch(() => ({}))
  const error = new Error(_messageFrom(err, res))
  error.status = res.status
  return error
}

function _messageFrom(err, res) {
  if (typeof err.detail === 'string') return err.detail
  if (Array.isArray(err.detail)) {
    const messages = err.detail.map((d) => String(d.msg ?? '').replace(/^Value error, /, ''))
    return messages.filter(Boolean).join('. ') || `Request failed (HTTP ${res.status})`
  }
  return `Request failed (HTTP ${res.status})`
}

// Every request sends the session cookie and the X-Requested-With header that the backend
// requires for state-changing calls (CSRF protection).
async function _request(path, { method = 'GET', body } = {}) {
  const init = {
    method,
    credentials: 'include',
    headers: { 'X-Requested-With': 'app' },
  }
  if (body !== undefined) {
    init.headers['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }

  let res
  try {
    res = await fetch(`${BASE_URL}${path}`, init)
  } catch {
    throw new Error('Could not reach the server. Check your connection and try again.')
  }
  if (res.status === 401 && !path.startsWith('/auth/')) {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  }
  if (!res.ok) throw await _errorFrom(res)
  return res.json()
}

const _get = (path) => _request(path)
const _post = (path, body) => _request(path, { method: 'POST', body })

// Session
export function getSession() {
  return _get('/auth/session')
}

export function login(email, password) {
  return _post('/auth/login', { email, password })
}

export function logout() {
  return _post('/auth/logout', {})
}

// Public sign-up. Creates an account and its own workspace, and does not sign the person in.
export function register(name, email, password) {
  return _post('/auth/register', { name, email, password })
}

// First-admin setup. Public, but the server refuses it once any account exists.
export function getSetupStatus() {
  return _get('/auth/setup-status')
}

export function createFirstAdmin(name, email, password) {
  return _post('/auth/setup', { name, email, password })
}

// Workspaces. The session decides which workspace data comes from; these calls manage workspaces and teams.
export function listAllWorkspaces() {
  return _get('/admin/workspaces')
}

export function createWorkspace(name) {
  return _post('/workspaces', { name })
}

export function renameWorkspace(workspaceId, name) {
  return _request(`/workspaces/${workspaceId}`, { method: 'PUT', body: { name } })
}

export function switchWorkspace(workspaceId) {
  return _post(`/workspaces/${workspaceId}/switch`, {})
}

export function listMembers(workspaceId) {
  return _get(`/workspaces/${workspaceId}/members`)
}

export function changeMemberRole(workspaceId, userId, role) {
  return _request(`/workspaces/${workspaceId}/members/${userId}`, { method: 'PUT', body: { role } })
}

export function removeMember(workspaceId, userId) {
  return _request(`/workspaces/${workspaceId}/members/${userId}`, { method: 'DELETE' })
}

export function listInvitations(workspaceId) {
  return _get(`/workspaces/${workspaceId}/invitations`)
}

export function createInvitation(workspaceId, email, role) {
  return _post(`/workspaces/${workspaceId}/invitations`, { email, role })
}

export function revokeInvitation(workspaceId, invitationId) {
  return _request(`/workspaces/${workspaceId}/invitations/${invitationId}`, { method: 'DELETE' })
}

// Invitations are opened from a link. The token is read from the link, sent once to be checked, and never stored.
export function previewInvitation(token) {
  return _post('/invitations/preview', { token })
}

export function acceptInvitation(token, name, password) {
  return _post('/invitations/accept', { token, name, password })
}

// Account: the signed-in user changes their own password.
export function changePassword(currentPassword, newPassword) {
  return _post('/auth/password', { current_password: currentPassword, new_password: newPassword })
}

// User management (admin only). The server enforces the role; the page only hides the controls.
export function listUsers() {
  return _get('/users')
}

export function createUser(body) {
  return _post('/users', body)
}

export function updateUser(userId, body) {
  return _request(`/users/${userId}`, { method: 'PUT', body })
}

export function resetUserPassword(userId, newPassword) {
  return _post(`/users/${userId}/reset-password`, { new_password: newPassword })
}

export function listAuditLog(limit = 100) {
  return _get(`/audit-log?limit=${limit}`)
}

export function checkHealth() {
  return _get('/health')
}

// City suggestions from the city database (GeoNames). One page of one country's cities; the country is always required.
export function searchCities(countryCode, query = '', { limit = 10, offset = 0 } = {}) {
  const params = new URLSearchParams({ q: query, limit: String(limit), offset: String(offset) })
  return _get(`/geo/countries/${encodeURIComponent(countryCode)}/cities?${params.toString()}`)
}

// Whether the city database is loaded, and the attribution to show with it.
export function getGeoStatus() {
  return _get('/geo/status')
}

// Industry profiles for the search form (names, subcategories, website features). Read-only.
export function getIndustries() {
  return _get('/industries')
}

// industry and subcategory are optional. Without them the search is a restaurant search, as before.
// cityId is the id of a city picked from the city database. Without it, city is searched as typed.
export async function discoverRestaurants(city, category, limit, industry = null, subcategory = null, countryCode = 'PK', cityId = null) {
  const body = { city, category, limit, country_code: countryCode }
  if (industry) body.industry = industry
  if (subcategory) body.subcategory = subcategory
  if (cityId != null) body.city_id = cityId
  return _post('/restaurants/discover', body)
}

const PAGE_SIZE = 1000
const MAX_PAGES = 50

// Reads every page, so bulk selection sees all restaurants, not just the first API page.
async function _getAllPages(path) {
  const rows = []
  for (let page = 0; page < MAX_PAGES; page += 1) {
    const separator = path.includes('?') ? '&' : '?'
    const batch = await _get(`${path}${separator}limit=${PAGE_SIZE}&offset=${page * PAGE_SIZE}`)
    rows.push(...batch)
    if (batch.length < PAGE_SIZE) break
  }
  return rows
}

export async function getRestaurants() {
  return _getAllPages('/restaurants')
}

// Phase 3 — website checks
export async function checkRestaurantWebsite(id) {
  return _post(`/restaurants/${id}/check`, {})
}

export async function checkRestaurantsBatch(ids) {
  return _post('/restaurants/check-batch', { ids })
}

// Phase 4 — contact discovery
export async function discoverContact(id) {
  return _post(`/restaurants/${id}/discover-contact`, {})
}

export async function discoverContactsBatch(ids) {
  return _post('/restaurants/discover-contacts-batch', { ids })
}

// Phase 4 — lead qualification
export async function qualifyLead(id) {
  return _post(`/restaurants/${id}/qualify`, {})
}

// A person has checked a lead that needs review and decided it can be contacted. Only needs_review leads change.
export async function markQualifiedByHand(id, note = '') {
  return _post(`/restaurants/${id}/manual-qualify`, { note })
}

export async function qualifyBatch(ids) {
  return _post('/restaurants/qualify-batch', { ids })
}

export async function getLeads(status = null) {
  const path = status
    ? `/restaurants/leads?status=${encodeURIComponent(status)}`
    : '/restaurants/leads'
  return _get(path)
}

// Phase 5 — outreach drafts
export async function generateDraft(restaurantId, campaign = 'default') {
  return _post('/outreach/generate', { restaurant_id: restaurantId, campaign })
}

export async function listDrafts(restaurantId = null, status = null) {
  const params = new URLSearchParams()
  if (restaurantId !== null) params.set('restaurant_id', restaurantId)
  if (status !== null) params.set('status', status)
  const qs = params.toString()
  return _getAllPages(`/outreach/drafts${qs ? '?' + qs : ''}`)
}

export async function getDraft(draftId) {
  return _get(`/outreach/drafts/${draftId}`)
}

export async function updateDraft(draftId, subject, body) {
  return _request(`/outreach/drafts/${draftId}`, { method: 'PUT', body: { subject, body } })
}

export async function approveDraft(draftId) {
  return _post(`/outreach/drafts/${draftId}/approve`, {})
}

export async function rejectDraft(draftId) {
  return _post(`/outreach/drafts/${draftId}/reject`, {})
}

export async function regenerateDraft(draftId, instructions = '') {
  return _post(`/outreach/drafts/${draftId}/regenerate`, { instructions })
}

// Deletes sample (demo) records. ids null means all demo records in the workspace. Real records are never touched.
export function deleteDemoRecords(ids = null) {
  return _post('/restaurants/delete-demo', { ids })
}

// Lead deletion is a soft delete. The lead can be restored from the Deleted leads view.
export function deleteLead(restaurantId) {
  return _request(`/restaurants/${restaurantId}`, { method: 'DELETE' })
}

export function bulkDeleteLeads(ids) {
  return _post('/restaurants/bulk-delete', { ids })
}

export function listDeletedLeads() {
  return _get('/restaurants/deleted')
}

export function restoreLead(restaurantId) {
  return _post(`/restaurants/${restaurantId}/restore`, {})
}

export async function optOut(restaurantId) {
  return _post(`/restaurants/${restaurantId}/opt-out`, {})
}

// Phase 6 — bulk campaigns
export function getEligibility() {
  return _get('/outreach/eligibility')
}

export function previewCampaign(name, restaurantIds) {
  return _post('/campaigns/preview', { name, restaurant_ids: restaurantIds })
}

export function createCampaign(name, restaurantIds) {
  return _post('/campaigns', { name, restaurant_ids: restaurantIds })
}

export function listCampaigns() {
  return _get('/campaigns')
}

export function getCampaign(campaignId) {
  return _get(`/campaigns/${campaignId}`)
}

export function getCampaignConfig() {
  return _get('/campaigns/config')
}

export function sendCampaign(campaignId) {
  return _post(`/campaigns/${campaignId}/send`, {})
}

export function pauseCampaign(campaignId) {
  return _post(`/campaigns/${campaignId}/pause`, {})
}

export function resumeCampaign(campaignId) {
  return _post(`/campaigns/${campaignId}/resume`, {})
}

export function cancelCampaign(campaignId) {
  return _post(`/campaigns/${campaignId}/cancel`, {})
}

export function retryFailedSends(campaignId) {
  return _post(`/campaigns/${campaignId}/retry-failed`, {})
}

export function retryFailedDrafts(campaignId) {
  return _post(`/campaigns/${campaignId}/retry-drafts`, {})
}

export function getDiscoveryMode() {
  return _get('/discovery/mode')
}

export function approveSending(campaignId, draftIds) {
  return _post(`/campaigns/${campaignId}/approve-sending`, { draft_ids: draftIds })
}

export function getCampaignLogs(campaignId) {
  return _get(`/campaigns/${campaignId}/logs`)
}

// Phase 17 — email verification
export function verifyEmail(restaurantId) {
  return _post(`/restaurants/${restaurantId}/verify-email`, {})
}

export function reviewEmail(restaurantId, decision, note = '') {
  return _post(`/restaurants/${restaurantId}/email-review`, { decision, note })
}

// Phase 18 — delivery events and replies
export function getRestaurantConversations(restaurantId) {
  return _get(`/restaurants/${restaurantId}/conversations`)
}

export function getReviewQueue() {
  return _get('/email/review-queue')
}

export function resolveConversation(conversationId, decision) {
  return _post(`/email/conversations/${conversationId}/resolve`, { decision })
}

// Only whether reply monitoring has its mailbox settings: { configured: true | false }. The settings are never sent.
export function getMailboxStatus() {
  return _get('/email/mailbox-status')
}

export function syncMailbox() {
  return _post('/email/sync', {})
}
